import json
import os
import urllib.request

BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offsets_bundled.json")


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
        try:
            remote = _fetch(cfg.get("fetch_url"), cfg.get("fetch_timeout", 8))
            if isinstance(remote, dict) and remote.get("Offsets"):
                data = remote["Offsets"]
                source = "remote (https://offsets.imtheo.lol)"
                version = remote.get("Roblox Version", version)
                print("[i] Offsets: {} | version {}".format(source, version))
            else:
                print("[i] Remote offsets empty; using bundled offsets.")
        except Exception as exc:
            print("[i] Offsets fetch failed ({}); using bundled offsets.".format(exc))
            print("[i] Bundled version: {}".format(version))

    return {"data": data, "version": version, "source": source}
