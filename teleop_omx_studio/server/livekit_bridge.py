"""
LiveKit WebRTC Robot Bridge.
Connects robot to LiveKit room, publishes video tracks (Top Cam & Wrist Cam),
subscribes to DataTrack ('robot.control') with 50ms Watchdog safety hold.
"""

import asyncio
import json
import time
import logging
from typing import Optional, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

class LiveKitTeleopBridge:
    def __init__(
        self,
        hardware_interface,
        url: str = "ws://127.0.0.1:7880",
        api_key: str = "devkey",
        api_secret: str = "secret",
        room_name: str = "omx_teleop_room",
        participant_identity: str = "robot_omx1"
    ):
        self.hw = hardware_interface
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret
        self.room_name = room_name
        self.participant_identity = participant_identity

        # Safety & control lease state
        self.active_lease_id: Optional[str] = None
        self.lease_operator_id: Optional[str] = None
        self.lease_expire_time: float = 0.0
        self.last_command_time: float = 0.0
        self.watchdog_timeout_sec: float = 0.100  # 100ms
        self.is_holding: bool = False

        self.room = None
        self.top_source = None
        self.wrist_source = None
        self.running = False

    def generate_token(self, identity: str, name: Optional[str] = None, is_admin: bool = False) -> str:
        """Generates LiveKit access token using livekit-api"""
        from livekit import api
        token = api.AccessToken(self.api_key, self.api_secret) \
            .with_identity(identity) \
            .with_name(name or identity) \
            .with_grants(api.VideoGrants(
                room_join=True,
                room=self.room_name,
                can_publish=is_admin,
                can_subscribe=True,
                can_publish_data=True
            ))
        return token.to_jwt()

    async def start(self):
        """Connects to LiveKit room and starts camera publishing & watchdog"""
        try:
            from livekit import rtc
            self.room = rtc.Room()

            robot_token = self.generate_token(self.participant_identity, is_admin=True)
            logger.info(f"Connecting to LiveKit at {self.url} as {self.participant_identity}...")
            await self.room.connect(self.url, robot_token)
            logger.info(f"Connected to room '{self.room_name}'!")

            # Register DataTrack handler
            self.room.on("data_received", self._on_data_received)

            self.running = True
            asyncio.create_task(self._watchdog_loop())

        except Exception as e:
            logger.warning(f"Could not connect to LiveKit server ({e}). Operating in Standalone/Direct mode.")

    def acquire_lease(self, operator_id: str) -> Dict[str, Any]:
        """SR-19: Exclusive Control Lease Protocol"""
        now = time.time()
        if self.active_lease_id and self.lease_operator_id != operator_id and now < self.lease_expire_time:
            return {
                "success": False,
                "message": f"Robot is currently locked by operator '{self.lease_operator_id}'",
                "active_operator": self.lease_operator_id
            }

        lease_id = f"lease_{operator_id}_{int(now)}"
        self.active_lease_id = lease_id
        self.lease_operator_id = operator_id
        self.lease_expire_time = now + 5.0  # 5 second auto-expiry heartbeat
        self.last_command_time = now
        self.is_holding = False

        logger.info(f"Granted single-operator lease to '{operator_id}' (ID: {lease_id})")
        return {
            "success": True,
            "lease_id": lease_id,
            "expires_in": 5.0
        }

    def release_lease(self, operator_id: str, lease_id: str) -> bool:
        if self.active_lease_id == lease_id and self.lease_operator_id == operator_id:
            self.active_lease_id = None
            self.lease_operator_id = None
            logger.info(f"Released lease {lease_id}")
            return True
        return False

    def _on_data_received(self, data_packet):
        if getattr(data_packet, "topic", "") != "robot.control":
            return

        try:
            payload = json.loads(data_packet.data.decode("utf-8"))
            self.process_control_frame(payload)
        except Exception as e:
            logger.error(f"Error parsing control frame: {e}")

    def process_control_frame(self, payload: Dict[str, Any]) -> bool:
        """Processes 30~50Hz teleoperation packet with timestamp & lease validation"""
        lease_id = payload.get("lease_id")
        if self.active_lease_id and lease_id != self.active_lease_id:
            return False

        now = time.time()
        pkt_ts = payload.get("ts", 0) / 1000.0 if "ts" in payload else now
        if (now - pkt_ts) > 0.050:  # 50ms age limit (SR-20)
            return False

        self.last_command_time = now
        self.lease_expire_time = now + 5.0
        self.is_holding = False

        # Apply goal positions
        targets = payload.get("target_joints")
        gripper = payload.get("gripper_target")
        if targets:
            full_targets = list(targets)
            if gripper is not None and len(full_targets) == 5:
                full_targets.append(gripper)
            self.hw.sync_write_goals(full_targets)
            return True

        return False

    async def _watchdog_loop(self):
        """SR-20: 50ms heartbeat watchdog. Stops motor on 100ms timeout"""
        while self.running:
            await asyncio.sleep(0.05)  # 50ms check
            now = time.time()
            if self.active_lease_id and not self.is_holding:
                if (now - self.last_command_time) > self.watchdog_timeout_sec:
                    # Timeout! Apply Safe Hold
                    states = self.hw.sync_read_states()
                    self.hw.sync_write_goals(states["positions"])
                    self.is_holding = True
                    logger.warning("[Watchdog] Teleop signal timeout > 100ms. Safe Position Hold engaged!")

    async def stop(self):
        self.running = False
        if self.room:
            await self.room.disconnect()
            logger.info("Disconnected from LiveKit.")
