"""What this computer can take: memory, and whether an NVIDIA graphics driver is there.

Alter Ego runs on big desktops and small laptops, so a few choices are made per
computer instead of in the settings:

    keep_voice_loaded()  16 GB of memory or more: the voice stays loaded between
                         replies (fast). Less: it is unloaded after a quiet while,
                         so its 2-3 GB go back to the system (voice/remote.py).
    has_nvidia_driver()  an NVIDIA card with its driver: the GPU pack may be
                         offered (core/gpu_pack.py). Says nothing about PyTorch.

Standard library only, never raises; environment variables override the answers
for testing (ALTER_EGO_KEEP_VOICE=1 or 0).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path

KEEP_VOICE_ENV = "ALTER_EGO_KEEP_VOICE"
KEEP_VOICE_MIN_GB = 16  # With less memory, the voice's 2-3 GB matter more than its reload time.


def total_ram_gb() -> float:
    """The computer's memory in GB, or 0.0 when it cannot be read."""
    try:
        if sys.platform == "win32":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys / 1024 ** 3
            return 0.0
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            for line in meminfo:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 ** 2  # kB -> GB
    except (OSError, ValueError, AttributeError):
        pass
    return 0.0


def process_memory_mb() -> int:
    """This process's memory in use (working set / resident), in MB; 0 when it cannot be read."""
    try:
        if sys.platform == "win32":
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi")
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return counters.WorkingSetSize >> 20
            return 0
        with open("/proc/self/status", encoding="ascii") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) >> 10  # kB -> MB
    except (OSError, ValueError, AttributeError):
        pass
    return 0


def keep_voice_loaded() -> bool:
    """Should the voice stay loaded between replies on this computer?"""
    override = os.environ.get(KEEP_VOICE_ENV, "").strip()
    if override in ("0", "1"):
        return override == "1"
    ram = total_ram_gb()
    return ram == 0.0 or ram >= KEEP_VOICE_MIN_GB  # Unknown memory: keep the old behaviour (fast).


def has_nvidia_driver() -> bool:
    """Is an NVIDIA graphics driver installed (so CUDA could work with a CUDA build of PyTorch)?"""
    if sys.platform == "win32":
        system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        return (system / "nvcuda.dll").is_file()
    if shutil.which("nvidia-smi"):
        return True
    return any(Path(folder, "libcuda.so.1").exists()
               for folder in ("/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib"))
