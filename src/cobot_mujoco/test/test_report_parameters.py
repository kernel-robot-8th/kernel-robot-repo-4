"""Guard actual-setting documentation and the verified two-box scene correction."""

from cobot_mujoco.common import PACKAGE, REPOSITORY, read_json
from cobot_mujoco.parameter_guide import EXPLANATIONS, parameter_data, parameter_html
from cobot_mujoco.scene_review import review_html


def test_every_recorded_setting_is_explained_without_dropping_trials():
    """Check all completed records are covered by the parameter guide."""
    root = REPOSITORY / "docs/mujoco_validation"
    trials = read_json(root / "trials.json")
    sweep = read_json(root / "schedule.json")["sweep"]
    guide = parameter_data(trials, sweep)
    assert len(guide["trials"]) == len(trials) == 36
    assert {k for t in trials for k in t["config"]} <= set(EXPLANATIONS)
    assert all(row["best_step"] <= row["end_step"] for row in guide["trials"])
    text, _ = parameter_html(trials, sweep)
    assert "실험 안에서는 고정" in text
    assert "박스 2개는 서로 다른 뜻" in text
    for trial in trials:
        assert trial["config"]["name"] in text


def test_default_count_matches_visual_review_and_preserves_original_provenance():
    """Keep future scenes at two boxes while retaining the historical three-box error."""
    root = REPOSITORY / "docs/mujoco_validation"
    scene = read_json(PACKAGE / "config/scene.json")
    review = read_json(root / "scene_count_review.json")
    assert scene["box_count"] == 2
    assert all(review["initial_box_counts"][str(i)] == 2 for i in range(10))
    assert all(review["initial_box_counts"][str(i)] == 1 for i in range(10, 15))
    assert read_json(root / "scene.json")["box_count"] == review["original_scene_box_count"] == 3
    assert review["original_policy_rollout_counts"] == {
        "three_box_conditions": 90,
        "one_box_conditions": 18,
        "two_box_conditions": 0,
    }
    text = review_html(review)
    assert "학습이 실패했다고" in text
    assert "박스 3개 조건 90회" in text
