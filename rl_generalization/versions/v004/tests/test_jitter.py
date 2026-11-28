import pytest
from omx_rl.jitter import analyze

def test_boundary_and_bad_clock():
    rows=[dict(t_s=str(i),joint='j0',act_target=str(x),sent_target=str(x),actual_position=str(x),chunk_id=str(c)) for i,x,c in [(0,0,0),(1,0,0),(2,10,1)]]
    r=analyze(rows)['j0']
    assert r['chunk_boundary_target_delta_mean']==10
    assert r['non_boundary_target_delta_mean']==0
    assert r['tracking_rmse_units']==0
    rows[2]['t_s']='1'
    with pytest.raises(ValueError): analyze(rows)
