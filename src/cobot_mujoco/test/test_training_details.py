"""Prevent completed jobs and historical simulation counts from being misrepresented."""

from cobot_mujoco.training_details import step_record, step_summary
from cobot_mujoco.sim_comparison import scenarios
from cobot_mujoco.common import PACKAGE, read_json


def test_completed_early_stopping_does_not_claim_maximum_step_was_reached():
    """Report the selected checkpoint and actual stopping point as different quantities."""
    row = {
        "config": {
            "name": "example",
            "family": "cnn",
            "regime": "basic_only",
            "max_steps": 20000,
            "split_plan": {"train": [0], "validation": [8], "test": [9]},
        },
        "steps": 4750,
        "best_validation_mae": 1.0,
        "status": "completed",
        "stop_reason": "validation_early_stopping",
        "history": [{"step": 2250, "validation_mae": 1.0}, {"step": 4750, "validation_mae": 1.1}],
    }
    value = step_record(row)
    assert value["target_steps"] == 20000
    assert value["actual_steps"] == 4750
    assert value["selected_step"] == 2250
    assert value["target_reached"] is False
    assert step_summary([row])[0]["target_reached_count"] == 0


def test_simulation_cases_pair_exactly_the_same_scene_changes_for_every_policy():
    """Use six distinct conditions and preserve the input scene rather than mutating defaults."""
    original = read_json(PACKAGE / "config/scene.json")
    cases = scenarios(original)
    assert len(cases) == 6
    assert original["box_count"] == 2
    assert [r["seed"] for r in cases] == [0, 17, 42, 0, 17, 42]
    assert [r["scene"]["box_count"] for r in cases] == [2, 2, 2, 1, 1, 1]
    assert cases[3]["scene"]["initial_state"] == original["single_box_initial_state"]
    assert cases[0]["scene"]["initial_state"] == original["initial_state"]
    cases[0]["scene"]["box_count"] = 999
    assert cases[1]["scene"]["box_count"] == 2
