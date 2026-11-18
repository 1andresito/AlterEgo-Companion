"""Which processor the voice conversion runs on: an NVIDIA GPU when one is usable, else the CPU.

Alter Ego runs on big desktops and on small laptops, so this is decided on
each machine, not in the settings: the GPU is used only when PyTorch was
installed with CUDA support and sees a card (`torch.cuda.is_available()`).
Everything else, including a missing or CPU-only PyTorch, means the CPU.

    ALTER_EGO_DEVICE=cpu   forces the CPU (a weak or busy GPU, or for testing)
    ALTER_EGO_DEVICE=cuda  asks for the GPU; still falls back to the CPU if there is none

The answer is worked out once, on first use (importing PyTorch takes a moment),
and never raises.
"""

from __future__ import annotations

import os
import threading
import warnings

DEVICE_ENV = "ALTER_EGO_DEVICE"
CPU = "cpu"
CUDA = "cuda"
MIN_GPU_MEMORY = 3 * 1024 ** 3  # The voice needs about 1 GB on the card, and Ollama's model shares it.

_lock = threading.Lock()
_device: str | None = None
_name = ""


def cpu_threads() -> int:
    """Threads for CPU inference: half the cores, so the rest of the computer keeps going."""
    return max(2, (os.cpu_count() or 4) // 2)


def compute_device() -> str:
    """"cuda" when an NVIDIA GPU is usable through PyTorch, else "cpu"."""
    global _device, _name
    with _lock:
        if _device is not None:
            return _device
        _device, _name = CPU, ""
        if os.environ.get(DEVICE_ENV, "").strip().lower() == CPU:
            return _device
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import torch

                if torch.cuda.is_available():
                    name = torch.cuda.get_device_name(0)
                    total = torch.cuda.get_device_properties(0).total_memory
                    if isinstance(total, int) and total < MIN_GPU_MEMORY:
                        # A small card would run out of memory next to the AI model: the CPU is safer.
                        print(f"Alter Ego: {name} has {total / 1024 ** 3:.1f} GB of video memory; "
                              "the voice uses the CPU.")
                    else:
                        _device, _name = CUDA, name
        except Exception as error:  # noqa: BLE001 - a broken CUDA install must only mean "use the CPU"
            print(f"Warning: could not check for a GPU ({type(error).__name__}: {error}); using the CPU.")
        return _device


def use_cpu() -> None:
    """Switch to the CPU for the rest of the run (after the GPU failed to load a model)."""
    global _device, _name
    with _lock:
        _device, _name = CPU, ""


def describe_device() -> str:
    """'GPU (NVIDIA GeForce RTX 5070)' or 'CPU, 6 threads', for the console and the menu."""
    device = compute_device()
    return f"GPU ({_name})" if device == CUDA else f"CPU, {cpu_threads()} threads"


def _reset_for_tests() -> None:
    global _device, _name
    with _lock:
        _device, _name = None, ""
