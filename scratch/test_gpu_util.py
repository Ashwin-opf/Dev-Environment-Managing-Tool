import ctypes
from ctypes import wintypes
import json
import re
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from platform_hw import _windows_gpus, _run, _nvidia_usage_rows

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

def get_dxgi_gpus():
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

def parse_pnp_ids(pnp_id: str):
    lower = pnp_id.lower()
    ven_match = re.search(r"ven_([0-9a-fA-F]+)", lower)
    dev_match = re.search(r"dev_([0-9a-fA-F]+)", lower)
    ven = int(ven_match.group(1), 16) if ven_match else None
    dev = int(dev_match.group(1), 16) if dev_match else None
    return ven, dev

def test_matching():
    gpus = _windows_gpus()
    dxgi_gpus = get_dxgi_gpus()
    print("Detected physical GPUs via WMI:")
    print(json.dumps(gpus, indent=2))
    print("\nDetected DXGI Adapters:")
    print(json.dumps(dxgi_gpus, indent=2))

    luid_to_util = {}
    ps_script = (
        "Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty CounterSamples | "
        "Select-Object InstanceName,CookedValue | ConvertTo-Json -Compress"
    )
    try:
        result = _run(["powershell", "-NoProfile", "-Command", ps_script], timeout=8)
        if result.returncode == 0 and result.stdout.strip():
            payload = json.loads(result.stdout)
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                instance = str(row.get("InstanceName") or "").lower()
                value = int(float(row.get("CookedValue") or 0))
                # Extract LUID from instance name: pid_1232_luid_0x00000000_0x06592551_phys_0_eng_0_engtype_3d
                luid_match = re.search(r"luid_(0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)", instance)
                if luid_match:
                    luid_str = f"luid_{luid_match.group(1)}".lower()
                    luid_to_util[luid_str] = max(luid_to_util.get(luid_str, 0), value)
    except Exception as e:
        print(f"Failed to query counters: {e}")

    print("\nLUID to Utilization Map:")
    print(json.dumps(luid_to_util, indent=2))

    # Match and produce entries
    entries = []
    nvidia_rows = _nvidia_usage_rows()
    nvidia_idx = 0

    for gpu in gpus:
        kind = gpu.get("kind") or "dedicated"
        entry = {
            "name": gpu["name"],
            "kind": kind,
            "kind_label": "Integrated GPU" if kind == "integrated" else "Dedicated GPU",
            "available": False,
            "usage_pct": 0,
            "source": "unavailable",
        }
        if kind == "integrated":
            # Default to Active if Status is OK or if driver version is present
            entry["integrated_status"] = "Active" if gpu.get("status", "").upper() == "OK" else "Inactive"
        
        # Match with DXGI adapter to find LUID
        matched_dxgi = None
        ven_pnp, dev_pnp = parse_pnp_ids(gpu["id"])
        
        for d_gpu in dxgi_gpus:
            # Match by Vendor ID and Device ID
            if ven_pnp is not None and dev_pnp is not None:
                if d_gpu["vendor_id"] == ven_pnp and d_gpu["device_id"] == dev_pnp:
                    matched_dxgi = d_gpu
                    break
        
        if not matched_dxgi:
            # Fallback to name match
            gpu_name_norm = re.sub(r"[^a-z0-9]", "", gpu["name"].lower())
            for d_gpu in dxgi_gpus:
                d_name_norm = re.sub(r"[^a-z0-9]", "", d_gpu["name"].lower())
                if gpu_name_norm in d_name_norm or d_name_norm in gpu_name_norm:
                    matched_dxgi = d_gpu
                    break

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
        elif matched_dxgi and matched_dxgi["luid"] in luid_to_util:
            luid = matched_dxgi["luid"]
            entry.update({
                "available": True,
                "usage_pct": luid_to_util[luid],
                "source": "Windows GPU counters",
            })
        else:
            # Last-resort fallback: check if any matched_dxgi is present but has 0 util
            if matched_dxgi:
                entry.update({
                    "available": True,
                    "usage_pct": 0,
                    "source": "Windows DXGI",
                })
            else:
                entry["message"] = "GPU detected. Live utilization may require vendor tools on Windows."

        entries.append(entry)

    print("\nResulting Entries:")
    print(json.dumps(entries, indent=2))

if __name__ == "__main__":
    test_matching()
