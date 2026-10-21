"""
DYNAMIXEL Protocol 2.0 Hardware Interface for OpenManipulator-F
Supports real hardware via USB Serial (OpenRB-150 / U2D2) and full Mock mode for offline simulation.
"""

import math
import time
import logging
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# DYNAMIXEL X-Series Control Table Addresses (Protocol 2.0)
ADDR_TORQUE_ENABLE          = 64    # 1 byte
ADDR_HARDWARE_ERROR_STATUS  = 70    # 1 byte
ADDR_POSITION_D_GAIN        = 80    # 2 bytes
ADDR_POSITION_I_GAIN        = 82    # 2 bytes
ADDR_POSITION_P_GAIN        = 84    # 2 bytes
ADDR_CURRENT_LIMIT          = 102   # 2 bytes (Gripper current limit)
ADDR_PROFILE_ACCELERATION   = 108   # 4 bytes
ADDR_PROFILE_VELOCITY       = 112   # 4 bytes
ADDR_GOAL_POSITION          = 116   # 4 bytes
ADDR_PRESENT_CURRENT        = 126   # 2 bytes
ADDR_PRESENT_VELOCITY       = 128   # 4 bytes
ADDR_PRESENT_POSITION       = 132   # 4 bytes
ADDR_PRESENT_INPUT_VOLTAGE  = 144   # 2 bytes
ADDR_PRESENT_TEMPERATURE    = 146   # 1 byte

LEN_SYNC_READ = 10  # 126 to 135: Current(2) + Velocity(4) + Position(4)

class DynamixelHardwareInterface:
    def __init__(
        self,
        device_name: str = "/dev/ttyUSB0",
        baudrate: int = 1000000,
        joint_ids: Optional[List[int]] = None,
        mock: bool = False
    ):
        self.device_name = device_name
        self.baudrate = baudrate
        self.joint_ids = joint_ids or [1, 2, 3, 4, 5, 6]  # 1~5: Arm, 6: Gripper
        self.mock = mock

        # Physical limits (radians for J1~5, meters for Gripper J6)
        self.limits: Dict[int, Tuple[float, float]] = {
            1: (-math.pi, math.pi),           # Base Yaw: -180 ~ +180 deg
            2: (-1.7453, 1.7453),             # Shoulder Pitch: -100 ~ +100 deg
            3: (-1.6580, 1.5707),             # Elbow Pitch: -95 ~ +90 deg
            4: (-1.8325, 1.8325),             # Wrist Pitch: -105 ~ +105 deg
            5: (-math.pi, math.pi),           # Wrist Roll: -180 ~ +180 deg
            6: (0.0, 0.05)                    # Gripper: 0.0 ~ 0.05m (linear open)
        }

        # Parameters storage
        self.p_gains: Dict[int, int] = {jid: 800 for jid in self.joint_ids}
        self.i_gains: Dict[int, int] = {jid: 0 for jid in self.joint_ids}
        self.d_gains: Dict[int, int] = {jid: 0 for jid in self.joint_ids}
        self.profile_velocities: Dict[int, int] = {jid: 100 for jid in self.joint_ids}
        self.profile_accelerations: Dict[int, int] = {jid: 30 for jid in self.joint_ids}
        self.torque_enabled: Dict[int, bool] = {jid: True for jid in self.joint_ids}
        self.gripper_current_limit_ma: int = 250

        # Hardware handles
        self.port_handler = None
        self.packet_handler = None
        self.group_sync_write = None
        self.group_sync_read = None

        # State storage (used in both real & mock)
        self.present_positions: Dict[int, float] = {jid: 0.0 for jid in self.joint_ids}
        self.present_velocities: Dict[int, float] = {jid: 0.0 for jid in self.joint_ids}
        self.present_currents: Dict[int, float] = {jid: 0.0 for jid in self.joint_ids}
        self.present_temperatures: Dict[int, int] = {jid: 35 for jid in self.joint_ids}
        self.present_voltages: Dict[int, float] = {jid: 12.0 for jid in self.joint_ids}
        self.goal_positions: Dict[int, float] = {jid: 0.0 for jid in self.joint_ids}
        self.last_update_time = time.time()

        self._init_hardware()

    def _init_hardware(self):
        if self.mock:
            logger.info("Initializing DynamixelHardwareInterface in MOCK mode.")
            return

        try:
            from dynamixel_sdk import (
                PortHandler,
                PacketHandler,
                GroupSyncWrite,
                GroupSyncRead,
                COMM_SUCCESS
            )
            self.COMM_SUCCESS = COMM_SUCCESS
            self.port_handler = PortHandler(self.device_name)
            self.packet_handler = PacketHandler(2.0)

            if not self.port_handler.openPort():
                logger.warning(f"Failed to open port {self.device_name}. Falling back to MOCK mode.")
                self.mock = True
                return

            if not self.port_handler.setBaudRate(self.baudrate):
                logger.warning(f"Failed to set baudrate {self.baudrate}. Falling back to MOCK mode.")
                self.mock = True
                return

            # SyncWrite for Goal Position
            self.group_sync_write = GroupSyncWrite(
                self.port_handler,
                self.packet_handler,
                ADDR_GOAL_POSITION,
                4
            )

            # SyncRead for Current + Vel + Pos
            self.group_sync_read = GroupSyncRead(
                self.port_handler,
                self.packet_handler,
                ADDR_PRESENT_CURRENT,
                LEN_SYNC_READ
            )

            for jid in self.joint_ids:
                self.group_sync_read.addParam(jid)

            logger.info(f"DYNAMIXEL hardware opened successfully on {self.device_name} @ {self.baudrate} bps.")

            # Enable torque and set initial gains
            self.set_torque_enable(True)
            for jid in self.joint_ids:
                self.set_pid_gains(jid, self.p_gains[jid], self.i_gains[jid], self.d_gains[jid])
                self.set_profile(jid, self.profile_velocities[jid], self.profile_accelerations[jid])

        except Exception as e:
            logger.warning(f"Error during DYNAMIXEL hardware init ({e}). Falling back to MOCK mode.")
            self.mock = True

    # --------------------------------------------------------------------------
    # Conversion Helpers
    # --------------------------------------------------------------------------
    @staticmethod
    def rad_to_step(rad: float) -> int:
        """Converts radians (-pi to +pi) to DYNAMIXEL 4096 step (0 to 4095, center 2048)"""
        step = int(round((rad / (2.0 * math.pi)) * 4096.0 + 2048.0))
        return max(0, min(4095, step))

    @staticmethod
    def step_to_rad(step: int) -> float:
        """Converts DYNAMIXEL step to radians"""
        return ((step - 2048.0) / 4096.0) * (2.0 * math.pi)

    @staticmethod
    def gripper_m_to_step(m: float) -> int:
        """Converts gripper opening in meters (0.0 to 0.05) to step (e.g. 1800 to 2250)"""
        norm = max(0.0, min(1.0, m / 0.05))
        return int(round(1800 + norm * (2250 - 1800)))

    @staticmethod
    def gripper_step_to_m(step: int) -> float:
        """Converts gripper step back to opening in meters"""
        norm = (step - 1800.0) / (2250.0 - 1800.0)
        norm = max(0.0, min(1.0, norm))
        return norm * 0.05

    def clamp_joint_target(self, joint_id: int, target: float) -> float:
        """Clamps target within physical joint limits"""
        if joint_id in self.limits:
            min_val, max_val = self.limits[joint_id]
            return max(min_val, min(max_val, target))
        return target

    # --------------------------------------------------------------------------
    # Core Read / Write Operations
    # --------------------------------------------------------------------------
    def sync_read_states(self, dt: Optional[float] = None) -> Dict[str, Any]:
        """
        Reads present position, velocity, current, temp, and voltage for all joints.
        Returns unified dictionary.
        """
        now = time.time()
        if dt is None:
            dt = max(1e-3, now - self.last_update_time)
        self.last_update_time = now

        if self.mock:
            # Simulate smooth movement toward goal_position
            for jid in self.joint_ids:
                if not self.torque_enabled[jid]:
                    # Zero torque: drifts slightly or stays
                    self.present_velocities[jid] = 0.0
                    continue

                curr = self.present_positions[jid]
                goal = self.goal_positions[jid]
                diff = goal - curr
                max_speed = 3.5  # rad/s max simulated speed
                step_dist = max_speed * dt

                if abs(diff) <= step_dist:
                    self.present_positions[jid] = goal
                    self.present_velocities[jid] = 0.0
                    self.present_currents[jid] = 15.0  # Holding current in mA
                else:
                    direction = 1.0 if diff > 0 else -1.0
                    self.present_positions[jid] += direction * step_dist
                    self.present_velocities[jid] = direction * max_speed
                    self.present_currents[jid] = 65.0  # Moving current in mA

                # Gripper resistance simulation
                if jid == 6 and self.present_positions[6] < 0.005:
                    self.present_currents[6] = 120.0  # Spikes on contact

                self.present_temperatures[jid] = 35
                self.present_voltages[jid] = 12.1

            return {
                "positions": [self.present_positions[jid] for jid in self.joint_ids],
                "velocities": [self.present_velocities[jid] for jid in self.joint_ids],
                "currents": [self.present_currents[jid] for jid in self.joint_ids],
                "temperatures": [self.present_temperatures[jid] for jid in self.joint_ids],
                "voltages": [self.present_voltages[jid] for jid in self.joint_ids],
                "torque_enabled": [self.torque_enabled[jid] for jid in self.joint_ids],
                "timestamp": now
            }

        # Real hardware SyncRead
        try:
            dxl_comm_result = self.group_sync_read.txRxPacket()
            if dxl_comm_result != self.COMM_SUCCESS:
                logger.error(f"SyncRead txRxPacket failed: {self.packet_handler.getTxRxResult(dxl_comm_result)}")

            for jid in self.joint_ids:
                data_present = self.group_sync_read.isAvailable(jid, ADDR_PRESENT_CURRENT, LEN_SYNC_READ)
                if data_present:
                    raw_curr = self.group_sync_read.getData(jid, ADDR_PRESENT_CURRENT, 2)
                    raw_vel = self.group_sync_read.getData(jid, ADDR_PRESENT_VELOCITY, 4)
                    raw_pos = self.group_sync_read.getData(jid, ADDR_PRESENT_POSITION, 4)

                    # Signed 2's complement conversion
                    curr_ma = float(raw_curr if raw_curr < 32768 else raw_curr - 65536) * 2.69  # XM430 current unit
                    vel_val = float(raw_vel if raw_vel < 2147483648 else raw_vel - 4294967296) * 0.229 * 0.1047  # rad/s

                    if jid == 6:
                        pos_m = self.gripper_step_to_m(raw_pos)
                        self.present_positions[jid] = pos_m
                    else:
                        pos_rad = self.step_to_rad(raw_pos)
                        self.present_positions[jid] = pos_rad

                    self.present_velocities[jid] = vel_val
                    self.present_currents[jid] = curr_ma
        except Exception as e:
            logger.error(f"SyncRead exception: {e}")

        return {
            "positions": [self.present_positions[jid] for jid in self.joint_ids],
            "velocities": [self.present_velocities[jid] for jid in self.joint_ids],
            "currents": [self.present_currents[jid] for jid in self.joint_ids],
            "temperatures": [self.present_temperatures[jid] for jid in self.joint_ids],
            "voltages": [self.present_voltages[jid] for jid in self.joint_ids],
            "torque_enabled": [self.torque_enabled[jid] for jid in self.joint_ids],
            "timestamp": now
        }

    def sync_write_goals(self, targets: List[float]) -> bool:
        """
        Sends goal positions for Joint 1~5 (rad) and Gripper (meters or percent).
        Targets length should be 6.
        """
        if len(targets) != len(self.joint_ids):
            logger.error(f"sync_write_goals: expected {len(self.joint_ids)} targets, got {len(targets)}")
            return False

        clamped = []
        for i, jid in enumerate(self.joint_ids):
            val = self.clamp_joint_target(jid, targets[i])
            self.goal_positions[jid] = val
            clamped.append(val)

        if self.mock:
            return True

        try:
            self.group_sync_write.clearParam()
            for i, jid in enumerate(self.joint_ids):
                if not self.torque_enabled[jid]:
                    continue

                if jid == 6:
                    step = self.gripper_m_to_step(clamped[i])
                else:
                    step = self.rad_to_step(clamped[i])

                param_goal_position = [
                    (step >> 0) & 0xFF,
                    (step >> 8) & 0xFF,
                    (step >> 16) & 0xFF,
                    (step >> 24) & 0xFF
                ]
                self.group_sync_write.addParam(jid, param_goal_position)

            dxl_comm_result = self.group_sync_write.txPacket()
            if dxl_comm_result != self.COMM_SUCCESS:
                logger.error(f"SyncWrite failed: {self.packet_handler.getTxRxResult(dxl_comm_result)}")
                return False
            return True
        except Exception as e:
            logger.error(f"SyncWrite exception: {e}")
            return False

    # --------------------------------------------------------------------------
    # Parameter Controls
    # --------------------------------------------------------------------------
    def set_pid_gains(self, joint_id: int, p: int, i: int, d: int) -> bool:
        self.p_gains[joint_id] = p
        self.i_gains[joint_id] = i
        self.d_gains[joint_id] = d

        if self.mock:
            return True

        try:
            self.packet_handler.write2ByteTxRx(self.port_handler, joint_id, ADDR_POSITION_P_GAIN, p)
            self.packet_handler.write2ByteTxRx(self.port_handler, joint_id, ADDR_POSITION_I_GAIN, i)
            self.packet_handler.write2ByteTxRx(self.port_handler, joint_id, ADDR_POSITION_D_GAIN, d)
            return True
        except Exception as e:
            logger.error(f"set_pid_gains error for joint {joint_id}: {e}")
            return False

    def set_profile(self, joint_id: int, velocity: int, acceleration: int) -> bool:
        self.profile_velocities[joint_id] = velocity
        self.profile_accelerations[joint_id] = acceleration

        if self.mock:
            return True

        try:
            self.packet_handler.write4ByteTxRx(self.port_handler, joint_id, ADDR_PROFILE_VELOCITY, velocity)
            self.packet_handler.write4ByteTxRx(self.port_handler, joint_id, ADDR_PROFILE_ACCELERATION, acceleration)
            return True
        except Exception as e:
            logger.error(f"set_profile error for joint {joint_id}: {e}")
            return False

    def set_torque_enable(self, enable: bool, joint_id: Optional[int] = None) -> bool:
        targets = [joint_id] if joint_id is not None else self.joint_ids
        for jid in targets:
            self.torque_enabled[jid] = enable

        if self.mock:
            return True

        try:
            val = 1 if enable else 0
            for jid in targets:
                self.packet_handler.write1ByteTxRx(self.port_handler, jid, ADDR_TORQUE_ENABLE, val)
            return True
        except Exception as e:
            logger.error(f"set_torque_enable error: {e}")
            return False

    def set_gripper_current_limit(self, current_ma: int) -> bool:
        self.gripper_current_limit_ma = current_ma
        if self.mock:
            return True

        try:
            # Convert mA to DYNAMIXEL unit (~2.69mA per unit)
            raw_limit = int(max(0, min(1000, current_ma)) / 2.69)
            self.packet_handler.write2ByteTxRx(self.port_handler, 6, ADDR_CURRENT_LIMIT, raw_limit)
            return True
        except Exception as e:
            logger.error(f"set_gripper_current_limit error: {e}")
            return False

    def close(self):
        if not self.mock and self.port_handler:
            self.set_torque_enable(False)
            self.port_handler.closePort()
            logger.info("Closed DYNAMIXEL port.")
