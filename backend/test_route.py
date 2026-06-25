import psutil
import os
import time

if __name__ == "__main__":
    current_uid = os.getuid() if hasattr(os, "getuid") else None

    print("Profiling original way (calling proc.uids().real)...")
    start = time.time()
    count = 0
    for proc in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent", "cmdline"]):
        try:
            info = proc.info
            username = info.get("username") or ""
            pid = proc.pid
            if pid <= 1 or pid == os.getpid() or not username:
                continue
            if current_uid is not None:
                if proc.uids().real != current_uid:
                    continue
            count += 1
        except Exception:
            pass
    print(f"Original: {time.time() - start:.3f} seconds for {count} processes")

    print("\nProfiling optimized way (passing 'uids' to process_iter)...")
    start = time.time()
    count = 0
    for proc in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent", "cmdline", "uids"]):
        try:
            info = proc.info
            username = info.get("username") or ""
            pid = proc.pid
            if pid <= 1 or pid == os.getpid() or not username:
                continue
            uids = info.get("uids")
            if current_uid is not None and uids is not None:
                if uids.real != current_uid:
                    continue
            count += 1
        except Exception:
            pass
    print(f"Optimized: {time.time() - start:.3f} seconds for {count} processes")
