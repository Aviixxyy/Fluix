import os
import subprocess
import sys








ICON = "fluix.ico"


def build(name, console):
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--icon", ICON, "--name", name, "main.py"]
    if not console:
        cmd.append("--windowed")
    print("==> building {} (console={})".format(name, console))
    subprocess.check_call(cmd)
    src = os.path.join("dist", name)
    if not os.path.isdir(src):
        src = src + ".exe"
    print("==> done: {}".format(os.path.abspath(src)))


if __name__ == "__main__":
    build("Fluix", console=True)
    build("FluixGUI", console=False)
