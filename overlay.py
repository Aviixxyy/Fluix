import math
import ctypes
from ctypes import wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SW_SHOW = 5
SW_HIDE = 0
LWA_COLORKEY = 0x00000001
NULL_BRUSH = 5
BLACKNESS = 0x00000042
SRCCOPY = 0x00CC0020
TRANSPARENT = 1
DT_CENTER = 0x00000001
DT_TOP = 0x00000000
DT_NOCLIP = 0x00000100
DT_SINGLELINE = 0x00000020

kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
kernel32.SetConsoleTitleW.argtypes = [wt.LPCWSTR]
kernel32.SetConsoleTitleW.restype = wt.BOOL

user32.SetProcessDPIAware.restype = wt.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.RegisterClassW.restype = wt.ATOM
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
user32.CreateWindowExW.restype = wt.HWND
user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.COLORREF, wt.BYTE, wt.DWORD]
user32.SetLayeredWindowAttributes.restype = wt.BOOL
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.restype = wt.BOOL
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.ClientToScreen.restype = wt.BOOL
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.SetWindowPos.restype = wt.BOOL
user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.IsIconic.argtypes = [wt.HWND]
user32.IsIconic.restype = wt.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wt.HWND
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindow.restype = wt.BOOL
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.PeekMessageW.restype = wt.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.TranslateMessage.restype = wt.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = ctypes.c_long
user32.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wt.HANDLE

gdi32.CreateFontW.argtypes = [ctypes.c_int] * 13 + [wt.LPCWSTR]
gdi32.CreateFontW.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [wt.HDC, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = wt.BOOL
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = ctypes.c_void_p
gdi32.CreateSolidBrush.argtypes = [wt.COLORREF]
gdi32.CreateSolidBrush.restype = ctypes.c_void_p
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wt.COLORREF]
gdi32.CreatePen.restype = ctypes.c_void_p
gdi32.MoveToEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.MoveToEx.restype = wt.BOOL
gdi32.LineTo.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.LineTo.restype = wt.BOOL
gdi32.PatBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.PatBlt.restype = wt.BOOL
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                        wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.BitBlt.restype = wt.BOOL
gdi32.SetTextColor.argtypes = [wt.HDC, wt.COLORREF]
gdi32.SetTextColor.restype = wt.COLORREF
gdi32.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int

user32.FillRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), ctypes.c_void_p]
user32.FillRect.restype = ctypes.c_int
user32.FrameRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), ctypes.c_void_p]
user32.FrameRect.restype = ctypes.c_int
user32.DrawTextW.argtypes = [wt.HDC, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.RECT), wt.UINT]
user32.DrawTextW.restype = ctypes.c_int

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_MOUSE = 0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", INPUT_UNION)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


def _colorref(color):
    r, g, b = color
    return (int(r) & 0xFF) | ((int(g) & 0xFF) << 8) | ((int(b) & 0xFF) << 16)


class Overlay:
    def __init__(self, target_hwnd, class_name="OverlayRenderWindow"):
        self.target_hwnd = target_hwnd
        self.class_name = class_name
        self.hwnd = None
        self.hdc = None
        self.memdc = None
        self.bitmap = None
        self.font = None
        self.w = 0
        self.h = 0
        self._class_registered = False
        self._wndproc = None

    def create(self):
        if not self.target_hwnd:
            return False
        self._register_class()
        hinst = kernel32.GetModuleHandleW(None)
        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            self.class_name,
            "",
            WS_POPUP | WS_VISIBLE,
            0, 0, 1, 1,
            None,
            None,
            hinst,
            None,
        )
        if not self.hwnd:
            return False
        user32.SetLayeredWindowAttributes(self.hwnd, 0, 0, LWA_COLORKEY)
        self.hdc = user32.GetDC(self.hwnd)
        self.font = gdi32.CreateFontW(-14, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, "Segoe UI")
        return True

    def _register_class(self):
        if self._class_registered:
            return
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc = WNDPROC(("DefWindowProcW", user32))
        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinst
        wc.hIcon = None
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = self.class_name
        user32.RegisterClassW(ctypes.byref(wc))
        self._class_registered = True

    def destroy(self):
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.memdc:
            gdi32.DeleteDC(self.memdc)
            self.memdc = None
        if self.font:
            gdi32.DeleteObject(self.font)
            self.font = None
        if self.hdc and self.hwnd:
            user32.ReleaseDC(self.hwnd, self.hdc)
            self.hdc = None
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None

    def sync(self):
        if not self.target_hwnd:
            return False
        if user32.IsIconic(self.target_hwnd):
            self.hide()
            return False
        rect = wt.RECT()
        if not user32.GetClientRect(self.target_hwnd, ctypes.byref(rect)):
            return False
        w = rect.right
        h = rect.bottom
        if w <= 0 or h <= 0:
            self.hide()
            return False
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(self.target_hwnd, ctypes.byref(pt))
        self._ensure_backbuffer(w, h)
        user32.SetWindowPos(self.hwnd, ctypes.c_void_p(-1), pt.x, pt.y, w, h,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW)
        return True

    def hide(self):
        if self.hwnd and user32.IsWindowVisible(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_HIDE)

    def show(self):
        if self.hwnd and not user32.IsWindowVisible(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_SHOW)

    def _ensure_backbuffer(self, w, h):
        if self.bitmap and self.w == w and self.h == h:
            return
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.memdc:
            gdi32.DeleteDC(self.memdc)
            self.memdc = None
        self.w = w
        self.h = h
        self.memdc = gdi32.CreateCompatibleDC(self.hdc)
        self.bitmap = gdi32.CreateCompatibleBitmap(self.hdc, w, h)
        gdi32.SelectObject(self.memdc, self.bitmap)

    def begin(self):
        if not self.memdc:
            return
        gdi32.PatBlt(self.memdc, 0, 0, self.w, self.h, BLACKNESS)

    def clear(self):
        self.begin()
        self.end()

    def end(self):
        if not self.memdc or not self.hdc:
            return
        gdi32.BitBlt(self.hdc, 0, 0, self.w, self.h, self.memdc, 0, 0, SRCCOPY)

    def fill_rect(self, x1, y1, x2, y2, color):
        brush = gdi32.CreateSolidBrush(_colorref(color))
        rect = wt.RECT(int(x1), int(y1), int(x2), int(y2))
        user32.FillRect(self.memdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)

    def frame_rect(self, x1, y1, x2, y2, color):
        brush = gdi32.CreateSolidBrush(_colorref(color))
        rect = wt.RECT(int(x1), int(y1), int(x2), int(y2))
        user32.FrameRect(self.memdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)

    def line(self, x1, y1, x2, y2, color, width=1):
        pen = gdi32.CreatePen(0, width, _colorref(color))
        old = gdi32.SelectObject(self.memdc, pen)
        gdi32.MoveToEx(self.memdc, int(x1), int(y1), None)
        gdi32.LineTo(self.memdc, int(x2), int(y2))
        gdi32.SelectObject(self.memdc, old)
        gdi32.DeleteObject(pen)

    def circle(self, cx, cy, r, color, segments=48):
        for i in range(segments):
            a1 = 2.0 * math.pi * i / segments
            a2 = 2.0 * math.pi * (i + 1) / segments
            self.line(cx + r * math.cos(a1), cy + r * math.sin(a1),
                      cx + r * math.cos(a2), cy + r * math.sin(a2), color, 1)

    def text(self, x, y, value, color, center=False, size=None):
        if not value:
            return
        font = self.font
        if size and size != 14:
            font = gdi32.CreateFontW(-size, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, "Segoe UI")
            gdi32.SelectObject(self.memdc, font)
        else:
            gdi32.SelectObject(self.memdc, self.font)
        gdi32.SetTextColor(self.memdc, _colorref(color))
        gdi32.SetBkMode(self.memdc, TRANSPARENT)
        flags = DT_TOP | DT_NOCLIP | DT_SINGLELINE | (DT_CENTER if center else 0)
        rect = wt.RECT(int(x), int(y), int(x + 800), int(y + 200))
        user32.DrawTextW(self.memdc, str(value), -1, ctypes.byref(rect), flags)
        if font != self.font:
            gdi32.DeleteObject(font)

    def text_outlined(self, x, y, value, color, shadow, center=False, size=None):
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            self.text(x + dx, y + dy, value, shadow, center, size)
        self.text(x, y, value, color, center, size)
