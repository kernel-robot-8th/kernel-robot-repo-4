"""Keep the 0.4.4 comparison scope and held-out recording boundary explicit."""

from cobot_mujoco.act044_training import command, trial_plan


def test_act044_scope_has_two_act_architectures_and_only_controlled_extra_variants():
    """Do not silently add a standalone CNN, change resolution, or miscount comparison cells."""
    plan = trial_plan()
    assert plan["required_lerobot"] == "0.4.4"
    assert len(plan["trials"]) == 12
    assert sum(len(r["comparison_steps"]) for r in plan["trials"]) == 44
    assert {r["architecture"] for r in plan["trials"]} == {"standard", "light"}
    for cfg in plan["trials"]:
        assert cfg["vision_backbone"] == "resnet18"
        assert cfg["image_shape"] == [3, 480, 640]
        assert cfg["batch_size"] == 8 and cfg["seed"] == 17
        if cfg["variant"] != "base":
            assert cfg["chunk"] == 32 and cfg["steps"] == 10000
            assert cfg["backbone_lr"] == 1e-5
            assert (cfg["lr"] == 3e-5) != (cfg["weight_decay"] == 1e-3)


def test_act044_upstream_command_never_passes_validation_or_test_as_training_episodes():
    """Avoid 0.6-only flags and 0.4.4 training leakage when using external checkpoint validation."""
    plan = trial_plan()
    cfg = plan["trials"][0]
    args = command("/tmp/source", "/tmp/output", cfg)
    ids = next(a for a in args if a.startswith("--dataset.episodes="))
    import ast

    actual = set(ast.literal_eval(ids.split("=", 1)[1]))
    assert actual == set(plan["split_plan"]["train"])
    assert actual.isdisjoint(plan["split_plan"]["validation"] + plan["split_plan"]["test"])
    assert "--eval_freq=0" in args
    assert not any(
        a.startswith(("--dataset.eval_split", "--env_eval_freq", "--prefetch_factor")) for a in args
    )
