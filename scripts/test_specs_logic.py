import platform
import psutil
import sqlite3
import re
import sys

sys.path.insert(0, 'backend')
from platform_hw import get_gpu_usage_info as platform_gpu_usage_info

def get_cpu_model():
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if val:
                return val.strip()
        except Exception:
            pass
    return platform.processor() or "x86_64 Processor"

def get_gpu_model():
    try:
        gpu_info = platform_gpu_usage_info()
        if gpu_info.get("gpus"):
            return gpu_info["gpus"][0].get("name") or "Active Graphics Adapter"
    except Exception:
        pass
    return "Active Graphics Adapter"

print("CPU Model:", get_cpu_model())
print("GPU Model:", get_gpu_model())
