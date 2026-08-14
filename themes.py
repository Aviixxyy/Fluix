"""Theme system for Fluix.

Each theme pairs a minimal icon (white motif on an accent rounded square)
with a matching braille ASCII motif (white dotted line art over sparse
accent-colored background dots), mirroring the original Fluix wave.

Geometry for every shape lives in braille-pixel space (x 0..192, y 0..64).
The same data drives both the ASCII art and the regenerated icon, so the
launcher splash, the settings preview and the tray/titlebar icon stay in
sync per theme.
"""

import json
import math
import os
import random

from PIL import Image, ImageDraw

_DIR = os.path.dirname(os.path.abspath(__file__))
PNG_PATH = os.path.join(_DIR, "fluix.png")
ICO_PATH = os.path.join(_DIR, "fluix.ico")
SETTINGS_PATH = os.path.join(_DIR, "settings.json")

SIZE = 256
BW, BH = 96, 16
BWX, BHY = BW * 2, BH * 4

DEFAULT = "fluix"

WHITE = (255, 255, 255, 255)
SNOW = (224, 230, 242, 255)





def _rgb_to_ansi256(r, g, b):
    r, g, b = max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b)))
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round((r - 8) / 247 * 24) + 232
    c = [0 if x < 48 else 1 if x < 115 else 2 if x < 155 else 3 if x < 195 else 4 if x < 235 else 5
         for x in (r, g, b)]
    return 16 + 36 * c[0] + 6 * c[1] + c[2]


def _ansi_fg(rgb):
    return "\x1b[38;5;{}m".format(_rgb_to_ansi256(*rgb))


def _dim_rgb(rgb, f=0.55):
    return tuple(int(c * f) for c in rgb)





def _polyline(fn, n=90):
    return [fn(i / n) for i in range(n + 1)]


def _arc(cx, cy, r, a0, a1, n):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def _ellipse_outline(cx, cy, rx, ry, rot, n=120):
    pts = []
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        dx, dy = rx * math.cos(a), ry * math.sin(a)
        pts.append((cx + dx * math.cos(rot) - dy * math.sin(rot),
                    cy + dx * math.sin(rot) + dy * math.cos(rot)))
    return pts


SHAPES = {
    "wave": {
        "lines": [_polyline(
            lambda t, t_=None: (6.0 + 184.0 * t,
                                32.0 + 15.0 * math.sin(2 * math.pi * 3.0 * t)), n=140)],
        "discs": [],
    },
    "mountain": {
        "lines": [
            [(40.0, 50.0), (48.0, 45.0), (56.0, 40.0), (64.0, 45.0), (72.0, 35.0),
             (80.0, 42.0), (88.0, 28.0), (96.0, 12.0), (104.0, 30.0), (112.0, 40.0),
             (120.0, 34.0), (128.0, 44.0), (136.0, 42.0), (144.0, 47.0), (152.0, 50.0)],
            [(40.0, 50.0), (152.0, 50.0)],
        ],
        "snow": [
            [(85.0, 22.0), (90.0, 15.0), (95.0, 19.0), (99.0, 15.0), (104.0, 22.0)],
        ],
        "discs": [],
    },
    "orbit": {
        "lines": [_ellipse_outline(96.0, 32.0, 42.0, 15.0, math.radians(24))],
        "discs": [(84.0, 18.0, 3.0)],
    },
}





def _braille_bit(r, c):
    if c == 0:
        return (1, 2, 4, 64)[r]
    return (8, 16, 32, 128)[r]


def _hit_lines(polylines, hw=1.0, cell=8):
    """Spatial-hash hit test so rasterizing many segments stays fast."""
    grid = {}
    segs = []
    for poly in polylines:
        for a, b in zip(poly, poly[1:]):
            segs.append((a, b))
    for a, b in segs:
        xmin, xmax = min(a[0], b[0]) - hw, max(a[0], b[0]) + hw
        ymin, ymax = min(a[1], b[1]) - hw, max(a[1], b[1]) + hw
        for cy in range(int(ymin // cell), int(ymax // cell) + 1):
            for cx in range(int(xmin // cell), int(xmax // cell) + 1):
                grid.setdefault((cx, cy), []).append((a, b))

    def hit(px, py):
        for (ax, ay), (bx, by) in grid.get((px // cell, py // cell), ()):
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            if l2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
                d = math.hypot(px - (ax + dx * t), py - (ay + dy * t))
            if d <= hw:
                return True
        return False

    return hit


def _hit_shape(sd, hw=1.0):
    """Returns hit(px, py) -> 0 none, 1 accent dot, 2 white motif, 3 snow."""
    motif = _hit_lines(sd["lines"], hw)
    snow = _hit_lines(sd.get("snow", []), hw) if sd.get("snow") else None
    discs = sd["discs"]

    def hit(px, py):
        if motif(px, py):
            return 2
        for cx, cy, r in discs:
            if math.hypot(px - cx, py - cy) <= r:
                return 2
        if snow is not None and snow(px, py):
            return 3
        return 0

    return hit


def make_ascii(shape, seed=7, bg_p=0.20):
    """Rows of (bits, kind): kind 0 empty, 1 accent bg dot, 2 white motif,
    3 snow/detail."""
    hit = _hit_shape(SHAPES[shape])
    rng = random.Random(seed)
    rows = []
    for by in range(BH):
        row = []
        for bx in range(BW):
            wbits = 0
            sbits = 0
            for r in range(4):
                for c in range(2):
                    k = hit(2 * bx + c, 4 * by + r)
                    if k == 2:
                        wbits |= _braille_bit(r, c)
                    elif k == 3:
                        sbits |= _braille_bit(r, c)
            if wbits:
                row.append((wbits, 2))
                continue
            if sbits:
                row.append((sbits, 3))
                continue
            bbits = 0
            for r in range(4):
                for c in range(2):
                    if rng.random() < bg_p:
                        bbits |= _braille_bit(r, c)
            row.append((bbits, 1) if bbits else (0, 0))
        rows.append(row)
    return rows


def make_preview_png(shape, accent_rgb, scale=6):
    """Render the braille motif to a bitmap (white on accent dots) for the
    settings preview without the overhead/wrapping of a text widget."""
    rows = make_ascii(shape, seed=7, bg_p=0.20)
    w, h = BW * scale, BH * scale
    img = Image.new("RGBA", (w, h), (18, 19, 23, 255))
    d = ImageDraw.Draw(img)
    dc = max(1, scale // 2)
    dr = max(1, scale // 4)
    motif = (245, 245, 245, 255)
    snow = (226, 232, 242, 255)
    bg = _dim_rgb(accent_rgb, 0.45) + (255,)
    for by, row in enumerate(rows):
        for bx, (bits, kind) in enumerate(row):
            if not bits:
                continue
            if kind == 2:
                col = motif
            elif kind == 3:
                col = snow
            else:
                col = bg
            for r in range(4):
                for c in range(2):
                    if bits & _braille_bit(r, c):
                        d.rectangle([bx * scale + c * dc, by * scale + r * dr,
                                     bx * scale + (c + 1) * dc, by * scale + (r + 1) * dr],
                                    fill=col)
    return img





def _icon_transform(lines, margin=40):
    pts = [p for poly in lines for p in poly]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = x1 - x0, y1 - y0
    scale = min((SIZE - 2 * margin) / w, (SIZE - 2 * margin) / h)
    ox = SIZE / 2.0 - (x0 + x1) / 2.0 * scale
    oy = SIZE / 2.0 - (y0 + y1) / 2.0 * scale
    return scale, ox, oy


def _map_polys(polylines, margin=40):
    """Remap braille-space geometry into the 256 icon square preserving aspect."""
    scale, ox, oy = _icon_transform(polylines, margin)
    return [[(p[0] * scale + ox, p[1] * scale + oy) for p in poly] for poly in polylines]


def _map_point_list(cx, cy, r, lines, margin=40):
    scale, ox, oy = _icon_transform(lines, margin)
    return cx * scale + ox, cy * scale + oy, max(1.5, r * scale)


def render_icon(shape, accent_rgb, size=SIZE):
    accent = tuple(int(c) for c in accent_rgb) + (255,)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 10
    d.rounded_rectangle([m, m, size - m, size - m], radius=int(size * 0.22), fill=accent)

    sd = SHAPES[shape]
    polys = _map_polys(sd["lines"])

    if shape == "wave":
        d.line(polys[0], fill=WHITE, width=22, joint="curve")
    elif shape == "mountain":
        ridge, base = polys
        d.polygon(ridge + [base[-1], base[0]], fill=WHITE)
        for poly in _map_polys(sd.get("snow", [])):
            d.line(poly, fill=SNOW, width=5, joint="curve")
    elif shape == "orbit":
        d.line(polys[0], fill=WHITE, width=12, joint="curve")
        for disc in sd["discs"]:
            cx, cy, r = _map_point_list(*disc, sd["lines"])
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    return img


def _map_disc(cx, cy, r, lines):
    """Translate/scale a disc using the same transform as the polylines."""
    pts = [p for poly in lines for p in poly]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = x1 - x0, y1 - y0
    scale = min((SIZE - 2 * 40) / w, (SIZE - 2 * 40) / h)
    ox = SIZE / 2.0 - (x0 + x1) / 2.0 * scale
    oy = SIZE / 2.0 - (y0 + y1) / 2.0 * scale
    return cx * scale + ox, cy * scale + oy, r * scale





THEMES = {
    "fluix": {"shape": "wave", "accent": (139, 92, 246), "title": "Fluix"},
    "slate": {"shape": "mountain", "accent": (130, 150, 180), "title": "Slate"},
    "orbit": {"shape": "orbit", "accent": (70, 180, 170), "title": "Orbit"},
}


def active():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("theme", DEFAULT)
        if name not in THEMES:
            name = DEFAULT
    except Exception:
        name = DEFAULT
    return name


def meta(name):
    return THEMES.get(name, THEMES[DEFAULT])


def apply(name, png=PNG_PATH, ico=ICO_PATH):
    if name not in THEMES:
        name = DEFAULT
    m = THEMES[name]
    img = render_icon(m["shape"], m["accent"])
    img.save(png)
    img.save(ico, format="ICO",
             sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    return m


def ansi(name):
    m = meta(name)
    accent = tuple(m["accent"])
    return {
        "title": _ansi_fg(accent),
        "dim": _ansi_fg(_dim_rgb(accent, 0.55)),
        "white": _ansi_fg((245, 245, 245)),
        "grey": _ansi_fg((199, 205, 216)),
        "reset": "\x1b[0m",
    }
