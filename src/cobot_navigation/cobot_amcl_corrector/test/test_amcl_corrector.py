"""cobot_amcl_corrector 단위 테스트.

검증 항목:
1. OverheadLocalizer Homography 투영 및 로봇 마커(ID 10~12 -> pinky1~3) 위치/방향 산출
2. VisionPoseStore 500ms 신선도(VISION_FRESH / VISION_STALE / VISION_NEVER) 및 스키마 검증
3. 정본(canonical gate67) <-> 실물(cobot_map_v9) 좌표 변환 정확도 (I1: (1.415, 1.639) <-> (0.0, 0.0))
4. AmclVisionCorrector 4중 안전 게이트:
   - 3회 연속 확인(confirm_count=3) 전에는 /initialpose 미발행, 3회째 원샷 발행
   - 주행 중(MOVING_TO_MAIN 등)에는 드리프트가 커도 자동 보정 억제 (버벅임 방지)
   - 원샷 보정 후 쿨다운(5.0초) 동안 재발행 억제
   - 운용자 수동 동기화(manual_sync) 즉시 원샷 발행 및 STALE/주행중 거부 검증
"""
from __future__ import annotations

import math
import numpy as np

from cobot_amcl_corrector.overhead_localizer import (
    OverheadConfig,
    OverheadLocalizer,
    TabletVisionService,
)
from cobot_amcl_corrector.pose_corrector import AmclVisionCorrector
from cobot_amcl_corrector.vision_ingest import (
    VISION_FRESH,
    VISION_NEVER,
    VISION_STALE,
    VisionPoseStore,
    canonical_to_v9,
    v9_to_canonical,
)


def _synthetic_marker_corners(cx: float, cy: float, half: float = 10.0) -> np.ndarray:
    """+X 방향(yaw=0)을 바라보는 정사각형 마커의 픽셀 코너 4개(TL, TR, BR, BL)를 생성한다."""
    return np.array(
        [
            [cx + half, cy + half],  # 0: front-left
            [cx + half, cy - half],  # 1: front-right
            [cx - half, cy - half],  # 2: back-right
            [cx - half, cy + half],  # 3: back-left
        ],
        dtype=np.float64,
    )


def test_overhead_localizer_and_tablet_service_three_robots():
    # 1m = 100px 스케일의 이상적인 항공뷰 픽셀 좌표
    cfg = OverheadConfig()
    service = TabletVisionService(cfg=cfg, frame_id="map", occlusion_after_s=0.5)

    detected = {
        0: _synthetic_marker_corners(0.0, 0.0),
        1: _synthetic_marker_corners(250.0, 0.0),
        2: _synthetic_marker_corners(250.0, 240.0),
        3: _synthetic_marker_corners(0.0, 240.0),
        10: _synthetic_marker_corners(141.5, 163.9),  # pinky1 at I1 (1.415, 1.639)
        11: _synthetic_marker_corners(141.5, 143.9),  # pinky2 at I2 (1.415, 1.439)
        12: _synthetic_marker_corners(141.5, 123.9),  # pinky3 at I3 (1.415, 1.239)
    }

    t0_ns = 1_000_000_000
    fixes = service.process_detected(detected, now_ns=t0_ns)
    assert len(fixes) == 3

    by_id = {f.robot_id: f for f in fixes}
    assert set(by_id.keys()) == {"pinky1", "pinky2", "pinky3"}
    assert abs(by_id["pinky1"].x - 1.415) < 1e-3
    assert abs(by_id["pinky1"].y - 1.639) < 1e-3
    assert abs(by_id["pinky1"].yaw - 0.0) < 1e-3
    assert not service.is_occluded("pinky1", now_ns=t0_ns + 200_000_000)
    assert service.is_occluded("pinky1", now_ns=t0_ns + 600_000_000)


def test_vision_pose_store_freshness_and_validation():
    now_ms = [1000]
    store = VisionPoseStore(stale_after_ms=500, clock_ms=lambda: now_ms[0])

    assert store.get("pinky1")["status"] == VISION_NEVER

    ok, err, rec = store.ingest(
        {
            "robot_id": "pinky1",
            "x": 1.415,
            "y": 1.639,
            "yaw": 0.0,
            "reproj_error": 1.2,
            "source_ts": 990,
        }
    )
    assert ok and err is None
    assert rec["status"] == VISION_FRESH

    # 450ms 경과 -> 여전히 FRESH
    now_ms[0] = 1450
    assert store.get("pinky1")["status"] == VISION_FRESH

    # 550ms 경과 -> STALE
    now_ms[0] = 1550
    assert store.get("pinky1")["status"] == VISION_STALE

    # reproj_error > 4.0px 거부 확인
    ok_bad, err_bad, _ = store.ingest(
        {
            "robot_id": "pinky1",
            "x": 1.0,
            "y": 1.0,
            "yaw": 0.0,
            "reproj_error": 5.5,
            "source_ts": 1550,
        }
    )
    assert not ok_bad and "reproj_error" in err_bad


def test_coordinate_frame_conversion_v9_and_canonical():
    # I1 홈 위치: cobot_map_v9 (0.0, 0.0) <-> 정본 gate67 (1.415, 1.639)
    cx, cy = v9_to_canonical(0.0, 0.0)
    assert (cx, cy) == (1.415, 1.639)

    vx, vy = canonical_to_v9(1.415, 1.639)
    assert (vx, vy) == (0.0, 0.0)

    # P1 웨이포인트: cobot_map_v9 (0.17, -0.6) <-> 정본 gate67 (1.585, 1.039)
    p1_can = v9_to_canonical(0.17, -0.6)
    assert p1_can == (1.585, 1.039)


def test_amcl_corrector_three_step_confirm_moving_guard_and_cooldown():
    now_ms = [10_000]
    now_sec = [10.0]
    store = VisionPoseStore(stale_after_ms=500, clock_ms=lambda: now_ms[0])
    corrector = AmclVisionCorrector(
        store=store,
        drift_dist_m=0.15,
        drift_yaw_rad=math.radians(20.0),
        confirm_count=3,
        cooldown_sec=5.0,
        frame_mode="canonical_to_v9",
        clock_sec=lambda: now_sec[0],
    )

    # pinky1의 실물 AMCL(v9 프레임)이 드리프트가 발생해 (0.25, 0.0, 0.0)으로 밀려난 상황 가정
    # 실제 항공뷰(정본 프레임)에서는 I1 (1.415, 1.639) == v9 (0.0, 0.0)에 정지해 있음 (오차 0.25m >= 0.15m)
    corrector.update_amcl_pose("pinky1", x=0.25, y=0.0, yaw=0.0)

    # 1) 주행 중(MOVING_TO_MAIN)일 때는 비전 데이터가 들어와도 자동 보정을 수행하지 않아야 함
    corrector.update_robot_state("pinky1", "MOVING_TO_MAIN", linear_speed_mps=0.08)
    for _ in range(4):
        store.ingest(
            {
                "robot_id": "pinky1",
                "x": 1.415,
                "y": 1.639,
                "yaw": 0.0,
                "reproj_error": 0.8,
                "source_ts": now_ms[0],
            }
        )
        assert corrector.evaluate_robot("pinky1") is None

    # 2) 로봇이 대기 상태(HOLDING_ZONE:zone_A)로 정지하면 3회 연속 확인 후 3번째에 원샷 발행
    corrector.update_robot_state("pinky1", "HOLDING_ZONE:zone_A", linear_speed_mps=0.0)

    # 1회차 확인 -> 아직 미발행
    store.ingest(
        {
            "robot_id": "pinky1",
            "x": 1.415,
            "y": 1.639,
            "yaw": 0.0,
            "reproj_error": 0.8,
            "source_ts": now_ms[0],
        }
    )
    assert corrector.evaluate_robot("pinky1") is None
    assert corrector.trackers["pinky1"].confirm_streak == 1

    # 2회차 확인 -> 아직 미발행
    now_ms[0] += 100
    now_sec[0] += 0.1
    store.ingest(
        {
            "robot_id": "pinky1",
            "x": 1.415,
            "y": 1.639,
            "yaw": 0.0,
            "reproj_error": 0.8,
            "source_ts": now_ms[0],
        }
    )
    assert corrector.evaluate_robot("pinky1") is None
    assert corrector.trackers["pinky1"].confirm_streak == 2

    # 3회차 확인 -> 원샷 InitialPoseCommand 발행 (v9 좌표 (0.0, 0.0)으로 변환되어 발행됨)
    now_ms[0] += 100
    now_sec[0] += 0.1
    store.ingest(
        {
            "robot_id": "pinky1",
            "x": 1.415,
            "y": 1.639,
            "yaw": 0.0,
            "reproj_error": 0.8,
            "source_ts": now_ms[0],
        }
    )
    cmd = corrector.evaluate_robot("pinky1")
    assert cmd is not None
    assert cmd.robot_id == "pinky1"
    assert cmd.reason == "auto_drift"
    assert abs(cmd.x - 0.0) < 1e-4
    assert abs(cmd.y - 0.0) < 1e-4
    assert abs(cmd.drift_dist_m - 0.25) < 1e-3

    # 3) 쿨다운(5초) 이내에 다시 드리프트가 생겨도 재발행 억제 확인
    corrector.update_amcl_pose("pinky1", x=0.30, y=0.0, yaw=0.0)
    now_ms[0] += 500
    now_sec[0] += 0.5
    for _ in range(3):
        store.ingest(
            {
                "robot_id": "pinky1",
                "x": 1.415,
                "y": 1.639,
                "yaw": 0.0,
                "reproj_error": 0.8,
                "source_ts": now_ms[0],
            }
        )
        assert corrector.evaluate_robot("pinky1") is None
        assert corrector.trackers["pinky1"].last_reason == "COOLDOWN"

    # 4) 운용자 수동 동기화(manual_sync)는 쿨다운과 무관하게 VISION_FRESH면 즉시 원샷 발행
    ok, reason, manual_cmd = corrector.manual_sync("pinky1")
    assert ok and reason == "ok" and manual_cmd is not None
    assert manual_cmd.reason == "manual_sync"
    assert abs(manual_cmd.x - 0.0) < 1e-4


def test_amcl_corrector_ros2_node_integration():
    """AmclCorrectorNode가 /amcl_pose, /overhead_pose를 수신해 /initialpose를 발행하는지 검증한다."""
    import rclpy
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
    from cobot_amcl_corrector.amcl_corrector_node import AmclCorrectorNode

    rclpy.init()
    try:
        node = AmclCorrectorNode()
        received = []
        sub = node.create_subscription(
            PoseWithCovarianceStamped,
            "/pinky1/initialpose",
            lambda msg: received.append(msg),
            10,
        )

        # 드리프트된 AMCL 포즈 주입: (1.70, 2.054) -> 실제 위치(1.41, 2.054)와 0.29m 오차
        amcl_msg = PoseWithCovarianceStamped()
        amcl_msg.header.frame_id = "map"
        amcl_msg.pose.pose.position.x = 1.70
        amcl_msg.pose.pose.position.y = 2.054
        amcl_msg.pose.pose.orientation.w = 1.0
        node._on_amcl_pose("pinky1", amcl_msg)

        # 오버헤드 실제 포즈 3회 연속 주입 (confirm_count=3)
        ov_msg = PoseStamped()
        ov_msg.header.frame_id = "map"
        ov_msg.pose.position.x = 1.41
        ov_msg.pose.position.y = 2.054
        ov_msg.pose.orientation.w = 1.0

        for _ in range(3):
            node._on_overhead_pose("pinky1", ov_msg)
            rclpy.spin_once(node, timeout_sec=0.05)

        assert len(received) == 1
        assert abs(received[0].pose.pose.position.x - 1.41) < 1e-3
        assert abs(received[0].pose.pose.position.y - 2.054) < 1e-3

        node.destroy_subscription(sub)
        node.destroy_node()
    finally:
        if rclpy.ok():
            rclpy.shutdown()

