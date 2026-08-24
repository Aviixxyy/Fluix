import math
import struct

import config

CAMERA_FOCUS_FALLBACK = 0x12C


class Camera:
    __slots__ = ("pos", "right", "up", "look", "fov", "viewport")

    def __init__(self, pos, right, up, look, fov, viewport=None):
        self.pos = pos
        self.right = right
        self.up = up
        self.look = look
        self.fov = fov if fov and fov > 1.0 else math.radians(70.0)
        self.viewport = viewport


def O(data, *path):
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return 0
        cur = cur.get(key, 0)
    return cur if isinstance(cur, int) else 0


def _plausible(text):
    if not text or len(text) > 64:
        return False
    return all(32 <= ord(ch) < 127 for ch in text)


def class_name(mem, inst, offs):
    if not inst:
        return ""
    desc = mem.ptr(inst + O(offs, "Instance", "ClassDescriptor"))
    if not desc:
        return ""
    name_ptr = mem.ptr(desc + O(offs, "Instance", "ClassName"))
    if not name_ptr:
        return ""
    return mem.rbx_string(name_ptr)


def instance_name(mem, inst, offs):
    if not inst:
        return ""
    container = mem.ptr(inst + O(offs, "Instance", "NameContainer"))
    if container:
        for delta in (O(offs, "Instance", "Name"), 0):
            text = mem.rbx_string(container + delta)
            if _plausible(text):
                return text
    base = inst + O(offs, "Instance", "NameContainer")
    for delta in (0, O(offs, "Instance", "Name")):
        text = mem.rbx_string(base + delta)
        if _plausible(text):
            return text
    return ""


def get_children(mem, inst, offs):
    if not inst:
        return []
    container = mem.ptr(inst + O(offs, "Instance", "ChildrenStart"))
    if not container:
        return []
    start = mem.ptr(container)
    end = mem.ptr(container + O(offs, "Instance", "ChildrenEnd"))
    if not start or not end or end <= start:
        return []
    diff = end - start
    if diff > 16 * 20000:
        return []
    count = diff // 16
    buf = mem.read(start, count * 16)
    if not buf:
        return []
    out = []
    for i in range(count):
        addr = int.from_bytes(buf[i * 16:i * 16 + 8], "little")
        if addr:
            out.append(addr)
    return out


def find_child_of_class(mem, inst, cls, offs):
    for child in get_children(mem, inst, offs):
        if class_name(mem, child, offs) == cls:
            return child
    return 0


def find_descendant_of_class(mem, inst, cls, offs, limit=2000):
    """Depth-first search for any descendant of the given class, so nested
    rigs (custom models) are still found even when the target isn't a direct
    child."""
    if not inst:
        return 0
    stack = [inst]
    guard = 0
    while stack and guard < limit:
        guard += 1
        node = stack.pop()
        for child in get_children(mem, node, offs):
            if class_name(mem, child, offs) == cls:
                return child
            stack.append(child)
    return 0


def get_datamodel(mem, offs):
    base = mem.base
    ptr_off = O(offs, "FakeDataModel", "Pointer")
    if not base or not ptr_off:
        return 0
    fdm = mem.ptr(base + ptr_off)
    if not fdm:
        return 0
    dm = mem.ptr(fdm + O(offs, "FakeDataModel", "RealDataModel"))
    if not dm or class_name(mem, dm, offs) != "DataModel":
        return 0
    return dm


def get_workspace(mem, dm, offs):
    if not dm:
        return 0
    ws = mem.ptr(dm + O(offs, "DataModel", "Workspace"))
    if ws and class_name(mem, ws, offs) == "Workspace":
        return ws
    return find_child_of_class(mem, dm, "Workspace", offs)


def get_place_id(mem, dm, offs):
    """The game's place ID (DataModel.PlaceId), or 0 if unavailable."""
    if not dm:
        return 0
    off = O(offs, "DataModel", "PlaceId")
    if not off:
        return 0
    try:


        as_i = mem.u64(dm + off)
        as_f = mem.f64(dm + off)
        for v in (as_i, as_f):
            if v and 1000 <= v <= 10 ** 15:
                return int(v)
        return int(as_i) if as_i else 0
    except Exception:
        return 0


def get_game_id(mem, dm, offs):
    """The game's universe ID (DataModel.GameId), or 0 if unavailable."""
    if not dm:
        return 0
    off = O(offs, "DataModel", "GameId")
    if not off:
        return 0
    try:
        as_i = mem.u64(dm + off)
        as_f = mem.f64(dm + off)
        for v in (as_i, as_f):
            if v and 1000 <= v <= 10 ** 15:
                return int(v)
        return int(as_i) if as_i else 0
    except Exception:
        return 0


def get_camera(mem, ws, offs):
    if not ws:
        return 0
    cam = mem.ptr(ws + O(offs, "Workspace", "CurrentCamera"))
    if cam and class_name(mem, cam, offs) == "Camera":
        return cam
    return find_child_of_class(mem, ws, "Camera", offs)


def _vec_len(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _camera_valid(right, up, back, fov):
    for v in (right, up, back):
        if not (0.8 < _vec_len(v) < 1.2):
            return False
    if abs(_vec_dot(right, up)) > 0.2:
        return False
    if abs(_vec_dot(up, back)) > 0.2:
        return False
    if abs(_vec_dot(right, back)) > 0.2:
        return False
    if not (0.03 < fov < 2.6):
        return False
    return True


def read_camera(mem, cam, offs, anchor=None):
    """Read the camera.

    On this build Camera.Rotation at 0xD8 is a 9-float rotation matrix stored
    in column-major order (right.x, up.x, back.x, right.y, up.y, back.y,
    right.z, up.z, back.z), and Camera.Position at 0xFC is the real render
    camera position (stable, includes zoom). The camera looks along -back.
    """
    if not cam:
        return None
    rot_off = O(offs, "Camera", "Rotation") or 0xD8
    raw = mem.read(cam + rot_off, 36)
    if raw and len(raw) >= 36:
        rot = struct.unpack("<9f", raw)
    else:
        rot = mem.floats(cam + rot_off, 9)
    if not rot or len(rot) < 9:
        return None

    right = (rot[0], rot[3], rot[6])
    up = (rot[1], rot[4], rot[7])
    back = (rot[2], rot[5], rot[8])
    fov = mem.f32(cam + (O(offs, "Camera", "FieldOfView") or 0x140))
    if not _camera_valid(right, up, back, fov):
        return None
    stored = mem.vec3(cam + (O(offs, "Camera", "Position") or 0xFC))
    pos = stored
    if anchor and pos:
        d = float(config.ESP.get("camera_distance", 8.0))
        rx = anchor[0] - pos[0]
        ry = anchor[1] - pos[1]
        rz = anchor[2] - pos[2]
        L = math.sqrt(rx * rx + ry * ry + rz * rz)
        if L > 300.0:
            pos = (anchor[0] + back[0] * d,
                   anchor[1] + back[1] * d,
                   anchor[2] + back[2] * d)
    if not pos:
        return None
    viewport = mem.floats(cam + 712, 2) if mem else None
    return Camera(
        pos,
        right,
        up,
        (-back[0], -back[1], -back[2]),
        fov,
        viewport,
    )

def get_players(mem, dm, offs):
    return find_child_of_class(mem, dm, "Players", offs)


def get_local_player(mem, players, offs):
    if not players:
        return 0
    lp = mem.ptr(players + O(offs, "Player", "LocalPlayer"))
    if lp and class_name(mem, lp, offs) == "Player":
        return lp
    return 0


def get_character(mem, player, offs):
    if not player:
        return 0
    char = mem.ptr(player + O(offs, "Player", "ModelInstance"))
    if char and class_name(mem, char, offs) == "Model":
        return char
    for child in get_children(mem, player, offs):
        if class_name(mem, child, offs) == "Model":
            if find_descendant_of_class(mem, child, "Humanoid", offs):
                return child
    for child in get_children(mem, player, offs):
        if class_name(mem, child, offs) == "Folder":
            found = find_descendant_of_class(mem, child, "Model", offs)
            if found and find_descendant_of_class(mem, found, "Humanoid", offs):
                return found
    return 0


def get_humanoid(mem, char, offs):
    return find_descendant_of_class(mem, char, "Humanoid", offs)


_PART_CLASSES = frozenset({
    "Part", "HumanoidRootPart", "BasePart", "MeshPart", "WedgePart",
    "CylinderPart", "CornerWedgePart", "TrussPart", "Seat", "VehicleSeat",
    "SpawnLocation", "UnionOperation", "NegateOperation",
})


def get_root_part(mem, char, humanoid, offs):
    if humanoid:
        hrp = mem.ptr(humanoid + O(offs, "Humanoid", "HumanoidRootPart"))
        if hrp and class_name(mem, hrp, offs) in _PART_CLASSES:
            return hrp
    for child in get_children(mem, char, offs):
        if instance_name(mem, child, offs) == "HumanoidRootPart":
            return child
    found = find_descendant_of_class(mem, char, "HumanoidRootPart", offs)
    if found:
        return found
    return 0


def get_part_position(mem, part, offs):
    if not part:
        return None
    prim = mem.ptr(part + O(offs, "BasePart", "Primitive"))
    if not prim:
        return None
    return mem.vec3(prim + O(offs, "Primitive", "Position"))


def get_character_extents(mem, char, root_pos, offs):
    """Compute the character's (foot_offset, head_offset) relative to its
    root part, across all BasePart descendants of the model.

    Only parts within a plausible vertical band around the root part are
    counted, so floating accessories (hats, props) don't inflate the box.
    Returning offsets (not absolute Y) lets the box track the root part while
    jumping, even when the result is cached. Returns None if no usable parts
    were found.
    """
    if not char or not root_pos:
        return None
    root_y = root_pos[1]
    band_bottom = root_y - 6.0
    band_top = root_y + 20.0
    min_y = None
    max_y = None
    stack = [char]
    guard = 0
    while stack and guard < 2000:
        guard += 1
        inst = stack.pop()
        if class_name(mem, inst, offs) in _PART_CLASSES:
            pos = get_part_position(mem, inst, offs)
            if pos:
                y = pos[1]
                if y < band_bottom or y > band_top:
                    continue
                if min_y is None or y < min_y:
                    min_y = y
                if max_y is None or y > max_y:
                    max_y = y
        stack.extend(get_children(mem, inst, offs))
    if min_y is None or max_y is None or not (max_y - min_y > 0.1):
        return None

    if max_y - min_y > 30.0:
        return None
    foot_off = max(-8.0, min_y - root_y)
    head_off = min(16.0, max_y - root_y)
    return (foot_off, head_off)


def get_head_position(mem, char, offs, root_pos=None):
    """Find the character's head point, or None if it can't be found.

    Prefers a part literally named "Head", otherwise falls back to the
    highest part within the extents band so custom rigs still get a
    sensible aim point.
    """
    if not char:
        return None
    band_bottom = (root_pos[1] - 6.0) if root_pos else -1e18
    band_top = (root_pos[1] + 20.0) if root_pos else 1e18
    named = None
    top = None
    top_y = -1e18
    stack = [char]
    guard = 0
    while stack and guard < 2000:
        guard += 1
        inst = stack.pop()
        if class_name(mem, inst, offs) in _PART_CLASSES:
            pos = get_part_position(mem, inst, offs)
            if pos:
                y = pos[1]
                if root_pos and (y < band_bottom or y > band_top):
                    stack.extend(get_children(mem, inst, offs))
                    continue
                if instance_name(mem, inst, offs) == "Head":
                    named = pos
                if y > top_y:
                    top_y = y
                    top = pos
        stack.extend(get_children(mem, inst, offs))
    return named if named is not None else top


def get_workspace_players_folder(mem, ws, offs):
    """Find the workspace Folder named 'Players' (Phantom Forces hides
    character models there instead of parenting them to Player)."""
    if not ws:
        return 0
    for child in get_children(mem, ws, offs):
        if (class_name(mem, child, offs) == "Folder"
                and instance_name(mem, child, offs) == "Players"):
            return child
    return 0


def _alt_character_box(mem, model, offs, min_height=3.0, rej=None):
    """Compute (pos, extents, head, anchor_addr, anchor_pos) for a character
    model that carries no Humanoid (Phantom Forces custom rigs) by scanning
    its parts. ``anchor_addr``/``anchor_pos`` identify the part closest to
    the box centre so callers can re-track the rig cheaply between full
    scans by re-reading a single part position."""
    xs, ys, zs = [], [], []
    parts = []
    stack = [model]
    guard = 0
    while stack and guard < 300:
        guard += 1
        inst = stack.pop()
        if class_name(mem, inst, offs) in _PART_CLASSES:
            p = get_part_position(mem, inst, offs)
            if p:
                xs.append(p[0])
                ys.append(p[1])
                zs.append(p[2])
                parts.append((inst, p))
        stack.extend(get_children(mem, inst, offs))
    if len(xs) < 3:
        if rej is not None:
            rej["parts<4"] = rej.get("parts<4", 0) + 1
        return None
    min_y, max_y = min(ys), max(ys)
    height = max_y - min_y
    if not (1.0 <= height <= 30.0):
        if rej is not None:
            rej["height"] = rej.get("height", 0) + 1
        return None
    xw = max(xs) - min(xs)
    zw = max(zs) - min(zs)
    if xw > 8.0 or zw > 8.0:
        if rej is not None:
            rej["width"] = rej.get("width", 0) + 1
        return None
    if xw < 1.0 or zw < 1.0:
        if rej is not None:
            rej["thin"] = rej.get("thin", 0) + 1
        return None
    cx = (min(xs) + max(xs)) * 0.5
    cz = (min(zs) + max(zs)) * 0.5
    mid_y = min_y + height * 0.45
    pos = (cx, mid_y, cz)
    head = (cx, max_y - 0.15, cz)
    extents = (min_y - pos[1], max_y - pos[1])
    anchor = 0
    anchor_pos = None
    best = None
    for inst, p in parts:
        d2 = (p[0] - cx) ** 2 + (p[1] - mid_y) ** 2 + (p[2] - cz) ** 2
        if best is None or d2 < best:
            best = d2
            anchor = inst
            anchor_pos = p
    return (pos, extents, head, anchor, anchor_pos, len(parts))


def get_alt_characters(mem, ws, offs, limit=40, rej=None):
    """Phantom Forces-style characters: models under
    Workspace/Folder:Players/<team folder>/<model>, obfuscated names and no
    Humanoid. Returns a list of (model_addr, team_key, (pos, extents, head))."""
    out = []
    pf = get_workspace_players_folder(mem, ws, offs)
    if not pf:
        if rej is not None:
            rej["no_folder"] = rej.get("no_folder", 0) + 1
        return out
    for team in get_children(mem, pf, offs):
        if class_name(mem, team, offs) != "Folder":
            continue
        team_key = instance_name(mem, team, offs) or ""
        for model in get_children(mem, team, offs):
            if class_name(mem, model, offs) != "Model":
                continue
            box = _alt_character_box(mem, model, offs, rej=rej)
            if box:
                out.append((model, team_key, box, team))
                if len(out) >= limit:
                    return out
    return out


def dominant_part_color(mem, model, offs):
    """Most common part Color3 across a rig, as (r, g, b) floats in 0-1.

    Phantom Forces teams wear distinct uniform colours, so this is used
    to match the local rig (client-side only, in Folder:Ignore) to its
    team folder under Folder:Players.
    """
    counts = {}
    stack = [model]
    guard = 0
    col_off = O(offs, "BasePart", "Color3")
    while stack and guard < 2000:
        guard += 1
        inst = stack.pop()
        if class_name(mem, inst, offs) in _PART_CLASSES and col_off:
            r = mem.f32(inst + col_off)
            g = mem.f32(inst + col_off + 4)
            b = mem.f32(inst + col_off + 8)
            if r >= 0.0 and g >= 0.0 and b >= 0.0:
                key = (int(r * 50), int(g * 50), int(b * 50))
                counts[key] = counts.get(key, 0) + 1
        stack.extend(get_children(mem, inst, offs))
    if not counts:
        return None
    best = max(counts, key=counts.get)
    return (best[0] / 50.0, best[1] / 50.0, best[2] / 50.0)


def get_dead_characters(mem, ws, offs, limit=40):
    out = []
    if not ws:
        return out
    ignore = 0
    for child in get_children(mem, ws, offs):
        if (class_name(mem, child, offs) == "Folder"
                and instance_name(mem, child, offs) == "Ignore"):
            ignore = child
            break
    if not ignore:
        return out
    for child in get_children(mem, ignore, offs):
        if (class_name(mem, child, offs) != "Folder"
                or instance_name(mem, child, offs) != "DeadBody"):
            continue
        for model in get_children(mem, child, offs):
            if class_name(mem, model, offs) != "Model":
                continue
            box = _alt_character_box(mem, model, offs)
            if box:
                out.append((model, box))
                if len(out) >= limit:
                    return out
    return out


def get_deadbody_raw(mem, ws, offs, limit=60):
    """All models under Ignore/DeadBody with an approximate position,
    skipping shape guards so lying-flat corpses always count."""
    out = []
    if not ws:
        return out
    ignore = 0
    for child in get_children(mem, ws, offs):
        if (class_name(mem, child, offs) == "Folder"
                and instance_name(mem, child, offs) == "Ignore"):
            ignore = child
            break
    if not ignore:
        return out
    for child in get_children(mem, ignore, offs):
        if (class_name(mem, child, offs) != "Folder"
                or instance_name(mem, child, offs) != "DeadBody"):
            continue
        for model in get_children(mem, child, offs):
            if class_name(mem, model, offs) != "Model":
                continue
            pos = None
            box = _alt_character_box(mem, model, offs)
            if box:
                pos = box[0]
            else:
                for part in get_children(mem, model, offs):
                    pc = class_name(mem, part, offs)
                    if pc in ("Part", "MeshPart", "UnionOperation"):
                        pos = get_part_position(mem, part, offs)
                        if pos:
                            break
            out.append((model, pos))
            if len(out) >= limit:
                return out
    return out


def get_local_character_alt(mem, ws, offs):
    """Find the local player's character when it has been reparented under
    Workspace/Folder:Ignore (Phantom Forces keeps the local Humanoid there
    while remote characters lose theirs). Corpse models inside the DeadBody
    sub-folder are skipped so a nearby ragdoll can never pose as the local
    rig."""
    if not ws:
        return 0
    for child in get_children(mem, ws, offs):
        if class_name(mem, child, offs) != "Folder":
            continue
        if instance_name(mem, child, offs) != "Ignore":
            continue
        for sub in get_children(mem, child, offs):
            cn = class_name(mem, sub, offs)
            if cn == "Folder" and instance_name(mem, sub, offs) == "DeadBody":
                continue
            if (cn == "Model"
                    and find_descendant_of_class(mem, sub, "Humanoid", offs)):
                return sub
    return 0


def get_team_name(mem, player, offs):
    if not player:
        return ""
    team = mem.ptr(player + O(offs, "Player", "Team"))
    if not team:
        return ""
    return instance_name(mem, team, offs)


def get_team_color(mem, player, offs):
    """Return the player's TeamColor BrickColor id (0 if unset).

    Phantom Forces leaves Player.Team nil but sets TeamColor, so teams
    can be compared by this id when the preset opts in via team_color_teams.
    """
    if not player:
        return 0
    tc = O(offs, "Player", "TeamColor")
    if not tc:
        return 0
    return mem.u32(player + tc)


def get_team_color_map(mem, players, offs):
    """Map character-model address -> TeamColor id for every remote player,
    plus the local player's own TeamColor id.

    Phantom Forces leaves Player.Team nil, so TeamColor is the only
    per-player team signal. Matching the local id against the team folders'
    member models identifies the local team without spatial guesses and
    survives respawns and team switches."""
    out = {}
    local_tc = 0
    if not players:
        return out, local_tc
    lp = get_local_player(mem, players, offs)
    if lp:
        local_tc = get_team_color(mem, lp, offs)
    for child in get_children(mem, players, offs):
        if child == lp or class_name(mem, child, offs) != "Player":
            continue
        tc = get_team_color(mem, child, offs)
        if not tc:
            continue
        char = get_character(mem, child, offs)
        if char:
            out[char] = tc
    return out, local_tc


def get_equipped_tool(mem, char, offs):
    """Return the name of the tool currently equipped by a character.

    When a tool is equipped it gets parented directly to the character
    model, so scanning the character's children for a Tool/HopperBin is
    enough - no extra offsets required.
    """
    if not char:
        return ""
    for child in get_children(mem, char, offs):
        if class_name(mem, child, offs) in ("Tool", "HopperBin"):
            return instance_name(mem, child, offs)
    return ""


def get_backpack(mem, player, offs):
    """Find the player's Backpack instance (where unequipped tools live)."""
    if not player:
        return 0
    return find_child_of_class(mem, player, "Backpack", offs)


def get_inventory_tools(mem, player, char, offs):
    """Names of every tool a player owns: equipped + stored in the Backpack.

    Games like Murder Mystery 2 keep the role's weapon in the backpack, so
    role detection must read the whole inventory, not just the equipped tool.
    """
    names = []
    seen = set()
    for root in (char, get_backpack(mem, player, offs)):
        if not root:
            continue
        for child in get_children(mem, root, offs):
            if class_name(mem, child, offs) in ("Tool", "HopperBin"):
                n = instance_name(mem, child, offs)
                if n and n not in seen:
                    seen.add(n)
                    names.append(n)
    return names


def _item_position(mem, inst, offs):
    pos = get_part_position(mem, inst, offs)
    if pos:
        return pos
    for kid in get_children(mem, inst, offs):
        if class_name(mem, kid, offs) in _PART_CLASSES:
            pos = get_part_position(mem, kid, offs)
            if pos:
                return pos
    return None


def find_items(mem, ws, offs, classes):
    """Scan Workspace at 2 levels for dropped items of the given classes.

    Returns a list of (name, position) tuples. Containers (Model/Folder) and
    their children are checked so items parented inside folders are found.
    """
    items = []
    visited = 0
    for child in get_children(mem, ws, offs):
        visited += 1
        if visited > 500:
            break
        cls = class_name(mem, child, offs)
        if cls in classes:
            pos = _item_position(mem, child, offs)
            if pos:
                items.append((instance_name(mem, child, offs) or cls, pos))
        elif cls in ("Model", "Folder"):
            for kid in get_children(mem, child, offs):
                visited += 1
                if visited > 500:
                    break
                kcls = class_name(mem, kid, offs)
                if kcls in classes:
                    pos = _item_position(mem, kid, offs)
                    if pos:
                        items.append((instance_name(mem, kid, offs) or kcls, pos))
        if len(items) > 200:
            break
    return items


def world_to_screen(world, cam, vw, vh):
    if cam is None or world is None or vw <= 0 or vh <= 0:
        return None
    rx = world[0] - cam.pos[0]
    ry = world[1] - cam.pos[1]
    rz = world[2] - cam.pos[2]
    cx = rx * cam.right[0] + ry * cam.right[1] + rz * cam.right[2]
    cy = rx * cam.up[0] + ry * cam.up[1] + rz * cam.up[2]
    cz = rx * cam.look[0] + ry * cam.look[1] + rz * cam.look[2]
    if cz <= 0.1:
        return None


    focal = (vh / 2.0) / math.tan(cam.fov / 2.0)
    sx = vw / 2.0 + (cx / cz) * focal
    sy = vh / 2.0 - (cy / cz) * focal
    return (sx, sy)


def project_vertical(cam, center_world, world_h, vw, vh):
    """Project a world-space vertical segment of length ``world_h`` centred
    on ``center_world``. Returns (sx, sy, screen_h) where ``screen_h`` depends
    only on distance (not on camera pitch/roll), keeping ESP boxes a constant
    size regardless of camera angle."""
    if cam is None or center_world is None or vw <= 0 or vh <= 0:
        return None
    rx = center_world[0] - cam.pos[0]
    ry = center_world[1] - cam.pos[1]
    rz = center_world[2] - cam.pos[2]
    cx = rx * cam.right[0] + ry * cam.right[1] + rz * cam.right[2]
    cy = rx * cam.up[0] + ry * cam.up[1] + rz * cam.up[2]
    cz = rx * cam.look[0] + ry * cam.look[1] + rz * cam.look[2]
    if cz <= 0.1:
        return None
    focal = (vh / 2.0) / math.tan(cam.fov / 2.0)
    sx = vw / 2.0 + (cx / cz) * focal
    sy = vh / 2.0 - (cy / cz) * focal
    return (sx, sy, max(0.0, focal * world_h / cz))


def tracer_endpoint(world, cam, vw, vh):
    """Screen point a tracer line should aim at. On-screen targets return the
    exact projection (edge=False). Off-screen or behind-camera targets return
    the point where the true-bearing ray from screen centre crosses the window
    edge (edge=True), turning the tracer into an off-screen indicator."""
    if cam is None or world is None or vw <= 0 or vh <= 0:
        return None
    rx = world[0] - cam.pos[0]
    ry = world[1] - cam.pos[1]
    rz = world[2] - cam.pos[2]
    cx = rx * cam.right[0] + ry * cam.right[1] + rz * cam.right[2]
    cy = rx * cam.up[0] + ry * cam.up[1] + rz * cam.up[2]
    cz = rx * cam.look[0] + ry * cam.look[1] + rz * cam.look[2]
    focal = (vh / 2.0) / math.tan(cam.fov / 2.0)
    if cz > 0.1:
        sx = vw / 2.0 + (cx / cz) * focal
        sy = vh / 2.0 - (cy / cz) * focal
        if 0.0 <= sx <= vw and 0.0 <= sy <= vh:
            return (sx, sy, False)
    dx = cx
    dy = -cy
    mag = math.hypot(dx, dy)
    if mag < 1e-6:
        return None
    ux = dx / mag
    uy = dy / mag
    margin = 10.0
    ox = vw / 2.0
    oy = vh / 2.0
    ts = []
    if ux > 1e-6:
        ts.append((vw - margin - ox) / ux)
    elif ux < -1e-6:
        ts.append((margin - ox) / ux)
    if uy > 1e-6:
        ts.append((vh - margin - oy) / uy)
    elif uy < -1e-6:
        ts.append((margin - oy) / uy)
    if not ts:
        return None
    t = max(0.0, min(ts))
    return (ox + ux * t, oy + uy * t, True)
