import os
import pytest
from fastapi.testclient import TestClient
from server.app import app, recorder

client = TestClient(app)

def test_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "positions" in data
    assert len(data["positions"]) == 6
    assert "recorder" in data
    assert "is_brought_up" in data

def test_bringup_gating_and_lifecycle():
    # 1. Reset to Server OFF (Not brought up)
    res_off = client.post("/api/server_off")
    assert res_off.status_code == 200
    assert res_off.json()["is_brought_up"] is False

    # 2. Verify gating: jog & preset & start_record MUST return 400
    res_jog_blocked = client.post("/api/arm/jog", json={"joint_index": 0, "delta": 0.1})
    assert res_jog_blocked.status_code == 400
    assert "BringUp" in res_jog_blocked.json()["detail"]

    res_preset_blocked = client.post("/api/arm/preset/ready")
    assert res_preset_blocked.status_code == 400

    res_rec_blocked = client.post("/api/record/start", json={"task_name": "task_load_s1"})
    assert res_rec_blocked.status_code == 400

    # 3. BringUp Call (Req 1 & 2)
    res_bringup = client.post("/api/bringup")
    assert res_bringup.status_code == 200
    data_bu = res_bringup.json()
    assert data_bu["success"] is True
    assert data_bu["is_brought_up"] is True
    assert len(data_bu["init_pose"]) == 6

    # 4. Now Jog & Preset MUST succeed
    res_jog_ok = client.post("/api/arm/jog", json={"joint_index": 0, "delta": 0.05})
    assert res_jog_ok.status_code == 200
    assert res_jog_ok.json()["success"] is True

    res_preset_ok = client.post("/api/arm/preset/ready")
    assert res_preset_ok.status_code == 200

    # 5. Record Success (Req 3)
    res_start1 = client.post("/api/record/start", json={"task_name": "task_load_s1"})
    assert res_start1.status_code == 200
    for _ in range(10):
        recorder.record_step([0.1]*12, [0.05]*6)
    res_succ = client.post("/api/record/stop_success")
    assert res_succ.status_code == 200
    assert res_succ.json()["status"] == "success"
    assert res_succ.json()["episode_info"]["success"] is True

    # 6. Record Fail (Req 3)
    res_start2 = client.post("/api/record/start", json={"task_name": "task_load_s2"})
    assert res_start2.status_code == 200
    for _ in range(10):
        recorder.record_step([0.2]*12, [0.1]*6)
    res_fail = client.post("/api/record/stop_fail")
    assert res_fail.status_code == 200
    assert res_fail.json()["status"] == "fail"
    assert res_fail.json()["episode_info"]["success"] is False

    # 7. Record Discard (Req 3)
    res_start3 = client.post("/api/record/start", json={"task_name": "task_sort_normal"})
    assert res_start3.status_code == 200
    for _ in range(10):
        recorder.record_step([0.3]*12, [0.15]*6)
    res_discard = client.post("/api/record/discard")
    assert res_discard.status_code == 200

    # 8. Server OFF (Req 4)
    res_off_final = client.post("/api/server_off")
    assert res_off_final.status_code == 200
    assert res_off_final.json()["is_brought_up"] is False

    # 9. Verify Gating is back active
    res_jog_blocked2 = client.post("/api/arm/jog", json={"joint_index": 0, "delta": 0.1})
    assert res_jog_blocked2.status_code == 400
