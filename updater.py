import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import config

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Fluix/{}".format(config.APP_VERSION)


def frozen():
    return bool(getattr(sys, "frozen", False))


def current_exe():
    return os.path.abspath(sys.executable)


def compare_versions(a, b):
    """True if version string a is older than b (supports 1.2, 1.2.3, v1.2.3)."""

    def key(v):
        out = []
        for part in str(v).lstrip("v").replace("-", ".").split("."):
            try:
                out.append(int(part))
            except ValueError:
                out.append(0)
        return out

    return key(a) < key(b)


def _api_url():
    u = config.UPDATE
    return "https://api.github.com/repos/{}/{}/releases/latest".format(
        u.get("github_user", ""), u.get("github_repo", ""))


def _fetch_json(url, timeout):
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                              "User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_url(name):
    u = config.UPDATE
    legacy = {"Fluix.exe": "FluixConsole.exe", "FluixGUI.exe": "FluixNoConsole.exe"}
    name = legacy.get(name, name)
    return "https://raw.githubusercontent.com/{}/{}/build/{}".format(
        u.get("github_user", ""), u.get("github_repo", ""), name)


def check_for_update():
    """Return (version, download_url) if a newer release exists, else None."""
    try:
        marker = os.path.join(tempfile.gettempdir(), "Fluix_update_ok.flag")
        pending = os.path.join(tempfile.gettempdir(), "Fluix_update.lock")
        if os.path.exists(marker):
            os.remove(marker)
        elif os.path.exists(pending):
            _warn_failed_update()
            return None

        data = _fetch_json(_api_url(), config.UPDATE.get("check_timeout", 8))
        tag = str(data.get("tag_name") or "")
        if not tag:
            return None
        version = tag.lstrip("v")
        if not compare_versions(config.APP_VERSION, version):
            return None
        return version, _build_url(os.path.basename(current_exe()))
    except Exception:
        return None


def _warn_failed_update():
    """Notify the user that the last update failed to apply."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "A previous Fluix update failed to install.\n\n"
            "Try right-clicking the .exe -> Run as administrator,\n"
            "or move Fluix to a non-OneDrive folder (e.g. C:\\Fluix).",
            "Fluix Update",
            0x00000010 | 0x00001000)
    except Exception:
        pass


def _download(url, dest, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)


def apply_update(version, url):
    """Download the new exe and schedule a swap + relaunch on exit.

    The running exe cannot replace itself, so a small hidden VBScript polls
    until this process is gone, copies the new exe over the old one and starts
    it again. Returns True if the update is staged.
    """
    try:
        exe = current_exe()
        new_exe = os.path.join(tempfile.gettempdir(),
                               "Fluix_{}.exe".format(version.replace(".", "_")))
        _download(url, new_exe, config.UPDATE.get("download_timeout", 120))
        if not os.path.exists(new_exe) or os.path.getsize(new_exe) < 100000:
            return False
        lock = os.path.join(tempfile.gettempdir(), "Fluix_update.lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except OSError:
            return False
        vbs = os.path.join(tempfile.gettempdir(), "Fluix_update.vbs")
        marker = os.path.join(tempfile.gettempdir(), "Fluix_update_ok.flag")
        esc = lambda s: s.replace('"', '""')
        with open(vbs, "w", encoding="utf-8") as f:
            f.write(
                'Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
                'Set sh = CreateObject("WScript.Shell")\r\n'
                'n = 0\r\n'
                'ok = False\r\n'
                'Do\r\n'
                '    On Error Resume Next\r\n'
                '    fso.CopyFile "{new}", "{exe}", True\r\n'
                '    ok = (Err.Number = 0)\r\n'
                '    On Error GoTo 0\r\n'
                '    If ok Then Exit Do\r\n'
                '    WScript.Sleep 1000\r\n'
                '    n = n + 1\r\n'
                '    If n >= 90 Then Exit Do\r\n'
                'Loop\r\n'
                'If ok Then\r\n'
                '    On Error Resume Next\r\n'
                '    fso.DeleteFile "{lock}"\r\n'
                '    On Error GoTo 0\r\n'
                '    Dim f2: Set f2 = fso.CreateTextFile("{marker}", True)\r\n'
                '    f2.Write "ok"\r\n'
                '    f2.Close\r\n'
                '    sh.Run "{exe}", 1, False\r\n'
                'End If\r\n'.format(
                    lock=esc(lock), new=esc(new_exe), exe=esc(exe),
                    marker=esc(marker)))
        subprocess.Popen(["wscript.exe", vbs],
                         creationflags=0x08000000,
                         close_fds=True)
        return True
    except Exception:
        return False


def notify(version):
    """Tell the user an update is being applied (console print + message box)."""
    msg = "Fluix {} downloaded.\n\nRestarting to apply the update.".format(version)
    try:
        print("[i] Update v{} downloaded - restarting to apply.".format(version))
        sys.stdout.flush()
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "Fluix Update",
                                         0x00000040 | 0x00001000)
    except Exception:
        pass
