"""Top-view closed-verification inference. Prints observations; it never issues robot commands."""
import argparse
import json
from pathlib import Path
from common import CLASSES, square, read_json

class TopPredictor:
    def __init__(self, selection, device='cpu'):
        from ultralytics import YOLO
        config=read_json(selection)
        self.size=config['size'];self.threshold=config.get('threshold',.95)
        self.model=YOLO(config['weights'])
        if set(self.model.names.values())!=set(CLASSES):
            raise ValueError('Expected not_verified/closed_verified classes trained on top-view images')
        self.device=device

    def predict(self,bgr):
        result=self.model.predict(square(bgr,self.size),imgsz=self.size,device=self.device,verbose=False)[0]
        return {name:float(result.probs.data[i]) for i,name in result.names.items()}

def main():
    import cv2
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--selection',type=Path,required=True)
    p.add_argument('--source',required=True,help='top camera index or top-view video path')
    p.add_argument('--device',default='cpu')
    a=p.parse_args();predictor=TopPredictor(a.selection,a.device)
    cap=cv2.VideoCapture(int(a.source) if a.source.isdecimal() else a.source)
    if not cap.isOpened():raise SystemExit('Cannot open top-view source')
    try:
        while True:
            ok,frame=cap.read()
            if not ok:break
            probs=predictor.predict(frame)
            print(json.dumps({'probabilities':probs,'closed_verified_candidate':probs['closed_verified']>=predictor.threshold}),flush=True)
    finally:cap.release()
if __name__=='__main__':main()
