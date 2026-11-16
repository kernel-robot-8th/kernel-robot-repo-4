"""실제 순찰 상태(JSON)와 odom 속도로 보정 게이트가 도는지 본다."""
from __future__ import annotations

import json

from cobot_amcl_corrector.pose_corrector import AmclVisionCorrector
from cobot_amcl_corrector.vision_ingest import VisionPoseStore


def status(state: str) -> str:
    """pinky_patrol_node 가 /patrol_status 로 내는 모양."""
    return json.dumps(
        {"state": state, "waypoint": 1, "total": 1, "detail": "ZA"}, ensure_ascii=False
    )


class Rig:
    def __init__(self) -> None:
        self.sec = 100.0
        self.store = VisionPoseStore(clock_ms=lambda: int(self.sec * 1000))
        self.corrector = AmclVisionCorrector(
            store=self.store, clock_sec=lambda: self.sec
        )
        self.corrector.update_amcl_pose("pinky1", 0.0, 0.0, 0.0)

    def see(self, x: float = 0.3):
        self.sec += 0.2
        self.store.ingest(
            {
                "robot_id": "pinky1",
                "x": x,
                "y": 0.0,
                "yaw": 0.0,
                "reproj_error": 0.5,
                "source_ts": 1,
            }
        )
        return self.corrector.evaluate_robot("pinky1")

    def still(self) -> None:
        self.corrector.update_robot_speed("pinky1", 0.0)

    def reason(self) -> str:
        return self.corrector.trackers["pinky1"].last_reason


def fired(rig: Rig, frames: int = 3, keep_speed: bool = True) -> list:
    out = []
    for _ in range(frames):
        if keep_speed:
            rig.still()
        out.append(rig.see() is not None)
    return out


def test_real_json_state_fires_on_third_frame():
    rig = Rig()
    rig.corrector.update_robot_state("pinky1", status("HOLDING_ZONE"))
    assert fired(rig) == [False, False, True]


def test_terminal_patrol_states_count_as_stationary():
    for state in ("DONE", "IDLE_WAIT", "IDLE", "STOPPED"):
        rig = Rig()
        rig.corrector.update_robot_state("pinky1", status(state))
        assert fired(rig) == [False, False, True], state


def test_driving_states_never_fire():
    for state in ("MOVING", "RETURNING", "LEAVING_ZONE", "RETREATING", "STARTING"):
        rig = Rig()
        rig.corrector.update_robot_state("pinky1", status(state))
        assert fired(rig, 5) == [False] * 5, state
        assert rig.reason() == f"MOVING({state})"


def test_legacy_colon_state_still_reads():
    rig = Rig()
    rig.corrector.update_robot_state("pinky1", "HOLDING_ZONE:zone_A")
    assert fired(rig) == [False, False, True]


def test_unreadable_status_blocks_correction():
    for raw in ("{broken", "", "[1]", '{"detail": "no state"}', '{"state": 3}'):
        rig = Rig()
        rig.corrector.update_robot_state("pinky1", raw)
        assert fired(rig, 5) == [False] * 5, raw


def test_no_status_yet_blocks_correction():
    rig = Rig()
    assert fired(rig, 5) == [False] * 5


def test_status_message_does_not_erase_measured_speed():
    rig = Rig()
    rig.corrector.update_robot_speed("pinky1", 0.12)
    rig.corrector.update_robot_state("pinky1", status("HOLDING_ZONE"))
    assert fired(rig, 4, keep_speed=False) == [False] * 4
    assert rig.reason().startswith("MOVING(HOLDING_ZONE")


def test_missing_or_old_speed_blocks_correction():
    rig = Rig()
    rig.corrector.update_robot_state("pinky1", status("HOLDING_ZONE"))
    assert fired(rig, 3, keep_speed=False) == [False] * 3
    assert rig.reason() == "SPEED_STALE"

    rig.still()
    rig.sec += 2.0
    assert rig.see() is None
    assert rig.reason() == "SPEED_STALE"


def test_stale_speed_resets_confirmation():
    rig = Rig()
    rig.corrector.update_robot_state("pinky1", status("HOLDING_ZONE"))
    assert fired(rig, 2) == [False, False]
    rig.sec += 2.0
    assert rig.see() is None
    assert rig.corrector.trackers["pinky1"].confirm_streak == 0


def test_manual_sync_uses_real_status_and_refuses_driving():
    rig = Rig()
    rig.corrector.update_robot_state("pinky1", status("MOVING"))
    rig.still()
    rig.see()
    ok, reason, cmd = rig.corrector.manual_sync("pinky1")
    assert not ok and cmd is None and "MOVING" in reason

    rig.corrector.update_robot_state("pinky1", status("HOLDING_ZONE"))
    rig.still()
    ok, _, cmd = rig.corrector.manual_sync("pinky1")
    assert ok and cmd.reason == "manual_sync"


def test_status_snapshot_shows_why():
    rig = Rig()
    rig.corrector.update_robot_state("pinky1", status("HOLDING_ZONE"))
    rig.still()
    rig.see()
    row = rig.corrector.status_snapshot()["robots"]["pinky1"]
    assert row["patrol_state"] == "HOLDING_ZONE"
    assert row["stationary"] is True
    assert row["speed_age_sec"] is not None
    assert row["amcl_age_sec"] is not None
