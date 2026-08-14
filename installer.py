import json
import os
import subprocess
import sys
import tempfile
import urllib.request

REPO = "Aviixxyy/Fluix"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Fluix-Setup"

LAUNCHERS = {
    "Fluix.exe": "Console Fluix (ascii art + status in a terminal)",
    "FluixGUI.exe": "No-console Fluix (silent, GUI only)",
}


def _build_url(name):
    return "https://raw.githubusercontent.com/{}/build/{}".format(REPO, name)


def _fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                              "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url, dest, label):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    sys.stdout.write("\r  {}: {}% ({:.1f} MB)".format(
                        label, int(done * 100 / total), done / 1048576.0))
                    sys.stdout.flush()
    sys.stdout.write("\r  {}: 100% ({:.1f} MB)".format(
        label, os.path.getsize(dest) / 1048576.0))
    sys.stdout.flush()
    print()


def _make_shortcut(target, link):
    try:
        vbs = os.path.join(tempfile.gettempdir(), "fluix_lnk.vbs")
        with open(vbs, "w") as f:
            f.write('Set sh = CreateObject("WScript.Shell")\r\n')
            f.write('Set lnk = sh.CreateShortcut("{}")\r\n'.format(
                link.replace('"', '""')))
            f.write('lnk.TargetPath = "{}"\r\n'.format(
                target.replace('"', '""')))
            f.write('lnk.WorkingDirectory = "{}"\r\n'.format(
                os.path.dirname(target).replace('"', '""')))
            f.write('lnk.Save()\r\n')
        subprocess.run(["cscript", "//nologo", vbs],
                       creationflags=0x08000000, check=True)
        return True
    except Exception:
        return False


def _install_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.environ.get("USERPROFILE", os.getcwd()), "AppData", "Local")
    return os.path.join(base, "Fluix")


def _start_menu_dir():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                        "Start Menu", "Programs", "Fluix")


def _desktop_dir():
    return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")


def _ask_number(prompt, lo, hi):
    while True:
        try:
            n = int(input(prompt).strip())
        except ValueError:
            print("  Type a number between {} and {}.".format(lo, hi))
            continue
        if lo <= n <= hi:
            return n
        print("  Type a number between {} and {}.".format(lo, hi))


def main():
    print("======================================")
    print("          Fluix Installer")
    print("======================================")
    print()
    print("Which launcher do you want?")
    for n, (name, desc) in enumerate(LAUNCHERS.items(), 1):
        print("  {}) {}  [{}]".format(n, desc, name))
    print("  3) Both")
    print()
    choice = _ask_number("Enter 1, 2 or 3: ", 1, 3)
    want = ["Fluix.exe", "FluixGUI.exe"] if choice == 3 else [
        ["Fluix.exe", "FluixGUI.exe"][choice - 1]]

    print()
    print("Where do you want shortcuts?")
    print("  1) Start Menu")
    print("  2) Desktop")
    print("  3) Both")
    print("  4) Neither")
    print()
    sc = _ask_number("Enter 1, 2, 3 or 4: ", 1, 4)
    sc_dirs = []
    if sc in (1, 3):
        sc_dirs.append(_start_menu_dir())
    if sc in (2, 3):
        sc_dirs.append(_desktop_dir())

    install_dir = _install_dir()
    os.makedirs(install_dir, exist_ok=True)

    print()
    print("1) Checking for the latest Fluix release...")
    try:
        data = _fetch_json("https://api.github.com/repos/{}/releases/latest"
                           .format(REPO))
        tag = data.get("tag_name", "?")
    except Exception:
        tag = "?"
    print("   Latest version: {}".format(tag))
    print()

    for name in want:
        print("2) Downloading {}...".format(name))
        dest = os.path.join(install_dir, name)
        try:
            _download(_build_url(name), dest, name)
            print("   Installed to: {}".format(dest))
        except Exception as exc:
            print("   !! Download failed: {}".format(exc))
    print()

    print("3) Creating shortcuts...")
    links = 0
    for name in want:
        exe = os.path.join(install_dir, name)
        if not os.path.exists(exe):
            continue
        for folder in sc_dirs:
            os.makedirs(folder, exist_ok=True)
            if _make_shortcut(exe, os.path.join(folder, name[:-4] + ".lnk")):
                links += 1
    print("   Created {} shortcut(s).".format(links))
    print()

    print("4) Done!")
    print()
    print("   Fluix is installed to: {}".format(install_dir))
    print("   The launchers are self-contained - no Python or other "
          "install needed.")
    print()
    input("Press Enter to close this installer...")
    return 0


if __name__ == "__main__":
    sys.exit(main())