"""Evidence-based findings from learning curves and held-out recording metrics."""

import numpy as np


def summarize_results(trials, final, diagnostics):
    """Keep observed overfitting patterns separate from unsupported causal claims."""
    overfit = []
    for trial in trials:
        history = trial.get("history", [])
        if len(history) < 3:
            continue
        best = min(history, key=lambda row: row["validation_mae"])
        last = history[-1]
        deterioration = last["validation_mae"] - best["validation_mae"]
        if (
            last["step"] > best["step"]
            and last["training_mae"] < best["training_mae"] * 0.95
            and deterioration > max(0.1, best["validation_mae"] * 0.1)
        ):
            overfit.append(
                {
                    "trial": trial["config"]["name"],
                    "best_step": best["step"],
                    "last_step": last["step"],
                    "validation_increase": deterioration,
                    "training_decrease": best["training_mae"] - last["training_mae"],
                }
            )
    scarcity = []
    for family, small, large in [("state", "state_bc_2", "state_bc_8"), ("act", "act_2", "act_baseline_8")]:
        lookup = {(t["config"]["name"].split("_seed")[0], t["config"]["seed"]): t for t in trials}
        pairs = []
        for name, seed in lookup:
            if name == small and (large, seed) in lookup:
                first, last = lookup[(small, seed)], lookup[(large, seed)]
                pairs.append(
                    {
                        "seed": seed,
                        "mae_2": first["best_validation_mae"],
                        "mae_8": last["best_validation_mae"],
                        "improvement": first["best_validation_mae"] - last["best_validation_mae"],
                    }
                )
        if pairs:
            scarcity.append(
                {
                    "family": family,
                    "paired_seeds": len(pairs),
                    "pairs": pairs,
                    "mean_improvement_2_to_8": float(np.mean([p["improvement"] for p in pairs])),
                }
            )
    generalization = []
    for candidate in final:
        trial = next(t for t in trials if t["config"]["name"] == candidate["trial"])
        test = candidate["test"]["control_mae"]
        baseline = candidate.get("persistence_baseline", {}).get("control_mae")
        generalization.append(
            {
                "trial": candidate["trial"],
                "validation_mae": trial["best_validation_mae"],
                "test_mae": test,
                "test_minus_validation": test - trial["best_validation_mae"],
                "beats_hold_current_state": None if baseline is None else test < baseline,
            }
        )
    replays = diagnostics.get("replay", [])
    return {
        "overfit_pattern_count": len(overfit),
        "overfit_candidates": overfit,
        "pattern_definition": (
            "After best validation: train MAE decreases >5%, validation increases >10% and >0.1"
        ),
        "scarcity": scarcity,
        "generalization": generalization,
        "replay_successes": sum(int(r["success_any_box"]) for r in replays),
        "replay_count": len(replays),
        "classification_metrics_available": False,
        "limitations": [
            "Only two validation recordings; hyperparameter selection may overfit them",
            "Learning curves do not prove additional data will always improve accuracy",
            "Motor MAE is not task success",
            "Simulator physics remains provisional",
        ],
    }
