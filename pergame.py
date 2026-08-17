import json
import os

import config

_SECTIONS = ("esp", "colors", "stealth", "hud", "aimbot")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


class PergameStore:
    def __init__(self, esp_cfg, colors_cfg, stealth_cfg, hud_cfg, aim_cfg):
        self._path = os.path.join(config.app_dir(), "settings.json")
        self._targets = {
            "esp": esp_cfg,
            "colors": colors_cfg,
            "stealth": stealth_cfg,
            "hud": hud_cfg,
            "aimbot": aim_cfg,
        }
        self._base = self._snapshot()
        self._store = {}
        self._active = None
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        self._loaded = True
        data = _read(self._path)
        store = data.get("per_game") or {}
        for gid, sections in store.items():
            if not isinstance(sections, dict):
                continue
            clean = {}
            for sec, values in sections.items():
                if sec not in self._targets or not isinstance(values, dict):
                    continue
                clean[sec] = {k: v for k, v in values.items() if k in self._targets[sec]}
            self._store[gid] = clean

    def _snapshot(self):
        snap = {}
        for sec, cfg in self._targets.items():
            snap[sec] = dict(cfg)
        return snap

    def _apply(self, gid):
        base = self._base
        for sec, cfg in self._targets.items():
            for k, v in base[sec].items():
                cfg[k] = v
        overrides = self._store.get(gid)
        if overrides:
            for sec, cfg in self._targets.items():
                for k, v in overrides.get(sec, {}).items():
                    if k in cfg:
                        cfg[k] = v

    def on_game_change(self, game_id):
        gid = str(game_id) if game_id else ""
        if gid and gid == self._active:
            return
        prev = self._active
        if prev:
            self._store[prev] = self._snapshot()
        self._active = gid or None
        if gid:
            self._apply(gid)
            self._persist()

    def close(self):
        if self._active:
            self._store[self._active] = self._snapshot()
        self._persist()

    def _persist(self):
        data = _read(self._path)
        data["per_game"] = self._store
        _write(self._path, data)

    def dump(self):
        return dict(self._store)


_store = None


def create_store(esp_cfg, colors_cfg, stealth_cfg, hud_cfg, aim_cfg):
    global _store
    _store = PergameStore(esp_cfg, colors_cfg, stealth_cfg, hud_cfg, aim_cfg)
    return _store


def get_store():
    return _store
