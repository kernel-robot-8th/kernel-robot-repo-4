"""Configure supported GPU acceleration, then call the unmodified upstream trainer."""

import json
import os

import torch


def main():
    """Enable BF16 through Accelerate and retain full-resolution ACT training."""
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("The requested BF16 training requires a supported CUDA GPU")
    os.environ["ACCELERATE_MIXED_PRECISION"] = "bf16"
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = True
    torch.backends.cudnn.deterministic = False
    torch.set_float32_matmul_precision("high")
    from accelerate import Accelerator
    from lerobot.scripts.lerobot_train import main as upstream_main

    accelerator = Accelerator()
    if accelerator.mixed_precision != "bf16":
        raise RuntimeError("Accelerate did not enable BF16 mixed precision")
    print(
        "GPU_ACCELERATION "
        + json.dumps(
            {
                "mixed_precision": accelerator.mixed_precision,
                "matmul_tf32": torch.backends.cuda.matmul.allow_tf32,
                "cudnn_tf32": torch.backends.cudnn.allow_tf32,
                "cudnn_benchmark": torch.backends.cudnn.benchmark,
                "matmul_precision": torch.get_float32_matmul_precision(),
                "compile": False,
            }
        ),
        flush=True,
    )
    upstream_main()


if __name__ == "__main__":
    main()
