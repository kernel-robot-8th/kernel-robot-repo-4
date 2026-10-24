"""One bounded, resumable trial with validation-based checkpoint selection."""

import argparse
import math
from pathlib import Path
import time

import numpy as np
import torch
from torch.utils.data import DataLoader

from .common import read_json, utc_now, write_json
from .data import RecordingDataset, SPLITS
from .learning import evaluate, make_policy, prepare_batch, seed_everything


def save_checkpoint(path, model, optimizer, config, statistics, step):
    temporary = Path(path).with_suffix(".tmp")
    torch.save(
        {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "config": config,
            "statistics": statistics,
            "step": step,
        },
        temporary,
    )
    temporary.replace(path)


def train_trial(cache, config, output, budget_s):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    seed_everything(config["seed"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device != "cuda":
        raise RuntimeError("Long sweep requires CUDA; CPU fallback must be explicitly configured")
    order = np.random.default_rng(config["seed"]).permutation(SPLITS["train"])
    training_ids = sorted(order[: config["train_episodes"]].tolist())
    train = RecordingDataset(cache, training_ids, config["horizon"], stride=3)
    stats = train.statistics
    validation = RecordingDataset(cache, SPLITS["validation"], config["horizon"], stats, stride=12)
    probe = RecordingDataset(cache, training_ids, config["horizon"], stats, stride=24)
    batch_size = config.get("batch_size", 24)
    loader = DataLoader(
        train, batch_size=batch_size, shuffle=True, num_workers=0, pin_memory=True, drop_last=False
    )
    val_loader = DataLoader(validation, batch_size=batch_size, num_workers=0)
    train_probe = DataLoader(probe, batch_size=batch_size, num_workers=0)
    policy = make_policy(config).to(device)
    optimizer = torch.optim.AdamW(policy.parameters(), lr=config["lr"], weight_decay=config["weight_decay"])
    best, step, stale = math.inf, 0, 0
    rows = []
    latest = output / "last.pt"
    if latest.exists():
        saved = torch.load(latest, map_location=device, weights_only=False)
        if saved["config"] != config:
            raise ValueError("Refusing to resume a checkpoint with different trial configuration")
        policy.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        step = saved["step"]
        if (output / "history.json").exists():
            rows = read_json(output / "history.json")
            best = min(row["validation_mae"] for row in rows)
    started = time.monotonic()
    deadline = started + budget_s
    torch.cuda.reset_peak_memory_stats()
    write_json(
        output / "status.json",
        {"status": "training", "started_at": utc_now(), "config": config, "statistics": stats},
    )
    criterion = "budget_exhausted"
    iterator = iter(loader)
    train_losses = []
    initial_step = step
    while time.monotonic() < deadline and step < config.get("max_steps", 30000):
        try:
            batch = next(iterator)
        except StopIteration:
            iterator = iter(loader)
            batch = next(iterator)
        policy.train()
        prepared = prepare_batch(
            batch,
            device,
            augment=config.get("augmentation", False),
            state_noise=config.get("state_noise", 0.0),
        )
        loss, _ = policy(prepared)
        if not torch.isfinite(loss):
            raise RuntimeError(f"Non-finite loss at step {step}")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(policy.parameters(), 10.0)
        optimizer.step()
        step += 1
        train_losses.append(loss.detach().item())
        if step % config.get("validation_every", 250) == 0 or step == initial_step + 1:
            val = evaluate(policy, val_loader, stats, device)
            fitted = evaluate(policy, train_probe, stats, device)
            improved = val["control_mae"] < best - 0.005
            if improved:
                best, stale = val["control_mae"], 0
                save_checkpoint(output / "best.pt", policy, optimizer, config, stats, step)
                write_json(output / "best_validation.json", val)
            else:
                stale += 1
            row = {
                "step": step,
                "elapsed_s": time.monotonic() - started,
                "training_loss": float(np.mean(train_losses)),
                "training_mae": fitted["control_mae"],
                "validation_mae": val["control_mae"],
                "gap": val["control_mae"] - fitted["control_mae"],
                "best_validation_mae": best,
                "gpu_peak_mib": torch.cuda.max_memory_allocated() / 2**20,
            }
            rows.append(row)
            write_json(output / "history.json", rows)
            save_checkpoint(latest, policy, optimizer, config, stats, step)
            write_json(
                output / "status.json",
                {"status": "training", "updated_at": utc_now(), "config": config, "statistics": stats, **row},
            )
            print(
                f"TRIAL {config['name']} step={step} train={row['training_mae']:.3f} "
                f"val={val['control_mae']:.3f} best={best:.3f}",
                flush=True,
            )
            train_losses.clear()
            if stale >= config.get("patience", 10) and step >= config.get("min_steps", 1000):
                criterion = "validation_early_stopping"
                break
    if step >= config.get("max_steps", 30000):
        criterion = "maximum_steps"
    if not (output / "best.pt").exists():
        raise RuntimeError("No validated checkpoint was produced within the budget")
    result = {
        "status": "completed",
        "finished_at": utc_now(),
        "config": config,
        "training_episodes": training_ids,
        "validation_episodes": SPLITS["validation"],
        "test_episodes_used": [],
        "normalization_fitted_on": training_ids,
        "selection_metric": "recording-balanced first-10-step control MAE",
        "steps": step,
        "elapsed_s": time.monotonic() - started,
        "best_validation_mae": best,
        "stop_reason": criterion,
        "gpu_peak_mib": torch.cuda.max_memory_allocated() / 2**20,
        "history": rows,
        "checkpoint": str(output / "best.pt"),
    }
    write_json(output / "result.json", result)
    write_json(output / "status.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--budget-s", type=float, default=1200)
    args = parser.parse_args()
    train_trial(args.cache, read_json(args.config), args.output, args.budget_s)


if __name__ == "__main__":
    main()
