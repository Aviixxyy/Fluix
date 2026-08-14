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
    stored = mem.vec3(cam + (O(offs, "Camera", "Position") or 0xFC))
    pos = stored
    if anchor and pos:




        d = float(config.ESP.get("camera_distance", 8.0))
        rx = anchor[0] - pos[0]
        ry = anchor[1] - pos[1]
        rz = anchor[2] - pos[2]
        L = math.sqrt(rx * rx + ry * ry + rz * rz)
        if L < 0.1 or L > 300.0:
            pos = (anchor[0] - back[0] * d,
                   anchor[1] - back[1] * d,
                   anchor[2] - back[2] * d)
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
            if find_child_of_class(mem, child, "Humanoid", offs):
                return child
    return 0


def get_humanoid(mem, char, offs):
    return find_child_of_class(mem, char, "Humanoid", offs)


_PART_CLASSES = frozenset({
    "Part", "HumanoidRootPart", "BasePart", "MeshPart", "WedgePart",
    "CylinderPart", "CornerWedgePart", "TrussPart",
})


def get_root_part(mem, char, humanoid, offs):
    if humanoid:
        hrp = mem.ptr(humanoid + O(offs, "Humanoid", "HumanoidRootPart"))
        if hrp and class_name(mem, hrp, offs) in _PART_CLASSES:
            return hrp
    for child in get_children(mem, char, offs):
        if instance_name(mem, child, offs) == "HumanoidRootPart":
            return child
    return 0


def get_part_position(mem, part, offs):
    if not part:
        return None
    prim = mem.ptr(part + O(offs, "BasePart", "Primitive"))
    if not prim:
        return None
    return mem.vec3(prim + O(offs, "Primitive", "Position"))


def get_character_extents(mem, char, root_pos, offs):
    """Compute (min_y, max_y) across all BasePart descendants of a model.

    Only parts within a plausible vertical band around the root part are
    counted, so floating accessories (hats, props) don't inflate the box.
    Returns None if no usable parts were found.
    """
    if not char or not root_pos:
        return None
    root_y = root_pos[1]
    band_bottom = root_y - 3.0
    band_top = root_y + 12.0
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

    if max_y - min_y > 14.0:
        return None
    return (min_y, max_y)


def get_team_name(mem, player, offs):
    if not player:
        return ""
    team = mem.ptr(player + O(offs, "Player", "Team"))
    if not team:
        return ""
    return instance_name(mem, team, offs)


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


def tracer_endpoint(world, cam, vw, vh):
    """Screen point a tracer line should aim at, including for targets behind
    the camera. Behind-camera targets project onto the correct screen side
    (turn-right -> right edge) and get clamped into view."""
    if cam is None or world is None or vw <= 0 or vh <= 0:
        return None
    rx = world[0] - cam.pos[0]
    ry = world[1] - cam.pos[1]
    rz = world[2] - cam.pos[2]
    cx = rx * cam.right[0] + ry * cam.right[1] + rz * cam.right[2]
    cy = rx * cam.up[0] + ry * cam.up[1] + rz * cam.up[2]
    cz = rx * cam.look[0] + ry * cam.look[1] + rz * cam.look[2]
    if abs(cz) < 0.1:
        return None
    focal = (vh / 2.0) / math.tan(cam.fov / 2.0)
    m = abs(cz)
    sx = vw / 2.0 + (cx / m) * focal
    sy = vh / 2.0 - (cy / m) * focal
    if cz > 0.1:
        return (sx, sy)
    margin = 8
    sx = max(margin, min(vw - margin, sx))
    sy = max(margin, min(vh - margin, sy))
    return (sx, sy)
