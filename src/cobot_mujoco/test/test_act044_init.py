"""Check initialization arrival and failure without touching robot hardware."""

import importlib.util
from types import SimpleNamespace

import pytest

from cobot_mujoco.common import REPOSITORY


@pytest.mark.parametrize("stalled", [False, True])
def test_init_bounds_commands_and_requires_arrival(stalled):
    """A stalled arm must cancel inference; a following arm must reach the saved pose."""
    path = REPOSITORY / "scripts/manipulation/act044_init.py"
    spec = importlib.util.spec_from_file_location("act044_init_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = module.load_pose(path.with_name("act044_init_pose.json"))
    current = dict.fromkeys(target, 0.0)
    clock = [0.0]

    def send(action):
        for key, value in action.items():
            motor = key.removesuffix(".pos")
            assert abs(value - current[motor]) <= 3.000001
            if not stalled:
                current[motor] = value

    def sleep(seconds):
        clock[0] += seconds

    robot = SimpleNamespace(
        bus=SimpleNamespace(sync_read=lambda _: dict(current)),
        send_action=send,
    )
    kwargs = {"clock": lambda: clock[0], "sleep": sleep}
    if stalled:
        with pytest.raises(RuntimeError, match="inference cancelled"):
            module.move_to_init(robot, target, 3, **kwargs)
    else:
        module.move_to_init(robot, target, 3, **kwargs)
        assert max(abs(target[k] - current[k]) for k in target) <= 3
