import ctypes
import time

import config
import esp
import memory
import offsets
import roblox


def main():
    mem = memory.MemoryReader()
    if not mem.open(config.PROCESS_NAME):
        print("[!] Roblox not running.")
        return 1
    print("[+] pid={} base=0x{:X}".format(mem.pid, mem.base))

    offs = offsets.load(config.OFFSETS)["data"]

    dm = None
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        dm = roblox.get_datamodel(mem, offs)
        if dm:
            break
        time.sleep(0.5)
    if not dm:
        print("[!] No DataModel found. Be inside a game, not the menu.")
        return 1

    ws = roblox.get_workspace(mem, dm, offs)
    players = roblox.get_players(mem, dm, offs)
    local = roblox.get_local_player(mem, players, offs)
    print("[+] workspace={} players={} local={}".format(ws, players, local))

    local_name = roblox.instance_name(mem, local, offs) if local else "?"
    print("[+] local player: {}".format(local_name))

    def dump_instance(inst, depth, max_depth, path):
        if not inst or depth > max_depth:
            return
        cls = roblox.class_name(mem, inst, offs)
        name = roblox.instance_name(mem, inst, offs)
        pos = roblox.get_part_position(mem, inst, offs) if cls in roblox._PART_CLASSES else None
        extra = ""
        if cls in ("Part", "MeshPart", "HumanoidRootPart", "BasePart") and pos:
            extra = " @ ({:.1f},{:.1f},{:.1f})".format(*pos)
        print("{}|-- {} '{}'{}".format("  " * depth, cls, name, extra))
        for child in roblox.get_children(mem, inst, offs):
            dump_instance(child, depth + 1, max_depth, path)

    if local:
        char = roblox.get_character(mem, local, offs)
        print("[+] local character: {}".format(char))
        if char:
            dump_instance(char, 1, 3, "")

    for p in roblox.get_children(mem, players, offs):
        if roblox.class_name(mem, p, offs) != "Player":
            continue
        pname = roblox.instance_name(mem, p, offs)
        char = roblox.get_character(mem, p, offs)
        humanoid = roblox.get_humanoid(mem, char, offs) if char else 0
        hrp = roblox.get_root_part(mem, char, humanoid, offs) if char else 0
        pos = roblox.get_part_position(mem, hrp, offs) if hrp else None
        health = mem.f32(humanoid + roblox.O(offs, "Humanoid", "Health")) if humanoid else 0.0
        print("[{}] '{}' char={} hum={} hrp={} pos={} hp={:.0f}".format(
            "LOCAL" if p == local else "PLAYER",
            pname, char, humanoid, hrp,
            "({:.1f},{:.1f},{:.1f})".format(*pos) if pos else "?",
            health))

    print("[i] Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
