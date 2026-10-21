import math
import pytest
from hardware.dynamixel_interface import DynamixelHardwareInterface

def test_mock_initialization():
    hw = DynamixelHardwareInterface(mock=True)
    assert hw.mock is True
    assert len(hw.joint_ids) == 6
    states = hw.sync_read_states()
    assert len(states["positions"]) == 6
    assert len(states["velocities"]) == 6
    assert len(states["currents"]) == 6
    assert len(states["temperatures"]) == 6
    assert all(t is True for t in states["torque_enabled"])

def test_joint_limits_clamping():
    hw = DynamixelHardwareInterface(mock=True)
    # Joint 2 limit: (-1.7453, 1.7453)
    clamped = hw.clamp_joint_target(2, 3.5)
    assert math.isclose(clamped, 1.7453, abs_tol=1e-4)

    clamped_min = hw.clamp_joint_target(2, -3.5)
    assert math.isclose(clamped_min, -1.7453, abs_tol=1e-4)

    # Gripper limit: (0.0, 0.05)
    clamped_grip = hw.clamp_joint_target(6, 0.10)
    assert math.isclose(clamped_grip, 0.05, abs_tol=1e-4)

def test_sync_write_and_convergence():
    hw = DynamixelHardwareInterface(mock=True)
    targets = [0.5, -0.3, 0.4, 0.1, 0.0, 0.035]
    success = hw.sync_write_goals(targets)
    assert success is True

    # Read state multiple times to simulate convergence (1.0s total)
    for _ in range(25):
        states = hw.sync_read_states(dt=0.05)

    for i in range(6):
        assert math.isclose(states["positions"][i], targets[i], abs_tol=0.05)

def test_parameter_tuning():
    hw = DynamixelHardwareInterface(mock=True)
    assert hw.set_pid_gains(1, p=1200, i=10, d=50) is True
    assert hw.p_gains[1] == 1200

    assert hw.set_profile(1, velocity=150, acceleration=40) is True
    assert hw.profile_velocities[1] == 150

    assert hw.set_gripper_current_limit(300) is True
    assert hw.gripper_current_limit_ma == 300

    assert hw.set_torque_enable(False, joint_id=1) is True
    assert hw.torque_enabled[1] is False
    assert hw.torque_enabled[2] is True
