"""Build a movable-object draft from v009 layout. No robot devices."""
import json,shutil,sys
from pathlib import Path
import xml.etree.ElementTree as E
import numpy as np

def prepare(source,out,cfg):
    shutil.copytree(source,out)
    path=out/'robotis_omx/omx.xml';robot=E.parse(path)
    robot.find('compiler').set('meshdir',str((out/'robotis_omx/assets').resolve()))
    k=robot.find('keyframe')
    if k is not None:robot.getroot().remove(k)
    robot.write(path)
    scene=E.parse(out/'scene.xml');wb=scene.find('worldbody')
    friction=' '.join(map(str,cfg['friction']))
    for i in range(2):
        geoms=[g for g in wb.findall('geom') if g.get('name','').startswith(f'shoe{i}_')]
        original=next(g for g in geoms if g.get('name')==f'shoe{i}_sole')
        origin=np.fromstring(original.get('pos'),sep=' ')
        body=E.SubElement(wb,'body',name=f'shoe{i}',pos=' '.join(map(str,origin)))
        E.SubElement(body,'freejoint',name=f'shoe{i}_free')
        for g in geoms:
            wb.remove(g)
            if g.get('pos') is not None:g.set('pos',' '.join(map(str,np.fromstring(g.get('pos'),sep=' ')-origin)))
            if g.get('fromto') is not None:g.set('fromto',' '.join(map(str,(np.fromstring(g.get('fromto'),sep=' ').reshape(2,3)-origin).ravel())))
            if g is original:g.set('mass',str(cfg['shoe_mass_kg']));g.set('friction',friction)
            body.append(g)
    old=wb.find("geom[@name='closed_box_placeholder']")
    center=np.fromstring(old.get('pos'),sep=' '); half=np.fromstring(old.get('size'),sep=' ')
    origin=center.copy();origin[2]-=half[2];wb.remove(old)
    for g in list(wb.findall('geom')):
        if g.get('name','').startswith('box_seam'):wb.remove(g)
    box=E.SubElement(wb,'body',name='paper_box',pos=' '.join(map(str,origin)))
    E.SubElement(box,'freejoint',name='box_free')
    t=cfg['wall_thickness_m'];w,d,h=half[0]*2,half[1]*2,half[2]*2
    def geom(body,name,pos,size,mass,color):
        E.SubElement(body,'geom',name=name,type='box',pos=' '.join(map(str,pos)),size=' '.join(map(str,size)),mass=str(mass),friction=friction,rgba=color)
    geom(box,'box_bottom',[0,0,t/2],[w/2,d/2,t/2],cfg['box_mass_kg']/5,'.60 .40 .22 1')
    for s in [-1,1]:
        geom(box,f'box_wall_x{s}',[s*(w-t)/2,0,(h+t)/2],[t/2,d/2,(h-t)/2],cfg['box_mass_kg']/5,'.60 .40 .22 1')
        geom(box,f'box_wall_y{s}',[0,s*(d-t)/2,(h+t)/2],[(w-2*t)/2,t/2,(h-t)/2],cfg['box_mass_kg']/5,'.60 .40 .22 1')
    # Detachable cap assumption: separate free body, not welded to box.
    lid=E.SubElement(wb,'body',name='paper_lid',pos=' '.join(map(str,origin+[0,0,h+.002])))
    E.SubElement(lid,'freejoint',name='lid_free')
    clear=cfg['lid_clearance_m'];outerx=w/2+clear+t;outery=d/2+clear+t;skirt=.01
    geom(lid,'lid_top',[0,0,t/2],[outerx,outery,t/2],cfg['lid_mass_kg']/5,'.69 .49 .28 1')
    for s in [-1,1]:
        geom(lid,f'lid_x{s}',[s*(outerx-t/2),0,-skirt/2],[t/2,outery,skirt/2],cfg['lid_mass_kg']/5,'.69 .49 .28 1')
        geom(lid,f'lid_y{s}',[0,s*(outery-t/2),-skirt/2],[outerx-t,t/2,skirt/2],cfg['lid_mass_kg']/5,'.69 .49 .28 1')
    mobile=cfg['logistics_robot'];px,py=mobile['center_xy_m'];z=mobile['tray_height_m']
    E.SubElement(wb,'geom',name='logistics_robot_PROXY',type='cylinder',pos=f'{px} {py} {z/2}',size=f'{mobile["radius_m"]} {z/2}',rgba='.2 .4 .65 1')
    E.SubElement(wb,'site',name='loading_target_UNMEASURED',pos=f'{px} {py} {z+.001}',size='.01',rgba='1 .7 0 1')
    scene.write(out/'scene.xml')
    (out/'dynamics.json').write_text(json.dumps(cfg,indent=2))
    return out/'scene.xml'
if __name__=='__main__':prepare(Path(sys.argv[1]),Path(sys.argv[2]),json.loads(Path(sys.argv[3]).read_text()))
