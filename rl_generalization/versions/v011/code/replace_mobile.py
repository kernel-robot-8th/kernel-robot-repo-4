"""Replace v010 mobile proxy by a fixed chassis and concave compound tray."""
import json, math, shutil, sys
from pathlib import Path
import xml.etree.ElementTree as E

def build(source, out, cfg):
    shutil.copytree(source, out)
    robot=out/'robotis_omx/omx.xml'
    tree=E.parse(robot); tree.find('compiler').set('meshdir',str((robot.parent/'assets').resolve())); tree.write(robot)
    scene=E.parse(out/'scene.xml'); wb=scene.find('worldbody')
    for tag,name in [('geom','logistics_robot_PROXY'),('site','loading_target_UNMEASURED')]:
        item=wb.find(f"{tag}[@name='{name}']")
        if item is not None: wb.remove(item)
    x,y=cfg['assumed']['center_xy_m']; z=cfg['confirmed']['tray_floor_height_m']
    w,d=cfg['assumed']['chassis_size_xy_m']; t=cfg['assumed']['tray_floor_thickness_m']
    radius=cfg['image_reading']['tray_outer_diameter_m']/2
    h=cfg['assumed']['rim_height_m']; wall=cfg['assumed']['rim_thickness_m']
    body=E.SubElement(wb,'body',name='stationary_logistics_robot',pos=f'{x} {y} 0')
    E.SubElement(body,'geom',name='fixed_rectangular_chassis',type='box',pos=f'0 0 {(z-t)/2}',size=f'{w/2} {d/2} {(z-t)/2}',rgba='.12 .13 .15 1')
    E.SubElement(body,'geom',name='tray_floor',type='cylinder',pos=f'0 0 {z-t/2}',size=f'{radius-wall} {t/2}',rgba='.94 .94 .92 1', solref='0.005 1', solimp='0.99 0.99 0.001', priority='1')
    # Independent tangent boxes retain an open interior; a single mesh convex hull would fill it.
    n=64; r=radius-wall/2
    for i in range(n):
        a=2*math.pi*i/n
        E.SubElement(body,'geom',name=f'tray_rim_{i:02}',type='box',pos=f'{r*math.cos(a)} {r*math.sin(a)} {z+h/2}',size=f'{wall/2} {r*math.tan(math.pi/n)*1.02} {h/2}',euler=f'0 0 {a}',rgba='.96 .96 .94 1')
    E.SubElement(body,'site',name='loading_target_PROVISIONAL',pos=f'0 0 {z+.001}',size='.005',rgba='1 .65 0 1')
    scene.write(out/'scene.xml'); (out/'mobile_layout.json').write_text(json.dumps(cfg,indent=2))
    return out/'scene.xml'
if __name__=='__main__':build(Path(sys.argv[1]),Path(sys.argv[2]),json.loads(Path(sys.argv[3]).read_text()))
