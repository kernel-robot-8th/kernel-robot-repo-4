"""Smooth closed shoe envelope, not a scan, hollow upper or cloth model. Toe is +x."""
import math
import numpy as np

def shoe_mesh(length,width,toe_height,peak_height,rear_height,rings=16,segments=64):
    def profile(x):
        t=min(1.,abs(x)/(length/2)); blend=t*t*(3-2*t)
        end=toe_height if x>=0 else rear_height
        return peak_height+(end-peak_height)*blend
    vertices=[[0,0,peak_height]]; faces=[]
    for ring in range(1,rings+1):
        r=ring/rings
        for i in range(segments):
            theta=2*math.pi*i/segments
            x=length/2*r*math.cos(theta); y=width/2*r*math.sin(theta)
            # Rounded transverse crown, endpoint heights preserved on centerline.
            z=profile(x)*(1-.20*(y/(width/2))**2)
            vertices.append([x,y,z])
    for i in range(segments):faces.append([0,1+i,1+(i+1)%segments])
    for ring in range(1,rings):
        inner=1+(ring-1)*segments;outer=inner+segments
        for i in range(segments):
            n=(i+1)%segments
            faces.extend([[inner+i,outer+i,outer+n],[inner+i,outer+n,inner+n]])
    outer=1+(rings-1)*segments;bottom=len(vertices)
    for i in range(segments):vertices.append([*vertices[outer+i][:2],0])
    center=len(vertices);vertices.append([0,0,0])
    for i in range(segments):
        n=(i+1)%segments
        faces.extend([[outer+i,bottom+i,bottom+n],[outer+i,bottom+n,outer+n],[center,bottom+n,bottom+i]])
    v=np.array(vertices);f=np.array(faces)
    np.testing.assert_allclose(np.ptp(v[:,:2],axis=0),[length,width],atol=1e-10)
    assert abs(v[:,2].max()-peak_height)<1e-10
    assert abs(v[outer,2]-toe_height)<1e-10
    # Closed, consistently oriented triangle mesh: each edge occurs twice with opposite direction.
    from collections import Counter
    edges=Counter((int(a),int(b)) for tri in f for a,b in zip(tri,np.roll(tri,-1)))
    assert all(count==1 and edges[b,a]==1 for (a,b),count in edges.items())
    return v,f
