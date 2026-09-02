"""
Cross-platform GPU and driver detection for Linux, Windows, and macOS.
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

OS_NAME = platform.system()


def _run(cmd: list[str] | str, *, shell: bool = False, timeout: int = 12) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        shell=shell,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout,
    )


def _classify_gpu_name(name: str, bus_hint: str = "") -> str:
    lower = f"{name} {bus_hint}".lower()
    if any(token in lower for token in ("nvidia", "geforce", "quadro", "rtx", "gtx")):
        return "dedicated"
    if any(token in lower for token in ("intel", "uhd", "iris", "hd graphics", "apple m", "apple gpu", "radeon graphics")):
        return "integrated"
    if "amd" in lower or "ati" in lower:
        return "integrated" if ":00:02." in bus_hint else "dedicated"
    return "dedicated"


def _linux_gpus() -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []
    try:
        result = _run("lspci -nn | grep -i -E 'vga|3d|display'", shell=True, timeout=5)
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            pci = line.split()[0]
            name = line.split("]:", 1)[1].strip() if "]:" in line else line
            name = re.sub(r"\s*\[[0-9a-f]{4}:[0-9a-f]{4}\].*$", "", name, flags=re.IGNORECASE).strip()
            gpus.append({
                "id": pci,
                "name": name,
                "kind": _classify_gpu_name(name, pci),
                "driver": None,
                "modules": [],
            })
    except Exception:
        pass

    try:
        result = _run("lspci -k", shell=True, timeout=5)
        driver_map: dict[str, dict[str, Any]] = {}
        current = None
        for line in result.stdout.splitlines():
            if not line.startswith(" ") and not line.startswith("\t"):
                current = line.strip()
                driver_map[current] = {"driver": "None", "modules": []}
            elif current:
                if "Kernel driver in use:" in line:
                    driver_map[current]["driver"] = line.split("Kernel driver in use:")[1].strip()
                elif "Kernel modules:" in line:
                    driver_map[current]["modules"] = [
                        part.strip()
                        for part in line.split("Kernel modules:")[1].split(",")
                        if part.strip()
                    ]
        for gpu in gpus:
            for device, info in driver_map.items():
                if gpu["name"] in device or gpu["id"] in device:
                    gpu["driver"] = info["driver"]
                    gpu["modules"] = info["modules"]
                    break
    except Exception:
        pass
    return gpus


def _classify_windows_gpu(name: str, pnp_id: str) -> str:
    lower_id = pnp_id.lower()
    lower_name = name.lower()
    if "ven_10de" in lower_id: # NVIDIA
        return "dedicated"
    if "ven_8086" in lower_id: # Intel
        return "integrated"
    if "ven_1002" in lower_id: # AMD
        if any(token in lower_name for token in ("radeon graphics", "amd radeon(tm)", "apu", "radeon hd")):
            return "integrated"
        return "dedicated"
    return _classify_gpu_name(name)


def _windows_gpus() -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []
    ps_script = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,PNPDeviceID,DriverVersion,AdapterRAM,Status | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = _run(["powershell", "-NoProfile", "-Command", ps_script], timeout=15)
        if result.returncode != 0 or not result.stdout.strip():
            return gpus
        payload = json.loads(result.stdout)
        rows = payload if isinstance(payload, list) else [payload]
        for index, row in enumerate(rows):
            name = str(row.get("Name") or "GPU").strip()
            pnp_id = str(row.get("PNPDeviceID") or "")
            if not name:
                continue
            # Keep Basic Display Adapter only if it represents a physical chip (has a PCI vendor)
            if name.lower() in ("microsoft basic display driver", "microsoft basic display adapter"):
                if not any(v in pnp_id.lower() for v in ("ven_10de", "ven_8086", "ven_1002")):
                    continue
            kind = _classify_windows_gpu(name, pnp_id)
            gpus.append({
                "id": pnp_id or f"gpu-{index}",
                "name": name,
                "kind": kind,
                "driver": str(row.get("DriverVersion") or "Unknown"),
                "modules": [],
                "status": str(row.get("Status") or ""),
                "vram_bytes": row.get("AdapterRAM"),
            })
    except Exception:
        pass
    return gpus


def _darwin_gpus() -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []
    try:
        result = _run(["system_profiler", "SPDisplaysDataType", "-json"], timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            payload = json.loads(result.stdout)
            displays = payload.get("SPDisplaysDataType") or []
            for index, item in enumerate(displays):
                chipset = str(item.get("sppci_model") or item.get("_name") or "GPU")
                vendor = str(item.get("sppci_vendor") or "")
                name = chipset if vendor in chipset else f"{vendor} {chipset}".strip()
                gpus.append({
                    "id": str(item.get("sppci_device_type") or f"display-{index}"),
                    "name": name,
                    "kind": _classify_gpu_name(name),
                    "driver": str(item.get("spdisplays_metal") or item.get("spdisplays_opengl") or "macOS"),
                    "modules": [],
                    "vram": item.get("spdisplays_vram") or item.get("spdisplays_vram_shared"),
                })
            if gpus:
                return gpus
    except Exception:
        pass

    try:
        result = _run(["system_profiler", "SPDisplaysDataType"], timeout=15)
        current = None
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.endswith(":") and line not in ("Chipset Model:", "Vendor:", "VRAM (Total):", "Metal:"):
                current = line[:-1]
            elif current and line.startswith("Chipset Model:"):
                name = line.split(":", 1)[1].strip()
                gpus.append({
                    "id": current,
                    "name": name,
                    "kind": _classify_gpu_name(name),
                    "driver": "macOS",
                    "modules": [],
                })
                current = None
    except Exception:
        pass
    return gpus


def list_gpus() -> list[dict[str, Any]]:
    if OS_NAME == "Linux":
        return _linux_gpus()
    if OS_NAME == "Windows":
        return _windows_gpus()
    if OS_NAME == "Darwin":
        return _darwin_gpus()
    return []


def _linux_recommended_drivers() -> list[str]:
    recommended: list[str] = []
    try:
        result = _run("ubuntu-drivers devices", shell=True, timeout=8)
        for line in result.stdout.splitlines():
            if "recommended" in line.lower():
                m = re.match(r"^\s*driver\s*:\s*(.+)", line, re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    if val:
                        recommended.append(val.split()[0])
    except Exception:
        pass
    return recommended


def _windows_recommended_drivers(gpus: list[dict[str, Any]]) -> list[str]:
    recs: list[str] = []
    for gpu in gpus:
        lower = gpu["name"].lower()
        if "nvidia" in lower:
            recs.append("NVIDIA GeForce Experience / Studio Driver")
        elif "amd" in lower or "radeon" in lower:
            recs.append("AMD Adrenalin Software")
        elif "intel" in lower:
            recs.append("Intel Graphics Driver (Intel Driver & Support Assistant)")
    if not recs and shutil.which("winget"):
        recs.append("winget upgrade --all (check for GPU vendor packages)")
    return list(dict.fromkeys(recs))


def _darwin_recommended_drivers() -> list[str]:
    return ["macOS Software Update (Apple-provided graphics firmware and drivers)"]


def get_installed_driver_packages() -> list[str]:
    import subprocess
    import platform
    installed = []
    if platform.system() == "Linux":
        try:
            res = subprocess.run(
                "dpkg-query -W -f='${Package}\\n' 'nvidia-driver-*' 'intel-media-*' 'mesa-vulkan-*' 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5
            )
            for line in res.stdout.splitlines():
                pkg = line.strip()
                if pkg:
                    installed.append(pkg)
        except Exception:
            pass
    return installed


def get_driver_info(
    *,
    package_check_command: str = "",
    package_update_command: str = "",
    fast: bool = False,
) -> dict[str, Any]:
    gpus = list_gpus()
    gpu_lines = []
    all_drivers = []
    for gpu in gpus:
        label = f"{gpu['name']} ({'Integrated' if gpu.get('kind') == 'integrated' else 'Dedicated'})"
        gpu_lines.append(label)
        all_drivers.append({
            "device": gpu["name"],
            "driver": gpu.get("driver") or "Unknown",
            "modules": gpu.get("modules") or [],
            "kind": gpu.get("kind") or "dedicated",
        })

    if OS_NAME == "Linux":
        try:
            result = _run("lspci -nn", shell=True, timeout=5)
            other_devices = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                if any(kw in line.lower() for kw in ("network", "ethernet", "audio", "multimedia")):
                    if not any(kw in line.lower() for kw in ("vga", "3d", "display")):
                        pci = line.split()[0]
                        name = line.split("]:", 1)[1].strip() if "]:" in line else line
                        name = re.sub(r"\s*\[[0-9a-f]{4}:[0-9a-f]{4}\].*$", "", name, flags=re.IGNORECASE).strip()
                        other_devices.append({
                            "id": pci,
                            "name": name,
                            "driver": None,
                            "modules": [],
                        })
            if other_devices:
                res_k = _run("lspci -k", shell=True, timeout=5)
                driver_map = {}
                current = None
                for line in res_k.stdout.splitlines():
                    if not line.startswith(" ") and not line.startswith("\t"):
                        current = line.strip()
                        driver_map[current] = {"driver": "None", "modules": []}
                    elif current:
                        if "Kernel driver in use:" in line:
                            driver_map[current]["driver"] = line.split("Kernel driver in use:")[1].strip()
                        elif "Kernel modules:" in line:
                            driver_map[current]["modules"] = [
                                part.strip()
                                for part in line.split("Kernel modules:")[1].split(",")
                                if part.strip()
                            ]
                for dev in other_devices:
                    for device, info in driver_map.items():
                        if dev["name"] in device or dev["id"] in device:
                            dev["driver"] = info["driver"]
                            dev["modules"] = info["modules"]
                            break
                    all_drivers.append({
                        "device": dev["name"],
                        "driver": dev["driver"] or "Unknown",
                        "modules": dev["modules"] or [],
                        "kind": "other",
                    })
        except Exception:
            pass

    if OS_NAME == "Linux" and not fast:
        recommended = _linux_recommended_drivers()
    elif OS_NAME == "Windows" and not fast:
        recommended = _windows_recommended_drivers(gpus)
    elif OS_NAME == "Darwin" and not fast:
        recommended = _darwin_recommended_drivers()
    else:
        recommended = []

    driver_package_updates = {
        "available": False,
        "checked": False,
        "command": package_update_command,
        "summary": "Driver update check is not configured for this OS." if not fast else "Driver package check pending...",
    }

    if package_check_command and not fast:
        try:
            result = _run(package_check_command, shell=True, timeout=30)
            output = f"{result.stdout}\n{result.stderr}".strip()
            driver_package_updates["checked"] = True
            driver_package_updates["available"] = (
                result.returncode == 0 and output and "0 upgraded" not in output.lower()
            )
            if OS_NAME == "Windows":
                driver_package_updates["available"] = (
                    "upgrades available" in output.lower()
                    or "found" in output.lower()
                    or len(output.splitlines()) > 1
                )
            elif OS_NAME == "Darwin":
                driver_package_updates["available"] = "recommended" in output.lower() or "*" in output
            if driver_package_updates["available"]:
                driver_package_updates["summary"] = "Driver or firmware updates are available."
            else:
                driver_package_updates["summary"] = "Driver packages appear up to date."
        except Exception:
            pass
    elif OS_NAME == "Windows" and shutil.which("winget"):
        driver_package_updates["command"] = package_update_command or "winget upgrade --all"
        driver_package_updates["summary"] = "Use Winget to update GPU vendor tools and drivers."
        driver_package_updates["checked"] = True
    elif OS_NAME == "Darwin":
        driver_package_updates["command"] = package_update_command or "softwareupdate -l"
        driver_package_updates["summary"] = "Use macOS Software Update for Apple graphics and firmware updates."
        driver_package_updates["checked"] = True

    return {
        "ok": True,
        "os": OS_NAME,
        "gpus": gpu_lines,
        "gpu_details": gpus,
        "recommended_drivers": recommended,
        "all_drivers": all_drivers,
        "driver_package_updates": driver_package_updates,
    }


def _nvidia_usage_rows() -> list[dict[str, Any]]:
    if shutil.which("nvidia-smi") is None:
        return []
    try:
        result = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        rows = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 5:
                continue
            rows.append({
                "name": parts[0],
                "usage_pct": int("".join(c for c in parts[1] if c.isdigit()) or 0),
                "mem_used_mb": int("".join(c for c in parts[2] if c.isdigit()) or 0),
                "mem_total_mb": int("".join(c for c in parts[3] if c.isdigit()) or 0),
                "temperature_c": int("".join(c for c in parts[4] if c.isdigit()) or 0),
            })
        return rows
    except Exception:
        return []


def _read_sysfs_int(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except Exception:
        return None


def _linux_gpu_usage(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drm_by_pci = _drm_cards_by_pci()
    nvidia_rows = _nvidia_usage_rows()
    nvidia_idx = 0
    entries: list[dict[str, Any]] = []

    for gpu in gpus:
        kind = gpu.get("kind") or "dedicated"
        entry: dict[str, Any] = {
            "name": gpu["name"],
            "kind": kind,
            "kind_label": "Integrated GPU" if kind == "integrated" else "Dedicated GPU",
            "available": False,
            "usage_pct": 0,
            "source": "unavailable",
        }
        lower_name = gpu["name"].lower()
        if "nvidia" in lower_name or "geforce" in lower_name:
            if nvidia_idx < len(nvidia_rows):
                row = nvidia_rows[nvidia_idx]
                nvidia_idx += 1
                entry.update({
                    "available": True,
                    "usage_pct": row["usage_pct"],
                    "mem_used_mb": row["mem_used_mb"],
                    "mem_total_mb": row["mem_total_mb"],
                    "temperature_c": row["temperature_c"],
                    "source": "nvidia-smi",
                    "name": row["name"],
                })
            else:
                entry["message"] = "Dedicated NVIDIA GPU detected, but live utilization is unavailable."
        elif kind == "integrated" and "intel" in lower_name:
            # Normalize PCI ID: lspci gives "00:02.0" but DRM uevent stores
            # "0000:00:02.0".  Try both forms so the lookup never silently fails.
            raw_id = gpu.get("id", "")
            card_dir = drm_by_pci.get(raw_id)
            if card_dir is None and raw_id and not raw_id.startswith("0000:"):
                card_dir = drm_by_pci.get(f"0000:{raw_id}")
            # Last-resort: scan all DRM cards for an Intel VGA device
            if card_dir is None:
                for pci_slot, cdir in drm_by_pci.items():
                    uevent = cdir / "device" / "uevent"
                    if uevent.is_file():
                        text = uevent.read_text()
                        # Intel VGA class is 030000 or 030200; vendor 8086
                        if "8086" in text and ("PCI_CLASS=30000" in text or "PCI_CLASS=30200" in text or "PCI_CLASS=38000" in text):
                            card_dir = cdir
                            break

            integrated_status = _intel_integrated_status(gpu, card_dir)
            entry["integrated_status"] = integrated_status
            usage = _intel_usage_from_tool()
            source = "intel_gpu_top"
            if usage is None and card_dir is not None:
                usage = _intel_usage_from_sysfs(card_dir)
                source = "i915 sysfs"
            if usage is not None:
                entry.update({"available": True, "usage_pct": usage, "source": source})
            elif integrated_status == "Inactive":
                entry.update({
                    "available": True,
                    "usage_pct": 0,
                    "source": "power state",
                    "message": "Integrated GPU is present but idle (0% does not mean broken).",
                })
            elif integrated_status == "Disabled":
                entry["message"] = "Integrated GPU driver is bound but the device appears disabled."
            elif integrated_status == "Not Detected":
                entry["message"] = "Integrated GPU hardware was not detected by the system."
            else:
                entry.update({
                    "available": True,
                    "usage_pct": 0,
                    "source": "active fallback",
                    "message": "Integrated GPU is active; utilization sampling is temporarily unavailable."
                })
        else:
            entry["message"] = "GPU detected, but live utilization is unavailable on this system."
        entries.append(entry)
    return entries


def _drm_cards_by_pci() -> dict[str, Path]:
    cards: dict[str, Path] = {}
    drm_root = Path("/sys/class/drm")
    if not drm_root.is_dir():
        return cards
    for card_dir in sorted(drm_root.iterdir()):
        if not card_dir.is_dir() or not re.fullmatch(r"card\d+", card_dir.name):
            continue
        uevent = card_dir / "device" / "uevent"
        if not uevent.is_file():
            continue
        for raw in uevent.read_text().splitlines():
            if raw.startswith("PCI_SLOT_NAME="):
                cards[raw.split("=", 1)[1].strip()] = card_dir
                break
    return cards


def _intel_usage_from_sysfs(card_dir: Path) -> Optional[int]:
    act = _read_sysfs_int(card_dir / "gt" / "gt0" / "rps_act_freq_mhz")
    max_freq = _read_sysfs_int(card_dir / "gt" / "gt0" / "rps_max_freq_mhz")
    if act is None or not max_freq:
        return None
    return max(0, min(100, int(act / max_freq * 100)))


def _intel_integrated_status(gpu: dict[str, Any], card_dir: Optional[Path]) -> str:
    """Classify integrated Intel GPU as Active, Inactive, Disabled, or Not Detected."""
    driver = str(gpu.get("driver") or "").strip()
    modules = [str(module).lower() for module in (gpu.get("modules") or [])]
    lower_name = str(gpu.get("name") or "").lower()
    if "intel" not in lower_name:
        return "Not Detected"
    if driver in ("", "None", "none"):
        if any(token in modules for token in ("i915", "xe")):
            return "Disabled"
        return "Not Detected"
    if card_dir is not None:
        runtime = card_dir / "device" / "power" / "runtime_status"
        if runtime.is_file():
            state = runtime.read_text().strip().lower()
            if state in ("suspended", "unsupported"):
                return "Inactive"
            if state == "active":
                return "Active"
        enabled = card_dir / "device" / "enable"
        if enabled.is_file():
            try:
                if enabled.read_text().strip() == "0":
                    return "Disabled"
            except Exception:
                pass
    if driver.lower() in ("i915", "xe", "i965"):
        return "Active"
    return "Inactive"


def _intel_usage_from_tool() -> Optional[int]:
    if shutil.which("intel_gpu_top") is None:
        return None
    try:
        result = _run(["intel_gpu_top", "-J", "-s", "500"], timeout=3)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        payload = json.loads(result.stdout)
        busy = [
            float(engine["busy"])
            for engine in (payload.get("engines") or {}).values()
            if isinstance(engine, dict) and "busy" in engine
        ]
        if not busy:
            return None
        return max(0, min(100, int(max(busy))))
    except Exception:
        return None


# Windows-only DXGI / COM interop — only loaded on Windows to avoid
# AttributeError: module 'ctypes' has no attribute 'wintypes' on Linux/macOS.
if OS_NAME == "Windows":
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]
        def __init__(self, guid_str):
            parts = guid_str.split('-')
            self.Data1 = int(parts[0], 16)
            self.Data2 = int(parts[1], 16)
            self.Data3 = int(parts[2], 16)
            for i in range(8):
                self.Data4[i] = int(parts[3][2*i:2*i+2] if i < 2 else parts[4][2*(i-2):2*(i-2)+2], 16)

    class LUID(ctypes.Structure):
        _fields_ = [
            ("LowPart", wintypes.DWORD),
            ("HighPart", wintypes.LONG),
        ]

    class DXGI_ADAPTER_DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", ctypes.c_wchar * 128),
            ("VendorId", ctypes.c_uint),
            ("DeviceId", ctypes.c_uint),
            ("SubSysId", ctypes.c_uint),
            ("Revision", ctypes.c_uint),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", LUID),
            ("Flags", ctypes.c_uint),
        ]

def _get_dxgi_gpus_internal() -> list[dict[str, Any]]:
    if OS_NAME != "Windows":
        return []
    try:
        dxgi = ctypes.windll.dxgi
    except Exception:
        return []

    IID_IDXGIFactory1 = GUID("770aae78-f26f-4dba-a829-253c83d1b387")
    factory = ctypes.c_void_p()
    hr = dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory))
    if hr < 0:
        return []

    def call_com_method(interface_ptr, index, prototype, *args):
        vtable_ptr = ctypes.cast(interface_ptr, ctypes.POINTER(ctypes.c_void_p))
        vtable = ctypes.cast(vtable_ptr[0], ctypes.POINTER(ctypes.c_void_p))
        func_ptr = vtable[index]
        func = prototype(func_ptr)
        return func(interface_ptr, *args)

    EnumAdapters1_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))
    GetDesc1_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC1))
    Release_proto = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)

    gpus = []
    index = 0
    while True:
        adapter = ctypes.c_void_p()
        hr = call_com_method(factory, 12, EnumAdapters1_proto, index, ctypes.byref(adapter))
        if hr < 0:
            break
        
        desc = DXGI_ADAPTER_DESC1()
        hr_desc = call_com_method(adapter, 10, GetDesc1_proto, ctypes.byref(desc))
        if hr_desc >= 0:
            luid_str = f"luid_0x{desc.AdapterLuid.HighPart:08x}_0x{desc.AdapterLuid.LowPart:08x}".lower()
            gpus.append({
                "name": desc.Description,
                "vendor_id": desc.VendorId,
                "device_id": desc.DeviceId,
                "luid": luid_str,
            })
        call_com_method(adapter, 2, Release_proto)
        index += 1

    call_com_method(factory, 2, Release_proto)
    return gpus

def _parse_pnp_ids(pnp_id: str):
    lower = pnp_id.lower()
    ven_match = re.search(r"ven_([0-9a-fA-F]+)", lower)
    dev_match = re.search(r"dev_([0-9a-fA-F]+)", lower)
    ven = int(ven_match.group(1), 16) if ven_match else None
    dev = int(dev_match.group(1), 16) if dev_match else None
    return ven, dev

def _windows_gpu_usage(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    nvidia_rows = _nvidia_usage_rows()
    nvidia_idx = 0

    # Query maximum live GPU engine utilization across all engines in under 200ms
    wmi_gpu_pct = 0
    try:
        wmi_script = (
            "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty UtilizationPercentage | Sort-Object -Descending | Select-Object -First 1"
        )
        wmi_r = _run(["powershell", "-NoProfile", "-Command", wmi_script], timeout=3)
        if wmi_r.returncode == 0 and wmi_r.stdout.strip():
            wmi_gpu_pct = int(float(wmi_r.stdout.strip()))
    except Exception:
        pass

    for gpu in gpus:
        kind = gpu.get("kind") or "dedicated"
        entry: dict[str, Any] = {
            "name": gpu["name"],
            "kind": kind,
            "kind_label": "Integrated GPU" if kind == "integrated" else "Dedicated GPU",
            "available": True,
            "usage_pct": max(0, min(100, wmi_gpu_pct)),
            "source": "WMI GPU perf counters",
        }
        if kind == "integrated":
            status_val = str(gpu.get("status") or "").upper()
            has_driver = gpu.get("driver") and gpu.get("driver") != "Unknown"
            entry["integrated_status"] = "Active" if (status_val in ("OK", "", "UNKNOWN") or has_driver) else "Inactive"

        lower = gpu["name"].lower()
        if "nvidia" in lower and nvidia_idx < len(nvidia_rows):
            row = nvidia_rows[nvidia_idx]
            nvidia_idx += 1
            entry.update({
                "available": True,
                "usage_pct": row["usage_pct"],
                "mem_used_mb": row["mem_used_mb"],
                "mem_total_mb": row["mem_total_mb"],
                "temperature_c": row["temperature_c"],
                "source": "nvidia-smi",
                "name": row["name"],
            })
        entries.append(entry)
    return entries


def _darwin_gpu_usage(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for gpu in gpus:
        kind = gpu.get("kind") or "integrated"
        entries.append({
            "name": gpu["name"],
            "kind": kind,
            "kind_label": "Integrated GPU" if kind == "integrated" else "Dedicated GPU",
            "available": False,
            "usage_pct": 0,
            "source": "macOS",
            "message": "macOS does not expose per-GPU utilization without additional tools. Hardware detection is active.",
        })
    return entries


_gpu_info_cache = None
_gpu_cache_lock = threading.Lock()
_bg_thread_started = False

def _bg_gpu_updater():
    global _gpu_info_cache
    while True:
        try:
            info = _query_gpu_usage_info_raw()
            with _gpu_cache_lock:
                _gpu_info_cache = info
        except Exception:
            pass
        time.sleep(2)

def _query_gpu_usage_info_raw() -> dict[str, Any]:
    gpus = list_gpus()
    if not gpus:
        return {"ok": True, "available": False, "gpus": [], "message": "No GPU hardware detected.", "os": OS_NAME}

    if OS_NAME == "Linux":
        entries = _linux_gpu_usage(gpus)
    elif OS_NAME == "Windows":
        entries = _windows_gpu_usage(gpus)
    elif OS_NAME == "Darwin":
        entries = _darwin_gpu_usage(gpus)
    else:
        entries = []

    any_available = any(item.get("available") for item in entries)
    return {
        "ok": True,
        "available": any_available,
        "gpus": entries,
        "os": OS_NAME,
        "message": None if any_available else "GPU hardware detected, but utilization data is unavailable.",
    }


def get_gpu_usage_info() -> dict[str, Any]:
    global _bg_thread_started, _gpu_info_cache
    if not _bg_thread_started:
        _bg_thread_started = True
        t = threading.Thread(target=_bg_gpu_updater, daemon=True)
        t.start()

    with _gpu_cache_lock:
        if _gpu_info_cache is not None:
            return _gpu_info_cache

    return _query_gpu_usage_info_raw()
