import config
import json
import os
import threading
import urllib.request

BUNDLED = os.path.join(config.bundle_dir(), "offsets_bundled.json")


def _load_bundled():
    with open(BUNDLED, "r", encoding="utf-8") as f:
        return json.load(f)


def _fetch(url, timeout):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load(cfg):
    bundled = _load_bundled()
    data = bundled.get("offsets", bundled)
    source = bundled.get("source", "bundled")
    version = bundled.get("roblox_version", "unknown")

    if cfg.get("auto_fetch", True):

        def _fetch_remote():
            try:
                remote = _fetch(cfg.get("fetch_url"), cfg.get("fetch_timeout", 8))
                if isinstance(remote, dict) and remote.get("Offsets"):
                    data.clear()
                    data.update(remote["Offsets"])
                    print("[i] Offsets: remote | version {}".format(
                        remote.get("Roblox Version", version)))
                else:
                    print("[i] Remote offsets empty; using bundled offsets.")
            except Exception as exc:
                print("[i] Offsets fetch failed ({}); using bundled offsets.".format(exc))

        threading.Thread(target=_fetch_remote, daemon=True,
                         name="OffsetFetch").start()

    return {"data": data, "version": version, "source": source}
