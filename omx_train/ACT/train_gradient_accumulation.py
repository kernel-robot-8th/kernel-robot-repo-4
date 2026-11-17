"""lerobot-train(0.4.4) + gradient accumulation.

lerobot에는 gradient accumulation 옵션이 없어서, 학습 한 step(update_policy)을 바꿔 끼운 뒤
원래 lerobot-train을 그대로 실행합니다. 나머지 옵션과 동작은 lerobot-train과 같습니다.

  python train_gradient_accumulation.py --grad_accum_steps=2 --batch_size=32 [lerobot-train 옵션...]

  --batch_size       : 모델을 한 번 업데이트할 때 쓰는 샘플 수(effective batch). 데이터로더가 이만큼 읽음
  --grad_accum_steps : 그 batch를 몇 조각으로 나눠 forward/backward 할지. GPU에는 batch_size / N 만큼씩 올라감
                       (환경변수 GRAD_ACCUM_STEPS로도 지정 가능, 기본 1 = 일반 학습과 같음)

예) --batch_size=32 --grad_accum_steps=2 → GPU 메모리는 batch 16만큼 쓰고, 업데이트는 batch 32와 같음.
--steps, --save_freq, --log_freq와 lr 스케줄은 모두 "모델 업데이트 횟수" 기준이라 일반 학습과 똑같이 셉니다.
"""

import logging
import os
import sys
import time
from contextlib import nullcontext

import torch

import lerobot.scripts.lerobot_train as lt
from lerobot.utils.utils import has_method


def pop_grad_accum_steps(argv):
    """Remove --grad_accum_steps from argv (lerobot-train would reject it) and return its value."""
    n = int(os.environ.get("GRAD_ACCUM_STEPS", "1"))
    rest = []
    it = iter(argv)
    for a in it:
        if a.startswith("--grad_accum_steps="):
            n = int(a.split("=", 1)[1])
        elif a == "--grad_accum_steps":
            n = int(next(it))
        else:
            rest.append(a)
    if n < 1:
        raise ValueError(f"--grad_accum_steps must be >= 1, got {n}")
    return n, rest


GRAD_ACCUM_STEPS, sys.argv[1:] = pop_grad_accum_steps(sys.argv[1:])


def split_batch(batch, n):
    """Split a batch dict into up to n micro-batches along dim 0. Returns [(micro_batch, fraction), ...]."""
    bs = next(v.shape[0] for v in batch.values() if isinstance(v, torch.Tensor) and v.ndim > 0)
    chunks = []
    for idx in torch.arange(bs).tensor_split(n):
        if len(idx) == 0:  # 마지막 batch가 N보다 작을 때
            continue
        sl = slice(int(idx[0]), int(idx[-1]) + 1)
        micro = {}
        for k, v in batch.items():
            if isinstance(v, torch.Tensor) and v.ndim > 0 and v.shape[0] == bs:
                micro[k] = v[sl]
            elif isinstance(v, (list, tuple)) and len(v) == bs:
                micro[k] = v[sl]
            else:
                micro[k] = v
        chunks.append((micro, len(idx) / bs))
    return chunks


def update_policy(
    train_metrics,
    policy,
    batch,
    optimizer,
    grad_clip_norm,
    accelerator,
    lr_scheduler=None,
    lock=None,
    rabc_weights_provider=None,
):
    """lerobot_train.update_policy와 같고, forward/backward만 micro-batch로 나눠 gradient를 모은 뒤 한 번 업데이트."""
    start_time = time.perf_counter()
    policy.train()

    # RA-BC 가중치는 전체 batch 기준으로 한 번 계산 (원본과 같은 정규화)
    rabc_batch_weights = rabc_batch_stats = None
    if rabc_weights_provider is not None:
        rabc_batch_weights, rabc_batch_stats = rabc_weights_provider.compute_batch_weights(batch)

    chunks = split_batch(batch, GRAD_ACCUM_STEPS)
    total_loss = 0.0
    sums, counts = {}, {}
    start = 0
    for i, (micro, frac) in enumerate(chunks):
        last = i == len(chunks) - 1
        # 여러 GPU일 때 마지막 조각에서만 gradient 동기화
        with accelerator.no_sync(policy) if not last else nullcontext():
            with accelerator.autocast():
                if rabc_batch_weights is not None:
                    n = next(v.shape[0] for v in micro.values() if isinstance(v, torch.Tensor) and v.ndim > 0)
                    w = rabc_batch_weights[start : start + n]
                    start += n
                    per_sample_loss, output_dict = policy.forward(micro, reduction="none")
                    # 조각별 합을 전체 가중치 합으로 나누면, 모두 더했을 때 원본 L_RA-BC와 같음
                    loss = (per_sample_loss * w).sum() / (rabc_batch_weights.sum() + 1e-6)
                else:
                    loss, output_dict = policy.forward(micro)
                    loss = loss * frac  # 평균 loss를 조각 크기 비율로 가중 → 합 = 전체 batch 평균
            accelerator.backward(loss)
        total_loss += loss.item()
        for k, v in (output_dict or {}).items():
            if isinstance(v, (int, float)):
                sums[k] = sums.get(k, 0.0) + v * frac
                counts[k] = counts.get(k, 0.0) + frac
    output_dict = {k: sums[k] / counts[k] for k in sums}
    if rabc_batch_stats is not None:
        output_dict["rabc_mean_weight"] = rabc_batch_stats["raw_mean_weight"]
        output_dict["rabc_num_zero_weight"] = rabc_batch_stats["num_zero_weight"]
        output_dict["rabc_num_full_weight"] = rabc_batch_stats["num_full_weight"]

    # 이하 원본과 동일: clip → optimizer step → zero_grad → scheduler (업데이트 1번에 1번씩)
    if grad_clip_norm > 0:
        grad_norm = accelerator.clip_grad_norm_(policy.parameters(), grad_clip_norm)
    else:
        grad_norm = torch.nn.utils.clip_grad_norm_(policy.parameters(), float("inf"), error_if_nonfinite=False)

    with lock if lock is not None else nullcontext():
        optimizer.step()

    optimizer.zero_grad()

    if lr_scheduler is not None:
        lr_scheduler.step()

    if has_method(accelerator.unwrap_model(policy, keep_fp32_wrapper=True), "update"):
        accelerator.unwrap_model(policy, keep_fp32_wrapper=True).update()

    train_metrics.loss = total_loss
    train_metrics.grad_norm = grad_norm.item()
    train_metrics.lr = optimizer.param_groups[0]["lr"]
    train_metrics.update_s = time.perf_counter() - start_time
    return train_metrics, output_dict


lt.update_policy = update_policy  # train() 루프가 모듈 전역 이름으로 호출하므로 이걸로 교체됨

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    print(f"gradient accumulation: {GRAD_ACCUM_STEPS} micro-batches per update", flush=True)
    lt.main()
