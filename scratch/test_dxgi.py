import ctypes
from ctypes import wintypes
import json

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, guid_str):
        # Format: "770aae78-f26f-4dba-a829-253c83d1b387"
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
    except Exception as e:
        print(f"Failed to load dxgi: {e}")
        return {"error": f"Failed to load dxgi.dll: {e}"}

    IID_IDXGIFactory1 = GUID("770aae78-f26f-4dba-a829-253c83d1b387")
    factory = ctypes.c_void_p()
    
    # CreateDXGIFactory1(REFIID riid, void **ppFactory)
    hr = dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory))
    print(f"CreateDXGIFactory1 hr: {hr:#x}")
    if hr < 0:
        return {"error": f"CreateDXGIFactory1 failed with hr={hr}"}

    # Helper to call COM methods
    def call_com_method(interface_ptr, index, prototype, *args):
        # Dereference interface pointer to get vtable pointer
        vtable_ptr = ctypes.cast(interface_ptr, ctypes.POINTER(ctypes.c_void_p))
        vtable = ctypes.cast(vtable_ptr[0], ctypes.POINTER(ctypes.c_void_p))
        func_ptr = vtable[index]
        func = prototype(func_ptr)
        return func(interface_ptr, *args)

    # IDXGIFactory1::EnumAdapters1 (index 10)
    EnumAdapters1_proto = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p)
    )

    # IDXGIAdapter1::GetDesc1 (index 10)
    GetDesc1_proto = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.POINTER(DXGI_ADAPTER_DESC1)
    )

    # IUnknown::Release (index 2)
    Release_proto = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)

    gpus = []
    index = 0
    while True:
        adapter = ctypes.c_void_p()
        hr = call_com_method(factory, 12, EnumAdapters1_proto, index, ctypes.byref(adapter))
        print(f"EnumAdapters1({index}) hr: {hr:#x}")
        if hr < 0:
            break
        
        desc = DXGI_ADAPTER_DESC1()
        hr_desc = call_com_method(adapter, 10, GetDesc1_proto, ctypes.byref(desc))
        print(f"GetDesc1 hr: {hr_desc:#x}")
        if hr_desc >= 0:
            luid_val = (desc.AdapterLuid.HighPart << 32) | desc.AdapterLuid.LowPart
            luid_str = f"luid_0x{desc.AdapterLuid.HighPart:08x}_0x{desc.AdapterLuid.LowPart:08x}"
            print(f"Found: {desc.Description} with LUID {luid_str}")
            gpus.append({
                "Description": desc.Description,
                "VendorId": desc.VendorId,
                "DeviceId": desc.DeviceId,
                "LUID": luid_str,
                "LUID_val": luid_val
            })
        
        call_com_method(adapter, 2, Release_proto)
        index += 1

    call_com_method(factory, 2, Release_proto)
    return gpus

if __name__ == "__main__":
    print(json.dumps(get_dxgi_gpus(), indent=2))
