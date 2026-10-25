"""Freeze collection-role comparisons before training or viewing their new metrics."""

from .data import validate_split_plan


def recording_fold(plan, fold, regime):
    """Keep one supplementary recording for selection and another for evaluation."""
    corrections = plan["correction_ids"]
    test = corrections[fold]
    validation = corrections[(fold + 1) % len(corrections)]
    extra = [i for i in corrections if i not in {test, validation}]
    train = list(plan["basic_train_ids"])
    if regime != "basic_only":
        train += extra
    split = {
        "train": train,
        "validation": plan["basic_validation_ids"] + [validation],
        "test": plan["basic_test_ids"] + [test],
    }
    return validate_split_plan(split), extra if regime != "basic_only" else []


def lightweight_grid(plan):
    """Use matched folds and seeds for basic, concatenated, and balanced learning."""
    result = []
    for seed in plan["seeds"]:
        for fold in range(len(plan["correction_ids"])):
            for family in plan["families"]:
                for regime in plan["regimes"]:
                    split, extra = recording_fold(plan, fold, regime)
                    result.append(
                        {
                            **plan["base"],
                            **family,
                            "name": f"{family['family']}_f{fold}_{regime}_seed{seed}",
                            "seed": seed,
                            "fold": fold,
                            "regime": regime,
                            "train_episodes": len(split["train"]),
                            "train_ids": split["train"],
                            "correction_train_ids": extra,
                            "sampling": "correction_balanced"
                            if regime == "correction_balanced"
                            else "uniform",
                            "split_plan": split,
                        }
                    )
    return result


def native_grid(plan):
    """Compare original LeRobot ACT on the same held-out folds at full resolution."""
    return [
        {
            "name": f"native_act_f{fold}_{regime}_seed17",
            "family": "native_act",
            "fold": fold,
            "regime": regime,
            "seed": 17,
            "split_plan": recording_fold(plan, fold, regime)[0],
        }
        for fold in range(len(plan["correction_ids"]))
        for regime in ["basic_only", "correction_concat"]
    ]
