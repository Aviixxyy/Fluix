import ctypes
import sys
import threading
import time
from ctypes import wintypes as wt

import config
import esp
import memory
import offsets
import overlay as overlay_mod
import roblox
import stats
import status
import themes
import updater

PM_REMOVE = 0x0001
HWND_TOPMOST = ctypes.c_void_p(-1)


def _enable_ansi():
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _print_launcher():
    _enable_ansi()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    name = themes.active()
    metas = themes.meta(name)
    a = themes.ansi(name)
    print()
    print("  " + a["title"] + "Fluix Launcher" + a["reset"])
    print()
    fg = {0: "", 1: a["dim"], 2: a["white"], 3: a["grey"]}
    for row in themes.make_ascii(metas["shape"], seed=7, bg_p=0.20):
        s = "\x1b[40m"
        for bits, kind in row:
            s += fg[kind] + (chr(0x2800 + bits) if bits else " ") + "\x1b[40m"
        print(s + a["reset"])
    print()


def find_game_window(pid):
    found = []

    def cb(hwnd, lparam):
        if overlay_mod.user32.IsWindowVisible(hwnd):
            wpid = wt.DWORD()
            overlay_mod.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                length = overlay_mod.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    overlay_mod.user32.GetWindowTextW(hwnd, buf, length + 1)
                    found.append((hwnd, buf.value))
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(cb)
    overlay_mod.user32.EnumWindows(callback, 0)
    if not found:
        return 0
    found.sort(key=lambda item: len(item[1]), reverse=True)
    return found[0][0]


def _pump_messages():
    msg = wt.MSG()
    while overlay_mod.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
        overlay_mod.user32.TranslateMessage(ctypes.byref(msg))
        overlay_mod.user32.DispatchMessageW(ctypes.byref(msg))


_key_prev = {}


def _pressed(vk):
    """Return True only on the rising edge of a key press."""
    state = bool(overlay_mod.user32.GetAsyncKeyState(vk) & 0x8000)
    prev = _key_prev.get(vk, False)
    _key_prev[vk] = state
    return state and not prev


def _is_settings_window(hwnd):
    if not hwnd:
        return False
    wpid = wt.DWORD()
    overlay_mod.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
    return wpid.value == ctypes.windll.kernel32.GetCurrentProcessId()


def _flush_key():
    time.sleep(0.25)


def _health_color(colors, ratio):
    low = colors["health_low"]
    high = colors["health_full"]
    r = int(low[0] + (high[0] - low[0]) * ratio)
    g = int(low[1] + (high[1] - low[1]) * ratio)
    b = int(low[2] + (high[2] - low[2]) * ratio)
    return (r, g, b)


def _draw_corners(overlay, left, top, right, bottom, color, ratio=0.25, width=1):
    length = min(right - left, bottom - top) * ratio
    for x1, y1, x2, y2 in (
        (left, top, left + length, top),
        (left, top, left, top + length),
        (right - length, top, right, top),
        (right, top, right, top + length),
        (left, bottom - length, left, bottom),
        (left, bottom, left + length, bottom),
        (right - length, bottom, right, bottom),
        (right, bottom - length, right, bottom),
    ):
        overlay.line(x1, y1, x2, y2, color, width)


def _draw_healthbar(overlay, entry, left, top, box_h, colors):
    bw = 3.0
    bx1 = left - bw - 2.0
    bx2 = left - 2.0
    by1 = top
    by2 = top + box_h
    ratio = 0.0
    if entry["max_health"] > 0:
        ratio = max(0.0, min(1.0, entry["health"] / entry["max_health"]))
    overlay.fill_rect(bx1, by1, bx2, by2, colors["health_bg"])
    if ratio > 0:
        fill_h = box_h * ratio
        overlay.fill_rect(bx1, by2 - fill_h, bx2, by2, _health_color(colors, ratio))
    overlay.frame_rect(bx1, by1, bx2, by2, colors["health_border"])


def _format_distance(studs, units):
    if studs is None:
        return ""
    if units == "feet":
        return "{}ft".format(int(round(studs * 0.9186)))
    if units == "meters":
        return "{}m".format(int(round(studs * 0.28)))
    return "{} studs".format(int(round(studs)))


def _draw_entities(overlay, snap, esp_cfg, colors, vw, vh, game_cfg=None):
    cam = snap["camera"]
    if not cam:
        return
    local_team = snap.get("local_team", "")
    height = esp_cfg.get("character_height", 5.0)
    ratio = esp_cfg.get("hrp_ratio", 0.45)
    foot_off = height * ratio
    head_off = height - foot_off

    target = None


    no_highlight = bool(game_cfg and game_cfg.get("no_closest_highlight", False))
    if esp_cfg.get("highlight_target", True) and not no_highlight:
        for entry in snap["entries"]:
            if entry.get("health", 1.0) <= 0.0:
                continue
            if entry.get("is_local"):
                continue
            d = entry.get("distance")
            if d is None:
                continue
            if target is None or d < target.get("distance", 1e18):
                target = entry

    for entry in snap["entries"]:
        pos = entry["pos"]
        extents = entry.get("extents")
        if extents:
            foot = (pos[0], extents[0], pos[2])
            head = (pos[0], extents[1], pos[2])
        else:
            foot = (pos[0], pos[1] - foot_off, pos[2])
            head = (pos[0], pos[1] + head_off, pos[2])

        dead = bool(entry.get("health", 1.0) <= 0.0)
        fade = bool(esp_cfg.get("fade_dead", True)) and dead
        teammate = bool(local_team and entry.get("team") == local_team)
        dead_color = colors.get("dead", (125, 125, 138))
        role = entry.get("role")
        rrole = game_cfg["roles"].get(role) if (game_cfg and role) else None

        show_tracer = bool(rrole.get("tracer", True)) if rrole \
            else bool(esp_cfg.get("tracers", False))
        if show_tracer:
            te = roblox.tracer_endpoint(pos, cam, vw, vh)
            if te:
                is_tgt = bool(target is not None and entry is target)
                if fade:
                    scale = max(0.1, min(1.0,
                                         float(esp_cfg.get("dead_tracer_scale", 0.55))))
                    overlay.line(vw / 2.0, vh / 2.0,
                                 vw / 2.0 + (te[0] - vw / 2.0) * scale,
                                 vh / 2.0 + (te[1] - vh / 2.0) * scale,
                                 colors.get("dead_tracer", dead_color), 1)
                else:
                    if rrole:
                        tracer_color = tuple(rrole.get("color", colors["tracer_enemy"]))
                    else:
                        tracer_color = (colors["tracer_teammate"] if teammate
                                        else colors["tracer_enemy"])
                    if is_tgt:
                        tracer_color = colors.get("highlight", (139, 92, 246))
                    overlay.line(vw / 2.0, vh / 2.0, te[0], te[1], tracer_color,
                                 2 if is_tgt else 1)

        pf = roblox.world_to_screen(foot, cam, vw, vh)
        ph = roblox.world_to_screen(head, cam, vw, vh)
        if not pf or not ph:
            continue

        top = min(pf[1], ph[1])
        bottom = max(pf[1], ph[1])
        box_h = bottom - top
        if box_h < esp_cfg.get("min_box_height", 4.0):
            continue

        box_w = box_h * esp_cfg.get("box_width_ratio", 0.5)
        left = pf[0] - box_w / 2.0
        right = pf[0] + box_w / 2.0

        is_target = bool(target is not None and entry is target)
        if fade:
            scale = max(0.2, min(1.0, float(esp_cfg.get("dead_box_scale", 0.5))))
            mid_y = (top + bottom) * 0.5
            box_h *= scale
            box_w *= scale
            top = mid_y - box_h * 0.5
            bottom = mid_y + box_h * 0.5
            left = pf[0] - box_w * 0.5
            right = pf[0] + box_w * 0.5
            box_color = dead_color
            name_color = dead_color
            use_corners = True
        else:
            if rrole:
                box_color = tuple(rrole.get("color", colors["box_enemy"]))
                name_color = box_color
                use_corners = esp_cfg.get("box_corners", False)
            else:
                box_color = colors["box_teammate"] if teammate else colors["box_enemy"]
                name_color = colors["name_teammate"] if teammate else colors["name_enemy"]
                use_corners = esp_cfg.get("box_corners", False)

        if esp_cfg.get("box", True) and (rrole is None or rrole.get("box", True)):
            if use_corners:
                _draw_corners(overlay, left, top, right, bottom, box_color)
            else:
                overlay.frame_rect(left, top, right, bottom, box_color)

        if esp_cfg.get("healthbar", True) and not fade:
            _draw_healthbar(overlay, entry, left, top, box_h, colors)

        if is_target:
            highlight_color = colors.get("highlight", (139, 92, 246))
            _draw_corners(overlay, left - 6, top - 6, right + 6, bottom + 6,
                          highlight_color, ratio=0.3, width=2)
            _draw_corners(overlay, left - 2, top - 2, right + 2, bottom + 2,
                          highlight_color, ratio=0.3, width=1)
            name_color = highlight_color

        if esp_cfg.get("name", True) and (rrole is None or rrole.get("name", True)) \
                and entry.get("name"):
            overlay.text_outlined(pf[0] - 400, top - 15, entry["name"],
                                  name_color, colors["shadow"], center=True)

        dist_color = name_color if rrole else colors["distance"]
        if esp_cfg.get("distance", True) and entry.get("distance") is not None:
            overlay.text_outlined(pf[0] - 400, bottom + 2,
                                  _format_distance(entry["distance"],
                                                   esp_cfg.get("distance_units", "studs")),
                                  dist_color, colors["shadow"], center=True)

        if esp_cfg.get("tool", False) and entry.get("tool"):
            overlay.text_outlined(pf[0] - 400, bottom + 18, entry["tool"],
                                  colors["tool"], colors["shadow"], center=True)

    if esp_cfg.get("item_esp", True):
        item_color = colors.get("item", (0, 200, 255))
        for item in snap.get("items", []):
            p = roblox.world_to_screen(item["pos"], cam, vw, vh)
            if not p:
                continue
            label = item["name"]
            if esp_cfg.get("distance", True) and item.get("distance") is not None:
                label += " " + _format_distance(item["distance"],
                                                esp_cfg.get("distance_units", "studs"))
            r = 4
            overlay.line(p[0] - r, p[1], p[0] + r, p[1], item_color, 1)
            overlay.line(p[0], p[1] - r, p[0], p[1] + r, item_color, 1)
            overlay.text_outlined(p[0] - 400, p[1] + 8, label,
                                  item_color, colors["shadow"], center=True)




VK_LBUTTON = 0x01
VK_MENU = 0x12
HUD_ORDER = ("fps", "ping", "players")
HUD_KEYS_TEXT = {
    "fps": "FPS",
    "ping": "PING",
    "players": "PLAYERS",
}


def _shade(color, amt):
    return tuple(max(0, min(255, int(round(c + amt)))) for c in color)


def _dot_rect(r):
    return (r[0] + r[2] - 16, r[1] + 4, 12, 12)


def _draw_hud(overlay, hud, state):
    if not hud.get("enabled"):
        return
    bg = tuple(hud.get("bg", (18, 20, 26)))
    border = tuple(hud.get("border", (139, 92, 246)))
    text_c = tuple(hud.get("text", (236, 234, 242)))
    size = {0: 11, 1: 13, 2: 15}.get(hud.get("font_size", 1), 13)
    labels = hud.get("show_title", True)
    layout = hud.get("layout", {})
    edit = bool(state.get("edit"))
    fps = state.get("fps", 0.0)
    ping = state.get("ping")
    players = state.get("players", 0)

    values = {
        "fps": str(int(round(fps))),
        "ping": "{}ms".format(ping) if ping is not None else "--",
        "players": str(players),
    }

    for key in HUD_ORDER:
        r = layout.get(key)
        if not r:
            continue
        enabled = hud.get(key, False)
        if not enabled and not edit:
            continue
        x, y, w, h = r
        if enabled:
            bg_c, border_c, value = bg, border, values[key]
        else:
            bg_c, border_c, value = _shade(bg, -6), _shade(border, -70), "--"
        overlay.fill_rect(x, y, x + w, y + h, bg_c)
        if state.get("drag_key") == key:
            overlay.frame_rect(x, y, x + w, y + h, border_c)
            overlay.frame_rect(x + 1, y + 1, x + w - 1, y + h - 1, border_c)
        else:
            overlay.frame_rect(x, y, x + w, y + h, border_c)
        cy = y + 2
        if labels:
            overlay.text_outlined(x + 6, cy, HUD_KEYS_TEXT[key], text_c,
                                  (20, 20, 20), size=max(8, size - 3))
            cy += max(8, size - 3) + 1
        overlay.text_outlined(x + 6, cy, value, text_c,
                              (20, 20, 20), size=size)
        grip = border_c
        overlay.line(x + w - 8, y + h - 1, x + w - 1, y + h - 1, grip, 1)
        overlay.line(x + w - 1, y + h - 8, x + w - 1, y + h - 1, grip, 1)
        if edit:
            dx, dy, dw, dh = _dot_rect(r)
            if enabled:
                overlay.fill_rect(dx, dy, dx + dw, dy + dh, border)
                overlay.frame_rect(dx, dy, dx + dw, dy + dh, _shade(border, -60))
            else:
                overlay.fill_rect(dx, dy, dx + dw, dy + dh, _shade(bg, 8))
                overlay.frame_rect(dx, dy, dx + dw, dy + dh, _shade(border, -60))


def _cursor_in_client(target_hwnd):
    pt = wt.POINT()
    overlay_mod.user32.GetCursorPos(ctypes.byref(pt))
    origin = wt.POINT(0, 0)
    overlay_mod.user32.ClientToScreen(target_hwnd, ctypes.byref(origin))
    return pt.x - origin.x, pt.y - origin.y


def _snap_box(rect, others, vw, vh, snap=8):
    x, y, w, h = rect[0], rect[1], rect[2], rect[3]
    best = snap
    bdx = bdy = 0
    for o in others:
        for kx in (o[0], o[0] + o[2]):
            for mx in (x, x + w):
                d = kx - mx
                if d and abs(d) <= best:
                    best = abs(d)
                    bdx = d
                    bdy = 0
        for ky in (o[1], o[1] + o[3]):
            for my in (y, y + h):
                d = ky - my
                if d and abs(d) <= best:
                    best = abs(d)
                    bdx = 0
                    bdy = d
    x = max(0, min(vw - w, x + bdx))
    y = max(0, min(vh - h, y + bdy))
    return [x, y, w, h]


_drag = {"active": False, "key": None, "mode": None, "ox": 0, "oy": 0, "base": None}


def _poll_hud_interaction(target_hwnd, hud, vw, vh):
    global _drag
    if not hud.get("enabled"):
        _drag = dict(_drag, active=False)
        return
    alt = bool(overlay_mod.user32.GetAsyncKeyState(VK_MENU) & 0x8000)
    down = bool(overlay_mod.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
    layout = hud.get("layout", {})
    keys = [k for k in HUD_ORDER if layout.get(k)]

    if _drag["active"] and (not alt or not down):
        _drag["active"] = False
        return

    x, y = _cursor_in_client(target_hwnd)

    if alt and _pressed(VK_LBUTTON) and not _drag["active"]:
        for key in keys:
            dx, dy, dw, dh = _dot_rect(layout[key])
            if dx <= x <= dx + dw and dy <= y <= dy + dh:
                hud[key] = not hud.get(key, False)
                return

    if not _drag["active"] and alt and down:
        for key in reversed(keys):
            r = layout[key]
            if r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]:
                mode = ("resize" if (x >= r[0] + r[2] - 16
                                     and y >= r[1] + r[3] - 16) else "move")
                _drag.update(active=True, key=key, mode=mode,
                             ox=x, oy=y, base=list(r))
                break

    if _drag["active"]:
        key = _drag["key"]
        r = layout[key]
        dx = x - _drag["ox"]
        dy = y - _drag["oy"]
        if _drag["mode"] == "move":
            r[0] = max(0, min(vw - r[2], r[0] + dx))
            r[1] = max(0, min(vh - r[3], r[1] + dy))
            others = [layout[k] for k in keys if k != key]
            snapped = _snap_box(r, others, vw, vh)
            r[0], r[1], r[2], r[3] = snapped
        else:
            r[2] = max(64, min(vw - r[0], _drag["base"][2] + dx))
            r[3] = max(22, min(vh - r[1], _drag["base"][3] + dy))
        _drag["ox"] = x
        _drag["oy"] = y


def main():
    overlay_mod.user32.SetProcessDPIAware()
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetConsoleTitleW(config.CONSOLE_TITLE)
    except Exception:
        pass

    try:
        themes.apply(themes.active())
    except Exception:
        pass

    _print_launcher()

    mem = memory.MemoryReader()
    if not mem.open(config.PROCESS_NAME):
        print("[!] Could not open Roblox process '{}'.".format(config.PROCESS_NAME))
        print("    Start Roblox and be inside a game, then run again.")
        print("    Run this script with the same privilege level as Roblox.")
        return 1

    print("[+] Process: pid={} base=0x{:X}".format(mem.pid, mem.base))

    offsets_data = offsets.load(config.OFFSETS)
    offs = offsets_data["data"]

    stats_finder = stats.Finder(mem)

    reader = esp.EspReader(mem, offs, config.ESP, config.STEALTH, config.GAMES)
    reader.start()
    status.set(esp=True)

    ui_mod = None
    try:
        import ui as ui_mod
        if ui_mod.load(config.ESP, config.COLORS, config.STEALTH, config.HUD,
                       config.GAMES):
            print("[i] Loaded saved settings.")
        ui_mod.start(config.ESP, config.COLORS, config.STEALTH, config.HUD,
                     config.GAMES)
        print("[i] Settings window opened.")
    except Exception as exc:
        print("[i] Settings UI unavailable ({}).".format(exc))

    print("[i] Controls: F8 = toggle ESP   F7 = settings   END = quit")

    game_hwnd = 0
    overlay = None
    running = True
    esp_enabled = True
    last_pid = mem.pid

    hud = config.HUD
    hud_state = {"fps": 0.0, "ping": None, "players": 0, "edit": False,
                 "hint": "", "hint_until": 0.0, "drag_key": None}
    fps_frames = 0
    fps_t0 = time.monotonic()
    stats_started = False
    stats_ready_at = 0.0

    update_state = {"quit": False}

    def _updater_thread():
        try:
            result = updater.check_for_update()
            if not result:
                return
            version, url = result
            print("[i] Update v{} found - downloading...".format(version))
            if updater.apply_update(version, url):
                updater.notify(version)
                update_state["quit"] = True
        except Exception:
            pass

    u_cfg = config.UPDATE
    if (u_cfg.get("enabled", True) and updater.frozen()
            and u_cfg.get("github_user") and u_cfg.get("github_repo")):
        threading.Thread(target=_updater_thread, daemon=True).start()

    def _stats_done():
        if stats_finder.state == "done":
            status.log("[i] Stats scan done: fps_addr=0x{:X} ping_addr=0x{:X}".format(
                stats_finder.fps_addr, stats_finder.ping_addr))
        else:
            status.log("[i] Stats scan failed - using overlay metrics.")

    overlay_mod.user32.IsWindow.argtypes = [wt.HWND]
    overlay_mod.user32.IsWindow.restype = wt.BOOL
    overlay_mod.user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    overlay_mod.user32.GetCursorPos.restype = wt.BOOL

    while running:
        if update_state["quit"]:
            running = False
            break
        if _pressed(config.KEYS["quit"]):
            running = False
        if _pressed(config.KEYS["toggle"]):
            esp_enabled = not esp_enabled
            status.set(esp=esp_enabled)
            status.log("[i] ESP {}".format("enabled" if esp_enabled else "disabled"))
            hud_state["hint"] = "ESP {}  -  F8 toggles  |  END quits".format(
                "enabled" if esp_enabled else "disabled")
            hud_state["hint_until"] = time.monotonic() + 2.5

        if ui_mod is not None and _pressed(config.KEYS.get("settings", 0)):
            ui_mod.request_toggle()

        if not mem.alive():
            if mem.reopen():
                stats_finder.invalidate()
                status.log("[i] Roblox restarted - re-attached to pid={} base=0x{:X}".format(
                    mem.pid, mem.base))
            else:
                status.log("[!] Roblox closed - exiting.")
                break

        if not game_hwnd or not overlay_mod.user32.IsWindow(game_hwnd) or mem.pid != last_pid:
            if overlay:
                overlay.destroy()
                overlay = None
            game_hwnd = 0
        last_pid = mem.pid

        if not game_hwnd:
            game_hwnd = find_game_window(mem.pid)
            if game_hwnd:
                overlay = overlay_mod.Overlay(game_hwnd)
                if overlay.create():
                    status.log("[+] Overlay window created.")
                    hud_state["hint"] = ("F8 toggles ESP  |  END quits  |  "
                                         "hold Alt + drag to move/resize the HUD")
                    hud_state["hint_until"] = time.monotonic() + 8.0
                    stats_ready_at = time.monotonic() + 2.0
                else:
                    status.log("[!] Failed to create overlay window.")
                    overlay = None
                    game_hwnd = 0

        if not overlay:
            time.sleep(0.5)
            continue

        fg = overlay_mod.user32.GetForegroundWindow()
        if fg != game_hwnd and not _is_settings_window(fg):
            overlay.hide()
            time.sleep(0.05)
            continue

        if not overlay.sync():
            time.sleep(0.05)
            continue

        _pump_messages()

        snap = reader._snap()
        frame_now = time.monotonic()
        fps_frames += 1
        if frame_now - fps_t0 >= 1.0:
            hud_state["fps"] = fps_frames / (frame_now - fps_t0)
            fps_frames = 0
            fps_t0 = frame_now
        stats_fps = stats_finder.fps()
        if stats_fps is not None:
            hud_state["fps"] = stats_fps
        if not stats_started and stats_finder.state == "idle" and frame_now >= stats_ready_at:
            stats_started = True
            stats_finder.scan_async(offsets_data["version"],
                                    on_done=_stats_done,
                                    fps_hint=lambda: hud_state.get("fps") or None)
        stats_ping = stats_finder.ping()
        hud_state["ping"] = stats_ping if stats_ping is not None else snap.get("ping")
        hud_state["players"] = snap.get("server_players", 0)
        hud_state["edit"] = bool(overlay_mod.user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        hud_state["drag_key"] = _drag["key"] if _drag["active"] else None
        _poll_hud_interaction(game_hwnd, hud, overlay.w, overlay.h)
        if frame_now >= hud_state["hint_until"]:
            hud_state["hint"] = ""

        overlay.begin()
        try:
            if esp_enabled:
                game = snap.get("game")
                game_cfg = config.GAMES.get(game) if game else None
                _draw_entities(overlay, snap, config.ESP, config.COLORS,
                               overlay.w, overlay.h, game_cfg)
            if hud_state["hint"]:
                overlay.text_outlined(overlay.w / 2.0, 6, hud_state["hint"],
                                      (236, 234, 242), (20, 20, 20),
                                      center=True, size=13)
            _draw_hud(overlay, hud, hud_state)
        finally:
            overlay.end()

        time.sleep(0.004)

    if overlay:
        overlay.destroy()
    reader.stop()
    mem.close()
    try:
        import ui
        ui.save(config.ESP, config.COLORS, config.STEALTH, hud=config.HUD,
                games=config.GAMES)
    except Exception:
        pass
    try:
        import ui
        ui.stop()
    except Exception:
        pass
    status.clear()
    print("Bye.")
    return 0


if __name__ == "__main__":
    import os as _os
    import sys as _sys
    _code = main()
    try:
        _sys.stdout.flush()
        _sys.stderr.flush()
    except Exception:
        pass
    _os._exit(_code)
