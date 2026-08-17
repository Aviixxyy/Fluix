import copy
import json
import math
import os
import threading
import tkinter as tk
from tkinter import colorchooser
from tkinter import font as tkfont

import ctypes

import config
import status
import themes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short

_ORIG_UNRAISABLE = None


def _quiet_tk_del(args):
    """Silence the harmless TkObject.__del__ noise at process exit only.

    tk.Variable/PhotoImage objects owned by the daemon UI thread can still
    be finalized by the main thread's garbage collector during interpreter
    shutdown, which makes their __del__ raise "main thread is not in main
    loop". That one message is expected and harmless at exit; anything else
    still goes to the original hook.
    """
    if isinstance(args.exc_value, RuntimeError) \
            and "main thread is not in main loop" in str(args.exc_value):
        return
    if _ORIG_UNRAISABLE:
        _ORIG_UNRAISABLE(args)


import sys as _sys
_ORIG_UNRAISABLE = _sys.unraisablehook
_sys.unraisablehook = _quiet_tk_del

_settings_hwnd = None

_window_open = False

_visible = True
_toggle_request = False
_profiles = {}


def is_open():
    return _window_open and _visible


def request_toggle():
    global _toggle_request
    _toggle_request = True


def profile_names():
    return sorted(_profiles)


def profile_save(name, esp_cfg, colors_cfg, stealth_cfg, hud_cfg):
    _profiles[name] = {
        "esp": dict(esp_cfg),
        "colors": {k: list(v) for k, v in colors_cfg.items()},
        "stealth": dict(stealth_cfg),
        "hud": dict(hud_cfg) if hud_cfg else {},
    }


def profile_delete(name):
    _profiles.pop(name, None)
_shutdown = threading.Event()
_close_requested = threading.Event()
_ui_thread = None
_SAVE_PATH = os.path.join(config.app_dir(), "settings.json")


def _trace(msg):
    import sys
    try:
        sys.stderr.write("[ui] " + msg + "\n")
        sys.stderr.flush()
    except Exception:
        pass
_ICON_PATH = os.path.join(config.bundle_dir(), "fluix.ico")
_LOGO_PATH = os.path.join(config.bundle_dir(), "fluix.png")


BG = "#17181c"
CARD = "#202127"
CARD_HOVER = "#24252d"
BORDER = "#30313a"
TEXT = "#eceaf2"
MUTED = "#8f91a0"
ACCENT = "#8b5cf6"
ACCENT_HOVER = "#7c3aed"
ACCENT_DARK = "#6d28d9"
TRACK_OFF = "#3a3b44"
GHOST_BORDER = "#3b3c47"
INPUT = "#1b1c22"
TAB_BOX = "#26272e"
TAB_HOVER = "#2c2d36"
TAB_SELECT = "#3b3d49"
STEP_MS = 16
FONT = "Segoe UI"


def get_settings_hwnd():
    return _settings_hwnd


def _apply_icon(root):
    try:
        root.iconbitmap(_ICON_PATH)
    except Exception:
        pass


def save(esp_cfg, colors_cfg, stealth_cfg, theme=None, hud=None, games=None,
         aim_cfg=None):
    data = {
        "esp": dict(esp_cfg),
        "colors": {k: list(v) for k, v in colors_cfg.items()},
        "stealth": dict(stealth_cfg),
        "theme": theme or themes.active(),
    }
    if hud:
        data["hud"] = hud
    if games:
        data["games"] = {
            k: {
                "enabled": g.get("enabled", False),
                "roles": {
                    rk: {
                        "tracer": r.get("tracer", True),
                        "box": r.get("box", True),
                        "name": r.get("name", True),
                        "color": list(r.get("color", [255, 255, 255])),
                    }
                    for rk, r in g.get("roles", {}).items()
                },
            }
            for k, g in games.items()
        }
    if aim_cfg:
        data["aimbot"] = dict(aim_cfg)
    try:
        import pergame
        store = pergame.get_store()
        if store is not None:
            data["per_game"] = store.dump()
    except Exception:
        pass
    if _profiles:
        data["profiles"] = _profiles
    try:
        with open(_SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def load(esp_cfg, colors_cfg, stealth_cfg, hud_cfg=None, games_cfg=None,
         aim_cfg=None):
    try:
        with open(_SAVE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    for section, target in (("esp", esp_cfg), ("stealth", stealth_cfg)):
        for key, value in data.get(section, {}).items():
            if key in target:
                target[key] = value
    for key, value in data.get("colors", {}).items():
        if key in colors_cfg:
            colors_cfg[key] = tuple(value)
    if hud_cfg:
        for key, value in data.get("hud", {}).items():
            if key in hud_cfg:
                hud_cfg[key] = value
    if aim_cfg:
        for key, value in data.get("aimbot", {}).items():
            if key in aim_cfg:
                aim_cfg[key] = value
    if games_cfg:
        for key, g in data.get("games", {}).items():
            if key not in games_cfg:
                continue
            for field in ("enabled",):
                if field in g:
                    games_cfg[key][field] = g[field]
            for rk, rv in g.get("roles", {}).items():
                role = games_cfg[key].get("roles", {}).get(rk)
                if role is None:
                    continue
                for field in ("tracer", "box", "name"):
                    if field in rv:
                        role[field] = rv[field]
                if "color" in rv:
                    role["color"] = list(rv["color"])
    if data.get("profiles"):
        _profiles.clear()
        _profiles.update(data["profiles"])
    return True


def _to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, int(c))) for c in rgb])


def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _round_rect_points(x1, y1, x2, y2, r):
    r = max(0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class Card(tk.Canvas):
    R = 18

    def __init__(self, master, title):
        super().__init__(master, bg=BG, highlightthickness=0)
        self._hover = False
        self._want = _to_rgb(BORDER)
        self._outline = _to_rgb(BORDER)
        self._pad = 9
        self.pack(fill="x", padx=14, pady=(0, 10))

        inner = tk.Frame(self, bg=CARD)
        self._inner = inner
        head = tk.Frame(inner, bg=CARD)
        head.pack(fill="x", padx=8, pady=(10, 2))
        dot = tk.Canvas(head, width=8, height=8, bg=CARD, highlightthickness=0)
        dot.pack(side="left", pady=(2, 0))
        dot.create_oval(1, 1, 7, 7, fill=ACCENT, outline="")
        ttl = tk.Label(head, text=title.upper(), bg=CARD, fg=MUTED,
                       font=(FONT, 8, "bold"))
        ttl.pack(side="left", padx=6)
        self.body = tk.Frame(inner, bg=CARD)
        self.body.pack(fill="x", padx=8, pady=(4, 12))

        self._bg_item = self.create_polygon(
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), smooth=True,
            fill=CARD, outline=BORDER)
        self._win = self.create_window(0, 0, window=inner, anchor="nw")

        inner.bind("<Configure>", self._relayout)
        self.bind("<Configure>", self._relayout)
        for w in (inner, head, ttl, self.body):
            w.bind("<Enter>", lambda e: self._set_hover(True))
            w.bind("<Leave>", lambda e: self._set_hover(False))

    def _relayout(self, _=None):
        w = self.winfo_width()
        pad = self._pad
        h = self._inner.winfo_reqheight() + 2 * pad + 2
        if w > 2 * pad + 4:
            self.coords(self._win, pad, pad)
            self.itemconfig(self._win, width=w - 2 * pad - 2)
        self.configure(height=h)
        self.coords(self._bg_item, *_round_rect_points(1, 1, w - 1, h - 1, self.R))

    def _set_hover(self, on):
        self._hover = bool(on)
        self._want = _lerp(_to_rgb(BORDER), _to_rgb(ACCENT), 0.35) \
            if self._hover else _to_rgb(BORDER)
        self._tick()

    def _tick(self):
        if not self.winfo_ismapped():
            self._outline = self._want
            return
        cur = self._outline
        want = self._want
        if cur == want:
            self._outline = want
            return
        self._outline = _lerp(cur, want, 0.4)
        self.itemconfig(self._bg_item, outline=_to_hex(self._outline))
        self.after(STEP_MS, self._tick)

    def entrance_delay(self, ms):
        self.cancel_entrance()
        self._entrance_after = self.after(ms, self._entrance)

    def cancel_entrance(self):
        if getattr(self, "_entrance_after", None) is not None:
            try:
                self.after_cancel(self._entrance_after)
            except Exception:
                pass
            self._entrance_after = None

    def _entrance(self):
        self._entrance_after = None
        if not self.winfo_ismapped():
            return
        self._outline = _to_rgb(ACCENT)
        self.itemconfig(self._bg_item, outline=_to_hex(self._outline))
        self.after(STEP_MS, self._tick)


def _to_rgb(hexstr):
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _set_ui_accent(theme):
    """Theme the UI accent palette from a theme before widgets are built."""
    global ACCENT, ACCENT_HOVER, ACCENT_DARK
    rgb = tuple(themes.meta(theme)["accent"])
    ACCENT = _to_hex(rgb)
    ACCENT_HOVER = _to_hex(_lerp(rgb, (255, 255, 255), 0.18))
    ACCENT_DARK = _to_hex(_lerp(rgb, (0, 0, 0), 0.22))


TOOLTIPS = {
    "box": "Draws a box around each player.",
    "box_corners": "Draws boxes as corner brackets instead of full rectangles.",
    "healthbar": "Shows a vertical health bar beside each player.",
    "name": "Shows the player name above their box.",
    "distance": "Shows the distance to each player below their box.",
    "tracers": "Draws a line from the centre of the screen to each player.",
    "tool": "Shows the tool each player is holding.",
    "team_check": "Hides teammates. Needs team data from the game.",
    "show_local_player": "Also draws ESP for your own character.",
    "dynamic_box": "Sizes boxes from the character's real dimensions instead of a fixed height.",
    "fade_dead": "Shrinks and dims the box of dead players.",
    "highlight_target": "Highlights the closest alive enemy with corner accents.",
    "skip_dead": "Hides dead players entirely.",
    "item_esp": "Shows nearby items (tools) with their distance.",
    "dead_box": "How much a dead player's box shrinks.",
    "dead_tracer": "How far a dead player's tracer reaches.",
    "max_distance": "Furthest distance (in studs) at which ESP is drawn.",
    "item_range": "How close an item must be to appear on the ESP.",
    "update_hz": "How many times per second the game memory is read.",
    "humanize": "Varies the read rate randomly to look less robotic.",
    "occlusion": "Dims the box of players that are behind walls. Uses a "
                 "cached raycast against the map's parts.",
    "aim_enabled": "Gently eases your crosshair onto the closest enemy. "
                   "Never writes game memory.",
    "aim_mode": "HOLD aims while you hold the key. ON FIRE aims while you "
                "hold the fire button.",
    "aim_hotkey": "Key that enables aim assist while held.",
    "aim_fov": "How close to your crosshair an enemy must be before the "
               "assist engages (in pixels).",
    "aim_show_fov": "Draws a circle on screen showing the aim assist's FOV "
                    "range around your crosshair.",
    "aim_speed": "How fast the crosshair eases onto the target. Lower is "
                 "snappier, higher is smoother.",
    "aim_distance": "Furthest enemy distance (in studs) the assist will "
                    "engage at.",
    "aim_target": "Which part of the enemy the assist aims at.",
    "aim_stutter": "Random micro-shake added to the movement so it looks "
                   "like a human hand.",
    "aim_curve": "How much the path curves instead of travelling straight "
                 "to the target.",
    "aim_orbit": "Distance at which the crosshair spirals in around the "
                 "target for a natural landing.",
    "aim_lock": "How strongly the aim holds onto a locked target before "
                "letting you pull off and switch. Higher = stickier.",
}

STATUS_TOOLTIPS = {
    "attached": "Whether the reader is attached to Roblox. "
                "Yellow = waiting for a game session, red = something's wrong.",
    "camera": "Whether the in-game camera could be read for ESP projection.",
    "targets": "How many players are currently detected.",
    "esp": "Whether ESP drawing is enabled (F8 toggles it).",
}

_KEYSYM_VK = {
    "space": 0x20, "Tab": 0x09, "Return": 0x0D, "Escape": 0x1B,
    "BackSpace": 0x08, "Delete": 0x2E, "Insert": 0x2D,
    "Home": 0x24, "End": 0x23, "Prior": 0x21, "Next": 0x22,
    "Left": 0x25, "Right": 0x27, "Up": 0x26, "Down": 0x28,
    "Shift_L": 0x10, "Shift_R": 0x10,
    "Control_L": 0x11, "Control_R": 0x11,
    "Alt_L": 0x12, "Alt_R": 0x12,
    "Win_L": 0x5B, "Win_R": 0x5C,
    "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
    "minus": 0xBD, "equal": 0xBB, "semicolon": 0xBA,
    "apostrophe": 0xDE, "bracketleft": 0xDB, "bracketright": 0xDD,
    "backslash": 0xDC, "grave": 0xC0,
}

_PRETTY_VK = {
    0x20: "Space", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
    0x08: "Backspace", 0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt",
    0x2E: "Del", 0x2D: "Ins", 0x24: "Home", 0x23: "End",
    0x21: "PgUp", 0x22: "PgDn", 0x25: "Left", 0x27: "Right",
    0x26: "Up", 0x28: "Down",
}

_MOUSE_VK = {
    0x01: "Left mouse", 0x02: "Right mouse", 0x04: "Middle mouse",
    0x05: "Mouse 4", 0x06: "Mouse 5",
}

_MOUSE_CAPTURE_VKS = (0x02, 0x04, 0x05, 0x06)


def _keysym_to_vk(name):
    if name.startswith("F") and name[1:].isdigit():
        n = int(name[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    if name in _KEYSYM_VK:
        return _KEYSYM_VK[name]
    if len(name) == 1:
        if name.isdigit():
            return ord(name)
        if name.isalpha():
            return ord(name.upper())
    return None


def _vk_to_label(vk, presets):
    for name, code in presets.items():
        if code == vk:
            return name
    if vk in _MOUSE_VK:
        return _MOUSE_VK[vk]
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return "F" + str(vk - 0x70 + 1)
    rev = {}
    for k, v in _KEYSYM_VK.items():
        rev.setdefault(v, k)
    if vk in rev:
        return _PRETTY_VK.get(vk, rev[vk].rstrip("_LR").title())
    return "Key {}".format(hex(vk))

_HUD_DEFAULT_LAYOUT = {
    "fps": [12, 12, 96, 30],
    "ping": [108, 12, 96, 30],
    "players": [204, 12, 116, 30],
}


class Tooltip:
    """Small delay-triggered tooltip that appears under the cursor."""

    def __init__(self, root):
        self.root = root
        self._tip = None
        self._after = None

    def schedule(self, text):
        self._cancel()
        if not text:
            return
        self._after = self.root.after(200, lambda: self._show(text))

    def _show(self, text):
        try:
            self._tip = tk.Toplevel(self.root)
            self._tip.overrideredirect(True)
            self._tip.attributes("-topmost", True)
            tk.Label(self._tip, text=text, bg="#0d0e11", fg=TEXT,
                     font=(FONT, 9), justify="left", wraplength=240,
                     padx=8, pady=5, highlightthickness=1,
                     highlightbackground=BORDER).pack()
            self.root.update_idletasks()
            tw = self._tip.winfo_reqwidth()
            th = self._tip.winfo_reqheight()
            px = self.root.winfo_pointerx()
            py = self.root.winfo_pointery() + 16
            wx, wy, ww, wh = (self.root.winfo_rootx(), self.root.winfo_rooty(),
                              self.root.winfo_width(), self.root.winfo_height())
            px = max(4, min(px, wx + ww - tw - 4))
            py = max(4, min(py, wy + wh - th - 4))
            self._tip.geometry("+{}+{}".format(px, py))
        except Exception:
            self.hide()

    def hide(self):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _cancel(self):
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
            except Exception:
                pass
            self._after = None


class Toggle(tk.Canvas):
    W, H, R = 50, 24, 11

    def __init__(self, master, value=False, command=None):
        super().__init__(master, width=self.W, height=self.H, bg=CARD,
                         highlightthickness=0, cursor="hand2")
        self.command = command
        self._on = bool(value)
        self._pos = 1.0 if self._on else 0.0
        self._target = self._pos
        self._animating = False
        self._hover = False
        r = 8
        cy = self.H / 2.0
        L, R = 2, self.W - 2
        self._lcap = L + r
        self._rcap = R - r
        self.track = self.create_polygon(
            self._capsule_points(L, R, cy, r), smooth=False,
            outline="", fill=TRACK_OFF)
        self.knob = self.create_oval(0, 0, 0, 0, fill="#f2f3f7", outline="")
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._hover_on(True))
        self.bind("<Leave>", lambda e: self._hover_on(False))
        self._redraw()

    def _capsule_points(self, L, R, cy, r, n=10):
        """Approximate a rounded-rect capsule as one polygon (no seams)."""
        pts = [[L + r, cy - r], [R - r, cy - r]]
        for i in range(n + 1):
            a = -math.pi / 2 + math.pi * i / n
            pts.append([R - r + r * math.cos(a), cy + r * math.sin(a)])
        pts += [[R - r, cy + r], [L + r, cy + r]]
        for i in range(n + 1):
            a = math.pi / 2 + math.pi * i / n
            pts.append([L + r + r * math.cos(a), cy + r * math.sin(a)])
        return [int(round(x)) for p in pts for x in p]

    def _click(self, _):
        self.set(not self._on)

    def _hover_on(self, on):
        self._hover = bool(on)
        self._redraw()

    def _redraw(self):
        p = max(0.0, min(1.0, self._pos))
        cx = self._lcap + p * (self._rcap - self._lcap)
        cy = self.H / 2.0
        track = _lerp(_to_rgb(TRACK_OFF), _to_rgb(ACCENT), p)
        if self._hover:
            track = _lerp(track, (255, 255, 255), 0.10)
        self.itemconfig(self.track, fill=_to_hex(track))
        r = 8
        self.coords(self.knob, cx - r, cy - r, cx + r, cy + r)

    def _tick(self):
        if abs(self._target - self._pos) > 0.001:
            self._pos += (self._target - self._pos) * 0.30
            if abs(self._target - self._pos) <= 0.001:
                self._pos = self._target
            self._redraw()
            self.after(STEP_MS, self._tick)
        else:
            self._animating = False

    def set(self, value):
        value = bool(value)
        if value == self._on:
            return
        self._on = value
        self._target = 1.0 if value else 0.0
        if not self._animating:
            self._animating = True
            self._tick()
        if self.command:
            self.command()

    def get(self):
        return self._on


class ModernSlider(tk.Canvas):
    def __init__(self, master, from_, to, value, command=None,
                 width=190, height=26):
        super().__init__(master, width=width, height=height, bg=CARD,
                         highlightthickness=0, cursor="hand2")
        self.from_ = from_
        self.to = to
        self.command = command
        self.x0 = 10
        self.x1 = width - 10
        self.yc = height / 2.0
        span = max(1e-9, to - from_)
        self._frac = max(0.0, min(1.0, (value - from_) / span))
        self._drag = False
        self._hover = False
        self.track = self.create_rectangle(self.x0, self.yc - 3,
                                           self.x1, self.yc + 3,
                                           outline="", fill=TRACK_OFF)
        self.fill = self.create_rectangle(self.x0, self.yc - 3,
                                          self.x0, self.yc + 3,
                                          outline="", fill=ACCENT)
        self.knob = self.create_oval(0, 0, 0, 0, fill="#f2f3f7",
                                     outline=ACCENT, width=1)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", lambda e: self._hover_on(True))
        self.bind("<Leave>", lambda e: self._hover_on(False))
        self._redraw()

    def _knob_x(self):
        return self.x0 + self._frac * (self.x1 - self.x0)

    def _hover_on(self, on):
        self._hover = bool(on)
        self._redraw()

    def _redraw(self):
        kx = self._knob_x()
        r = 8.5 if self._hover else 7
        self.coords(self.knob, kx - r, self.yc - r, kx + r, self.yc + r)
        self.coords(self.fill, self.x0, self.yc - 3, max(kx, self.x0 + 0.5),
                    self.yc + 3)
        track = TRACK_OFF
        if self._hover:
            track = _to_hex(_lerp(_to_rgb(TRACK_OFF), (255, 255, 255), 0.12))
        self.itemconfig(self.track, fill=track)

    def _press(self, event):
        self._drag = True
        self._update(event.x)

    def _motion(self, event):
        if self._drag:
            self._update(event.x)

    def _release(self, _):
        self._drag = False

    def _update(self, x):
        self._frac = max(0.0, min(1.0, (x - self.x0) / (self.x1 - self.x0)))
        self._redraw()
        if self.command:
            self.command()

    def set(self, value):
        span = max(1e-9, self.to - self.from_)
        self._frac = max(0.0, min(1.0, (value - self.from_) / span))
        self._redraw()

    def get(self):
        return self.from_ + self._frac * (self.to - self.from_)


class AccentButton(tk.Canvas):
    def __init__(self, master, text, command=None, filled=True, width=120, height=34):
        super().__init__(master, width=width, height=height, bg=BG,
                         highlightthickness=0, cursor="hand2")
        self.command = command
        self._text = text
        self._filled = filled
        self._fill = _to_rgb(ACCENT) if filled else _to_rgb(CARD)
        self._target = self._fill
        self._tcolor = "#ffffff" if filled else TEXT
        self.shape = self.create_polygon(
            _round_rect_points(1, 1, width - 1, height - 1, height // 2 - 1),
            smooth=True, outline="")
        self.label = self.create_text(width / 2.0, height / 2.0,
                                      text=text, font=(FONT, 9, "bold"))
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self._redraw()

    def _redraw(self):
        self.itemconfig(self.shape, fill=_to_hex(self._fill),
                        outline=ACCENT if self._filled else GHOST_BORDER)
        self.itemconfig(self.label, fill=self._tcolor)

    def _hover(self, on):
        if on:
            self._target = _to_rgb(ACCENT_HOVER) if self._filled else _to_rgb(CARD_HOVER)
        else:
            self._target = _to_rgb(ACCENT) if self._filled else _to_rgb(CARD)
        self._tick()

    def _tick(self):
        cur = self._fill
        want = self._target
        if cur == want:
            self._fill = self._target
            self._redraw()
            return
        self._fill = _lerp(cur, want, 0.35)
        self._redraw()
        self.after(STEP_MS, self._tick)

    def _press(self, _):
        self._fill = _lerp(self._target, (10, 10, 14), 0.3)
        self._redraw()

    def _release(self, _):
        self._tick()
        if self.command:
            self.command()


class SegButton(AccentButton):
    def __init__(self, master, text, selected=False, command=None, width=54, height=24):
        super().__init__(master, text, command=command, filled=selected,
                         width=width, height=height)
        self._tcolor = "#ffffff" if selected else TEXT

    def select(self, on):
        self._filled = bool(on)
        self._target = _to_rgb(ACCENT) if on else _to_rgb(CARD)
        self._tcolor = "#ffffff" if on else TEXT
        self._tick()

    def _redraw(self):
        self.itemconfig(self.shape, fill=_to_hex(self._fill),
                        outline=ACCENT if self._filled else GHOST_BORDER)
        self.itemconfig(self.label, fill=self._tcolor)


class SidebarButton(tk.Canvas):
    """Full-width vertical sidebar entry drawn as its own rounded box.

    Selection is shown by a lighter box fill plus the sliding accent bar.
    """

    def __init__(self, master, text, selected=False, command=None, height=36):
        super().__init__(master, height=height, bg=CARD, highlightthickness=0,
                         cursor="hand2")
        self.command = command
        self._text = text
        self._on = bool(selected)
        self._hover = False
        self._shape = None
        self._fill = TAB_SELECT if selected else TAB_BOX
        self.label = self.create_text(20, height / 2.0, text=text, anchor="w",
                                      font=(FONT, 9, "bold"),
                                      fill=TEXT if selected else MUTED)
        self.bind("<Configure>", self._resize_shape)
        self.bind("<Enter>", lambda e: self._hov(True))
        self.bind("<Leave>", lambda e: self._hov(False))
        self.bind("<Button-1>", lambda e: self.command() if self.command else None)
        self._redraw()

    def _resize_shape(self, _=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 4 or h <= 4:
            return
        if self._shape is not None:
            self.delete(self._shape)
        self._shape = self.create_polygon(
            _round_rect_points(3, 3, w - 3, h - 3, 8), smooth=True,
            outline="", fill=self._fill)
        self.tag_lower(self._shape)
        self.coords(self.label, 20, h / 2.0)

    def _hov(self, on):
        self._hover = bool(on)
        self._redraw()

    def _redraw(self):
        if self._on:
            self._fill = TAB_SELECT
        elif self._hover:
            self._fill = TAB_HOVER
        else:
            self._fill = TAB_BOX
        if self._shape is not None:
            self.itemconfig(self._shape, fill=self._fill)
        self.itemconfig(self.label, fill=TEXT if self._on else MUTED)

    def select(self, on):
        self._on = bool(on)
        self._redraw()


class ColorSwatch(tk.Canvas):
    def __init__(self, master, color, command=None, size=26):
        super().__init__(master, width=size, height=size, bg=CARD,
                         highlightthickness=0, cursor="hand2")
        self.command = command
        self._color = color
        self.s = self.create_polygon(
            _round_rect_points(1, 1, size - 1, size - 1, size // 2 - 1),
            smooth=True, outline="")
        self.bind("<Enter>", lambda e: self.itemconfig(self.s, outline=ACCENT))
        self.bind("<Leave>", lambda e: self.itemconfig(self.s, outline=BORDER))
        self.bind("<Button-1>", lambda e: self.command() if self.command else None)
        self._redraw()

    def _redraw(self):
        self.itemconfig(self.s, fill=_to_hex(self._color), outline=BORDER)

    def set_color(self, color):
        self._color = color
        self._redraw()


class NumberField(tk.Canvas):
    R = 11

    def __init__(self, master, value, on_set, lo=None, hi=None, width=6):
        cw = width * 8 + 18
        ch = 24
        super().__init__(master, width=cw, height=ch, bg=CARD,
                         highlightthickness=0, cursor="xterm")
        self._on_set = on_set
        self._lo = lo
        self._hi = hi
        self._value = value
        self._focused = False
        self._hover = False
        self.shape = self.create_polygon(
            _round_rect_points(1, 1, cw - 1, ch - 1, self.R), smooth=True,
            fill=INPUT, outline=GHOST_BORDER)
        self.entry = tk.Entry(self, justify="center", bg=INPUT, fg=ACCENT,
                              insertbackground=TEXT, relief="flat", bd=0,
                              font=(FONT, 9, "bold"), highlightthickness=0)
        self._win = self.create_window(cw / 2.0, ch / 2.0, window=self.entry,
                                       width=width * 8, height=ch - 4)
        self._sync()
        self.entry.bind("<Return>", self._commit)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.entry.bind("<Escape>", self._revert)
        self.entry.bind("<FocusIn>", self._focus_in)
        self.bind("<Enter>", lambda e: self._hover_on(True))
        self.bind("<Leave>", lambda e: self._hover_on(False))

    def _hover_on(self, on):
        self._hover = bool(on)
        self._refresh_border()

    def _refresh_border(self):
        self.itemconfig(self.shape,
                        outline=ACCENT if self._focused
                        else (BORDER if self._hover else GHOST_BORDER))

    def _focus_in(self, _=None):
        self._focused = True
        self._refresh_border()

    def _focus_out(self, event=None):
        self._focused = False
        self._refresh_border()
        return self._commit(event)

    def _sync(self):
        self.entry.delete(0, "end")
        self.entry.insert(0, "{:d}".format(int(round(self._value))))

    def _commit(self, event=None):
        try:
            raw = float(self.entry.get().strip().replace(",", ""))
            v = int(round(raw))
            if self._lo is not None:
                v = max(self._lo, v)
            if self._hi is not None:
                v = min(self._hi, v)
            self._value = v
            self._on_set(v)
        except ValueError:
            pass
        self._sync()
        return "break"

    def _revert(self, event=None):
        self._sync()
        return "break"

    def set(self, value):
        self._value = value
        self._sync()

    def delete(self, *args):
        return self.entry.delete(*args)

    def insert(self, *args):
        return self.entry.insert(*args)

    def get(self):
        return self.entry.get()


class SettingsWindow:
    TABS = (("display", "DISPLAY"), ("distance", "DISTANCE"),
            ("colors", "COLORS"), ("rate", "READ RATE"), ("aim", "AIM"),
            ("themes", "THEMES"), ("hud", "HUD"), ("profiles", "CONFIGS"),
            ("games", "GAMES"))

    def __init__(self, root, esp_cfg, colors_cfg, stealth_cfg, hud_cfg=None,
                 games_cfg=None, aim_cfg=None):
        self.root = root
        self.esp = esp_cfg
        self.colors = colors_cfg
        self.stealth = stealth_cfg
        self.hud = hud_cfg or {}
        self.games = games_cfg or {}
        self.aim = aim_cfg or {}
        self.theme = themes.active()
        _trace("theme resolved")
        self.tooltip = Tooltip(root)
        _set_ui_accent(self.theme)
        _trace("accent set")
        root.title("Fluix - Settings")
        root.configure(bg=BG)
        root.resizable(False, False)
        _trace("root configured")
        root.attributes("-alpha", 0.0)
        _trace("alpha set")

        self.toggle_vars = {}
        self.toggles = {}
        self.color_buttons = {}
        self.hud_vars = {}
        self.hud_colors = {}

        self._sidebar_open = False
        self._current = "display"
        self._sidebar_after = None
        self._bar_after = None
        self._page_after = None
        self._shown_page = None
        self._game_key = next(iter(self.games)) if self.games else ""
        if self._game_key:
            for k, g in self.games.items():
                g["enabled"] = (k == self._game_key)

        self._build_header()
        _trace("header built")
        self._build_body()
        _trace("body built")
        self._grow_accent(0)

        root.update_idletasks()
        self._resize_window(initial=True)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._fade_in(0.0)
        self._started = True


    def _build_header(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 4))
        burger = tk.Canvas(head, width=22, height=22, bg=BG, highlightthickness=0,
                           cursor="hand2")
        burger.pack(side="left", pady=(14, 0))
        self._burger_lines = [
            burger.create_line(3, 6, 19, 6, fill=MUTED, width=2),
            burger.create_line(3, 11, 19, 11, fill=MUTED, width=2),
            burger.create_line(3, 16, 19, 16, fill=MUTED, width=2),
        ]
        burger.bind("<Button-1>", lambda e: self._toggle_sidebar())
        burger.bind("<Enter>", lambda e: self._burger_hover(True))
        burger.bind("<Leave>", lambda e: self._burger_hover(False))
        self._burger = burger
        logo = None
        try:
            img = tk.PhotoImage(file=_LOGO_PATH)
            n = max(2, min(img.width(), img.height()) // 32)
            if n > 1:
                img = img.subsample(n, n)
            self._logo_img = img
            logo = tk.Label(head, image=img, bg=BG)
        except Exception:
            logo = None
        if logo is not None:
            logo.pack(side="left")
            self._logo = logo
            titles_pad = 10
        else:
            glow = tk.Canvas(head, width=14, height=14, bg=BG, highlightthickness=0)
            glow.pack(side="left", pady=(2, 0))
            glow.create_oval(2, 2, 12, 12, fill=ACCENT, outline="")
            self._glow = glow
            titles_pad = 10
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left", padx=titles_pad)
        tk.Label(titles, text="Fluix", bg=BG, fg=TEXT,
                 font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(titles, text="SETTINGS", bg=BG, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w")
        self._pulse_glow(0.0)

    def _burger_hover(self, on):
        color = ACCENT if on else MUTED
        for lid in self._burger_lines:
            self._burger.itemconfig(lid, fill=color)

    def _ease_out(self, t):
        """Ease-out cubic: fast start, gentle settle."""
        return 1.0 - (1.0 - t) ** 3

    def _toggle_sidebar(self):
        self._sidebar_open = not self._sidebar_open
        self._animate_sidebar()

    def _animate_sidebar(self):
        """Push the content panel right while the drawer slides in behind it.

        Both widgets are only *translated* (fixed widths) - nothing reflows,
        so there's no pixelation or dragging. The window stays fixed too.
        """
        if self._sidebar_after is not None:
            try:
                self.root.after_cancel(self._sidebar_after)
            except Exception:
                pass
        steps = 14
        DW = 176
        CX = 88

        def step(i=0):
            t = (i + 1) / float(steps)
            e = self._ease_out(t)
            try:
                alive = (self.sidebar.winfo_exists()
                         and self._main.winfo_exists())
            except Exception:
                alive = False
            if not alive:
                self._sidebar_after = None
                return
            if self._sidebar_open:
                dx = int(-DW + DW * e)
                mx = int(CX + (DW - CX) * e)
            else:
                dx = int(0 - DW * e)
                mx = int(DW - (DW - CX) * e)
            self.sidebar.place(x=dx, y=0, width=DW, relheight=1.0)
            self._main.place(x=mx, y=0, width=830 - DW, relheight=1.0)
            self.root.update_idletasks()
            if i + 1 < steps:
                self._sidebar_after = self.root.after(10, lambda: step(i + 1))
            else:
                self._sidebar_after = None

        self._sidebar_after = None
        step()

    def _animate_sidebar_bar(self, key):
        """Slide the accent bar up/down to the selected tab (eased)."""
        bar = getattr(self, "sidebar_bar", None)
        if bar is None or not getattr(self, "_bar_pos", None) or key not in self._bar_pos:
            return
        if self._bar_after is not None:
            try:
                self.root.after_cancel(self._bar_after)
            except Exception:
                pass
        ty0, ty1 = self._bar_pos[key]
        try:
            cy0 = bar.winfo_y()
        except Exception:
            cy0 = ty0
        steps = 12
        dy0 = ty0 - cy0
        h = max(1, ty1 - ty0)

        def step(i=0):
            try:
                if not bar.winfo_exists():
                    self._bar_after = None
                    return
            except Exception:
                self._bar_after = None
                return
            e = self._ease_out((i + 1) / float(steps))
            bar.place(x=10, y=int(cy0 + dy0 * e), width=3, height=h)
            if i + 1 < steps:
                self._bar_after = self.root.after(10, lambda: step(i + 1))
            else:
                self._bar_after = None

        self._bar_after = None
        step()

    def _layout_sidebar_bar(self):
        """Compute each tab button's y-range and park the bar on the current tab.

        Must run after the window has been sized (so winfo_y is real). Retries
        briefly until the window is actually mapped and heights are valid.
        """
        bar = getattr(self, "sidebar_bar", None)
        if bar is None:
            return
        pos = {}
        ok = True
        try:
            for key, b in self.tab_buttons.items():
                by = b.winfo_y()
                h = b.winfo_height()
                if h < 10:
                    ok = False
                    break
                pos[key] = (by + 3, by + h - 3)
        except Exception:
            return
        if not ok:
            self.root.after(40, self._layout_sidebar_bar)
            return
        self._bar_pos = pos
        y0, y1 = pos.get(self._current, pos.get(self.TABS[0][0], (0, 0)))
        bar.place(x=10, y=y0, width=3, height=max(1, y1 - y0))

    def _resize_window(self, initial=False):


        width = 830
        height = 700
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry("{}x{}+{}+{}".format(width, height,
                                                (sw - width) // 2, (sh - height) // 2))
        self.root.update_idletasks()
        self._layout_sidebar_bar()

    def _build_body(self):
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)
        self._body = body

        self.tab_buttons = {}


        self._main = tk.Frame(body, bg=BG)
        self._main.place(x=88, y=0, width=830 - 176, relheight=1.0)
        self._build_content(self._main)


        self.sidebar = tk.Frame(body, bg=CARD, width=176)
        self.sidebar.place(x=-176, y=0, width=176, relheight=1.0)
        self.sidebar.pack_propagate(False)
        self._build_sidebar(self.sidebar)

    def _build_sidebar(self, parent):
        tk.Label(parent, text="MENU", bg=CARD, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w", padx=16, pady=(14, 8))
        self.tab_buttons = {}
        for key, label in self.TABS:
            b = SidebarButton(parent, label, selected=(key == self._current),
                              command=lambda k=key: self._show_page(k))
            b.pack(fill="x", padx=10, pady=(0, 6))
            self.tab_buttons[key] = b
        parent.update_idletasks()



        self.sidebar_bar = tk.Canvas(parent, width=3, height=2, bg=CARD,
                                     highlightthickness=0)
        self.sidebar_bar.create_rectangle(0, 0, 3, 200, outline="", fill=ACCENT)
        self._bar_pos = {}

    def _build_content(self, parent):
        self.underline = tk.Canvas(parent, height=2, bg=BG, highlightthickness=0)
        self.underline.pack(fill="x", padx=18, pady=(0, 10))
        self.underline.create_rectangle(0, 0, 0, 2, fill=ACCENT, outline="")
        self._build_status_bar(parent)
        self.content = tk.Frame(parent, bg=BG)
        self.content.pack(fill="both", expand=True)

        self._scroll_canvas = tk.Canvas(self.content, bg=BG, highlightthickness=0,
                                        bd=0)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar = tk.Scrollbar(self.content, orient="vertical",
                                       command=self._scroll_canvas.yview,
                                       bg=BG, activebackground=CARD,
                                       troughcolor=BG, bd=0, width=10,
                                       relief="flat", highlightthickness=0)
        self._scrollbar.pack(side="right", fill="y")
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)
        self._page_host = tk.Frame(self._scroll_canvas, bg=BG)
        self._host_item = self._scroll_canvas.create_window(
            (0, 0), window=self._page_host, anchor="nw")
        self._page_host.bind("<Configure>", self._on_host_configure)
        self._scroll_canvas.bind("<Configure>", self._on_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_wheel)

        self._card_i = 0
        self._page_key = None
        self.pages = {}
        self.page_cards = {}
        builders = (
            ("display", self._build_display),
            ("distance", self._build_distance),
            ("colors", self._build_colors),
            ("rate", self._build_readrate),
            ("aim", self._build_aim),
            ("themes", self._build_themes),
            ("hud", self._build_hud),
            ("profiles", self._build_profiles),
            ("games", self._build_games),
        )
        for key, builder in builders:
            _trace("building page: " + key)
            page = tk.Frame(self._page_host, bg=BG)
            self._page_key = key
            self.page_cards[key] = []
            self._card_i = 0
            builder(page)
            _trace("page built: " + key)
            self.pages[key] = page

        self._build_footer(parent)
        self._show_page(self._current)

    def _on_host_configure(self, _=None):
        self._scroll_canvas.configure(
            scrollregion=self._scroll_canvas.bbox("all"))

    def _on_canvas_configure(self, _=None):
        self._scroll_canvas.itemconfigure(
            self._host_item, width=max(1, self._scroll_canvas.winfo_width()))

    def _on_wheel(self, event):
        try:
            if self._scroll_canvas.winfo_exists():
                self._scroll_canvas.yview_scroll(
                    -1 * (event.delta // 120), "units")
        except Exception:
            pass
        return "break"

    def _build_status_bar(self, parent=None):
        parent = parent or self.root
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=18, pady=(6, 2))
        self._status_bar = bar
        self._status_cells = {}
        self._status = {}
        for key in ("attached", "camera", "targets", "esp", "game"):
            cell = tk.Frame(bar, bg=BG)
            cell.pack(side="left", padx=(0, 16))
            self._status_cells[key] = cell
            dot = tk.Label(cell, text="\u25cf", bg=BG, fg=MUTED,
                           font=(FONT, 9))
            dot.pack(side="left")
            lab = tk.Label(cell, text=key, bg=BG, fg=MUTED,
                           font=(FONT, 8))
            lab.pack(side="left", padx=(3, 0))
            self._status[key] = (dot, lab)
            if STATUS_TOOLTIPS.get(key):
                self._bind_tip((cell, dot, lab), STATUS_TOOLTIPS[key])
        self._msg = tk.Label(parent, text="", bg=BG, fg="#f59e0b",
                             font=(FONT, 8, "bold"), anchor="w")
        self._msg.pack(fill="x", padx=20, pady=(0, 4))
        self._tick_status()

    def _tick_status(self):
        try:
            global _toggle_request
            if _toggle_request:
                _toggle_request = False
                self._toggle_visible()
            if _shutdown.is_set() and getattr(self, "_started", False):
                self._cancel_afters()
                self.root.destroy()
                return
            s = status.snapshot()
            ok_green = "#22c55e"
            bad_red = "#ef4444"
            muted = "#8f91a0"

            def apply(key, ok, text):
                dot, lab = self._status[key]
                dot.configure(fg=ok_green if ok else (bad_red if ok is not None else muted))
                lab.configure(text=text)

            att = s["attached"]
            if s.get("waiting"):

                self._pulse = not getattr(self, "_pulse", False)
                dot, lab = self._status["attached"]
                dot.configure(fg="#f59e0b" if self._pulse else "#7a4d0a")
                lab.configure(text="connecting")
            else:
                apply("attached", att,
                      "attached: {}".format("yes" if att else "no"))
            apply("camera", s["camera"],
                  "camera: {}".format("readable" if s["camera"] else "unreadable"))
            dot, lab = self._status["targets"]
            dot.configure(fg=ACCENT)
            lab.configure(text="targets: {}".format(s["targets"]))
            apply("esp", s["esp"],
                  "esp: {}".format("on" if s["esp"] else "off"))
            game = (s.get("game") or "").strip()
            gid = s.get("game_id") or 0
            if game or gid:
                dot, lab = self._status["game"]
                dot.configure(fg=ACCENT)
                gid_txt = " ({})".format(gid) if gid else ""
                lab.configure(text="game: {}{}".format(game or "unknown", gid_txt))
                self._fit_game_label(lab, game or "unknown", gid_txt)
            else:
                dot, lab = self._status["game"]
                dot.configure(fg=muted)
                lab.configure(text="game: --")
            msg = (s.get("message") or "").strip()
            self._msg.configure(text="  " + msg if msg else "")
            self.root.after(250, self._tick_status)
        except Exception:
            pass

    def _game_budget(self):
        """Width left on the status bar for the game cell after the others."""
        bar = getattr(self, "_status_bar", None)
        if bar is None:
            return None
        w = bar.winfo_width()
        if w < 60:
            return None
        used = 0
        for key in ("attached", "camera", "targets", "esp"):
            cell = self._status_cells.get(key)
            if cell is not None and cell.winfo_ismapped():
                used += cell.winfo_width() + 16
        return w - used

    def _fit_game_label(self, lab, game, gid_txt):
        """Shrink the game name with an ellipsis so long IDs never get clipped."""
        budget = self._game_budget()
        if budget is None:
            return
        try:
            f = tkfont.Font(family=FONT, size=8)
        except Exception:
            return
        prefix = "game: "
        ell = "\u2026"
        room = budget - f.measure(prefix) - f.measure(gid_txt)
        if room <= f.measure(ell):
            lab.configure(text=prefix + ell + gid_txt)
        elif f.measure(game) > room:
            shown = game
            while shown and f.measure(shown + ell) > room:
                shown = shown[:-1]
            lab.configure(text=prefix + (shown + ell if shown else ell) + gid_txt)

    def _show_page(self, key):
        self._current = key
        self._scroll_canvas.yview_moveto(0)
        for name, page in self.pages.items():
            page.place_forget()
            if name == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
                for card in self.page_cards.get(name, []):
                    card.cancel_entrance()
        for name, b in self.tab_buttons.items():
            b.select(name == key)
        self._animate_sidebar_bar(key)
        cards = self.page_cards.get(key, [])
        for i, card in enumerate(cards):
            card.entrance_delay(140 + i * 80)
        if self._shown_page != key:
            self._animate_page_entrance(key, self._shown_page)
        self._shown_page = key
        if key == "themes":
            self._update_tile_rings()

    def _animate_page_entrance(self, key, old_key):
        """Slide the new page in from the direction you moved.

        Going down the tab list slides the new page up in from the bottom;
        going up slides it in from the top. Only the incoming page translates
        so per-frame redraws are light - moving both pages per frame smeared
        and pixelated on this layered window.
        """
        new = self.pages.get(key)
        if new is None:
            return
        content = self.content
        ch = content.winfo_height()
        if ch < 50:
            return
        if self._page_after is not None:
            try:
                self.root.after_cancel(self._page_after)
            except Exception:
                pass
        cw = self._scroll_canvas.winfo_width()
        keys = [k for k, _ in self.TABS]
        try:
            direction = 1 if keys.index(key) >= keys.index(old_key) else -1
        except ValueError:
            direction = 1
        steps = 16
        new.place(x=0, y=direction * ch, width=cw, height=ch)

        def step(i=0):
            try:
                if not new.winfo_exists():
                    self._page_after = None
                    return
            except Exception:
                self._page_after = None
                return
            e = self._ease_out((i + 1) / float(steps))
            new.place(x=0, y=int(direction * ch * (1.0 - e)), width=cw, height=ch)
            self.root.update_idletasks()
            if i + 1 < steps:
                self._page_after = self.root.after(16, lambda: step(i + 1))
            else:
                self._page_after = None
                new.place_forget()
                new.pack(fill="both", expand=True)
                self.root.update_idletasks()

        self._page_after = None
        step()

    def _stagger(self, card):
        self._card_i += 1
        self.page_cards[self._page_key].append(card)

    def _bind_tip(self, widgets, text):
        for w in widgets:
            w.bind("<Enter>", lambda e, d=text: self.tooltip.schedule(d), add="+")
            w.bind("<Leave>", lambda e: self.tooltip.hide(), add="+")

    def _add_toggle(self, parent, row, col, key, label):
        var = tk.BooleanVar(value=bool(self.esp.get(key, False)))
        self.toggle_vars[key] = var
        cell = tk.Frame(parent, bg=CARD)
        cell.grid(row=row, column=col, sticky="w", padx=(0, 16), pady=3)
        tgl = Toggle(cell, value=var.get())
        tgl.command = lambda k=key, v=var, t=tgl: (v.set(t.get()), self._set_bool(k, v.get()))
        tgl.pack(side="left")
        txt = tk.Label(cell, text=label, bg=CARD, fg=TEXT, font=(FONT, 9),
                       cursor="hand2")
        txt.pack(side="left", padx=(8, 0))
        txt.bind("<Button-1>", lambda e, t=tgl: t.set(not t.get()))
        self.toggles[key] = tgl

        def _hl(on):
            c = CARD_HOVER if on else CARD
            cell.configure(bg=c)
            txt.configure(bg=c)
            tgl.configure(bg=c)
        for w in (cell, txt):
            w.bind("<Enter>", lambda e: _hl(True))
            w.bind("<Leave>", lambda e: _hl(False))
        tgl.bind("<Enter>", lambda e: _hl(True), add="+")
        tgl.bind("<Leave>", lambda e: _hl(False), add="+")

        if TOOLTIPS.get(key):
            self._bind_tip((cell, tgl, txt), TOOLTIPS[key])

    def _add_reset_button(self, parent, key):
        row = tk.Frame(parent, bg=CARD)
        btn = AccentButton(row, "RESET TO DEFAULTS",
                           command=lambda k=key: self._reset_tab(k),
                           filled=False, width=200, height=32)
        btn.pack(side="left")
        self._bind_tip((row, btn),
                       "Restores every setting on this tab to the built-in "
                       "defaults.")
        if parent.grid_slaves():
            r = parent.grid_size()[1]
            row.grid(row=r, column=0, columnspan=2, sticky="w", padx=14,
                     pady=(2, 12))
        else:
            row.pack(fill="x", padx=14, pady=(2, 12))

    def _reset_tab(self, key):
        if key in ("display", "distance"):
            self.esp.clear()
            self.esp.update(copy.deepcopy(config.ESP))
        elif key == "colors":
            self.colors.clear()
            self.colors.update(copy.deepcopy(config.COLORS))
        elif key == "rate":
            self.stealth.clear()
            self.stealth.update(copy.deepcopy(config.STEALTH))
        elif key == "aim":
            self.aim.clear()
            self.aim.update(copy.deepcopy(config.AIMBOT))
        elif key == "themes":
            self.theme = config.THEME
            themes.apply(self.theme)
            if self.hud.get("follow_theme", True):
                self._sync_hud_theme()
        elif key == "hud":
            self.hud.clear()
            self.hud.update(copy.deepcopy(config.HUD))
            if self.hud.get("follow_theme", True):
                self._sync_hud_theme()
        elif key == "profiles":
            _profiles.clear()
        elif key == "games":
            self.games.clear()
            self.games.update(copy.deepcopy(config.GAMES))
        self._retheme()

    def _build_display(self, parent):
        card = Card(parent, "Display")
        self._stagger(card)
        rows = [
            ("box", "Box"),
            ("box_corners", "Corner box"),
            ("healthbar", "Health bar"),
            ("name", "Name"),
            ("distance", "Distance"),
            ("tracers", "Tracers"),
            ("tool", "Equipped tool"),
            ("team_check", "Hide teams"),
            ("show_local_player", "Show self"),
            ("dynamic_box", "Dynamic box"),
            ("fade_dead", "Fade dead"),
            ("highlight_target", "Target highlight"),
            ("skip_dead", "Skip dead"),
            ("item_esp", "Item ESP"),
            ("occlusion", "Occlusion check"),
        ]
        for i, (key, label) in enumerate(rows):
            self._add_toggle(card.body, i // 2, i % 2, key, label)

        dead_row = tk.Frame(card.body, bg=CARD)
        dead_row.grid(row=8, column=0, columnspan=2, sticky="we", pady=(8, 0))
        tk.Label(dead_row, text="Dead box size", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.dead_val = tk.Label(dead_row, text="", bg=CARD, fg=MUTED,
                                 font=(FONT, 8))
        self.dead_val.pack(side="right")
        self.dead_box = ModernSlider(
            dead_row, 0.2, 1.0, float(self.esp.get("dead_box_scale", 0.5)),
            command=self._on_dead_box_slide, width=150)
        self.dead_box.pack(side="right", padx=(0, 8))
        self.dead_val.config(text="{}%".format(int(round(float(
            self.esp.get("dead_box_scale", 0.5)) * 100.0))))
        self._bind_tip((dead_row, self.dead_box), TOOLTIPS["dead_box"])

        trow = tk.Frame(card.body, bg=CARD)
        trow.grid(row=9, column=0, columnspan=2, sticky="we", pady=(8, 0))
        tk.Label(trow, text="Dead tracer len", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.dead_tval = tk.Label(trow, text="", bg=CARD, fg=MUTED,
                                 font=(FONT, 8))
        self.dead_tval.pack(side="right")
        self.dead_tracer = ModernSlider(
            trow, 0.1, 1.0, float(self.esp.get("dead_tracer_scale", 0.55)),
            command=self._on_dead_trace_slide, width=150)
        self.dead_tracer.pack(side="right", padx=(0, 8))
        self.dead_tval.config(text="{}%".format(int(round(float(
            self.esp.get("dead_tracer_scale", 0.55)) * 100.0))))
        self._bind_tip((trow, self.dead_tracer), TOOLTIPS["dead_tracer"])
        self._add_reset_button(card.body, "display")

    def _build_distance(self, parent):
        card = Card(parent, "Distance")
        self._stagger(card)
        ttk_row = tk.Frame(card.body, bg=CARD)
        ttk_row.pack(fill="x")
        tk.Label(ttk_row, text="Max studs", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.max_dist_field = NumberField(
            ttk_row, int(round(float(self.esp.get("max_distance", 1500.0)))),
            self._set_max_distance, lo=100, hi=5000, width=6)
        self.max_dist_field.pack(side="right")
        self.max_distance = ModernSlider(
            ttk_row, 100, 5000, float(self.esp.get("max_distance", 1500.0)),
            command=self._on_max_dist_slide, width=250)
        self.max_distance.pack(fill="x", pady=(6, 0))
        self._bind_tip((ttk_row, self.max_distance, self.max_dist_field),
                       TOOLTIPS["max_distance"])

        unit_row = tk.Frame(card.body, bg=CARD)
        unit_row.pack(fill="x", pady=(8, 0))
        tk.Label(unit_row, text="Units", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.units = tk.StringVar(value=self.esp.get("distance_units", "studs"))
        self.unit_buttons = {}
        for i, u in enumerate(("studs", "feet", "meters")):
            b = SegButton(unit_row, u, selected=(u == self.units.get()),
                          command=lambda u=u: self._pick_units(u),
                          width=56)
            b.pack(side="left", padx=(8, 0))
            self.unit_buttons[u] = b

        irange_row = tk.Frame(card.body, bg=CARD)
        irange_row.pack(fill="x", pady=(8, 0))
        tk.Label(irange_row, text="Item range", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.item_range = ModernSlider(
            irange_row, 25, 1000, float(self.esp.get("item_distance", 300.0)),
            command=self._on_item_range_slide, width=250)
        self.item_range.pack(fill="x", pady=(6, 0))
        self._bind_tip((irange_row, self.item_range), TOOLTIPS["item_range"])
        self._add_reset_button(card.body, "distance")

    def _build_colors(self, parent):
        card = Card(parent, "Colors")
        self._stagger(card)
        rows = [
            ("box_teammate", "Teammate box"),
            ("box_enemy", "Enemy box"),
            ("name", "Name text"),
            ("distance", "Distance text"),
            ("tool", "Tool text"),
            ("health_full", "Health full"),
            ("health_low", "Health low"),
            ("tracer_teammate", "Tracer (team)"),
            ("tracer_enemy", "Tracer (enemy)"),
            ("dead", "Dead / faded"),
            ("dead_tracer", "Dead tracer"),
            ("highlight", "Target highlight"),
            ("item", "Items"),
        ]
        for i, (key, label) in enumerate(rows):
            row, col = divmod(i, 2)
            cell = tk.Frame(card.body, bg=CARD)
            cell.grid(row=row, column=col, sticky="w", padx=(0, 14), pady=3)
            sw = ColorSwatch(cell, self.colors.get(key, (255, 255, 255)),
                             command=lambda k=key: self._pick_color(k))
            sw.pack(side="left")
            tk.Label(cell, text=label, bg=CARD, fg=TEXT,
                     font=(FONT, 9)).pack(side="left", padx=(8, 0))
            self.color_buttons[key] = sw
        self._add_reset_button(card.body, "colors")

    def _build_readrate(self, parent):
        card = Card(parent, "Read rate")
        self._stagger(card)
        row = tk.Frame(card.body, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Update rate", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.hz_field = NumberField(
            row, int(round(float(self.stealth.get("update_hz", 144.0)))),
            self._set_hz_value, lo=30, hi=240, width=5)
        self.hz_field.pack(side="right")
        tk.Label(row, text="Hz", bg=CARD, fg=MUTED,
                 font=(FONT, 8)).pack(side="right", padx=(4, 0))
        self.update_hz = ModernSlider(
            row, 30, 240, float(self.stealth.get("update_hz", 144.0)),
            command=self._on_hz_slide, width=250)
        self.update_hz.pack(fill="x", pady=(6, 0))
        self._bind_tip((row, self.update_hz, self.hz_field),
                       TOOLTIPS["update_hz"])

        hrow = tk.Frame(card.body, bg=CARD)
        hrow.pack(fill="x", pady=(8, 0))
        self.humanize_var = tk.BooleanVar(value=bool(self.stealth.get("humanize", False)))
        tgl = Toggle(hrow, value=self.humanize_var.get())
        tgl.command = lambda t=tgl: (self.humanize_var.set(t.get()), self._set_humanize())
        tgl.pack(side="left")
        tk.Label(hrow, text="Humanize (random 90-144 Hz)", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left", padx=(8, 0))
        self._bind_tip((hrow, tgl), TOOLTIPS["humanize"])
        self._add_reset_button(card.body, "rate")

    def _build_aim(self, parent):
        card = Card(parent, "Aim assist")
        self._stagger(card)

        grid_i = [0]

        def g_next(columnspan=2, sticky="w", px=(0, 16), py=(8, 0)):
            row = grid_i[0]
            grid_i[0] += 1
            f = tk.Frame(card.body, bg=CARD)
            f.grid(row=row, column=0, columnspan=columnspan, sticky=sticky,
                   padx=px, pady=py)
            return f

        note_row = g_next(sticky="we", py=(0, 4))
        tk.Label(note_row,
                 text="Gently eases your crosshair onto the closest enemy "
                      "with a curved, human-like path. No game memory is "
                      "written.",
                 bg=CARD, fg=MUTED, font=(FONT, 8), justify="left",
                 wraplength=540).pack(anchor="w", fill="x")

        en_row = g_next(sticky="we", py=(12, 0))
        var = tk.BooleanVar(value=bool(self.aim.get("enabled", False)))
        self.aim_vars = {"enabled": var}
        tgl = Toggle(en_row, value=var.get())
        tgl.command = lambda t=tgl: (var.set(t.get()),
                                     self.aim.__setitem__("enabled", t.get()))
        tgl.pack(side="left")
        txt = tk.Label(en_row, text="Aim assist", bg=CARD, fg=TEXT,
                       font=(FONT, 9, "bold"), cursor="hand2")
        txt.pack(side="left", padx=(8, 0))
        self._bind_tip((en_row, tgl, txt), TOOLTIPS["aim_enabled"])

        mode_row = g_next(sticky="we")
        tk.Label(mode_row, text="Trigger", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_mode = self.aim.get("mode", "hold")
        self.aim_mode_btns = {}
        for key, label in (("hold", "HOLD"), ("click", "ON FIRE")):
            b = SegButton(mode_row, label, selected=(key == self.aim_mode),
                          command=lambda k=key: self._pick_aim_mode(k),
                          width=72)
            b.pack(side="left", padx=(8, 0))
            self.aim_mode_btns[key] = b
        self._bind_tip((mode_row,), TOOLTIPS["aim_mode"])

        hot_row = g_next(sticky="we")
        tk.Label(hot_row, text="Hold key", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_hot_options = {
            "E": 0x45, "Q": 0x51, "V": 0x56, "X": 0x58,
            "Right mouse": 0x02, "Shift": 0x10,
        }
        cur = self.aim.get("hotkey", 0x45)
        label = _vk_to_label(cur, self.aim_hot_options)
        self.aim_hot = tk.StringVar(value=label)
        options = list(self.aim_hot_options.keys()) + ["Custom..."]
        om = tk.OptionMenu(hot_row, self.aim_hot, *options,
                           command=self._on_aim_hotkey)
        om.configure(bg=INPUT, fg=TEXT, activebackground=ACCENT,
                     activeforeground="#ffffff", relief="flat",
                     highlightthickness=1, highlightbackground=GHOST_BORDER,
                     font=(FONT, 9), width=14)
        menu = om["menu"]
        menu.configure(bg=INPUT, fg=TEXT, activebackground=ACCENT,
                       activeforeground="#ffffff", relief="flat",
                       font=(FONT, 9))
        om.pack(side="left", padx=(10, 0))
        self._bind_tip((hot_row, om), TOOLTIPS["aim_hotkey"])

        fov_row = g_next(sticky="we")
        tk.Label(fov_row, text="FOV (px)", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_fov_val = tk.Label(fov_row, text="", bg=CARD, fg=MUTED,
                                    font=(FONT, 8))
        self.aim_fov_val.pack(side="right")
        self.aim_fov = ModernSlider(
            fov_row, 20, 500, float(self.aim.get("fov_px", 250.0)),
            command=self._on_aim_fov_slide, width=300)
        self.aim_fov.pack(fill="x", pady=(6, 0))
        self.aim_fov_val.config(text="{}px".format(int(round(
            float(self.aim.get("fov_px", 250.0))))))
        self._bind_tip((fov_row, self.aim_fov), TOOLTIPS["aim_fov"])

        show_fov_row = g_next(sticky="we")
        sf_var = tk.BooleanVar(value=bool(self.aim.get("show_fov", True)))
        self.aim_show_fov = sf_var
        sf_tgl = Toggle(show_fov_row, value=sf_var.get())
        sf_tgl.command = lambda t=sf_tgl: (sf_var.set(t.get()),
                                           self.aim.__setitem__("show_fov",
                                                                t.get()))
        sf_tgl.pack(side="left")
        sf_txt = tk.Label(show_fov_row, text="Show aim FOV circle",
                          bg=CARD, fg=TEXT, font=(FONT, 9), cursor="hand2")
        sf_txt.pack(side="left", padx=(8, 0))
        sf_txt.bind("<Button-1>", lambda e, t=sf_tgl: t.set(not t.get()))
        self._bind_tip((show_fov_row, sf_tgl, sf_txt),
                       TOOLTIPS["aim_show_fov"])

        dist_row = g_next(sticky="we")
        tk.Label(dist_row, text="Max distance", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_dist_val = tk.Label(dist_row, text="", bg=CARD, fg=MUTED,
                                     font=(FONT, 8))
        self.aim_dist_val.pack(side="right")
        self.aim_dist = ModernSlider(
            dist_row, 50, 1500, float(self.aim.get("max_distance", 300.0)),
            command=self._on_aim_dist_slide, width=300)
        self.aim_dist.pack(fill="x", pady=(6, 0))
        self.aim_dist_val.config(text="{} studs".format(int(round(
            float(self.aim.get("max_distance", 300.0))))))
        self._bind_tip((dist_row, self.aim_dist), TOOLTIPS["aim_distance"])

        spd_row = g_next(sticky="we")
        tk.Label(spd_row, text="Smoothness", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_spd_val = tk.Label(spd_row, text="", bg=CARD, fg=MUTED,
                                    font=(FONT, 8))
        self.aim_spd_val.pack(side="right")
        self.aim_speed = ModernSlider(
            spd_row, 20, 400, float(self.aim.get("speed", 0.12)) * 1000.0,
            command=self._on_aim_speed_slide, width=300)
        self.aim_speed.pack(fill="x", pady=(6, 0))
        self.aim_spd_val.config(text="{} ms".format(int(round(
            float(self.aim.get("speed", 0.12)) * 1000.0))))
        self._bind_tip((spd_row, self.aim_speed), TOOLTIPS["aim_speed"])

        tgt_row = g_next(sticky="we")
        tk.Label(tgt_row, text="Aim point", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_target = self.aim.get("target", "head")
        self.aim_target_btns = {}
        for key, label in (("head", "HEAD"), ("torso", "TORSO")):
            b = SegButton(tgt_row, label, selected=(key == self.aim_target),
                          command=lambda k=key: self._pick_aim_target(k),
                          width=72)
            b.pack(side="left", padx=(8, 0))
            self.aim_target_btns[key] = b
        self._bind_tip((tgt_row,), TOOLTIPS["aim_target"])

        stut_row = g_next(sticky="we")
        tk.Label(stut_row, text="Micro stutter", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_stut_val = tk.Label(stut_row, text="", bg=CARD, fg=MUTED,
                                     font=(FONT, 8))
        self.aim_stut_val.pack(side="right")
        self.aim_stutter = ModernSlider(
            stut_row, 0, 12, float(self.aim.get("stutter", 3.0)),
            command=self._on_aim_stutter_slide, width=300)
        self.aim_stutter.pack(fill="x", pady=(6, 0))
        self.aim_stut_val.config(text="{} px".format(int(round(
            float(self.aim.get("stutter", 3.0))))))
        self._bind_tip((stut_row, self.aim_stutter), TOOLTIPS["aim_stutter"])

        curve_row = g_next(sticky="we")
        tk.Label(curve_row, text="Curve", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_curve_val = tk.Label(curve_row, text="", bg=CARD, fg=MUTED,
                                      font=(FONT, 8))
        self.aim_curve_val.pack(side="right")
        self.aim_curve = ModernSlider(
            curve_row, 0, 1.2, float(self.aim.get("curve", 0.5)),
            command=self._on_aim_curve_slide, width=300)
        self.aim_curve.pack(fill="x", pady=(6, 0))
        self.aim_curve_val.config(text="{:.2f}".format(
            float(self.aim.get("curve", 0.5))))
        self._bind_tip((curve_row, self.aim_curve), TOOLTIPS["aim_curve"])

        orb_row = g_next(sticky="we")
        tk.Label(orb_row, text="Orbit radius", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_orb_val = tk.Label(orb_row, text="", bg=CARD, fg=MUTED,
                                    font=(FONT, 8))
        self.aim_orb_val.pack(side="right")
        self.aim_orbit = ModernSlider(
            orb_row, 10, 200, float(self.aim.get("orbit_radius", 60.0)),
            command=self._on_aim_orbit_slide, width=300)
        self.aim_orbit.pack(fill="x", pady=(6, 0))
        self.aim_orb_val.config(text="{} px".format(int(round(
            float(self.aim.get("orbit_radius", 60.0))))))
        self._bind_tip((orb_row, self.aim_orbit), TOOLTIPS["aim_orbit"])

        lock_row = g_next(sticky="we")
        tk.Label(lock_row, text="Target lock", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.aim_lock_val = tk.Label(lock_row, text="", bg=CARD, fg=MUTED,
                                     font=(FONT, 8))
        self.aim_lock_val.pack(side="right")
        self.aim_lock = ModernSlider(
            lock_row, 5, 30, float(self.aim.get("lock_keep", 1.5)) * 10.0,
            command=self._on_aim_lock_slide, width=300)
        self.aim_lock.pack(fill="x", pady=(6, 0))
        self.aim_lock_val.config(text="{:.1f}".format(
            float(self.aim.get("lock_keep", 1.5))))
        self._bind_tip((lock_row, self.aim_lock), TOOLTIPS["aim_lock"])
        self._add_reset_button(card.body, "aim")

    def _pick_aim_mode(self, key):
        self.aim["mode"] = key
        self.aim_mode = key
        for k, b in self.aim_mode_btns.items():
            b.select(k == key)

    def _on_aim_hotkey(self, name):
        if name == "Custom...":
            self._begin_hotkey_capture()
            return
        vk = self.aim_hot_options.get(name)
        if vk is not None:
            self.aim["hotkey"] = vk

    def _begin_hotkey_capture(self):
        self._finish_hotkey_capture()
        self._capturing = True
        self.aim_hot.set("Press a key...")
        self._capture_after = self.root.after(6000,
                                              self._finish_hotkey_capture)
        self.root.focus_force()
        self._capture_bind = self.root.bind("<Key>",
                                            self._on_hotkey_capture)
        self._mouse_after = self.root.after(40, self._poll_mouse_capture)

    def _on_hotkey_capture(self, event):
        vk = _keysym_to_vk(event.keysym)
        if vk is not None:
            self.aim["hotkey"] = vk
            self.aim_hot.set(_vk_to_label(vk, self.aim_hot_options))
            self._finish_hotkey_capture()
        return "break"

    def _poll_mouse_capture(self):
        if not getattr(self, "_capturing", False):
            return
        for vk in _MOUSE_CAPTURE_VKS:
            if _user32.GetAsyncKeyState(vk) & 0x8000:
                self.aim["hotkey"] = vk
                self.aim_hot.set(_vk_to_label(vk, self.aim_hot_options))
                self._finish_hotkey_capture()
                return
        self._mouse_after = self.root.after(40, self._poll_mouse_capture)

    def _finish_hotkey_capture(self):
        if getattr(self, "_capture_after", None) is not None:
            try:
                self.root.after_cancel(self._capture_after)
            except Exception:
                pass
            self._capture_after = None
        if getattr(self, "_capture_bind", None) is not None:
            try:
                self.root.unbind("<Key>", self._capture_bind)
            except Exception:
                pass
            self._capture_bind = None
        if getattr(self, "_mouse_after", None) is not None:
            try:
                self.root.after_cancel(self._mouse_after)
            except Exception:
                pass
            self._mouse_after = None
        if getattr(self, "_capturing", False):
            self._capturing = False
            self.aim_hot.set(_vk_to_label(
                self.aim.get("hotkey", 0x45), self.aim_hot_options))

    def _on_aim_fov_slide(self, _=None):
        v = int(round(self.aim_fov.get()))
        self.aim["fov_px"] = v
        self.aim_fov_val.config(text="{}px".format(v))

    def _on_aim_dist_slide(self, _=None):
        v = int(round(self.aim_dist.get()))
        self.aim["max_distance"] = v
        self.aim_dist_val.config(text="{} studs".format(v))

    def _on_aim_speed_slide(self, _=None):
        v = int(round(self.aim_speed.get()))
        self.aim["speed"] = v / 1000.0
        self.aim_spd_val.config(text="{} ms".format(v))

    def _pick_aim_target(self, key):
        self.aim["target"] = key
        self.aim_target = key
        for k, b in self.aim_target_btns.items():
            b.select(k == key)

    def _on_aim_stutter_slide(self, _=None):
        v = int(round(self.aim_stutter.get()))
        self.aim["stutter"] = float(v)
        self.aim_stut_val.config(text="{} px".format(v))

    def _on_aim_curve_slide(self, _=None):
        v = round(self.aim_curve.get(), 2)
        self.aim["curve"] = v
        self.aim_curve_val.config(text="{:.2f}".format(v))

    def _on_aim_orbit_slide(self, _=None):
        v = int(round(self.aim_orbit.get()))
        self.aim["orbit_radius"] = float(v)
        self.aim_orb_val.config(text="{} px".format(v))

    def _on_aim_lock_slide(self, _=None):
        v = round(self.aim_lock.get() / 10.0, 1)
        self.aim["lock_keep"] = v
        self.aim_lock_val.config(text="{:.1f}".format(v))

    def _build_themes(self, parent):
        card = Card(parent, "Theme")
        self._stagger(card)

        grid = tk.Frame(card.body, bg=CARD)
        grid.pack(fill="x")
        self.theme_tiles = {}
        for i, name in enumerate(themes.THEMES):
            tile = self._theme_tile(grid, name)
            tile.grid(row=i // 3, column=i % 3, sticky="we",
                      padx=(0, 10), pady=4)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        grid.grid_columnconfigure(2, weight=1)

        tk.Label(card.body, text="PREVIEW", bg=CARD, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w", pady=(12, 4))
        self.preview = tk.Label(card.body, bg="#0e0f12")
        self.preview.pack(fill="x", pady=(0, 6))

        self._refresh_preview()
        self._add_reset_button(card.body, "themes")

    def _theme_tile(self, parent, name):
        m = themes.meta(name)
        tile = tk.Frame(parent, bg=CARD, cursor="hand2",
                        highlightthickness=2, highlightbackground=BG,
                        highlightcolor=BG)
        dot = tk.Canvas(tile, width=24, height=24, bg=CARD, highlightthickness=0)
        dot.pack(side="left", padx=(8, 0), pady=8)
        dot.create_oval(3, 3, 21, 21, fill=_to_hex(m["accent"]), outline="")
        lab = tk.Label(tile, text=m["title"], bg=CARD, fg=TEXT,
                       font=(FONT, 9, "bold"))
        lab.pack(side="left", padx=(10, 14), pady=8)
        for w in (tile, dot, lab):
            w.bind("<Button-1>", lambda e, n=name: self._select_theme(n))
        self.theme_tiles[name] = tile
        return tile

    def _update_tile_rings(self):
        for name, tile in self.theme_tiles.items():
            on = (name == self.theme)
            tile.configure(highlightbackground=ACCENT if on else BG,
                           highlightcolor=ACCENT if on else BG,
                           highlightthickness=2 if on else 0)

    def _select_theme(self, name):
        if name == self.theme:
            return
        self.theme = name
        themes.apply(name)
        if self.hud.get("follow_theme", True):
            self._sync_hud_theme()
        self._retheme()

    def _sync_hud_theme(self):
        bg, border, text = themes.hud_palette(self.theme)
        self.hud["bg"] = list(bg)
        self.hud["border"] = list(border)
        self.hud["text"] = list(text)
        for key, sw in self.hud_colors.items():
            sw.set_color(tuple(self.hud.get(key, (255, 255, 255))))

    def _retheme(self):
        """Apply the accent of the currently selected theme and rebuild the
        window so all widgets pick up the new colors / icon immediately."""
        _set_ui_accent(self.theme)
        self._cancel_afters()
        self.sidebar = None
        self._main = None
        self.sidebar_bar = None
        self._bar_pos = {}
        self.pages = {}
        self.page_cards = {}
        self._sidebar_after = None
        self._bar_after = None
        self._page_after = None
        for w in self.root.winfo_children():
            w.destroy()
        self.toggle_vars = {}
        self.toggles = {}
        self.color_buttons = {}
        self.hud_vars = {}
        self.hud_colors = {}
        self._build_header()
        self._build_body()
        if self._sidebar_open:
            self.sidebar.place(x=0, y=0, width=176, relheight=1.0)
            self._main.place(x=176, y=0, width=830 - 176, relheight=1.0)
        else:
            self.sidebar.place(x=-176, y=0, width=176, relheight=1.0)
            self._main.place(x=88, y=0, width=830 - 176, relheight=1.0)
        self._resize_window()
        self.root.update_idletasks()
        self._update_logo()
        self._grow_accent(0)

    def _refresh_preview(self):
        try:
            from PIL import ImageTk as itk
            m = themes.meta(self.theme)
            img = themes.make_preview_png(m["shape"], m["accent"], scale=6)
            self._preview_img = itk.PhotoImage(img)
            self.preview.configure(image=self._preview_img)
        except Exception:
            self.preview.configure(image="")

    def _update_logo(self):
        try:
            img = tk.PhotoImage(file=themes.PNG_PATH)
            n = max(2, min(img.width(), img.height()) // 32)
            if n > 1:
                img = img.subsample(n, n)
            self._logo_img = img
            self._logo.configure(image=img)
        except Exception:
            pass
        try:
            self.root.iconbitmap(themes.ICO_PATH)
        except Exception:
            pass

    def _build_hud(self, parent):
        card = Card(parent, "HUD")
        self._stagger(card)

        grid_i = [0]

        def g_next(columnspan=2, sticky="w", px=(0, 16), py=3):
            row = grid_i[0]
            grid_i[0] += 1
            f = tk.Frame(card.body, bg=CARD)
            f.grid(row=row, column=0, columnspan=columnspan, sticky=sticky,
                   padx=px, pady=py)
            return f

        on_row = g_next(sticky="we", px=(0, 16), py=(0, 8))
        var = tk.BooleanVar(value=bool(self.hud.get("enabled", True)))
        self.hud_vars["enabled"] = var
        tgl = Toggle(on_row, value=var.get())
        tgl.command = lambda t=tgl: self.hud.__setitem__("enabled", t.get())
        tgl.pack(side="left")
        txt = tk.Label(on_row, text="Show HUD", bg=CARD, fg=TEXT,
                       font=(FONT, 9, "bold"), cursor="hand2")
        txt.pack(side="left", padx=(8, 0))
        self._bind_tip((on_row, tgl, txt),
                       "Enable or disable the in-game HUD boxes.")

        rows = [
            ("fps", "FPS box",
             "Overlay draw rate (how often the ESP refreshes per second)."),
            ("ping", "Ping box",
             "Network latency - needs a Stats offset in the offsets dump; "
             "shows '--' until one is added."),
            ("players", "Server players box",
             "Total players currently in the server."),
            ("show_title", "Box labels",
             "Show the FPS / PING / PLAYERS caption in each box."),
        ]
        for i, (key, label, desc) in enumerate(rows):
            row, col = divmod(i, 2)
            cell = tk.Frame(card.body, bg=CARD)
            cell.grid(row=row + 1, column=col, sticky="w", padx=(0, 16), pady=3)
            var = tk.BooleanVar(value=bool(self.hud.get(key, False)))
            self.hud_vars[key] = var
            tgl = Toggle(cell, value=var.get())
            tgl.command = lambda k=key, v=var, t=tgl: (v.set(t.get()),
                                                       self.hud.__setitem__(k, v.get()))
            tgl.pack(side="left")
            txt = tk.Label(cell, text=label, bg=CARD, fg=TEXT,
                           font=(FONT, 9), cursor="hand2")
            txt.pack(side="left", padx=(8, 0))
            self._bind_tip((cell, tgl, txt), desc)

        size_row = g_next(sticky="we", py=(10, 0))
        tk.Label(size_row, text="Text size", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.hud_size = int(self.hud.get("font_size", 1))
        self.hud_size_btns = {}
        for i, label in enumerate(("Small", "Medium", "Large")):
            b = SegButton(size_row, label,
                          selected=(i == self.hud_size),
                          command=lambda i=i: self._pick_hud_size(i),
                          width=64)
            b.pack(side="left", padx=(6, 0))
            self.hud_size_btns[i] = b

        colors = [
            ("bg", "Backdrop"),
            ("border", "Border"),
            ("text", "Text"),
        ]
        theme_row = g_next(sticky="w", py=(10, 0))
        tvar = tk.BooleanVar(value=bool(self.hud.get("follow_theme", True)))
        self.hud_vars["follow_theme"] = tvar
        ttgl = Toggle(theme_row, value=tvar.get())
        ttgl.command = lambda: self._toggle_hud_theme(ttgl.get())
        ttgl.pack(side="left")
        ttxt = tk.Label(theme_row, text="Match theme accent", bg=CARD, fg=TEXT,
                        font=(FONT, 9), cursor="hand2")
        ttxt.pack(side="left", padx=(8, 0))
        self._bind_tip((theme_row, ttgl, ttxt),
                       "Use the selected theme's accent color for the HUD "
                       "boxes. Turn off to pick custom colors below.")
        color_row = g_next(sticky="we", py=(4, 0))
        tk.Label(color_row, text="Colors", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.hud_colors = {}
        for key, label in colors:
            cell = tk.Frame(color_row, bg=CARD)
            cell.pack(side="left", padx=(10, 0))
            sw = ColorSwatch(cell, tuple(self.hud.get(key, (255, 255, 255))),
                             command=lambda k=key: self._pick_hud_color(k))
            sw.pack(side="left")
            tk.Label(cell, text=label, bg=CARD, fg=TEXT,
                     font=(FONT, 9)).pack(side="left", padx=(6, 0))
            self.hud_colors[key] = sw

        reset_row = g_next(sticky="w", py=(12, 0))
        tk.Button(reset_row, text="Reset layout",
                  command=self._reset_hud, bg=CARD, fg=TEXT,
                  activebackground=ACCENT, activeforeground="#0b0c10",
                  relief="flat", font=(FONT, 9, "bold"),
                  highlightthickness=0, cursor="hand2",
                  padx=10, pady=4).pack(side="left")

        note_row = g_next(sticky="w", py=(10, 0))
        tk.Label(note_row,
                 text="Move & resize in-game: hold Alt and drag a box to move "
                      "it, or drag a box's bottom-right corner to resize. "
                      "Boxes snap to each other's edges.",
                 bg=CARD, fg=MUTED, font=(FONT, 8), justify="left",
                 wraplength=560).pack(side="left")
        self._add_reset_button(card.body, "hud")

    def _toggle_hud_theme(self, on):
        self.hud["follow_theme"] = on
        if on:
            self._sync_hud_theme()

    def _pick_hud_color(self, key):
        current = self.hud.get(key, [255, 255, 255])
        rgb, _ = colorchooser.askcolor(color=_to_hex(tuple(current)),
                                       parent=self.root,
                                       title="Pick {}".format(key))
        if rgb:
            self.hud[key] = [int(c) for c in rgb]
            self.hud_colors[key].set_color(tuple(self.hud[key]))

    def _pick_hud_size(self, i):
        self.hud_size = i
        self.hud["font_size"] = i
        self.hud["layout"] = self.hud.get("layout", {})
        for k, b in self.hud_size_btns.items():
            b.select(k == i)
        if self.hud.get("enabled"):
            base = 30 + i * 4
            for k in ("fps", "ping", "players"):
                r = self.hud["layout"].get(k)
                if r is not None:
                    r[3] = base

    def _reset_hud(self):
        for k in ("fps", "ping", "players"):
            self.hud["layout"][k] = list(_HUD_DEFAULT_LAYOUT[k])
        for k in ("fps", "ping", "players", "show_title"):
            if k in self.hud_vars:
                self.hud_vars[k].set(bool(self.hud.get(k, False)))


    def _build_games(self, parent):
        card = Card(parent, "Game presets")
        self._stagger(card)
        tk.Label(card.body,
                 text="Pick a game from the dropdown to activate its role-based "
                      "ESP - tracers, boxes and names get coloured by role, e.g. "
                      "Murder Mystery 2 murderer / sheriff / innocent. Roles are "
                      "matched from team names and each player's inventory.",
                 bg=CARD, fg=MUTED, font=(FONT, 8), justify="left",
                 wraplength=540).pack(anchor="w", fill="x")

        if not self.games:
            tk.Label(card.body, text="No presets defined yet.", bg=CARD, fg=TEXT,
                     font=(FONT, 9)).pack(anchor="w", pady=(12, 0))
            self._add_reset_button(card.body, "games")
            return

        sel_row = tk.Frame(card.body, bg=CARD)
        sel_row.pack(fill="x", pady=(10, 8))
        tk.Label(sel_row, text="Game", bg=CARD, fg=TEXT,
                 font=(FONT, 9)).pack(side="left")
        self._game_names = {g.get("name", k): k for k, g in self.games.items()}
        if self._game_key not in self.games:
            self._game_key = next(iter(self.games))
        for k, g in self.games.items():
            g["enabled"] = (k == self._game_key)
        game_label = self.games[self._game_key].get("name", self._game_key)
        self.game_var = tk.StringVar(value=game_label)
        om = tk.OptionMenu(sel_row, self.game_var, *self._game_names.keys(),
                           command=self._on_preset_change)
        om.configure(bg=INPUT, fg=TEXT, activebackground=ACCENT,
                     activeforeground="#ffffff", relief="flat",
                     highlightthickness=1, highlightbackground=GHOST_BORDER,
                     font=(FONT, 9, "bold"), width=26)
        menu = om["menu"]
        menu.configure(bg=INPUT, fg=TEXT, activebackground=ACCENT,
                       activeforeground="#ffffff", relief="flat", font=(FONT, 9))
        om.pack(side="left", padx=(10, 0))

        auto_row = tk.Frame(card.body, bg=CARD)
        auto_row.pack(fill="x", pady=(2, 4))
        auto_var = tk.BooleanVar(value=bool(self.esp.get("auto_preset", True)))
        auto = Toggle(auto_row, value=auto_var.get())
        auto.command = lambda v=auto_var, t=auto: (
            v.set(t.get()), self.esp.__setitem__("auto_preset", v.get()))
        auto.pack(side="left")
        tk.Label(auto_row, text="Auto-detect game", bg=CARD, fg=TEXT,
                 font=(FONT, 9, "bold")).pack(side="left", padx=(8, 0))
        tk.Label(auto_row,
                 text="  switches the active preset to match the game you join "
                      "(by place ID)",
                 bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="left", padx=(8, 0))
        self._bind_tip((auto_row, auto),
                       "When on, joining a game whose place ID matches a preset "
                       "auto-activates that preset. When off, only the preset "
                       "picked from the dropdown applies.")

        self._game_editor = tk.Frame(card.body, bg=CARD)
        self._game_editor.pack(fill="x", pady=(4, 0))
        self._build_game_editor()
        self._add_reset_button(card.body, "games")

    def _on_preset_change(self, name):
        key = self._game_names.get(name)
        if not key:
            return
        if key == self._game_key and self.games[key].get("enabled"):
            return
        for k, g in self.games.items():
            g["enabled"] = k == key
        self._game_key = key
        self._build_game_editor()

    def _build_game_editor(self):
        for w in self._game_editor.winfo_children():
            w.destroy()
        g = self.games[self._game_key]

        roles = g.get("roles", {})
        if not roles:
            tk.Label(self._game_editor, text="This preset has no roles.",
                     bg=CARD, fg=MUTED, font=(FONT, 8)).pack(anchor="w")
            return

        head = tk.Frame(self._game_editor, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text="Role", bg=CARD, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(side="left", padx=(34, 0))
        for lab in ("NAME", "BOX", "TRACER"):
            tk.Label(head, text=lab, bg=CARD, fg=MUTED,
                     font=(FONT, 7, "bold")).pack(side="right", padx=(0, 8))

        for rk, role in roles.items():
            row = tk.Frame(self._game_editor, bg=CARD)
            row.pack(fill="x", pady=2)
            sw = ColorSwatch(row, tuple(role.get("color", (255, 255, 255))),
                             command=lambda k=rk: self._pick_role_color(k))
            sw.pack(side="left")
            tk.Label(row, text=role.get("label", rk), bg=CARD, fg=TEXT,
                     font=(FONT, 9, "bold")).pack(side="left", padx=(6, 0))
            for f, _ in (("name", "NAME"), ("box", "BOX"), ("tracer", "TRACER")):
                fv = tk.BooleanVar(value=bool(role.get(f, True)))
                t = Toggle(row, value=fv.get())
                t.command = lambda k=rk, ff=f, v=fv, tg=t: (
                    v.set(tg.get()),
                    self.games[self._game_key]["roles"][k].__setitem__(ff, v.get()))
                t.pack(side="right", padx=(4, 0))

        tk.Label(self._game_editor,
                 text="Roles update ~every {}s from each player's team and "
                      "inventory.".format(
                          float(self.esp.get("role_refresh_s", 2.0))),
                 bg=CARD, fg=MUTED, font=(FONT, 8)).pack(anchor="w", pady=(10, 0))

    def _pick_role_color(self, rk):
        current = self.games[self._game_key]["roles"][rk].get("color", [255, 255, 255])
        rgb, _ = colorchooser.askcolor(color=_to_hex(tuple(current)),
                                       parent=self.root,
                                       title="Pick {}".format(rk))
        if rgb:
            self.games[self._game_key]["roles"][rk]["color"] = [int(c) for c in rgb]
            self._build_game_editor()

    def _build_footer(self, parent=None):
        parent = parent or self.root
        foot = tk.Frame(parent, bg=BG)
        foot.pack(fill="x", padx=18, pady=(6, 16))
        save_btn = AccentButton(foot, "SAVE", command=self._save, filled=True,
                                width=160, height=36)
        save_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
        close_btn = AccentButton(foot, "CLOSE", command=self._close, filled=False,
                                 width=120, height=36)
        close_btn.pack(side="right", expand=True, fill="x", padx=(6, 0))
        ver = tk.Label(parent, text="v{}".format(config.APP_VERSION), bg=BG,
                       fg=MUTED, font=(FONT, 8))
        ver.pack(side="bottom", anchor="e", padx=(0, 22), pady=(0, 4))

    def _build_profiles(self, parent):
        card = Card(parent, "Config profiles")
        self._stagger(card)
        tk.Label(card.body,
                 text="Save snapshots of your ESP / colors / read-rate / HUD "
                      "settings and switch between them instantly. Everything "
                      "except game presets is captured.",
                 bg=CARD, fg=MUTED, font=(FONT, 8), justify="left",
                 wraplength=540).pack(anchor="w", fill="x")

        save_row = tk.Frame(card.body, bg=CARD)
        save_row.pack(fill="x", pady=(12, 10))
        tk.Label(save_row, text="Name", bg=CARD, fg=TEXT,
                 font=(FONT, 9, "bold")).pack(side="left")
        self.profile_name = tk.Entry(save_row, bg=INPUT, fg=TEXT,
                                     insertbackground=TEXT, relief="flat", bd=0,
                                     font=(FONT, 9), highlightthickness=1,
                                     highlightbackground=GHOST_BORDER)
        self.profile_name.pack(side="left", padx=(10, 0), ipady=4, ipadx=6,
                               fill="x", expand=True)
        btn = AccentButton(save_row, "SAVE CURRENT AS", command=self._save_profile,
                           filled=True, width=170, height=30)
        btn.pack(side="left", padx=(10, 0))

        self._profile_list = tk.Frame(card.body, bg=CARD)
        self._profile_list.pack(fill="x")
        self._build_profile_list()
        self._add_reset_button(card.body, "profiles")

    def _build_profile_list(self):
        for w in self._profile_list.winfo_children():
            w.destroy()
        names = profile_names()
        if not names:
            tk.Label(self._profile_list, text="No saved configs yet - name one "
                     "above and hit SAVE CURRENT AS.",
                     bg=CARD, fg=MUTED, font=(FONT, 8)).pack(anchor="w", pady=(4, 0))
            return
        for name in names:
            row = tk.Frame(self._profile_list, bg=CARD)
            row.pack(fill="x", pady=(0, 6))
            tk.Label(row, text=name, bg=CARD, fg=TEXT,
                     font=(FONT, 9, "bold")).pack(side="left")
            del_btn = AccentButton(row, "DELETE", command=lambda n=name: self._delete_profile(n),
                                   filled=False, width=72, height=26)
            del_btn.pack(side="right")
            load_btn = AccentButton(row, "LOAD", command=lambda n=name: self._load_profile(n),
                                    filled=True, width=72, height=26)
            load_btn.pack(side="right", padx=(0, 6))

    def _capture_profile(self):
        return {
            "esp": dict(self.esp),
            "colors": {k: list(v) for k, v in self.colors.items()},
            "stealth": dict(self.stealth),
            "hud": dict(self.hud) if self.hud else {},
        }

    def _save_profile(self):
        name = self.profile_name.get().strip()
        if not name:
            return
        profile_save(name, self.esp, self.colors, self.stealth, self.hud)
        self._save()
        self.profile_name.delete(0, "end")
        self._build_profile_list()

    def _load_profile(self, name):
        data = _profiles.get(name)
        if not data:
            return
        for section, target in (("esp", self.esp), ("stealth", self.stealth)):
            for k, v in data.get(section, {}).items():
                if k in target:
                    target[k] = v
        for k, v in data.get("colors", {}).items():
            if k in self.colors:
                self.colors[k] = tuple(v)
        if self.hud is not None:
            for k, v in data.get("hud", {}).items():
                if k in self.hud:
                    self.hud[k] = v
        self._retheme()

    def _delete_profile(self, name):
        profile_delete(name)
        self._save()
        self._build_profile_list()


    def _fade_in(self, alpha):
        alpha = min(1.0, alpha + 0.1)
        self.root.attributes("-alpha", alpha)
        self.root.update_idletasks()
        if alpha < 1.0:
            self.root.after(STEP_MS, lambda: self._fade_in(alpha))

    def _grow_accent(self, step=0):
        steps = 12
        e = self._ease_out((step + 1) / float(steps))
        w = int(348 * e)
        self.underline.coords(self.underline.find_all()[0], 0, 0, w, 2)
        if step + 1 < steps:
            self.underline.after(STEP_MS, lambda: self._grow_accent(step + 1))

    def _pulse_glow(self, phase):
        glow = getattr(self, "_glow", None)
        if glow is None:
            return
        r = 6 + int(2 * phase)
        glow.coords(glow.find_all()[0], 2 - (r - 6), 2 - (r - 6),
                    12 + (r - 6), 12 + (r - 6))
        self._glow.after(700, lambda: self._pulse_glow(1.0 - phase))


    def _set_bool(self, key, value):
        self.esp[key] = bool(value)

    def _on_max_dist_slide(self, _=None):
        v = int(round(self.max_distance.get()))
        self.esp["max_distance"] = v
        self.max_dist_field.set(v)

    def _on_dead_box_slide(self, _=None):
        v = max(0.2, min(1.0, self.dead_box.get()))
        self.esp["dead_box_scale"] = v
        self.dead_val.config(text="{}%".format(int(round(v * 100.0))))

    def _on_dead_trace_slide(self, _=None):
        v = max(0.1, min(1.0, self.dead_tracer.get()))
        self.esp["dead_tracer_scale"] = v
        self.dead_tval.config(text="{}%".format(int(round(v * 100.0))))

    def _on_item_range_slide(self, _=None):
        v = int(round(max(25.0, min(1000.0, self.item_range.get()))))
        self.esp["item_distance"] = v

    def _set_max_distance(self, value):
        v = max(100, min(5000, int(round(value))))
        self.esp["max_distance"] = v
        self.max_distance.set(v)
        self.max_dist_field.set(v)

    def _pick_units(self, unit):
        self.units.set(unit)
        self.esp["distance_units"] = unit
        for u, b in self.unit_buttons.items():
            b.select(u == unit)

    def _on_hz_slide(self, _=None):
        v = int(round(self.update_hz.get()))
        self.stealth["update_hz"] = v
        self.hz_field.set(v)

    def _set_hz_value(self, value):
        v = max(30, min(240, int(round(value))))
        self.stealth["update_hz"] = v
        self.update_hz.set(v)
        self.hz_field.set(v)

    def _set_humanize(self):
        value = bool(self.humanize_var.get())
        self.stealth["humanize"] = value
        if value:
            self.stealth["hz_min"] = float(self.stealth.get("hz_min", 90.0))
            self.stealth["hz_max"] = float(self.stealth.get("hz_max", 144.0))

    def _save(self):
        if save(self.esp, self.colors, self.stealth, self.theme, self.hud,
                aim_cfg=self.aim):
            print("[i] Settings saved to settings.json")
        else:
            print("[!] Failed to save settings.")

    def _close(self):
        self._save()
        self._cancel_afters()
        _close_requested.set()
        self.root.destroy()

    def _toggle_visible(self):
        global _visible
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            _visible = True
        else:
            self.root.withdraw()
            _visible = False

    def _cancel_afters(self):
        """Cancel every pending interp-level ``after`` timer.

        ``after`` timers live on the Tcl interpreter, not the widget, and are
        held by the UI thread's Tcl state. If any are still pending when the
        process exits, they get torn down from the main thread and Tcl
        aborts with "async handler deleted by the wrong thread". Cancelling
        them here, from the UI thread, keeps process exit clean.
        """
        try:
            for name in self.root.tk.splitlist(self.root.tk.call("after", "info")):
                self.root.tk.call("after", "cancel", name)
        except Exception:
            pass

    def _pick_color(self, key):
        current = self.colors.get(key, (255, 255, 255))
        rgb, _ = colorchooser.askcolor(color=_to_hex(current), parent=self.root,
                                       title="Pick {}".format(key))
        if rgb:
            self.colors[key] = tuple(int(c) for c in rgb)
            self.color_buttons[key].set_color(self.colors[key])


def start(esp_cfg, colors_cfg, stealth_cfg, hud_cfg=None, games_cfg=None,
          aim_cfg=None):
    global _ui_thread
    _shutdown.clear()
    _close_requested.clear()
    _ui_thread = threading.Thread(target=_run,
                                  args=(esp_cfg, colors_cfg, stealth_cfg,
                                        hud_cfg, games_cfg, aim_cfg),
                                  daemon=True, name="SettingsUI")
    _ui_thread.start()
    return _ui_thread


def stop(timeout=2.0):
    _shutdown.set()
    if _ui_thread is not None:
        _ui_thread.join(timeout)


def quit_requested():
    return _close_requested.is_set()


def _run(esp_cfg, colors_cfg, stealth_cfg, hud_cfg=None, games_cfg=None,
         aim_cfg=None):
    global _settings_hwnd, _window_open
    try:
        _trace("thread start")
        root = tk.Tk()
        _trace("root created")
        _settings_hwnd = root.winfo_id()
        SettingsWindow(root, esp_cfg, colors_cfg, stealth_cfg, hud_cfg,
                       games_cfg, aim_cfg)
        _trace("window built, entering mainloop")
        try:
            root.after_idle(lambda: _apply_icon(root))
        except Exception:
            pass
        _window_open = True
        root.mainloop()
        _window_open = False
        _trace("mainloop exited")
    except Exception:
        import traceback as _tb
        _tb.print_exc()
        print("[ui] Settings window could not be opened - see traceback above.")
