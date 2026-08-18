import math
import random
import threading
import time

import memory
import occlusion
import roblox
import status
import ui


def _classify_role(team, tools, game_cfg):
    """Map a player to a preset role using their team name and owned tools.

    Roles are matched in preset order: first by team keyword, then by any
    owned tool name containing a role weapon keyword. Everyone that matches
    nothing is assigned the preset's catch-all "innocent" role (if defined).
    """
    roles = game_cfg.get("roles", {})
    team_l = (team or "").lower()
    for key, role in roles.items():
        for kw in role.get("teams", []):
            if kw and kw in team_l:
                return key
    for key, role in roles.items():
        weapons = [w for w in role.get("weapons", []) if w]
        if not weapons:
            continue
        for t in tools:
            tl = t.lower()
            for w in weapons:
                if w in tl:
                    return key
    if "innocent" in roles:
        return "innocent"
    return None


class EspReader(threading.Thread):
    def __init__(self, mem, offsets, esp_cfg, stealth_cfg, games_cfg=None,
                 pergame=None):
        super().__init__(daemon=True, name="EspReader")
        self.mem = mem
        self.offs = offsets
        self.esp_cfg = esp_cfg
        self.stealth = stealth_cfg
        self.games_cfg = games_cfg or {}
        self._pergame = pergame
        self._pergame_game = None
        self._occ = None
        self._last_occ = 0.0
        self._lock = threading.Lock()
        self._stop = False
        self._dm = 0
        self._extents = {}
        self._heads = {}
        self._tool_cache = {}
        self._role_cache = {}
        self._warned_no_team = False
        self._waiting = False
        self._last_camera = None
        self._game_names = {}
        self._hz_cur = None
        self._hz_burst = 0
        self._game_name_lookups = {}
        self.snapshot = {
            "camera": None,
            "local_pos": None,
            "local_team": "",
            "entries": [],
            "items": [],
            "ok": False,
            "message": "",
            "server_players": 0,
            "ping": None,
            "game": None,
            "game_id": 0,
            "game_name": "",
            "cam_addr": 0,
            "local_anchor": None,
        }

    def stop(self):
        self._stop = True

    def _snap(self):
        with self._lock:
            return self.snapshot

    def _publish(self, **fields):
        with self._lock:
            self.snapshot.update(fields)

    def _push_status(self, camera=None, targets=0, message="", waiting=None,
                     game=None, game_name="", game_id=0):
        if waiting is None:
            waiting = self._waiting
        status.set(attached=self.mem.alive(), camera=bool(camera),
                   targets=targets, message=message, waiting=waiting,
                   game=game_name, game_id=game_id)

    def run(self):
        update = 0
        last_render = 0.0
        status.set(attached=self.mem.alive())
        while not self._stop:
            now = time.monotonic()
            try:
                self._collect(update)
            except Exception:

                import traceback
                traceback.print_exc()
            update += 1
            if now - last_render >= 0.35:
                last_render = now
                if not ui.is_open():
                    status.render()

            hz = max(float(self.stealth.get("update_hz", 12.0)), 1.0)
            if self.stealth.get("humanize", False):
                lo = max(float(self.stealth.get("hz_min", 60.0)), 1.0)
                hi = max(float(self.stealth.get("hz_max", hz)), lo)
                if self._hz_cur is None or self._hz_burst <= 0:
                    self._hz_cur = random.uniform(lo, hi)
                    self._hz_burst = random.randint(4, 9)
                hz = self._hz_cur
                self._hz_burst -= 1
            jitter = float(self.stealth.get("jitter", 0.4))
            delay = (1.0 / hz) * random.uniform(1.0 - jitter, 1.0 + jitter)
            if random.random() < float(self.stealth.get("skip_chance", 0.0)):
                delay *= random.uniform(2.0, 4.0)
            pause_min = float(self.stealth.get("pause_min", 0.0))
            pause_max = float(self.stealth.get("pause_max", 0.0))
            if pause_max > pause_min:
                delay += random.uniform(pause_min, pause_max)
            delay = max(delay, 0.004)
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline and not self._stop:
                time.sleep(0.002)

    def _collect(self, update):
        mem = self.mem
        offs = self.offs
        esp = self.esp_cfg
        now = time.monotonic()



        if update % 60 == 0:
            new_pid = memory.find_best_pid(mem.process_name)
            if new_pid and (new_pid != mem.pid or not mem.alive()):
                self._dm = 0
                if mem.reopen():
                    status.log("[ESP] re-attached to process {} @ 0x{:X}".format(
                        mem.pid, mem.base))

        validate = (update % max(int(self.stealth.get("validate_every", 90)), 1)) == 0
        if validate:
            self._dm = 0

        dm = self._dm or roblox.get_datamodel(mem, offs)
        if not dm:
            self._dm = 0
            self._waiting = True
            msg = ("Waiting for a game session - make sure you are inside a game "
                   "(not the menu)")
            self._publish(entries=[], camera=None, local_pos=None, ok=False,
                      message=msg, server_players=0, ping=None, game=None,
                      game_id=0, game_name="")
            self._push_status(message=msg)
            return
        self._dm = dm
        self._waiting = False

        game_id = roblox.get_place_id(mem, dm, offs)
        if game_id:
            if self._pergame is not None and game_id != self._pergame_game:
                self._pergame.on_game_change(game_id)
                self._pergame_game = game_id
        else:
            self._pergame_game = None
        game_key = self._active_game(game_id)
        game_cfg = self.games_cfg.get(game_key) if game_key else None

        ws = roblox.get_workspace(mem, dm, offs)
        if not ws:
            msg = "Workspace not found"
            self._publish(entries=[], ok=False, message=msg, game=None,
                          game_id=0, game_name="")
            self._push_status(message=msg)
            return

        players = roblox.get_players(mem, dm, offs)
        if not players:
            msg = "Players service not found"
            self._publish(entries=[], ok=False, message=msg, game=None,
                          game_id=0, game_name="")
            self._push_status(message=msg)
            return
        try:
            server_count = sum(
                1 for p in roblox.get_children(mem, players, offs)
                if roblox.class_name(mem, p, offs) == "Player")
        except Exception:
            server_count = 0

        local = roblox.get_local_player(mem, players, offs)
        local_team = roblox.get_team_name(mem, local, offs) if local else ""
        no_team_data = bool(esp.get("team_check", True) and not local_team)
        if no_team_data and not self._warned_no_team:
            self._warned_no_team = True
            status.log("[i] 'Hide teammates' is on but no team data was detected, "
                       "so teammates will not be hidden.")
        elif not no_team_data and self._warned_no_team:
            self._warned_no_team = False
        local_char = roblox.get_character(mem, local, offs) if local else 0
        if not local_char:
            local_char = roblox.get_local_character_alt(mem, ws, offs)
        local_humanoid = roblox.get_humanoid(mem, local_char, offs) if local_char else 0
        local_hrp = roblox.get_root_part(mem, local_char, local_humanoid, offs) if local_char else 0
        local_pos = roblox.get_part_position(mem, local_hrp, offs) if local_hrp else None
        local_anchor = (local_pos[0], local_pos[1] + 1.5, local_pos[2]) if local_pos else None

        cam = roblox.get_camera(mem, ws, offs)
        camera = roblox.read_camera(mem, cam, offs, anchor=local_anchor) if cam else None
        if camera is None:
            camera = self._last_camera
        else:
            self._last_camera = camera

        entries = []
        seen = 0
        no_char = 0
        no_humanoid = 0
        no_hrp = 0
        no_pos = 0
        skipped_team = 0
        skipped_dist = 0
        skipped_dead = 0
        for p in roblox.get_children(mem, players, offs):
            if roblox.class_name(mem, p, offs) != "Player":
                continue
            seen += 1
            char = roblox.get_character(mem, p, offs)
            if not char:
                no_char += 1
                continue
            humanoid = roblox.get_humanoid(mem, char, offs)
            if not humanoid:
                no_humanoid += 1
                continue
            hrp = roblox.get_root_part(mem, char, humanoid, offs)
            pos = roblox.get_part_position(mem, hrp, offs) if hrp else None
            if not pos:
                no_pos += 1
                continue
            extents = None
            head_pos = None
            if esp.get("dynamic_box", True):
                refresh_s = float(esp.get("extents_refresh_s", 1.5))
                last_scan, cached = self._extents.get(char, (0.0, None))
                if cached and now - last_scan < refresh_s:
                    extents = cached
                else:
                    extents = roblox.get_character_extents(mem, char, pos, offs)
                    self._extents[char] = (now, extents)
                    if len(self._extents) > 256:
                        self._extents.clear()
                last_head, cached_head = self._heads.get(char, (0.0, None))
                if cached_head and now - last_head < refresh_s:
                    head_pos = cached_head
                else:
                    head_pos = roblox.get_head_position(mem, char, offs, pos)
                    self._heads[char] = (now, head_pos)
                    if len(self._heads) > 256:
                        self._heads.clear()
            name = roblox.instance_name(mem, p, offs) or "?"
            team = roblox.get_team_name(mem, p, offs)
            is_local = bool(local and p == local)

            distance = None
            if local_pos and pos:
                dx = pos[0] - local_pos[0]
                dz = pos[2] - local_pos[2]
                distance = math.sqrt(dx * dx + dz * dz)

            if not esp.get("show_local_player", False) and is_local:
                continue
            if esp.get("team_check", True) and not is_local and local_team and team == local_team:
                skipped_team += 1
                continue
            if distance is not None and distance > esp.get("max_distance", 300.0):
                skipped_dist += 1
                continue

            health = mem.f32(humanoid + roblox.O(offs, "Humanoid", "Health"))
            max_health = mem.f32(humanoid + roblox.O(offs, "Humanoid", "MaxHealth"))
            if max_health <= 0:
                max_health = 100.0
            if esp.get("skip_dead", False) and health <= 0:
                skipped_dead += 1
                continue

            tool = ""
            if esp.get("tool", False):
                refresh_s = float(esp.get("tool_refresh_s", 0.5))
                last_scan, cached = self._tool_cache.get(char, (0.0, ""))
                if now - last_scan < refresh_s:
                    tool = cached
                else:
                    tool = roblox.get_equipped_tool(mem, char, offs)
                    self._tool_cache[char] = (now, tool)

            role = None
            if game_cfg:
                refresh_s = float(esp.get("role_refresh_s", 2.0))
                last_scan, cached = self._role_cache.get(p, (0.0, None))
                if cached is not None and now - last_scan < refresh_s:
                    role = cached
                else:
                    tools = roblox.get_inventory_tools(mem, p, char, offs)
                    role = _classify_role(team, tools, game_cfg)
                    self._role_cache[p] = (now, role)
                    if len(self._role_cache) > 512:
                        self._role_cache.clear()

            entries.append({
                "name": name,
                "team": team,
                "health": health,
                "max_health": max_health,
                "pos": pos,
                "distance": distance,
                "is_local": is_local,
                "alive": health > 0,
                "extents": extents,
                "head": head_pos,
                "tool": tool,
                "role": role,
                "occluded": False,
            })

        alt_count = 0
        if not entries and (game_cfg is None or game_cfg.get("alt_characters", False)):
            alt_models = []
            for model, team_key, box in roblox.get_alt_characters(mem, ws, offs):
                alt_models.append((model, team_key, box))
            alt_local_key = ""
            alt_local_model = 0
            if local_pos:
                best_d2 = 3.0 * 3.0
                for model, team_key, box in alt_models:
                    pos, _, _ = box
                    if not pos:
                        continue
                    dx = pos[0] - local_pos[0]
                    dy = pos[1] - local_pos[1]
                    dz = pos[2] - local_pos[2]
                    d2 = dx * dx + dy * dy + dz * dz
                    if d2 < best_d2:
                        best_d2 = d2
                        alt_local_key = team_key
                        alt_local_model = model
            if alt_local_key:
                local_team = alt_local_key
            for model, team_key, box in alt_models:
                alt_count += 1
                pos, extents, head = box
                is_local = bool(alt_local_model and model == alt_local_model)
                if not esp.get("show_local_player", False) and is_local:
                    continue
                if esp.get("team_check", True) and not is_local and \
                        alt_local_key and team_key == alt_local_key:
                    skipped_team += 1
                    continue
                distance = None
                if local_pos and pos:
                    dx = pos[0] - local_pos[0]
                    dz = pos[2] - local_pos[2]
                    distance = math.sqrt(dx * dx + dz * dz)
                if distance is not None and distance > esp.get("max_distance", 300.0):
                    skipped_dist += 1
                    continue
                entries.append({
                    "name": "",
                    "team": team_key,
                    "health": 100.0,
                    "max_health": 100.0,
                    "pos": pos,
                    "distance": distance,
                    "is_local": is_local,
                    "alive": True,
                    "extents": extents,
                    "head": head,
                    "tool": "",
                    "role": None,
                    "occluded": False,
                })

        if esp.get("debug", False) and update % 300 == 0:
            game_name = self._game_names.get(game_id) or ""
            status.log("[ESP-dbg] game_id={} game={!r}".format(
                game_id, game_name))
            lp = roblox.get_local_player(mem, players, offs)
            camdbg = roblox.read_camera(mem, cam, offs,
                                        anchor=local_anchor) if cam else None
            if camdbg:
                status.log("[ESP-dbg] camera pos=({:.1f},{:.1f},{:.1f}) "
                           "look=({:.2f},{:.2f},{:.2f}) fov={:.2f}".format(
                    camdbg.pos[0], camdbg.pos[1], camdbg.pos[2],
                    camdbg.look[0], camdbg.look[1], camdbg.look[2],
                    math.degrees(camdbg.fov)))
            else:
                status.log("[ESP-dbg] camera read FAILED (falling back to "
                           "last good camera)")
            team_info = []
            for p in (roblox.get_children(mem, players, offs) or [])[:3]:
                team = mem.ptr(p + roblox.O(offs, "Player", "Team"))
                team_info.append("0x{:X}:{}:{}".format(
                    team or 0,
                    roblox.class_name(mem, team, offs) if team else "-",
                    roblox.instance_name(mem, team, offs) if team else "-"))
            status.log("[ESP-dbg] teams sample={} local_pos={}".format(
                team_info, local_pos))
            ws_children = ["{}:{}".format(
                roblox.class_name(mem, k, offs),
                roblox.instance_name(mem, k, offs))
                for k in roblox.get_children(mem, ws, offs)]
            status.log("[ESP-dbg] workspace kids={}".format(ws_children))
            for sub in roblox.get_children(mem, ws, offs):
                sub_cls = roblox.class_name(mem, sub, offs)
                sub_nm = roblox.instance_name(mem, sub, offs)
                if sub_cls not in ("Folder", "Model") or sub_nm == "Map":
                    continue
                kids = []
                for k in roblox.get_children(mem, sub, offs):
                    kids.append("{}:{}".format(
                        roblox.class_name(mem, k, offs),
                        roblox.instance_name(mem, k, offs)))
                status.log("[ESP-dbg] {}:{} all {} direct kids: {}".format(
                    sub_cls, sub_nm, len(kids), kids))
                if sub_nm == "Players":
                    for k in roblox.get_children(mem, sub, offs):
                        self._dump_character(status, mem, k, offs, 0)

        items = []
        if esp.get("item_esp", True) and local_pos:
            classes = [c.strip() for c in str(
                esp.get("item_classes", "Tool")).split(",") if c.strip()]
            range_sq = float(esp.get("item_distance", 300.0)) ** 2
            for name, ipos in roblox.find_items(mem, ws, offs, classes):
                dx = ipos[0] - local_pos[0]
                dz = ipos[2] - local_pos[2]
                if dx * dx + dz * dz > range_sq:
                    continue
                items.append({"name": name, "pos": ipos,
                              "distance": math.sqrt(dx * dx + dz * dz)})

        if esp.get("occlusion", False) and camera and entries \
                and now - self._last_occ >= float(esp.get("occ_rate", 0.12)):
            self._last_occ = now
            if self._occ is None:
                self._occ = occlusion.OcclusionTracker(mem, offs)
            self._occ.set_refresh(float(esp.get("occ_scan_s", 4.0)))
            self._occ.pump(now, ws)
            self._apply_occlusion(camera, entries, esp)
        elif not esp.get("occlusion", False) and self._occ is not None:
            self._occ.drop()

        preset_name = (game_cfg.get("name", game_key) if game_cfg else "")
        game_name = self._game_names.get(game_id) or preset_name
        if game_id and not game_name and game_id not in self._game_name_lookups:
            self._game_name_lookups[game_id] = True
            threading.Thread(target=self._lookup_game_name, args=(game_id,),
                             daemon=True, name="GameName").start()

        self._publish(camera=camera, local_pos=local_pos, local_team=local_team,
                      entries=entries, items=items, ok=True, message="",
                      server_players=server_count, ping=None, game=game_key,
                      game_id=game_id, game_name=game_name,
                      cam_addr=cam, local_anchor=local_anchor)
        self._push_status(camera=camera, targets=len(entries), game=game_key,
                          game_name=game_name, game_id=game_id)

    def _dump_character(self, logger, mem, node, offs, depth):
        line = []
        cur = node
        for _ in range(10):
            if not cur:
                break
            cls = roblox.class_name(mem, cur, offs)
            nm = roblox.instance_name(mem, cur, offs)
            line.insert(0, "{}:{}".format(cls, nm))
            cur = mem.ptr(cur + roblox.O(offs, "Instance", "Parent"))
        found = []
        stack = [node]
        guard = 0
        while stack and guard < 5000:
            guard += 1
            n = stack.pop()
            for k in roblox.get_children(mem, n, offs):
                cls = roblox.class_name(mem, k, offs)
                if cls in ("Part", "MeshPart", "WedgePart", "CylinderPart",
                           "TrussPart", "CornerWedgePart"):
                    pos = roblox.get_part_position(mem, k, offs)
                    if pos:
                        found.append(pos)
                if cls in ("Part", "MeshPart", "WedgePart", "CylinderPart",
                           "TrussPart", "CornerWedgePart", "Texture", "Decal",
                           "Humanoid"):
                    continue
                stack.append(k)
        if not found:
            logger.log("[ESP-dbg] {} no parts, chain={}".format(
                "  " * depth, " <- ".join(line)))
            return
        ys = [p[1] for p in found]
        xs = [p[0] for p in found]
        zs = [p[2] for p in found]
        logger.log("[ESP-dbg] {} chain={} parts={} pos=({:.0f},{:.0f},{:.0f}) "
                   "y=[{:.0f},{:.0f}]".format(
                       "  " * depth, " <- ".join(line), len(found),
                       sum(xs) / len(xs), sum(ys) / len(ys),
                       sum(zs) / len(zs), min(ys), max(ys)))

    def _dump_subtree(self, logger, mem, node, offs, depth, max_depth):
        line = []
        cur = node
        for _ in range(10):
            if not cur:
                break
            cls = roblox.class_name(mem, cur, offs)
            nm = roblox.instance_name(mem, cur, offs)
            line.insert(0, "{}:{}".format(cls, nm))
            cur = mem.ptr(cur + roblox.O(offs, "Instance", "Parent"))
        kids = []
        for k in roblox.get_children(mem, node, offs):
            kids.append("{}:{}".format(
                roblox.class_name(mem, k, offs),
                roblox.instance_name(mem, k, offs)))
        logger.log("[ESP-dbg] {}{} chain={} kids[{}]={}".format(
            "  " * depth, "node", " <- ".join(line), len(kids), kids[:12]))
        if depth < max_depth:
            for k in roblox.get_children(mem, node, offs):
                cls = roblox.class_name(mem, k, offs)
                if cls in ("Folder", "Model", "Workspace", "Players",
                           "Player", "DataModel"):
                    self._dump_subtree(logger, mem, k, offs, depth + 1,
                                       max_depth)

    def _lookup_game_name(self, place_id):
        try:
            import json
            import urllib.request
            uid = ""
            req = urllib.request.Request(
                "https://apis.roblox.com/universes/v1/places/{}/universe".format(place_id),
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                uid = json.loads(resp.read().decode("utf-8", "replace")).get("universeId") or ""
            name = ""
            if uid:
                req2 = urllib.request.Request(
                    "https://games.roblox.com/v1/games?universeIds={}".format(uid),
                    headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req2, timeout=6) as resp2:
                    data = json.loads(resp2.read().decode("utf-8", "replace")).get("data") or []
                    if data:
                        name = data[0].get("name", "") or ""
            if name:
                self._game_names[place_id] = name
        except Exception:
            pass
        finally:
            self._game_name_lookups.pop(place_id, None)

    def _apply_occlusion(self, camera, entries, esp):
        occ = self._occ
        height = float(esp.get("character_height", 5.0))
        ratio = float(esp.get("hrp_ratio", 0.45))
        points = []
        idx = []
        for i, e in enumerate(entries):
            e["occluded"] = False
            if e.get("is_local") or not e.get("alive", True):
                continue
            pos = e["pos"]
            ext = e.get("extents")
            hp = e.get("head")
            if hp:
                py = hp[1]
            elif ext:
                py = pos[1] + (ext[0] + ext[1]) * 0.5
            else:
                py = pos[1] + height - height * ratio
            points.append((pos[0], py, pos[2]))
            idx.append(i)
        if not points or not occ.ready():
            return
        blocked = occ.raycast_many(camera.pos, points)
        for i, b in zip(idx, blocked):
            entries[i]["occluded"] = bool(b)

    def _active_game(self, place_id=0):
        """Pick the preset to apply.

        With auto_preset on, the preset whose place_id matches the currently
        joined game wins. Otherwise the first enabled preset is used.
        """
        if self.esp_cfg.get("auto_preset", True):
            if place_id:
                for key, g in self.games_cfg.items():
                    pid = g.get("place_id")
                    if pid and str(pid) == str(place_id):
                        return key
            return None
        for key, g in self.games_cfg.items():
            if g.get("enabled"):
                return key
        return None
