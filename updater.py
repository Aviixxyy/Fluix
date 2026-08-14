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
    return "https://raw.githubusercontent.com/{}/{}/build/{}".format(
        u.get("github_user", ""), u.get("github_repo", ""), name)


def check_for_update():
    """Return (version, download_url) if a newer release exists, else None."""
    try:
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


def _download(url, dest, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)


def apply_update(version, url):
    """Download the new exe and schedule a swap + relaunch on exit.

    The running exe cannot replace itself, so a small hidden batch file polls
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
        bat = os.path.join(tempfile.gettempdir(), "Fluix_update.bat")
        with open(bat, "w", encoding="utf-8") as f:
            f.write(
                "@echo off\r\n"
                "setlocal EnableExtensions\r\n"
                'set "SELF={exe}"\r\n'
                'set "NEW={new}"\r\n'
                ":wait\r\n"
                'copy /y "%NEW%" "%SELF%" >nul 2>&1\r\n'
                "if not errorlevel 1 goto relaunch\r\n"
                "ping -n 2 127.0.0.1 >nul\r\n"
                "goto wait\r\n"
                ":relaunch\r\n"
                'del "%NEW%" >nul 2>&1\r\n'
                'start "" "%SELF%"\r\n'
                "exit\r\n".format(exe=exe, new=new_exe))
        subprocess.Popen(["cmd.exe", "/c", bat],
                         creationflags=0x08000000 | 0x00000008,
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
