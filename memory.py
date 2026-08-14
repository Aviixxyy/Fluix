import ctypes
import struct
from ctypes import wintypes as wt

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
STILL_ACTIVE = 259

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", wt.LPVOID),
        ("AllocationBase", wt.LPVOID),
        ("AllocationProtect", wt.DWORD),
        ("PartitionId", wt.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

kernel32.VirtualQueryEx.argtypes = [
    wt.HANDLE,
    wt.LPCVOID,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t

user32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wt.ULONG)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", wt.LPVOID),
        ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE),
        ("szModule", wt.WCHAR * 256),
        ("szExePath", wt.WCHAR * 260),
    ]


kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wt.BOOL
kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wt.BOOL
kernel32.Module32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32FirstW.restype = wt.BOOL
kernel32.Module32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32NextW.restype = wt.BOOL
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.GetExitCodeProcess.restype = wt.BOOL
kernel32.ReadProcessMemory.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = wt.BOOL


def _snapshot(flags, pid=0):
    snap = kernel32.CreateToolhelp32Snapshot(flags, pid)
    if snap == INVALID_HANDLE_VALUE:
        return None
    return snap


def find_pid(process_name):
    pids = find_all_pids(process_name)
    return pids[0] if pids else 0


def find_all_pids(process_name):
    pids = []
    snap = _snapshot(TH32CS_SNAPPROCESS)
    if snap is None:
        return pids
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.lower() == process_name.lower():
                pids.append(pe.th32ProcessID)
            ok = kernel32.Process32NextW(snap, ctypes.byref(pe))
        return pids
    finally:
        kernel32.CloseHandle(snap)


_WNDPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
_wnd_callbacks = []


def _pid_has_visible_window(pid):
    result = [False]

    def cb(hwnd, lparam):
        wpid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            result[0] = True
            return False
        return True

    cb_ref = _WNDPROC(cb)
    _wnd_callbacks.append(cb_ref)
    try:
        user32.EnumWindows(cb_ref, 0)
    finally:
        _wnd_callbacks.remove(cb_ref)
    return result[0]


def find_best_pid(process_name):
    """Prefer the game process that has a visible window (i.e. is in-game),
    falling back to any instance of the process (e.g. the background preloader)."""
    pids = find_all_pids(process_name)
    if not pids:
        return 0
    for pid in pids:
        if _pid_has_visible_window(pid):
            return pid
    return pids[0]


def find_module_base(pid, module_name):
    snap = _snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap is None:
        return (0, 0)
    try:
        me = MODULEENTRY32W()
        me.dwSize = ctypes.sizeof(MODULEENTRY32W)
        ok = kernel32.Module32FirstW(snap, ctypes.byref(me))
        while ok:
            if me.szModule.lower() == module_name.lower():
                base = ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value or 0
                return (base, me.modBaseSize)
            ok = kernel32.Module32NextW(snap, ctypes.byref(me))
        return (0, 0)
    finally:
        kernel32.CloseHandle(snap)


class MemoryReader:
    def __init__(self):
        self.handle = None
        self.pid = 0
        self.base = 0
        self.size = 0
        self.process_name = "RobloxPlayerBeta.exe"

    def open(self, process_name="RobloxPlayerBeta.exe"):
        self.process_name = process_name
        pid = find_best_pid(process_name)
        if not pid:
            return False
        handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not handle:
            return False
        base, size = find_module_base(pid, process_name)
        if not base:
            kernel32.CloseHandle(handle)
            return False
        self.handle = handle
        self.pid = pid
        self.base = base
        self.size = size
        return True

    def reopen(self):
        """Re-target the newest/most active process. Returns True if the
        underlying process (or its base) changed."""
        if self.handle:
            new_pid = find_best_pid(self.process_name)
            if new_pid and new_pid == self.pid and self.alive():
                return False
        self.close()
        return self.open(self.process_name)

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def alive(self):
        if not self.handle:
            return False
        code = wt.DWORD()
        if not kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE

    def regions(self):
        """Yield (address, size) of committed, readable memory regions."""
        if not self.handle:
            return
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION()
        while addr < 0x7FFFFFFF0000:
            got = kernel32.VirtualQueryEx(
                self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi),
                ctypes.sizeof(mbi))
            if not got or mbi.RegionSize == 0:
                break
            size = mbi.RegionSize
            if (mbi.State == MEM_COMMIT and size and
                    mbi.Protect & 0xFF and
                    not (mbi.Protect & PAGE_GUARD) and
                    mbi.Protect != PAGE_NOACCESS):
                yield (addr, size)
            addr += size

    def read(self, addr, size):
        if not self.handle or not addr or size <= 0:
            return None
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)
        )
        if not ok or got.value != size:
            return None
        return buf.raw

    def u8(self, addr):
        data = self.read(addr, 1)
        return data[0] if data else 0

    def u16(self, addr):
        data = self.read(addr, 2)
        return struct.unpack("<H", data)[0] if data else 0

    def u32(self, addr):
        data = self.read(addr, 4)
        return struct.unpack("<I", data)[0] if data else 0

    def u64(self, addr):
        data = self.read(addr, 8)
        return struct.unpack("<Q", data)[0] if data else 0

    def i32(self, addr):
        data = self.read(addr, 4)
        return struct.unpack("<i", data)[0] if data else 0

    def f32(self, addr):
        data = self.read(addr, 4)
        return struct.unpack("<f", data)[0] if data else 0.0

    def f64(self, addr):
        data = self.read(addr, 8)
        return struct.unpack("<d", data)[0] if data else 0.0

    def ptr(self, addr):
        return self.u64(addr)

    def vec3(self, addr):
        data = self.read(addr, 12)
        if data is None:
            return None
        x, y, z = struct.unpack("<fff", data)
        if x == 0.0 and y == 0.0 and z == 0.0:
            return None
        return (x, y, z)

    def floats(self, addr, count):
        data = self.read(addr, count * 4)
        if data is None:
            return None
        return struct.unpack("<{}f".format(count), data)

    def cstr(self, addr, maxlen=256):
        if not addr:
            return ""
        data = self.read(addr, maxlen)
        if data is None:
            return ""
        end = data.find(b"\x00")
        if end >= 0:
            data = data[:end]
        return data.decode("utf-8", "replace").strip("\x00\r\n")

    def rbx_string(self, addr, maxlen=512):
        if not addr:
            return ""
        size = self.u64(addr + 0x10)
        if size and 0 < size <= maxlen:
            data_addr = addr if size < 16 else self.u64(addr)
            if data_addr:
                raw = self.read(data_addr, size)
                if raw is not None:
                    text = raw.decode("utf-8", "replace").split("\x00")[0]
                    if text:
                        return text
        size = self.u64(addr + 0x8)
        if size and 0 < size <= maxlen:
            data_addr = addr if size < 16 else self.u64(addr)
            if data_addr:
                raw = self.read(data_addr, size)
                if raw is not None:
                    text = raw.decode("utf-8", "replace").split("\x00")[0]
                    if text:
                        return text
        return self.cstr(addr, min(maxlen, 256))
