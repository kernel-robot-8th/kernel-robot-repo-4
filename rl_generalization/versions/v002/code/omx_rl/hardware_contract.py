"""Required real-adapter contract, NOT an implementation or a robot connection."""
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class Observation:
    timestamp_monotonic_s: float
    joint_positions: tuple[float, ...]
    ee_position_base_m: tuple[float, float, float]
    target_grasp_base_m: tuple[float, float, float]
    target_id: str
    target_valid: bool
    calibration_id: str
    object_held_verified: bool | None

class RealGraspBackend(Protocol):
    """Implement only after driver units, IK, reset and detector are verified.

    No oracle attachment flags may be substituted for unmeasured object state.
    send_delta must reject stale/invalid observations, unreachable IK and limits;
    it must be the sole command owner and log requested AND applied commands.
    """
    def reset_with_operator(self) -> Observation: ...
    def observe(self) -> Observation: ...
    def send_delta(self, delta_xyz_m: tuple[float, float, float],
                   gripper_target: float) -> Observation: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
