import pytest
from fastapi.testclient import TestClient
from server.app import app

client = TestClient(app)

def test_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "positions" in data
    assert len(data["positions"]) == 6
    assert "recorder" in data

def test_api_arm_jog():
    res = client.post("/api/arm/jog", json={"joint_index": 0, "delta": 0.1})
    assert res.status_code == 200
    assert res.json()["success"] is True

def test_api_arm_preset():
    res = client.post("/api/arm/preset/ready")
    assert res.status_code == 200
    assert res.json()["preset"] == "ready"

def test_api_torque_toggle():
    res = client.post("/api/arm/torque", json={"enable": False})
    assert res.status_code == 200
    assert res.json()["torque_enabled"] is False

    res_on = client.post("/api/arm/torque", json={"enable": True})
    assert res_on.status_code == 200
    assert res_on.json()["torque_enabled"] is True

def test_api_record_lifecycle():
    # Start
    res_start = client.post("/api/record/start", json={"task_name": "task_load_s1"})
    assert res_start.status_code == 200
    assert res_start.json()["success"] is True

    # Check status
    res_stat = client.get("/api/status")
    assert res_stat.json()["recorder"]["recording"] is True

    # Discard
    res_discard = client.post("/api/record/discard")
    assert res_discard.status_code == 200
    assert res_discard.json()["success"] is True
