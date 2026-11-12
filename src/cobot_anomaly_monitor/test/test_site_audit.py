from pathlib import Path

from cobot_anomaly_monitor.site_audit import audit


def test_gate67_offset_alone_puts_exit_and_queue_in_wall():
    src = Path(__file__).resolve().parents[2]
    result = audit(src / 'cobot_bringup/config/maps/map_shoe_store_1021_gate67.yaml',
                   src / 'cobot_navigation/cobot_pinky_patrol/config/sites/lab.yaml',
                   src / 'cobot_navigation/cobot_zone_traffic_control/config/zone_params.yaml',
                   (1.415, 1.639))
    assert not result['missing']
    assert result['checked_centers'] == 53
    for name in ('ZC_EXIT', 'queue_C_0', 'queue_C_1', 'queue_C_2'):
        assert result['blocked'][name]['reason'] == 'OCCUPIED'
    assert 'P6' not in result['blocked']
