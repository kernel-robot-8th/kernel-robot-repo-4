"""Search YOLO classification settings/checkpoints using the 9:1 image holdout.

The dataset test/ images are used as a model-selection holdout (parameter and
checkpoint selection), not as an unbiased final score. The separate MP4 remains
for later human review and is never read here.
"""
import argparse
import csv
import itertools
import json
import math
import shutil
from pathlib import Path
from common import CLASSES, read_json, write_json


def metrics(labels, probs, threshold):
    tp=sum(y=='closed_verified' and p>=threshold for y,p in zip(labels,probs))
    fp=sum(y=='not_verified' and p>=threshold for y,p in zip(labels,probs))
    positives=labels.count('closed_verified');negatives=len(labels)-positives
    precision=tp/max(1,tp+fp);recall=tp/max(1,positives)
    return dict(threshold=float(threshold),tp=tp,fp=fp,fn=positives-tp,tn=negatives-fp,
                precision=precision,recall=recall,f1=2*precision*recall/max(1e-12,precision+recall),
                false_closed_rate=fp/max(1,negatives))


def average_precision(labels,probs):
    positives=labels.count('closed_verified')
    if not positives:return 0.0
    ranked=sorted(zip(map(float,probs),labels),key=lambda x:x[0],reverse=True)
    hits=seen=0;prev=ap=0.0;i=0
    while i<len(ranked):
        j=i
        while j<len(ranked) and ranked[j][0]==ranked[i][0]:
            hits+=ranked[j][1]=='closed_verified';seen+=1;j+=1
        recall=hits/positives;ap+=(recall-prev)*(hits/seen);prev=recall;i=j
    return ap


def choose_threshold(labels,probs):
    options=sorted(set([0.0,1.0,*map(float,probs)]))
    rows=[metrics(labels,probs,t) for t in options]
    safe=[r for r in rows if r['fp']==0]
    chosen=max(safe,key=lambda r:(r['recall'],r['threshold'])) if safe else max(rows,key=lambda r:(r['f1'],-r['false_closed_rate']))
    return chosen,rows


def write_csv(path,rows):
    if rows:
        with Path(path).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def balanced_data(source,destination,max_negative_ratio=4):
    """Create symlinked train-only data, oversampling positives in train only."""
    root=Path(destination);train=root/'train'
    for cls in CLASSES:(train/cls).mkdir(parents=True,exist_ok=True)
    samples={c:sorted((Path(source)/'train'/c).glob('*.jpg')) for c in CLASSES}
    if not samples['closed_verified'] or not samples['not_verified']:
        raise ValueError('Both train classes must contain images')
    for cls,paths in samples.items():
        for src in paths:(train/cls/src.name).symlink_to(src.resolve())
    target=math.ceil(len(samples['not_verified'])/max_negative_ratio)
    for i in range(max(0,target-len(samples['closed_verified']))):
        src=samples['closed_verified'][i%len(samples['closed_verified'])]
        (train/'closed_verified'/f'oversample_{i:05d}_{src.name}').symlink_to(src.resolve())
    return root


def predict(model,folder,size,device):
    paths=sorted(p for c in CLASSES for p in (Path(folder)/c).glob('*.jpg'))
    if not paths:raise ValueError(f'No labeled holdout images in {folder}')
    probs=[]
    for result in model.predict([str(p) for p in paths],imgsz=size,device=device,stream=True,verbose=False):
        pos=next(i for i,n in result.names.items() if n=='closed_verified')
        probs.append(float(result.probs.data[pos]))
    return paths,[p.parent.name for p in paths],probs


def plot_results(out,trial_rows,checkpoint_rows,selected_trial,threshold_rows,confusion):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels=[f"{r['optimizer']} lr={r['lr0']} b={r['batch']} d={r['dropout']}" for r in trial_rows]
    fig,ax=plt.subplots(figsize=(max(11,len(labels)*.85),5));x=range(len(trial_rows))
    ax.bar([i-.18 for i in x],[float(r['best_ap']) for r in trial_rows],.36,label='Best holdout AP')
    ax.bar([i+.18 for i in x],[float(r['safe_recall']) for r in trial_rows],.36,label='Recall at zero-FP threshold')
    ax.set_xticks(list(x),labels,rotation=55,ha='right',fontsize=8);ax.set_ylim(0,1.05);ax.legend();ax.grid(axis='y',alpha=.2)
    fig.tight_layout();fig.savefig(out/'hyperparameter_comparison.png',dpi=160);plt.close(fig)
    # Every tested epoch checkpoint, allowing reviewers to see selection instability.
    fig,ax=plt.subplots(figsize=(9,5))
    for row in trial_rows:
        vals=[r for r in checkpoint_rows if int(r['trial'])==int(row['trial'])]
        ax.plot([int(r['epoch']) for r in vals],[float(r['average_precision']) for r in vals],alpha=.55,
                label=f"{row['optimizer']} lr={row['lr0']} b={row['batch']} d={row['dropout']}")
    ax.set_xlabel('Epoch checkpoint');ax.set_ylabel('Holdout average precision');ax.set_ylim(-.03,1.03);ax.grid(alpha=.2);ax.legend(fontsize=6,ncol=2)
    fig.tight_layout();fig.savefig(out/'checkpoint_search.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,5));ax.plot([r['false_closed_rate'] for r in threshold_rows],[r['recall'] for r in threshold_rows],marker='.')
    ax.set_xlabel('False closed rate');ax.set_ylabel('Recall');ax.set_xlim(-.03,1.03);ax.set_ylim(-.03,1.03);ax.grid(alpha=.25)
    fig.tight_layout();fig.savefig(out/'threshold_curve.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(5,4));ax.imshow(confusion,cmap='Blues')
    ax.set_xticks([0,1],['not_verified','closed_verified']);ax.set_yticks([0,1],['not_verified','closed_verified'])
    ax.set_xlabel('Predicted');ax.set_ylabel('Actual')
    for (i,j),v in __import__('numpy').ndenumerate(confusion):ax.text(j,i,str(v),ha='center',va='center')
    fig.tight_layout();fig.savefig(out/'best_confusion_matrix.png',dpi=160);plt.close(fig)
    # Training-loss curves copied from each Ultralytics run.
    fig,ax=plt.subplots(figsize=(9,5))
    for row in trial_rows:
        rp=out/'trials'/f"trial_{int(row['trial']):02d}"/'results.csv'
        if not rp.exists():continue
        with rp.open() as f:curve=list(csv.DictReader(f))
        if not curve:continue
        key=next((k for k in curve[0] if 'loss' in k.lower() and 'val' not in k.lower()),None)
        if key:ax.plot(range(1,len(curve)+1),[float(r[key]) for r in curve],alpha=.55,
                       label=f"{row['optimizer']} lr={row['lr0']} b={row['batch']} d={row['dropout']}")
    ax.set_xlabel('Epoch');ax.set_ylabel('Training loss');ax.grid(alpha=.2);ax.legend(fontsize=6,ncol=2)
    fig.tight_layout();fig.savefig(out/'training_curves.png',dpi=160);plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path('dataset_top_closed_verified_strict'))
    parser.add_argument('--output',type=Path,default=Path('runs_top_strict_sweep'))
    parser.add_argument('--device',default='0');parser.add_argument('--epochs',type=int,default=40)
    parser.add_argument('--workers',type=int,default=2);parser.add_argument('--model',default='yolo11n-cls.pt')
    args=parser.parse_args();prov=read_json(args.data/'provenance.json')
    if prov['camera']!='observation.images.top':raise ValueError('Top-view-only dataset required')
    if args.output.exists() and any(args.output.iterdir()):raise ValueError('Choose a new empty --output folder')
    test=args.data/'test'
    if not any(test.rglob('*.jpg')):raise ValueError('Missing 9:1 labeled test holdout images')
    counts={s:{c:len(list((args.data/s/c).glob('*.jpg'))) for c in CLASSES} for s in ('train','test')}
    if counts['test']['closed_verified']<1:raise ValueError('Test holdout has no closed_verified examples')
    args.output.mkdir(parents=True,exist_ok=True);trials_root=args.output/'trials';trials_root.mkdir()
    from ultralytics import YOLO
    from ultralytics.models.yolo.classify.train import ClassificationTrainer
    class TrainOnlyTrainer(ClassificationTrainer):
        def validate(self):self.metrics={};return {},0.0
    grid=[(opt,lr,batch,dropout)
          for opt,lrs in (('AdamW',[0.0001,0.0003,0.001]),('SGD',[0.001,0.003,0.01]))
          for lr,batch,dropout in itertools.product(lrs,[16,32],[0.0,0.15])]
    all_checkpoint_rows=[];trial_rows=[];global_best=None
    for ti,(optimizer,lr0,batch,dropout) in enumerate(grid,1):
        work=trials_root/f'trial_{ti:02d}';work.mkdir()
        data=balanced_data(args.data,work/'data')
        model=YOLO(args.model)
        model.train(data=str(data.resolve()),trainer=TrainOnlyTrainer,epochs=args.epochs,imgsz=prov['size'],
                    batch=batch,device=args.device,workers=args.workers,seed=42,deterministic=True,
                    optimizer=optimizer,lr0=lr0,lrf=.01,weight_decay=.0005,dropout=dropout,
                    patience=0,cos_lr=True,val=False,save_period=1,
                    scale=0.0,fliplr=0.0,flipud=0.0,auto_augment=None,erasing=0.0,
                    hsv_h=.01,hsv_s=.2,hsv_v=.2,project=str(work.resolve()),name='fit',exist_ok=True)
        run_dir=Path(model.trainer.save_dir);weight_dir=run_dir/'weights'
        checkpoints=sorted(weight_dir.glob('epoch*.pt'),key=lambda p:int(p.stem[5:]))
        if not checkpoints and (weight_dir/'last.pt').exists():checkpoints=[weight_dir/'last.pt']
        if not checkpoints:raise RuntimeError(f'No saved checkpoints under {weight_dir}; save_period must be enabled')
        trial_candidates=[]
        for checkpoint in checkpoints:
            epoch=int(checkpoint.stem[5:]) if checkpoint.stem.startswith('epoch') else args.epochs
            paths,labels,probs=predict(YOLO(str(checkpoint)),test,prov['size'],args.device)
            ap=average_precision(labels,probs);m05=metrics(labels,probs,.5);safe,threshold_rows=choose_threshold(labels,probs)
            row=dict(trial=ti,epoch=epoch,optimizer=optimizer,lr0=lr0,batch=batch,dropout=dropout,
                     average_precision=ap,f1_at_0_5=m05['f1'],precision_at_0_5=m05['precision'],
                     recall_at_0_5=m05['recall'],zero_fp_recall=safe['recall'],zero_fp_threshold=safe['threshold'],
                     zero_fp_false_positives=safe['fp'])
            all_checkpoint_rows.append(row);trial_candidates.append((row,checkpoint,safe))
            key=(ap,safe['recall'],m05['f1'],-epoch)
            if global_best is None or key>global_best[0]:
                global_best=(key,row,checkpoint,safe)
                shutil.copy2(checkpoint,args.output/'best.pt')
            del paths,labels,probs
        best_row,best_checkpoint,best_safe=max(trial_candidates,key=lambda x:(float(x[0]['average_precision']),float(x[0]['zero_fp_recall']),float(x[0]['f1_at_0_5']),-int(x[0]['epoch'])))
        trial_rows.append(dict(trial=ti,optimizer=optimizer,lr0=lr0,batch=batch,dropout=dropout,
                               best_epoch=best_row['epoch'],best_ap=best_row['average_precision'],
                               f1_at_0_5=best_row['f1_at_0_5'],safe_recall=best_row['zero_fp_recall'],
                               safe_threshold=best_row['zero_fp_threshold']))
        if (run_dir/'results.csv').exists():shutil.copy2(run_dir/'results.csv',work/'results.csv')
        shutil.rmtree(run_dir,ignore_errors=True);shutil.rmtree(work/'data',ignore_errors=True)
        print(f"{ti}/{len(grid)} best epoch={best_row['epoch']} AP={best_row['average_precision']:.4f} {optimizer} lr={lr0} batch={batch} dropout={dropout}",flush=True)
        del model
    _,winner,_,winner_safe=global_best
    # Re-infer the selected checkpoint once to save per-image evidence and plots.
    best_model=YOLO(str(args.output/'best.pt'))
    paths,labels,probs=predict(best_model,test,prov['size'],args.device)
    selected_threshold,threshold_rows=choose_threshold(labels,probs)
    write_csv(args.output/'results.csv',trial_rows)
    write_csv(args.output/'checkpoint_results.csv',all_checkpoint_rows)
    write_csv(args.output/'threshold_results.csv',threshold_rows)
    write_csv(args.output/'test_predictions.csv',[dict(image=p.name,label=y,probability=q) for p,y,q in zip(paths,labels,probs)])
    selection={k:winner[k] for k in ('optimizer','lr0','batch','dropout','epoch','average_precision')}
    selection.update(weights=str((args.output/'best.pt').resolve()),size=prov['size'],threshold=selected_threshold['threshold'],
                     selection_split='dataset/test (internal 9:1 parameter-selection holdout)',
                     holdout_metrics=selected_threshold,external_video='test_classification.mp4 (reserved for human review)')
    write_json(args.output/'selected.json',selection)
    confusion=[[selected_threshold['tn'],selected_threshold['fp']],[selected_threshold['fn'],selected_threshold['tp']]]
    plot_results(args.output,trial_rows,all_checkpoint_rows,winner,threshold_rows,confusion)
    print('best.pt and selected.json saved; selected settings:',selection)

if __name__=='__main__':main()
