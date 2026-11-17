"""Pad strict top-view images to the same 640x640 gray-letterboxed geometry."""
import json
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'dataset_top_closed_verified_strict'

def main():
    changed=[]
    for split in ('train','test'):
        for cls in ('not_verified','closed_verified'):
            for path in sorted((DATA/split/cls).glob('*.jpg')):
                with Image.open(path) as source:
                    im=source.convert('RGB')
                if im.size==(640,640):continue
                w,h=im.size
                scale=640/max(w,h); nw,nh=round(w*scale),round(h*scale)
                im=im.resize((nw,nh),Image.Resampling.LANCZOS)
                canvas=Image.new('RGB',(640,640),(114,114,114))
                canvas.paste(im,((640-nw)//2,(640-nh)//2))
                canvas.save(path,quality=95)
                changed.append(str(path.relative_to(DATA)))
    p=DATA/'provenance.json';prov=json.loads(p.read_text())
    prov['preprocessing']={'geometry':'640x640 centered letterbox','padding_rgb':[114,114,114],
                           'reason':'Match the original FFmpeg-extracted not_verified frames to raw strict_plus frames'}
    p.write_text(json.dumps(prov,ensure_ascii=False,indent=2))
    print(f'Padded {len(changed)} images; all train/test images now use a 640x640 canvas.')
    print('\n'.join(changed[:12]))
if __name__=='__main__':main()
