import ctypes
import math
import random
import sys
import threading
import time
import traceback
from ctypes import wintypes as wt

import config
import esp
import memory
import offsets
import overlay as overlay_mod
import pergame
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
        (right, bottom, right, bottom - length),
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

    ents = snap["entries"]
    if game_cfg and game_cfg.get("max_esp_entries") is not None:
        cap = int(game_cfg["max_esp_entries"] or 0)
    else:
        cap = int(esp_cfg.get("max_esp_entries", 0) or 0)
    if cap > 0 and len(ents) > cap:
        enemies = []
        mates = []
        for e in ents:
            if e.get("is_local"):
                continue
            (mates if (local_team and e.get("team") == local_team)
             or e.get("forced_teammate") else enemies).append(e)
        enemies.sort(key=lambda e: e.get("distance") or 1e18)
        if len(enemies) > cap:
            enemies = enemies[:cap]
        ents = enemies + mates

    for entry in ents:
        pos = entry["pos"]
        extents = entry.get("extents")
        if extents:
            foot_y = pos[1] + extents[0]
            head_y = pos[1] + extents[1]
        else:
            foot_y = pos[1] - foot_off
            head_y = pos[1] + head_off
        world_h = max(0.1, head_y - foot_y)
        mid = (pos[0], (foot_y + head_y) * 0.5, pos[2])
        dead = bool(entry.get("health", 1.0) <= 0.0)
        fade = bool(esp_cfg.get("fade_dead", True)) and dead
        teammate = bool(local_team and entry.get("team") == local_team) \
            or bool(entry.get("forced_teammate"))
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
                    if te[2]:
                        _draw_arrowhead(overlay, vw / 2.0, vh / 2.0,
                                        te[0], te[1], tracer_color)

        pr = roblox.project_vertical(cam, mid, world_h, vw, vh)
        if not pr:
            continue
        px, mid_y, box_h = pr
        if box_h < esp_cfg.get("min_box_height", 4.0):
            continue
        box_w = box_h * esp_cfg.get("box_width_ratio", 0.5)
        top = mid_y - box_h * 0.5
        bottom = mid_y + box_h * 0.5
        left = px - box_w * 0.5
        right = px + box_w * 0.5

        is_target = bool(target is not None and entry is target)
        if fade:
            scale = max(0.2, min(1.0, float(esp_cfg.get("dead_box_scale", 0.5))))
            mid_y = (top + bottom) * 0.5
            box_h *= scale
            box_w *= scale
            top = mid_y - box_h * 0.5
            bottom = mid_y + box_h * 0.5
            left = px - box_w * 0.5
            right = px + box_w * 0.5
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

        occl = bool(esp_cfg.get("occlusion", False))
        if entry.get("occluded"):
            box_color = _mix(box_color, (220, 220, 220), 0.45)
            name_color = _mix(name_color, (220, 220, 220), 0.45)
        elif occl:
            box_color = colors["box_enemy"]
            name_color = colors["name_enemy"]

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
            overlay.text_outlined(px - 400, top - 15, entry["name"],
                                  name_color, colors["shadow"], center=True)

        dist_color = name_color if rrole else colors["distance"]
        if esp_cfg.get("distance", True) and entry.get("distance") is not None:
            overlay.text_outlined(px - 400, bottom + 2,
                                  _format_distance(entry["distance"],
                                                   esp_cfg.get("distance_units", "studs")),
                                  dist_color, colors["shadow"], center=True)

        if esp_cfg.get("tool", False) and entry.get("tool"):
            overlay.text_outlined(px - 400, bottom + 18, entry["tool"],
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

_aim = {"active": False, "angle": 0.0, "last_ts": 0.0, "lock": None,
        "lock_id": None, "moving": False, "last_move": (0, 0),
        "override_until": 0.0, "lock_ts": 0.0, "over_cnt": 0,
        "prev_dd": None, "drift_cnt": 0, "rem_x": 0.0, "rem_y": 0.0,
        "sx": None, "sy": None, "settled": False, "psx": None, "psy": None,
        "vx": 0.0, "vy": 0.0}

_cur = {"x": 0.0, "y": 0.0}

_OVERRIDE_VEL = 4000.0
_OVERRIDE_FRAMES = 2
_OVERRIDE_LOCK_S = 0.12
_FP_CAM_DIST = 5.0
_LOCK_STUDS = 2.5
_LOCK_KEEP = 1.2
_SNAP_BOOST = 2.5
_SNAP_WINDOW = 0.12
_LOCK_TRACK = 1.4
_MAX_MOVE = 6.0
_LOCK_DEAD = 4.0
_DRIFT_EPS = 2.0
_DRIFT_FRAMES = 3
_RELEASE_PAUSE = 0.15


def _client_origin(hwnd):
    pt = wt.POINT(0, 0)
    overlay_mod.user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return (float(pt.x), float(pt.y))


def _check_override(hwnd, dt, frame_now, first_person):
    global _cur
    pt = wt.POINT()
    overlay_mod.user32.GetCursorPos(ctypes.byref(pt))
    ox, oy = _client_origin(hwnd)
    nx = float(pt.x) - ox
    ny = float(pt.y) - oy
    raw_dx = nx - _cur["x"]
    raw_dy = ny - _cur["y"]
    _cur["x"] = nx
    _cur["y"] = ny
    if first_person:
        return
    udx = raw_dx
    udy = raw_dy
    if _aim.get("moving") and _aim.get("last_move"):
        lx, ly = _aim["last_move"]
        udx -= lx
        udy -= ly
    if dt > 0 and math.hypot(udx, udy) / dt > _OVERRIDE_VEL:
        _aim["over_cnt"] = _aim.get("over_cnt", 0) + 1
    else:
        _aim["over_cnt"] = 0
    if _aim.get("over_cnt", 0) >= _OVERRIDE_FRAMES:
        _aim["active"] = False
        _aim["lock"] = None
        _aim["lock_id"] = None
        _aim["over_cnt"] = 0
        _aim["override_until"] = frame_now + _OVERRIDE_LOCK_S


def _aim_center(cam, anchor, vw, vh):
    if cam and anchor:
        dx = cam.pos[0] - anchor[0]
        dy = cam.pos[1] - anchor[1]
        dz = cam.pos[2] - anchor[2]
        if math.sqrt(dx * dx + dy * dy + dz * dz) < _FP_CAM_DIST:
            return (vw / 2.0, vh / 2.0, True)
    return (_cur["x"], _cur["y"], False)


def _acquire(cand):
    _aim["drift_cnt"] = 0
    _aim["prev_dd"] = None
    if _aim.get("lock") is None or math.hypot(
            cand[2][0] - _aim["lock"][0],
            cand[2][1] - _aim["lock"][1],
            cand[2][2] - _aim["lock"][2]) > _LOCK_STUDS:
        _aim["lock_ts"] = time.monotonic()
    _aim["lock"] = cand[2]
    _aim["lock_id"] = cand[3] if len(cand) > 3 else None


def _aim_target(snap, aim_cfg, esp_cfg, vw, vh, center, cursor_priority=False):
    global _aim
    cam = snap.get("camera")
    if not cam:
        return None
    local_team = snap.get("local_team", "")
    team_check = bool(esp_cfg.get("team_check", True))
    max_dist = float(aim_cfg.get("max_distance", 300.0))
    fov = float(aim_cfg.get("fov_px", 250.0))
    aim_at = aim_cfg.get("target", "head")
    height = float(esp_cfg.get("character_height", 5.0))
    ratio = float(esp_cfg.get("hrp_ratio", 0.45))
    cx = center[0]
    cy = center[1]
    lock_keep = max(0.5, float(aim_cfg.get("lock_keep", 1.2)))
    threat_first = bool(aim_cfg.get("threat_first", True))
    threat_cos = math.cos(math.radians(
        max(1.0, float(aim_cfg.get("threat_fov_deg", 14.0)))))
    fallback_closest = bool(aim_cfg.get("fallback_closest", True))
    lock = _aim.get("lock")
    lock_id = _aim.get("lock_id")
    best = None
    best_d = fov
    lock_cand = None
    lock_cand_id = None
    lock_dd = None
    threat = None
    threat_dd = None
    far = None
    far_d = None
    cam_pos = cam.pos
    shooter = snap.get("local_pos") or cam_pos
    for e in snap.get("entries", []):
        if e.get("is_local") or not e.get("alive", True):
            continue
        if e.get("forced_teammate"):
            continue
        if team_check and local_team and e.get("team") == local_team:
            continue
        d = e.get("distance")
        if d is None or d > max_dist:
            continue
        eid = e.get("id")
        pos = e["pos"]
        ext = e.get("extents")
        if aim_at == "torso":
            if ext:
                py = pos[1] + (ext[0] + ext[1]) * 0.5
            else:
                py = pos[1] + height * 0.5
        else:
            hp = e.get("head")
            if hp:
                py = hp[1]
            elif ext:
                py = pos[1] + (ext[0] + ext[1]) * 0.5
            else:
                py = pos[1] + height - height * ratio
        wp = (pos[0], py, pos[2])
        sp = roblox.world_to_screen(wp, cam, vw, vh)
        if not sp:
            continue
        dd = math.hypot(sp[0] - cx, sp[1] - cy)
        if threat_first:
            lk = e.get("look")
            if lk:
                vx = shooter[0] - wp[0]
                vy = shooter[1] - wp[1]
                vz = shooter[2] - wp[2]
                vd = math.sqrt(vx * vx + vy * vy + vz * vz)
                if vd > 2.0:
                    dot = (lk[0] * vx + lk[1] * vy + lk[2] * vz) / vd
                    if dot >= threat_cos and (
                            threat is None or dd < threat_dd):
                        threat = (sp[0], sp[1], wp, eid)
                        threat_dd = dd
        if fallback_closest:
            if far is None or d < far_d:
                far = (sp[0], sp[1], wp, eid)
                far_d = d
        if lock_id is not None and eid == lock_id:
            if dd <= fov * lock_keep:
                lock_cand = (sp[0], sp[1], wp, eid)
                lock_dd = dd
        elif lock and eid is None:
            ldx = wp[0] - lock[0]
            ldy = wp[1] - lock[1]
            ldz = wp[2] - lock[2]
            if math.hypot(ldx, ldy, ldz) <= _LOCK_STUDS and dd <= fov * lock_keep:
                lock_cand = (sp[0], sp[1], wp, eid)
                lock_dd = dd
        if dd <= best_d:
            best_d = dd
            best = (sp[0], sp[1], wp, eid)
    if cursor_priority and best is not None:
        deadzone = float(aim_cfg.get("cursor_deadzone", 0.35)) * fov
        if best_d <= deadzone:
            if _aim.get("lock_id") is not None and best[3] != _aim.get("lock_id"):
                _aim["lock"] = None
                _aim["lock_id"] = None
            _acquire(best)
            return (best[0], best[1])
    if threat is not None:
        _acquire(threat)
        return (threat[0], threat[1])
    if lock_cand is not None:
        prev = _aim.get("prev_dd")
        if prev is not None and lock_dd > prev + _DRIFT_EPS:
            _aim["drift_cnt"] = _aim.get("drift_cnt", 0) + 1
        else:
            _aim["drift_cnt"] = 0
        _aim["prev_dd"] = lock_dd
        if _aim["drift_cnt"] >= _DRIFT_FRAMES:
            _aim["lock"] = None
            _aim["lock_id"] = None
            _aim["drift_cnt"] = 0
            _aim["prev_dd"] = None
            _aim["override_until"] = time.monotonic() + _RELEASE_PAUSE
            return None
        _acquire(lock_cand)
        return (lock_cand[0], lock_cand[1])
    if best is not None:
        if (lock_id is not None and best[3] is not None and best[3] != lock_id
                and best_d <= fov * 0.85):
            _aim["lock"] = None
            _aim["lock_id"] = None
        _acquire(best)
        return (best[0], best[1])
    if fallback_closest and far is not None:
        _acquire(far)
        return (far[0], far[1])
    _aim["lock"] = None
    _aim["lock_id"] = None
    _aim["drift_cnt"] = 0
    _aim["prev_dd"] = None
    return None


def _aim_tick(dt, point, aim_cfg, cx, cy):
    global _aim
    if point is None:
        _aim["active"] = False
        _aim["moving"] = False
        _aim["last_move"] = (0, 0)
        _aim["rem_x"] = 0.0
        _aim["rem_y"] = 0.0
        _aim["settled"] = False
        _aim["psx"] = None
        _aim["psy"] = None
        _aim["vx"] = 0.0
        _aim["vy"] = 0.0
        return
    locked = _aim.get("lock") is not None
    tau = 0.025 if locked else 0.012
    kp = 1.0 - math.exp(-dt / tau)
    sx = _aim.get("sx")
    if sx is None:
        sx = float(point[0])
        sy = float(point[1])
    else:
        sx += (point[0] - sx) * kp
        sy = _aim.get("sy", point[1])
        sy += (point[1] - sy) * kp
    _aim["sx"] = sx
    _aim["sy"] = sy
    dist_s = math.hypot(sx - cx, sy - cy)
    tx = sx
    ty = sy
    pdt = max(dt, 0.003)
    psx = _aim.get("psx")
    if locked and psx is not None:
        ivx = (sx - psx) / pdt
        ivy = (_aim.get("psy", sy) - sy) / pdt
        vx = _aim.get("vx", 0.0) * 0.8 + ivx * 0.2
        vy = _aim.get("vy", 0.0) * 0.8 + ivy * 0.2
        _aim["vx"] = vx
        _aim["vy"] = vy
        cl = max(0.0, dist_s) * 0.3
        tx = sx + max(-cl, min(cl, vx * 0.02))
        ty = sy + max(-cl, min(cl, vy * 0.02))
    _aim["psx"] = sx
    _aim["psy"] = sy
    dx = tx - cx
    dy = ty - cy
    dist = math.hypot(dx, dy)
    if locked:
        if dist < _LOCK_DEAD:
            _aim["active"] = False
            _aim["moving"] = False
            _aim["last_move"] = (0, 0)
            _aim["rem_x"] = 0.0
            _aim["rem_y"] = 0.0
            _aim["psx"] = None
            _aim["psy"] = None
            _aim["vx"] = 0.0
            _aim["vy"] = 0.0
            return
        _aim["settled"] = False
    else:
        settle = 2.0
        if _aim.get("settled"):
            if dist < settle + 1.0:
                _aim["active"] = False
                _aim["moving"] = False
                _aim["last_move"] = (0, 0)
                _aim["rem_x"] = 0.0
                _aim["rem_y"] = 0.0
                _aim["psx"] = None
                _aim["psy"] = None
                _aim["vx"] = 0.0
                _aim["vy"] = 0.0
                return
            _aim["settled"] = False
        if dist < settle:
            _aim["settled"] = True
            _aim["active"] = False
            _aim["moving"] = False
            _aim["last_move"] = (0, 0)
            _aim["rem_x"] = 0.0
            _aim["rem_y"] = 0.0
            _aim["psx"] = None
            _aim["psy"] = None
            _aim["vx"] = 0.0
            _aim["vy"] = 0.0
            return
    if not _aim["active"]:
        _aim["active"] = True
        _aim["angle"] = random.uniform(-1.0, 1.0)
    ux = dx / dist
    uy = dy / dist
    curve = float(aim_cfg.get("curve", 0.5))
    orbit = max(1.0, float(aim_cfg.get("orbit_radius", 60.0)))
    speed = max(0.02, float(aim_cfg.get("speed", 0.06)))
    k = max(0.0, min(1.0, dist / orbit))
    if not locked:
        _aim["angle"] += random.uniform(-1.0, 1.0) * 0.05 * k
        _aim["angle"] *= 0.95
        spin = _aim["angle"] * curve * k * 0.4
        cos = math.cos(spin)
        sin = math.sin(spin)
        rx = ux * cos - uy * sin
        ry = ux * sin + uy * cos
    else:
        rx = ux
        ry = uy
    alpha = min(1.0, dt / speed)
    if locked:
        alpha = min(1.0, alpha * _LOCK_TRACK)
    elif time.monotonic() - _aim.get("lock_ts", 0.0) < _SNAP_WINDOW:
        alpha = min(1.0, alpha * _SNAP_BOOST)
    move = min(dist * alpha, _MAX_MOVE)
    if locked:
        stutter = 0.0
    else:
        stutter = max(0.0, float(aim_cfg.get("stutter", 3.0))) * k * k * 0.15
    fx = rx * move + random.uniform(-stutter, stutter)
    fy = ry * move + random.uniform(-stutter, stutter)
    rem_x = _aim.get("rem_x", 0.0) + fx
    rem_y = _aim.get("rem_y", 0.0) + fy
    mx = int(round(rem_x))
    my = int(round(rem_y))
    _aim["rem_x"] = rem_x - mx
    _aim["rem_y"] = rem_y - my
    _send_mouse_move(mx, my)
    _aim["moving"] = bool(mx or my)
    _aim["last_move"] = (mx, my)


def _send_mouse_move(dx, dy):
    mi = overlay_mod.MOUSEINPUT()
    mi.dx = int(dx)
    mi.dy = int(dy)
    mi.mouseData = 0
    mi.dwFlags = overlay_mod.MOUSEEVENTF_MOVE
    mi.time = 0
    mi.dwExtraInfo = None
    inp = overlay_mod.INPUT()
    inp.type = overlay_mod.INPUT_MOUSE
    inp.mi = mi
    overlay_mod.user32.SendInput(1, ctypes.byref(inp),
                                 ctypes.sizeof(overlay_mod.INPUT))


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def _press_mouse(flags):
    mi = overlay_mod.MOUSEINPUT()
    mi.dx = 0
    mi.dy = 0
    mi.mouseData = 0
    mi.dwFlags = flags
    mi.time = 0
    mi.dwExtraInfo = None
    inp = overlay_mod.INPUT()
    inp.type = overlay_mod.INPUT_MOUSE
    inp.mi = mi
    overlay_mod.user32.SendInput(1, ctypes.byref(inp),
                                 ctypes.sizeof(overlay_mod.INPUT))


_click_lock = threading.Lock()


def _send_click():
    def _fire():
        if not _click_lock.acquire(blocking=False):
            return
        try:
            _press_mouse(MOUSEEVENTF_LEFTDOWN)
            time.sleep(random.uniform(0.014, 0.026))
            _press_mouse(MOUSEEVENTF_LEFTUP)
        finally:
            _click_lock.release()
    threading.Thread(target=_fire, daemon=True).start()


def _seg_hits_rect(x0, y0, x1, y1, l, t, r, b):
    dx = x1 - x0
    dy = y1 - y0
    t0 = 0.0
    t1 = 1.0
    for p, q in ((-dx, x0 - l), (dx, r - x0),
                 (-dy, y0 - t), (dy, b - y0)):
        if p == 0.0:
            if q < 0.0:
                return False
        else:
            u = q / p
            if p < 0.0:
                if u > t1:
                    return False
                if u > t0:
                    t0 = u
            else:
                if u < t0:
                    return False
                if u < t1:
                    t1 = u
    return t0 <= t1


def _trigger_hit(snap, esp_cfg, vw, vh, center, prev=None, pad=1.15):
    cam = snap.get("camera")
    if not cam:
        return False
    local_team = snap.get("local_team", "")
    team_check = bool(esp_cfg.get("team_check", True))
    max_dist = float(esp_cfg.get("max_distance", 1500.0))
    height = float(esp_cfg.get("character_height", 5.0))
    ratio = float(esp_cfg.get("hrp_ratio", 0.45))
    min_h = float(esp_cfg.get("min_box_height", 4.0))
    wr = float(esp_cfg.get("box_width_ratio", 0.5))
    cx = center[0]
    cy = center[1]
    for e in snap.get("entries", []):
        if e.get("is_local") or not e.get("alive", True):
            continue
        if e.get("health", 1.0) <= 0.0:
            continue
        if e.get("forced_teammate"):
            continue
        if team_check and local_team and e.get("team") == local_team:
            continue
        d = e.get("distance")
        if d is None or d > max_dist:
            continue
        pos = e["pos"]
        ext = e.get("extents")
        if ext:
            foot_y = pos[1] + ext[0]
            head_y = pos[1] + ext[1]
        else:
            foot_y = pos[1] - height * ratio
            head_y = pos[1] + height - height * ratio
        world_h = max(0.1, head_y - foot_y)
        mid = (pos[0], (foot_y + head_y) * 0.5, pos[2])
        pr = roblox.project_vertical(cam, mid, world_h, vw, vh)
        if not pr:
            continue
        px, mid_y, box_h = pr
        if box_h < min_h:
            continue
        box_w = max(box_h * wr, min_h * wr)
        hw = box_w * 0.5 * pad
        hh = box_h * 0.5 * pad
        if prev is None:
            hit = abs(cx - px) <= hw and abs(cy - mid_y) <= hh
        else:
            hit = _seg_hits_rect(prev[0], prev[1], cx, cy,
                                 px - hw, mid_y - hh, px + hw, mid_y + hh)
        if hit:
            return True
    return False


def _shade(color, amt):
    return tuple(max(0, min(255, int(round(c + amt)))) for c in color)


def _draw_arrowhead(overlay, ox, oy, ex, ey, color):
    dx = ex - ox
    dy = ey - oy
    m = math.hypot(dx, dy)
    if m < 1e-3:
        return
    ux = dx / m
    uy = dy / m
    px = -uy
    py = ux
    size = 9.0
    spread = 5.0
    bx = ex - ux * size
    by = ey - uy * size
    overlay.line(ex, ey, bx + px * spread, by + py * spread, color, 2)
    overlay.line(ex, ey, bx - px * spread, by - py * spread, color, 2)


def _mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


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

    u_cfg = config.UPDATE
    if (u_cfg.get("enabled", True) and updater.frozen()
            and u_cfg.get("github_user") and u_cfg.get("github_repo")):
        try:
            result = updater.check_for_update()
            if result:
                version, url = result
                print("[i] Update v{} found - downloading...".format(version))
                if updater.apply_update(version, url):
                    updater.notify(version)
                    print("[i] Update staged - restarting to apply.")
                    return 0
        except Exception:
            pass

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

    ui_mod = None
    try:
        import ui as ui_mod
        if ui_mod.load(config.ESP, config.COLORS, config.STEALTH, config.HUD,
                       config.GAMES, config.AIMBOT):
            print("[i] Loaded saved settings.")
        if config.HUD.get("follow_theme", True):
            bg, border, text = themes.hud_palette(themes.active())
            config.HUD["bg"] = list(bg)
            config.HUD["border"] = list(border)
            config.HUD["text"] = list(text)
        ui_mod.start(config.ESP, config.COLORS, config.STEALTH, config.HUD,
                     config.GAMES, config.AIMBOT)
        print("[i] Settings window opened.")
    except Exception as exc:
        print("[i] Settings UI unavailable ({}).".format(exc))

    pergame_store = pergame.create_store(config.ESP, config.COLORS,
                                         config.STEALTH, config.HUD,
                                         config.AIMBOT)
    pergame_store.load()

    reader = esp.EspReader(mem, offs, config.ESP, config.STEALTH, config.GAMES,
                           pergame=pergame_store)
    reader.start()
    status.set(esp=True)

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
    last_frame = time.monotonic()
    stats_started = False
    stats_ready_at = 0.0
    cam_fail = 0
    cam_fail_logged = 0.0
    overlay_hidden = False
    draw_errs = 0

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
    overlay_mod.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    overlay_mod.user32.SetCursorPos.restype = wt.BOOL

    while running:
        if ui_mod is not None and ui_mod.quit_requested():
            running = False
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
        if fg != game_hwnd:
            if not overlay_hidden:
                overlay_hidden = True
                status.log("[ESP-cut] overlay hidden (game window not "
                           "foreground, fg=0x{:X} game=0x{:X})".format(
                               fg or 0, game_hwnd or 0))
            overlay.hide()
            time.sleep(0.05)
            continue
        overlay_hidden = False

        if not overlay.sync():
            time.sleep(0.05)
            continue

        _pump_messages()

        snap = reader._snap()
        frame_now = time.monotonic()
        dt = frame_now - last_frame
        last_frame = frame_now

        cam_addr = snap.get("cam_addr")
        if cam_addr and mem.alive():
            fresh = roblox.read_camera(
                mem, cam_addr, offsets_data, anchor=snap.get("local_anchor"))
            if fresh:
                snap = dict(snap)
                snap["camera"] = fresh
                cam_fail = 0
            else:
                cam_fail += 1
                if cam_fail == 30 and time.monotonic() - cam_fail_logged > 5.0:
                    cam_fail_logged = time.monotonic()
                    status.log("[i] camera read failing ({}/frame) - "
                               "using last good camera".format(cam_fail))
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
        aim_cfg = config.AIMBOT
        cam_snap = snap.get("camera")
        anchor = snap.get("local_anchor")
        aim_center = _aim_center(cam_snap, anchor, overlay.w, overlay.h)
        _check_override(game_hwnd, dt, frame_now, aim_center[2])
        if aim_cfg.get("enabled", False):
            if frame_now < _aim.get("override_until", 0.0):
                aim_on = False
            elif aim_cfg.get("mode", "hold") == "hold":
                aim_on = bool(overlay_mod.user32.GetAsyncKeyState(
                    int(aim_cfg.get("hotkey", 0x45))) & 0x8000)
            else:
                aim_on = bool(overlay_mod.user32.GetAsyncKeyState(VK_LBUTTON)
                              & 0x8000)
            if aim_on:
                snap_game = snap.get("game")
                _cursor_prio = False
                if snap_game:
                    _gc = config.GAMES.get(snap_game)
                    if _gc and _gc.get("aim_cursor_priority", False):
                        _cursor_prio = True
                aim_point = _aim_target(snap, aim_cfg, config.ESP,
                                        overlay.w, overlay.h, aim_center,
                                        cursor_priority=_cursor_prio)
                _aim_tick(dt, aim_point, aim_cfg,
                          aim_center[0], aim_center[1])
            else:
                _aim["active"] = False
        else:
            _aim["active"] = False
        trig_key = int(aim_cfg.get("trigger_hotkey", 0) or 0)
        trig_prev = _aim.get("trig_prev")
        if aim_cfg.get("trigger", False) and trig_key and \
                not bool(overlay_mod.user32.GetAsyncKeyState(VK_LBUTTON)
                         & 0x8000) and \
                bool(overlay_mod.user32.GetAsyncKeyState(trig_key) & 0x8000):
            snap_ts = float(snap.get("ts", 0.0) or 0.0)
            if frame_now - snap_ts <= 0.30 and \
                    frame_now - _aim.get("trig_last", 0.0) >= \
                    max(0.05, float(aim_cfg.get("trigger_interval", 0.18))):
                if _trigger_hit(snap, config.ESP, overlay.w, overlay.h,
                                aim_center, trig_prev,
                                float(aim_cfg.get("trigger_padding",
                                                  1.15))):
                    _send_click()
                    _aim["trig_last"] = frame_now
        _aim["trig_prev"] = (aim_center[0], aim_center[1])
        if frame_now >= hud_state["hint_until"]:
            hud_state["hint"] = ""

        overlay.begin()
        try:
            if esp_enabled:
                game = snap.get("game")
                game_cfg = config.GAMES.get(game) if game else None
                _draw_entities(overlay, snap, config.ESP, config.COLORS,
                               overlay.w, overlay.h, game_cfg)
            if (aim_cfg.get("enabled", False)
                    and aim_cfg.get("show_fov", True)):
                fov_r = max(4.0, float(aim_cfg.get("fov_px", 250.0)))
                overlay.circle(aim_center[0], aim_center[1], fov_r,
                               (139, 92, 246))
            if hud_state["hint"]:
                overlay.text_outlined(overlay.w / 2.0, 6, hud_state["hint"],
                                      (236, 234, 242), (20, 20, 20),
                                      center=True, size=13)
            _draw_hud(overlay, hud, hud_state)
        except Exception:
            draw_errs += 1
            if draw_errs <= 5:
                try:
                    status.log("[DRAW-err] {}\n".format(
                        traceback.format_exc()))
                except Exception:
                    pass
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
                games=config.GAMES, aim_cfg=config.AIMBOT)
    except Exception:
        pass
    try:
        pergame_store.close()
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
