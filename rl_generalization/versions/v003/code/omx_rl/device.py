"""Explicit accelerator selection; never silently downgrade --device cuda."""
import torch


def resolve_device(requested):
    if requested not in {'auto', 'cpu', 'cuda'}:
        raise ValueError(f'Unknown device: {requested}')
    if requested == 'cpu':
        return 'cpu'
    if not torch.cuda.is_available():
        if requested == 'cuda':
            raise RuntimeError('CUDA requested but unavailable. Check NVIDIA driver and PyTorch wheel.')
        return 'cpu'
    # Detect incompatible GPU architecture/driver with an actual operation.
    value = (torch.ones(4, device='cuda') * 2).sum().item()
    if value != 8:
        raise RuntimeError('CUDA self-check failed')
    return 'cuda'
