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
        self._look_cache = {}
        self._warned_no_team = False
        self._waiting = False
        self._last_camera = None
        self._game_names = {}
        self._hz_cur = None
        self._hz_burst = 0
        self._game_name_lookups = {}
        self._alt_cache = (0.0, [])
        self._dead_cache = (0.0, [])
        self._color_cache = (0.0, None)
        self._last_local_team = ""
        self._scan_busy = False
        self._last_scan = 0.0
        self._dbg_last_n = 0
        self._rig_last_seen = {}
        self._rig_last_box = {}
        self._rig_fresh = set()
        self._rig_motion = {}
        self._rig_parts = {}
        self._rig_hum = {}
        self._tc_map = ({}, 0)
        self._last_hum = (0, 0, 0)
        self._last_ndl = 0
        self._last_lsrc = ""
        self._local_char = 0
        self._last_lchar = 0
        self._spawn_ts = 0.0
        self._spawn_votes = {}
        self._lock_done = True
        self._team_lock = ""
        self._lock_tc = None
        self._pulse_ts = 0.0
        self._pulse_n = 0
        self._pulse_dead = {}
        self._pulse_drops = 0
        self._last_local_pos = None
        self._last_local_pos_ts = 0.0
        self._last_scan_dur = 0.0
        self._scan_scheduled = 0
        self._scan_ran = 0
        self._last_scan_err = ""
        self._last_probe = ""
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
            "ts": 0.0,
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
        self._publish(ts=now)
        exc_raw = esp.get("exceptions") or ""
        if not isinstance(exc_raw, str):
            exc_raw = " ".join(str(x) for x in exc_raw)
        exc_set = {w.lower() for w in exc_raw.replace(",", " ").split() if w}



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
        if game_cfg and "team_check" in game_cfg:
            team_check = bool(game_cfg["team_check"])
        else:
            team_check = bool(esp.get("team_check", True))
        if game_cfg and "skip_dead" in game_cfg:
            skip_dead = bool(game_cfg["skip_dead"])
        else:
            skip_dead = bool(esp.get("skip_dead", False))
        corpse_filter = bool(esp.get("corpse_filter", True))
        team_color_teams = bool(game_cfg and game_cfg.get("team_color_teams"))
        if team_color_teams:
            tc = roblox.get_team_color(mem, local, offs) if local else 0
            local_team = "tc:{}".format(tc) if tc else ""
        else:
            local_team = roblox.get_team_name(mem, local, offs) if local else ""
        no_team_data = bool(team_check and not local_team)
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
        local_pos_fresh = local_pos is not None
        if local_pos:
            self._last_local_pos = local_pos
            self._last_local_pos_ts = now
        elif self._last_local_pos is not None and \
                now - self._last_local_pos_ts < 4.0:
            local_pos = self._last_local_pos
        local_anchor = (local_pos[0], local_pos[1] + 1.5, local_pos[2]) if local_pos else None

        cam = roblox.get_camera(mem, ws, offs)
        camera = roblox.read_camera(mem, cam, offs, anchor=local_anchor) if cam else None
        cam_fresh = camera is not None
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
            forced_teammate = name.strip().lower() in exc_set
            if team_color_teams:
                tc = roblox.get_team_color(mem, p, offs)
                team = "tc:{}".format(tc) if tc else ""
            else:
                team = roblox.get_team_name(mem, p, offs)
            is_local = bool(local and p == local)
            if corpse_filter and not is_local and extents:
                h = max(0.1, extents[1] - extents[0])
                mrec = self._rig_motion.get(char)
                corpse = False
                if mrec is None:
                    self._rig_motion[char] = [pos, now, now, 0.0, h, 0.0, 1]
                else:
                    prev_h = mrec[4] if len(mrec) > 4 else h
                    if len(mrec) < 7:
                        mrec.extend([h, 0.0, 1])
                    else:
                        mrec[4] = h
                    if prev_h >= 4.5 and h <= 2.7:
                        corpse = True
                    if h <= 2.7:
                        if not mrec[5]:
                            mrec[5] = now
                        elif now - mrec[5] > 2.0:
                            corpse = True
                    else:
                        mrec[5] = 0.0
                    mdx = pos[0] - mrec[0][0]
                    mdy = pos[1] - mrec[0][1]
                    mdz = pos[2] - mrec[0][2]
                    mdd = mdx * mdx + mdy * mdy + mdz * mdz
                    if mdd > 0.09:
                        mrec[0] = pos
                        mrec[2] = now
                        mrec[3] = mrec[3] + math.sqrt(mdd)
                    elif now - mrec[2] > 3.5 or \
                            (mrec[2] == mrec[1] and now - mrec[1] > 0.8):
                        corpse = True
                if corpse:
                    skipped_dead += 1
                    continue

            distance = None
            if local_pos and pos:
                dx = pos[0] - local_pos[0]
                dz = pos[2] - local_pos[2]
                distance = math.sqrt(dx * dx + dz * dz)

            if not esp.get("show_local_player", False) and is_local:
                continue
            if (team_check and not is_local
                    and not forced_teammate and local_team
                    and team == local_team):
                skipped_team += 1
                continue
            if distance is not None and distance > esp.get("max_distance", 300.0):
                skipped_dist += 1
                continue

            health = mem.f32(humanoid + roblox.O(offs, "Humanoid", "Health"))
            max_health = mem.f32(humanoid + roblox.O(offs, "Humanoid", "MaxHealth"))
            if max_health <= 0:
                max_health = 100.0
            if skip_dead and health <= 0:
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

            look = None
            if hrp:
                look_ttl, look_cache = self._look_cache.get(hrp, (0.0, None))
                if now - look_ttl < 1.0:
                    look = look_cache
                else:
                    look = roblox.get_part_look(mem, hrp, offs)
                    self._look_cache[hrp] = (now, look)
                    if len(self._look_cache) > 256:
                        self._look_cache.clear()

            eff_team = team if team_check else ""
            entries.append({
                "id": p,
                "name": name,
                "team": eff_team,
                "forced_teammate": forced_teammate,
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
                "look": look,
            })

        alt_count = 0
        alt_tally = {}
        if not entries and (game_cfg is None or game_cfg.get("alt_characters", False)):
            alt_ts, alt_cached = self._alt_cache
            alt_models = []
            for model, team_key, box, tfolder in alt_cached:
                pos, extents, head, anchor, apos, nparts = box
                self._rig_parts[model] = nparts
                if anchor and apos:
                    ap = roblox.get_part_position(mem, anchor, offs)
                    if ap:
                        dx = ap[0] - apos[0]
                        dy = ap[1] - apos[1]
                        dz = ap[2] - apos[2]
                        pos = (pos[0] + dx, pos[1] + dy, pos[2] + dz)
                        head = (head[0] + dx, head[1] + dy, head[2] + dz)
                alt_models.append((model, team_key, (pos, extents, head),
                                   tfolder))
            alt_local_key = ""
            alt_local_model = 0
            lsrc = ""
            m2tc, local_tc = self._tc_map
            if local_tc and getattr(self, "_lock_tc", None) and \
                    local_tc != self._lock_tc:
                self._team_lock = ""
                self._lock_tc = None
            lchar = getattr(self, "_local_char", 0)
            if lchar != getattr(self, "_last_lchar", 0):
                self._last_lchar = lchar
                self._spawn_ts = now if lchar else 0.0
                self._spawn_votes = {}
                self._lock_done = False
            if lchar and not getattr(self, "_lock_done", True):
                win = now - getattr(self, "_spawn_ts", 0.0)
                if local_pos and local_pos_fresh and 0.0 <= win <= 3.0:
                    for model, team_key, box, _tf in alt_models:
                        if model not in self._rig_fresh:
                            continue
                        p, _, _ = box
                        if not p:
                            continue
                        dx = p[0] - local_pos[0]
                        dy = p[1] - local_pos[1]
                        dz = p[2] - local_pos[2]
                        if dx * dx + dy * dy + dz * dz < 1600.0:
                            self._spawn_votes[team_key] = \
                                self._spawn_votes.get(team_key, 0) + 1
                nvotes = sum(self._spawn_votes.values())
                if nvotes >= 3 or (win > 3.0 and nvotes >= 1):
                    self._team_lock = max(self._spawn_votes,
                                          key=self._spawn_votes.get)
                    self._lock_tc = local_tc or self._lock_tc
                    self._lock_done = True
                elif win > 3.0:
                    self._lock_done = True
            if not alt_local_key and getattr(self, "_team_lock", ""):
                alt_local_key = self._team_lock
                lsrc = "lock"
            if local_tc and m2tc:
                folder_tc = {}
                for model, team_key, box, _tf in alt_models:
                    if model in self._rig_fresh:
                        tc = m2tc.get(model)
                        if tc and team_key not in folder_tc:
                            folder_tc[team_key] = tc
                for tk, tc in folder_tc.items():
                    if tc == local_tc:
                        alt_local_key = tk
                        lsrc = "tc"
                        break
            if not alt_local_key and team_color_teams:
                color_ts, color_cached = self._color_cache
                if color_cached:
                    folder_cols, local_col = color_cached
                    best_key = ""
                    best_d = None
                    second_d = None
                    if local_col:
                        colored = [tk for tk, col in folder_cols.items()
                                   if col]
                        if len(colored) >= 2:
                            dists = []
                            for tk in colored:
                                col = folder_cols[tk]
                                d = math.sqrt((col[0] - local_col[0]) ** 2 +
                                              (col[1] - local_col[1]) ** 2 +
                                              (col[2] - local_col[2]) ** 2)
                                dists.append((d, tk))
                            dists.sort()
                            best_d, best_key = dists[0]
                            if len(dists) > 1:
                                second_d = dists[1][0]
                    cur = getattr(self, "_col_team", "")
                    if best_key and best_d is not None and best_d < 0.35:
                        accept = True
                        if cur and best_key != cur:
                            accept = (second_d is not None
                                      and best_d <= second_d - 0.08)
                        if accept:
                            self._col_team = best_key
                            self._col_miss_ts = 0.0
                    elif cur:
                        if best_d is None or best_d > 0.6:
                            if not self._col_miss_ts:
                                self._col_miss_ts = now
                            elif now - self._col_miss_ts > 2.0:
                                self._col_team = ""
                                self._col_miss_ts = 0.0
                        else:
                            self._col_miss_ts = 0.0
                    if getattr(self, "_col_team", ""):
                        alt_local_key = self._col_team
                        lsrc = "col"
            if not alt_local_key and self._last_local_team:
                alt_local_key = self._last_local_team
                lsrc = "sticky"
            if not alt_local_key and local_pos and local_pos_fresh:
                best_d2 = 3.0 * 3.0
                for model, team_key, box, _tf in alt_models:
                    if model not in self._rig_fresh:
                        continue
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
                        lsrc = "near"
            if alt_local_key:
                local_team = alt_local_key
            if local_team:
                self._last_local_team = local_team
            else:
                local_team = self._last_local_team
            self._last_lsrc = lsrc
            alt_tally = {}
            pulsed = set()
            cands = []
            if self._pulse_n > 0 and now - self._pulse_ts <= 4.0:
                pulse_pos = getattr(self, "_pulse_positions", []) or []
                for model, team_key, box, _tf in alt_models:
                    if model in self._pulse_dead:
                        continue
                    if model in self._rig_fresh and \
                            self._rig_parts.get(model, 0) >= 4:
                        continue
                    p = box[0]
                    if not p or not pulse_pos:
                        continue
                    best_d2 = None
                    for dp in pulse_pos:
                        ddx = p[0] - dp[0]
                        ddy = p[1] - dp[1]
                        ddz = p[2] - dp[2]
                        d2 = ddx * ddx + ddy * ddy + ddz * ddz
                        if best_d2 is None or d2 < best_d2:
                            best_d2 = d2
                    if best_d2 is not None and best_d2 < 64.0:
                        cands.append((best_d2, model))
                cands.sort()
                n_drop = min(self._pulse_n, len(cands))
                for i in range(n_drop):
                    pulsed.add(cands[i][1])
                    self._pulse_dead[cands[i][1]] = now
                    self._pulse_drops += 1
                self._pulse_n -= n_drop
            elif now - self._pulse_ts > 4.0 and self._pulse_n:
                self._pulse_n = 0
            if esp.get("debug", False) and \
                    getattr(self, "_pulse_fresh_event", False):
                self._pulse_fresh_event = False
                status.log(
                    "[ESP-pulse] pos={} dropped={} cand_d2={}".format(
                        [(round(p[0]), round(p[1]), round(p[2]))
                         for p in (getattr(self, "_pulse_positions", []) or [])],
                        [hex(m) for m in pulsed],
                        [round(d2, 1) for d2, _m in cands[:4]]))
            for model, team_key, box, tfolder in alt_models:
                alt_count += 1
                t = alt_tally.setdefault(team_key, [0, 0, 0, 0, 0, 0])
                if model in self._rig_fresh:
                    t[0] += 1
                else:
                    t[1] += 1
                pos, extents, head = box
                healthy = self._rig_parts.get(model, 0) >= 4
                if not healthy and model not in self._rig_motion:
                    skipped_dead += 1
                    continue
                if model in pulsed or model in self._pulse_dead:
                    t[5] += 1
                    skipped_dead += 1
                    continue
                mrec = self._rig_motion.get(model)
                h = extents[1] - extents[0]
                rag = 0
                if mrec is None:
                    self._rig_motion[model] = [pos, now, now, 0.0, h, 0.0]
                else:
                    prev_h = mrec[4] if len(mrec) > 4 else 6.0
                    if len(mrec) < 6:
                        mrec.extend([h, 0.0])
                    else:
                        mrec[4] = h
                    if prev_h >= 4.5 and h <= 2.7:
                        rag = 1
                    if h <= 2.7:
                        if not mrec[5]:
                            mrec[5] = now
                        elif now - mrec[5] > 2.0:
                            rag = 1
                    else:
                        mrec[5] = 0.0
                    mdx = pos[0] - mrec[0][0]
                    mdy = pos[1] - mrec[0][1]
                    mdz = pos[2] - mrec[0][2]
                    mdd = mdx * mdx + mdy * mdy + mdz * mdz
                    if mdd > 0.1225:
                        mrec[0] = pos
                        mrec[2] = now
                        mrec[3] = mrec[3] + math.sqrt(mdd)
                    elif now - mrec[2] > 3.5 or \
                            (mrec[2] == mrec[1] and
                             now - mrec[1] > 0.8) or \
                            (not healthy and
                             now - mrec[2] > 1.0) or \
                            (now - mrec[1] > 10.0 and
                             mrec[3] < 2.0):
                        rag = 1
                    if rag:
                        t[2] += 1
                        skipped_dead += 1
                        continue
                is_local = bool(alt_local_model and model == alt_local_model)
                if not esp.get("show_local_player", False) and is_local:
                    t[2] += 1
                    continue
                if team_check and not is_local and \
                        local_team and team_key == local_team:
                    t[3] += 1
                    skipped_team += 1
                    continue
                distance = None
                if local_pos and pos:
                    dx = pos[0] - local_pos[0]
                    dz = pos[2] - local_pos[2]
                    distance = math.sqrt(dx * dx + dz * dz)
                if distance is not None and distance > esp.get("max_distance", 300.0):
                    t[4] += 1
                    skipped_dist += 1
                    continue
                entries.append({
                    "name": "",
                    "team": team_key if team_check else "",
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

            if len(self._rig_motion) > 400:
                live_keys = {m for m, _, _, _ in alt_cached}
                self._rig_motion = {k: v for k, v in
                                    self._rig_motion.items()
                                    if k in live_keys}
                self._rig_parts = {k: v for k, v in
                                   self._rig_parts.items()
                                   if k in live_keys}

            if not esp.get("skip_dead", False) and \
                    (game_cfg is None or game_cfg.get("alt_characters", False)):
                dead_ts, dead_cached = self._dead_cache
                for model, box in dead_cached:
                    pos, extents, head, anchor, apos, _npc = box
                    if anchor and apos:
                        ap = roblox.get_part_position(mem, anchor, offs)
                        if ap:
                            dx = ap[0] - apos[0]
                            dy = ap[1] - apos[1]
                            dz = ap[2] - apos[2]
                            pos = (pos[0] + dx, pos[1] + dy, pos[2] + dz)
                            head = (head[0] + dx, head[1] + dy, head[2] + dz)
                    distance = None
                    if local_pos and pos:
                        dx = pos[0] - local_pos[0]
                        dz = pos[2] - local_pos[2]
                        distance = math.sqrt(dx * dx + dz * dz)
                    if distance is not None and distance > esp.get("max_distance", 300.0):
                        continue
                    entries.append({
                        "name": "",
                        "team": "",
                        "health": 0.0,
                        "max_health": 100.0,
                        "pos": pos,
                        "distance": distance,
                        "is_local": False,
                        "alive": False,
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
                tc_off = roblox.O(offs, "Player", "TeamColor") or 944
                tc = mem.u32(p + tc_off) if tc_off else 0
                kids = []
                for k in roblox.get_children(mem, p, offs) or []:
                    kc = roblox.class_name(mem, k, offs)
                    kn = roblox.instance_name(mem, k, offs)
                    if kc.endswith("Value"):
                        voff = roblox.O(offs, "Misc", "Value") or 184
                        vraw = mem.u32(k + voff) if voff else 0
                        vstr = ""
                        if kc == "StringValue":
                            vstr = mem.rbx_string(vraw) if vraw else ""
                        kids.append("{}:{}={}/{}".format(
                            kc, kn, vraw, vstr))
                    else:
                        kids.append("{}:{}".format(kc, kn))
                team_info.append("0x{:X}:{}:{} tc={} kids={}".format(
                    team or 0,
                    roblox.class_name(mem, team, offs) if team else "-",
                    roblox.instance_name(mem, team, offs) if team else "-",
                    tc, kids[:14]))
            status.log("[ESP-dbg] teams sample={} local_pos={}".format(
                team_info, local_pos))
            status.log("[ESP-dbg] skip stats seen={} no_char={} "
                       "no_humanoid={} no_hrp={} no_pos={} team_skip={} "
                       "dist_skip={} dead_skip={} entries={} "
                       "server_players={}".format(
                seen, no_char, no_humanoid, no_hrp, no_pos,
                skipped_team, skipped_dist, skipped_dead, len(entries),
                server_count))
            status.log("[ESP-dbg] local_team={!r} alt={} tc_mode={}".format(
                local_team, alt_count, team_color_teams))
            status.log("[ESP-team] lpos_fresh={} lteam={} lsrc={} lk={}/{} "
                       "pl={}/{} scandur={:.3f}s "
                       "sched={} ran={} err={} ltc={} ntc={} hum={}/{} "
                       "db={} ndl={} probe={} tally={}".format(
                           local_pos_fresh, local_team,
                           getattr(self, "_last_lsrc", ""),
                           getattr(self, "_team_lock", ""),
                           sum(getattr(self, "_spawn_votes", {}).values()),
                           self._pulse_n, self._pulse_drops,
                           self._last_scan_dur,
                           self._scan_scheduled, self._scan_ran,
                           self._last_scan_err,
                           self._tc_map[1], len(self._tc_map[0]),
                           self._last_hum[0], self._last_hum[1],
                           self._last_hum[2], self._last_ndl,
                           self._last_probe,
                           {k: tuple(v) for k, v in alt_tally.items()}))
            par_samples = []
            poff = roblox.O(offs, "Instance", "Parent")
            for model, team_key, box, tfolder in alt_models[:3]:
                par = mem.ptr(model + poff) if poff else 0
                par_samples.append("par=0x{:X} tf=0x{:X}".format(
                    par or 0, tfolder or 0))
            status.log("[ESP-par] poff={} {}".format(
                poff, "; ".join(par_samples)))
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

        if esp.get("debug", False):
            n_now = len(entries)
            if self._dbg_last_n > 0 and n_now == 0:
                ats, ac = self._alt_cache
                status.log(
                    "[ESP-cut] DROP n={}->0 cam_fresh={} local_pos={} "
                    "alt_n={} alt_age={:.1f}s scan_busy={} seen={} no_char={} "
                    "no_humanoid={} no_pos={} skip_team={} skip_dist={} "
                    "skip_dead={} lteam={} lsrc={} lk={}/{} rej={} "
                    "tally={}".format(
                        self._dbg_last_n, cam_fresh, local_pos is not None,
                        len(ac), now - ats, self._scan_busy, seen, no_char,
                        no_humanoid, no_pos, skipped_team, skipped_dist,
                        skipped_dead, local_team, getattr(self, "_last_lsrc",
                                                         ""),
                        getattr(self, "_team_lock", ""),
                        sum(getattr(self, "_spawn_votes", {}).values()),
                        getattr(self, "_last_probe", ""), alt_tally))
            elif self._dbg_last_n == 0 and n_now > 0:
                status.log("[ESP-cut] RECOVER 0->{}".format(n_now))
            self._dbg_last_n = n_now

        self._publish(camera=camera, local_pos=local_pos, local_team=local_team,
                      entries=entries, items=items, ok=True, message="",
                      server_players=server_count, ping=None, game=game_key,
                      game_id=game_id, game_name=game_name,
                      cam_addr=cam, local_anchor=local_anchor)
        self._push_status(camera=camera, targets=len(entries), game=game_key,
                          game_name=game_name, game_id=game_id)

        scan_gap = float(esp.get("extents_refresh_s", 1.5))
        if (game_cfg is None or game_cfg.get("alt_characters", False)) and \
                now - self._last_scan >= scan_gap and not self._scan_busy:
            self._last_scan = now
            self._scan_busy = True
            self._scan_scheduled += 1
            threading.Thread(target=self._refresh_alt_caches,
                             args=(now, ws, mem, offs, esp, game_cfg,
                                   players),
                             daemon=True, name="AltScan").start()

    def _refresh_alt_caches(self, now, ws, mem, offs, esp, game_cfg,
                            players=0):
        t0 = time.time()
        self._scan_ran += 1
        try:
            alt_models = []
            fresh_set = set()
            with_hum = 0
            dead_hum = 0
            dead_db = 0
            rej = {} if esp.get("debug", False) else None
            found = roblox.get_alt_characters(mem, ws, offs, rej=rej)
            self._tc_map = roblox.get_team_color_map(mem, players, offs)
            dead_list = roblox.get_dead_characters(mem, ws, offs)
            self._dead_cache = (now, dead_list)
            dead_pos = []
            for _dm, dbox in dead_list:
                dpos = dbox[0]
                if dpos:
                    dead_pos.append(dpos)
            ndl_now = len(dead_pos)
            self._last_ndl = ndl_now
            self._last_dead_pos = dead_pos
            raw_dead = roblox.get_deadbody_raw(mem, ws, offs)
            prev_raw = getattr(self, "_raw_dead_addrs", None)
            cur_raw = {a for a, _p in raw_dead}
            self._raw_dead_addrs = cur_raw
            now_pulses = []
            if prev_raw:
                for a, p in raw_dead:
                    if a in prev_raw or not p:
                        continue
                    dup = False
                    for pp, pts in getattr(self, "_pulse_seen", []):
                        ddx = p[0] - pp[0]
                        ddy = p[1] - pp[1]
                        ddz = p[2] - pp[2]
                        if ddx * ddx + ddy * ddy + ddz * ddz < 16.0 \
                                and now - pts < 2.0:
                            dup = True
                            break
                    if not dup:
                        now_pulses.append(p)
            if now_pulses:
                seen = getattr(self, "_pulse_seen", [])
                seen.extend((p, now) for p in now_pulses)
                self._pulse_ts = now
                self._pulse_n += len(now_pulses)
                self._pulse_positions = now_pulses
                self._pulse_fresh_event = True
            seen = getattr(self, "_pulse_seen", [])
            if seen:
                self._pulse_seen = [(sp, st) for sp, st in seen
                                    if now - st <= 10.0]
            if not found and esp.get("debug", False):
                pf = roblox.get_workspace_players_folder(mem, ws, offs)
                nteams = 0
                nmodels = 0
                if pf:
                    for team in roblox.get_children(mem, pf, offs):
                        if roblox.class_name(mem, team, offs) == "Folder":
                            nteams += 1
                            for m in roblox.get_children(mem, team, offs):
                                mc = roblox.class_name(mem, m, offs)
                                if mc == "Model":
                                    nmodels += 1
                self._last_probe = ("pf=0x{:X} teams={} models={} "
                                    "ws=0x{:X} rej={}".format(
                                        pf or 0, nteams, nmodels, ws or 0,
                                        rej))
            else:
                self._last_probe = "rej={}".format(rej) \
                    if rej is not None else ""
            for model, team_key, box, tfolder in found:
                if not self._rig_alive(mem, model, offs):
                    self._rig_last_box.pop(model, None)
                    self._rig_last_seen.pop(model, None)
                    self._rig_motion.pop(model, None)
                    continue
                hum = self._rig_hum.get(model, -1)
                if hum == -1:
                    hum = roblox.find_descendant_of_class(
                        mem, model, "Humanoid", offs) or 0
                    self._rig_hum[model] = hum
                if hum:
                    with_hum += 1
                    hoff = roblox.O(offs, "Humanoid", "Health")
                    if hoff:
                        try:
                            hp = mem.f32(hum + hoff)
                        except Exception:
                            hp = None
                        if hp is not None and hp <= 0.0:
                            dead_hum += 1
                            self._rig_last_box.pop(model, None)
                            self._rig_last_seen.pop(model, None)
                            self._rig_motion.pop(model, None)
                            continue
                pos_d = box[0]
                db_hit = False
                if pos_d:
                    for dpos in dead_pos:
                        dx = pos_d[0] - dpos[0]
                        dy = pos_d[1] - dpos[1]
                        dz = pos_d[2] - dpos[2]
                        if dx * dx + dy * dy + dz * dz < 6.25:
                            db_hit = True
                            break
                if db_hit:
                    dead_db += 1
                    self._rig_last_box.pop(model, None)
                    self._rig_last_seen.pop(model, None)
                    self._rig_motion.pop(model, None)
                    continue
                alt_models.append((model, team_key, box, tfolder))
                fresh_set.add(model)
                self._rig_last_seen[model] = now
                self._rig_last_box[model] = (team_key, box, tfolder)
            self._last_hum = (with_hum, dead_hum, dead_db)
            local_stale = now - self._last_local_pos_ts > 2.0
            for model in list(self._rig_last_box.keys()):
                if model in fresh_set:
                    continue
                if model in self._pulse_dead:
                    del self._rig_last_box[model]
                    self._rig_last_seen.pop(model, None)
                    continue
                if now - self._rig_last_seen.get(model, 0.0) <= 4.0:
                    if local_stale:
                        del self._rig_last_box[model]
                        self._rig_last_seen.pop(model, None)
                        continue
                    team_key, box, tfolder = self._rig_last_box[model]
                    alt_models.append((model, team_key, box, tfolder))
                else:
                    del self._rig_last_box[model]
                    self._rig_last_seen.pop(model, None)
            self._rig_fresh = fresh_set
            if len(self._rig_last_box) > 400:
                keep = {m for m, ts in self._rig_last_seen.items()
                        if now - ts <= 4.0}
                self._rig_last_box = {k: v for k, v in
                                      self._rig_last_box.items()
                                      if k in keep}
                self._rig_last_seen = {k: v for k, v in
                                       self._rig_last_seen.items()
                                       if k in keep}
                self._rig_hum = {k: v for k, v in
                                 self._rig_hum.items() if k in keep}
            self._alt_cache = (now, alt_models)
            if self._pulse_dead:
                self._pulse_dead = {a: t for a, t in
                                    self._pulse_dead.items()
                                    if now - t <= 6.0}
            if len(self._pulse_dead) > 200:
                self._pulse_dead.clear()
            if game_cfg and game_cfg.get("team_color_teams"):
                local_char = roblox.get_local_character_alt(mem, ws, offs)
                self._local_char = local_char or 0
                local_col = None
                if local_char:
                    local_col = roblox.dominant_part_color(mem, local_char,
                                                           offs)
                cols = {}
                for model, team_key, box, _tf in alt_models:
                    lst = cols.setdefault(team_key, [])
                    if len(lst) < 4:
                        c = roblox.dominant_part_color(mem, model, offs)
                        if c:
                            lst.append(c)
                folder_cols = {}
                for tk, lst in cols.items():
                    if not lst:
                        folder_cols[tk] = None
                        continue
                    chans = []
                    for i in range(3):
                        vals = sorted(c[i] for c in lst)
                        n = len(vals)
                        mid = n // 2
                        v = (vals[mid] + vals[(n - 1) // 2]) * 0.5
                        chans.append(v)
                    folder_cols[tk] = tuple(chans)
                self._color_cache = (now, (folder_cols, local_col))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._last_scan_err = repr(exc)[:120]
            status.log("[ESP-scan] ERROR {}".format(repr(exc)[:200]))
        finally:
            self._scan_busy = False
            self._last_scan_dur = time.time() - t0
            if self._last_scan_dur > 1.0:
                status.log("[ESP-scan] slow scan {:.2f}s".format(
                    self._last_scan_dur))

    def _rig_alive(self, mem, model, offs):
        cur = mem.ptr(model + roblox.O(offs, "Instance", "Parent"))
        for _ in range(6):
            if not cur:
                return True
            cls = roblox.class_name(mem, cur, offs)
            if not cls:
                return True
            nm = roblox.instance_name(mem, cur, offs)
            if cls == "Folder" and nm == "Ignore":
                return False
            if cls == "Folder" and nm == "Players":
                return True
            cur = mem.ptr(cur + roblox.O(offs, "Instance", "Parent"))
        return True

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
