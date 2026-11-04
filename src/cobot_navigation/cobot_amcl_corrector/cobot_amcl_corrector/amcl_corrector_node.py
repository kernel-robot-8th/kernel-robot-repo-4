"""ROS 2 Domain 100 AMCL 비전 보정 노드 (amcl_corrector_node).

데이터 흐름:
1. 항공뷰/태블릿 비전 데이터 입력:
   - HTTP POST /api/vision/pose 또는 /api/vision/pose_fix (포트 기본 8785)
   - ROS 2 /amcl_corrector/vision_json (std_msgs/String JSON)
   - ROS 2 /pinky1~3/overhead_pose (geometry_msgs/PoseStamped)
2. 로봇 상태 및 AMCL 추정 포즈 수신 (cobot_domain_bridge 경유):
   - /pinky1~3/amcl_pose (geometry_msgs/PoseWithCovarianceStamped)
   - /pinky1~3/patrol_status (std_msgs/String)
3. 보정 판정 및 원샷 재초기화 발행:
   - 자동 보정(500ms 신선도 + 정지/대기 상태 + 0.15m/20deg 3회 연속 확인 + 5초 쿨다운)
   - 수동 동기화(/amcl_corrector/trigger 토픽 또는 POST /api/vision/sync_amcl)
   - /pinky1~3/initialpose (geometry_msgs/PoseWithCovarianceStamped) 발행
     -> cobot_domain_bridge가 각 로봇(Domain 10, 20, 30)의 /initialpose로 전달.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import threading
import time
from typing import Dict, Optional

from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .pose_corrector import AmclVisionCorrector, InitialPoseCommand
from .vision_ingest import ALLOWED_ROBOTS, VisionPoseStore


def quat_to_yaw(z: float, w: float, x: float = 0.0, y: float = 0.0) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def yaw_to_quat(yaw: float) -> tuple[float, float, float, float]:
    half = 0.5 * float(yaw)
    return (0.0, 0.0, math.sin(half), math.cos(half))


class AmclCorrectorNode(Node):
    def __init__(self) -> None:
        super().__init__("amcl_corrector_node")

        self.declare_parameter("robot_names", list(ALLOWED_ROBOTS))
        self.declare_parameter("stale_after_ms", 500)
        self.declare_parameter("drift_dist_m", 0.15)
        self.declare_parameter("drift_yaw_deg", 20.0)
        self.declare_parameter("confirm_count", 3)
        self.declare_parameter("cooldown_sec", 5.0)
        self.declare_parameter("max_stationary_speed_mps", 0.03)
        self.declare_parameter("frame_mode", "identity")
        self.declare_parameter("target_frame_id", "map")
        self.declare_parameter("cov_x", 0.04)
        self.declare_parameter("cov_y", 0.04)
        self.declare_parameter("cov_yaw", 0.05)
        self.declare_parameter("auto_correct_enabled", True)
        self.declare_parameter("enable_http", True)
        self.declare_parameter("http_host", "0.0.0.0")
        self.declare_parameter("http_port", 8785)

        robot_names = tuple(
            self.get_parameter("robot_names").get_parameter_value().string_array_value
            or ALLOWED_ROBOTS
        )
        stale_after_ms = int(self.get_parameter("stale_after_ms").value)
        drift_dist_m = float(self.get_parameter("drift_dist_m").value)
        drift_yaw_deg = float(self.get_parameter("drift_yaw_deg").value)
        confirm_count = int(self.get_parameter("confirm_count").value)
        cooldown_sec = float(self.get_parameter("cooldown_sec").value)
        max_speed = float(self.get_parameter("max_stationary_speed_mps").value)
        frame_mode = str(self.get_parameter("frame_mode").value)
        target_frame_id = str(self.get_parameter("target_frame_id").value)
        cov_x = float(self.get_parameter("cov_x").value)
        cov_y = float(self.get_parameter("cov_y").value)
        cov_yaw = float(self.get_parameter("cov_yaw").value)
        auto_correct = bool(self.get_parameter("auto_correct_enabled").value)

        self._lock = threading.Lock()
        self.store = VisionPoseStore(
            allowed_robots=robot_names,
            stale_after_ms=stale_after_ms,
        )
        self.corrector = AmclVisionCorrector(
            store=self.store,
            allowed_robots=robot_names,
            drift_dist_m=drift_dist_m,
            drift_yaw_rad=math.radians(drift_yaw_deg),
            confirm_count=confirm_count,
            cooldown_sec=cooldown_sec,
            max_stationary_speed_mps=max_speed,
            frame_mode=frame_mode,
            target_frame_id=target_frame_id,
            cov_x=cov_x,
            cov_y=cov_y,
            cov_yaw=cov_yaw,
            auto_correct_enabled=auto_correct,
        )

        self.initialpose_pubs: Dict[str, object] = {}
        for rid in robot_names:
            self.initialpose_pubs[rid] = self.create_publisher(
                PoseWithCovarianceStamped, f"/{rid}/initialpose", 10
            )
            self.create_subscription(
                PoseWithCovarianceStamped,
                f"/{rid}/amcl_pose",
                lambda msg, r=rid: self._on_amcl_pose(r, msg),
                10,
            )
            self.create_subscription(
                String,
                f"/{rid}/patrol_status",
                lambda msg, r=rid: self._on_patrol_status(r, msg),
                10,
            )
            self.create_subscription(
                PoseStamped,
                f"/{rid}/overhead_pose",
                lambda msg, r=rid: self._on_overhead_pose(r, msg),
                10,
            )

        self.create_subscription(
            String, "/amcl_corrector/vision_json", self._on_vision_json, 20
        )
        self.create_subscription(
            String, "/amcl_corrector/trigger", self._on_trigger, 10
        )
        self.status_pub = self.create_publisher(String, "/amcl_corrector/status", 10)
        self.create_timer(0.5, self._publish_status)

        self._http_server: Optional[ThreadingHTTPServer] = None
        if bool(self.get_parameter("enable_http").value):
            host = str(self.get_parameter("http_host").value)
            port = int(self.get_parameter("http_port").value)
            self._start_http_server(host, port)

        self.get_logger().info(
            f"AMCL Corrector started for {robot_names} "
            f"(frame_mode={frame_mode}, drift={drift_dist_m}m/{drift_yaw_deg}deg, "
            f"confirm={confirm_count}, cooldown={cooldown_sec}s)"
        )

    def _on_amcl_pose(self, robot_id: str, msg: PoseWithCovarianceStamped) -> None:
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        yaw = quat_to_yaw(q.z, q.w, q.x, q.y)
        with self._lock:
            self.corrector.update_amcl_pose(robot_id, p.x, p.y, yaw)

    def _on_patrol_status(self, robot_id: str, msg: String) -> None:
        with self._lock:
            self.corrector.update_robot_state(robot_id, msg.data)

    def _on_overhead_pose(self, robot_id: str, msg: PoseStamped) -> None:
        p = msg.pose.position
        q = msg.pose.orientation
        yaw = quat_to_yaw(q.z, q.w, q.x, q.y)
        payload = {
            "robot_id": robot_id,
            "x": float(p.x),
            "y": float(p.y),
            "yaw": float(yaw),
            "reproj_error": 0.5,
            "source_ts": int(time.time() * 1000),
            "frame_id": msg.header.frame_id or "map",
        }
        self.handle_vision_payload(payload, is_pose_fix=False)

    def _on_vision_json(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except Exception as exc:
            self.get_logger().warning(f"Invalid vision_json payload: {exc}")
            return
        is_pose_fix = "header" in payload and "reprojection_error_px" in payload
        self.handle_vision_payload(payload, is_pose_fix=is_pose_fix)

    def handle_vision_payload(
        self, payload: dict, is_pose_fix: bool = False
    ) -> tuple[bool, Optional[str], Optional[dict]]:
        with self._lock:
            if is_pose_fix:
                ok, err, decorated = self.store.ingest_pose_fix(payload)
            else:
                ok, err, decorated = self.store.ingest(payload)
            if not ok or decorated is None:
                return False, err, None
            rid = payload.get("robot_id", "")
            cmd = self.corrector.evaluate_robot(rid)
        if cmd is not None:
            self._emit_initialpose(cmd)
        return True, None, decorated

    def _on_trigger(self, msg: String) -> None:
        raw = (msg.data or "").strip()
        if not raw:
            return
        lower = raw.lower()
        if lower.startswith("auto:"):
            mode = lower.split(":", 1)[1].strip()
            with self._lock:
                self.corrector.auto_correct_enabled = mode in ("on", "true", "1")
            self.get_logger().info(
                f"Auto AMCL correction set to {self.corrector.auto_correct_enabled}"
            )
            self._publish_status()
            return

        if lower.startswith("frame:"):
            new_frame = raw.split(":", 1)[1].strip()
            with self._lock:
                self.corrector.frame_mode = new_frame
            self.get_logger().info(f"Frame mode updated to {new_frame}")
            self._publish_status()
            return

        if lower.startswith("sync:") or lower.startswith("force_sync:"):
            force = lower.startswith("force_sync:")
            target = raw.split(":", 1)[1].strip()
            targets = (
                list(self.corrector.allowed_robots)
                if target.lower() == "all"
                else [target]
            )
            for rid in targets:
                with self._lock:
                    ok, reason, cmd = self.corrector.manual_sync(
                        rid, force_while_moving=force
                    )
                if ok and cmd is not None:
                    self._emit_initialpose(cmd)
                else:
                    self.get_logger().warning(f"Manual sync skipped for {rid}: {reason}")
            self._publish_status()

    def _emit_initialpose(self, cmd: InitialPoseCommand) -> None:
        pub = self.initialpose_pubs.get(cmd.robot_id)
        if pub is None:
            return
        msg = PoseWithCovarianceStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = cmd.frame_id
        msg.pose.pose.position.x = float(cmd.x)
        msg.pose.pose.position.y = float(cmd.y)
        msg.pose.pose.position.z = 0.0
        qx, qy, qz, qw = yaw_to_quat(cmd.yaw)
        msg.pose.pose.orientation.x = qx
        msg.pose.pose.orientation.y = qy
        msg.pose.pose.orientation.z = qz
        msg.pose.pose.orientation.w = qw

        cov = [0.0] * 36
        cov[0] = float(cmd.cov_x)
        cov[7] = float(cmd.cov_y)
        cov[35] = float(cmd.cov_yaw)
        msg.pose.covariance = cov
        pub.publish(msg)

        self.get_logger().info(
            f"[{cmd.robot_id}] Published /initialpose ({cmd.reason}): "
            f"x={cmd.x:.3f}, y={cmd.y:.3f}, yaw={math.degrees(cmd.yaw):.1f}deg "
            f"(drift={cmd.drift_dist_m:.3f}m / {math.degrees(cmd.drift_yaw_rad):.1f}deg)"
        )

    def _publish_status(self) -> None:
        with self._lock:
            snap = self.corrector.status_snapshot()
        out = String()
        out.data = json.dumps(snap, ensure_ascii=False)
        self.status_pub.publish(out)

    def _start_http_server(self, host: str, port: int) -> None:
        node_ref = self

        class VisionGatewayHandler(BaseHTTPRequestHandler):
            def _send_json(self, code: int, body: dict) -> None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/api/vision/status"):
                    with node_ref._lock:
                        snap = node_ref.corrector.status_snapshot()
                    self._send_json(200, {"ok": True, "data": snap})
                    return
                self._send_json(404, {"ok": False, "error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception as exc:
                    self._send_json(400, {"ok": False, "error": f"invalid json: {exc}"})
                    return

                if self.path == "/api/vision/pose":
                    ok, err, rec = node_ref.handle_vision_payload(
                        payload, is_pose_fix=False
                    )
                    if not ok:
                        self._send_json(400, {"ok": False, "error": err})
                        return
                    self._send_json(200, {"ok": True, "record": rec})
                    return

                if self.path == "/api/vision/pose_fix":
                    ok, err, rec = node_ref.handle_vision_payload(
                        payload, is_pose_fix=True
                    )
                    if not ok:
                        self._send_json(400, {"ok": False, "error": err})
                        return
                    self._send_json(200, {"ok": True, "record": rec})
                    return

                if self.path == "/api/vision/sync_amcl":
                    rid = str(payload.get("robot_id", "all"))
                    force = bool(payload.get("force", False))
                    targets = (
                        list(node_ref.corrector.allowed_robots)
                        if rid == "all"
                        else [rid]
                    )
                    results = {}
                    for t in targets:
                        with node_ref._lock:
                            ok, reason, cmd = node_ref.corrector.manual_sync(
                                t, force_while_moving=force
                            )
                        if ok and cmd is not None:
                            node_ref._emit_initialpose(cmd)
                            results[t] = {"ok": True, "command": cmd.to_dict()}
                        else:
                            results[t] = {"ok": False, "reason": reason}
                    self._send_json(200, {"ok": True, "results": results})
                    return

                self._send_json(404, {"ok": False, "error": "not found"})

            def log_message(self, format: str, *args) -> None:  # noqa: A002
                return

        try:
            self._http_server = ThreadingHTTPServer((host, port), VisionGatewayHandler)
            thread = threading.Thread(
                target=self._http_server.serve_forever, daemon=True
            )
            thread.start()
            self.get_logger().info(f"Vision HTTP gateway listening on {host}:{port}")
        except OSError as exc:
            self.get_logger().warning(
                f"Could not bind HTTP server on {host}:{port} ({exc}); ROS topics remain active."
            )

    def destroy_node(self) -> bool:
        if self._http_server is not None:
            self._http_server.shutdown()
            self._http_server.server_close()
            self._http_server = None
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = AmclCorrectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
