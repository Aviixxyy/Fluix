"""Single-line status bar rendered on the terminal.

The EspReader thread and the main loop feed fields into a tiny shared
state; the reader redraws one fixed line in place (carriage return +
erase) so the console isn't spammed with periodic status dumps. Event
messages print through :func:`log`, which keeps the status line intact.

Locking rules: the shared lock is acquired exactly once per call, only
to read/write the tiny fields dict, and never while doing console I/O.
This keeps snapshot/set instant so no other thread (e.g. the settings
window) can ever stall waiting on the terminal.
"""

import sys
import threading

_lock = threading.Lock()
_fields = {
    "attached": None,
    "camera": None,
    "targets": 0,
    "esp": None,
    "waiting": False,
    "message": "",
    "game": "",
    "game_id": 0,
}

_GREEN = "\x1b[32m"
_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"
_GRAY = "\x1b[90m"
_CYAN = "\x1b[96m"
_RESET = "\x1b[0m"


def set(**kw):
    with _lock:
        _fields.update(kw)


def snapshot():
    with _lock:
        return dict(_fields)


def _dot(ok):
    if ok is None:
        return _GRAY + "\u25cf" + _RESET
    return (_GREEN if ok else _RED) + "\u25cf" + _RESET


def _line(fields):
    parts = []
    att = fields["attached"]
    if att is not None or fields.get("waiting"):
        if fields.get("waiting"):
            parts.append("{} attached".format(
                _YELLOW + "\u25cf" + _RESET))
        else:
            parts.append("{} attached: {}".format(
                _dot(att), "yes" if att else "no"))
    if fields["camera"] is not None:
        parts.append("{} camera: {}".format(
            _dot(fields["camera"]),
            "readable" if fields["camera"] else "unreadable"))
    parts.append(_CYAN + "\u2b22" + _RESET + " targets: {}".format(
        fields["targets"]))
    if fields["esp"] is not None:
        parts.append("{} esp: {}".format(
            _dot(fields["esp"]), "on" if fields["esp"] else "off"))
    if fields["game"]:
        gid = fields.get("game_id")
        if gid:
            parts.append(_CYAN + "game: {} ({})".format(fields["game"], gid) + _RESET)
        else:
            parts.append(_CYAN + "game: {}".format(fields["game"]) + _RESET)
    s = "   ".join(parts)
    if fields["message"]:
        s += "   " + _GRAY + fields["message"] + _RESET
    return s


def render():
    fields = _snap()
    sys.stdout.write("\r\x1b[2K" + _line(fields))
    sys.stdout.flush()


def clear():
    sys.stdout.write("\r\x1b[2K")
    sys.stdout.flush()


def log(msg):
    fields = _snap()
    sys.stdout.write("\r\x1b[2K" + msg + "\n")
    sys.stdout.flush()
    sys.stdout.write("\x1b[2K" + _line(fields))
    sys.stdout.flush()


def _snap():
    with _lock:
        return dict(_fields)
