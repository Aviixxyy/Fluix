import numpy as np

import roblox

_PART_CLASSES = frozenset({
    "Part", "MeshPart", "WedgePart", "CylinderPart", "CornerWedgePart",
    "TrussPart",
})
_SCAN_CAP = 3500
_BATCH = 150
_NODE_CAP = 6000


class OcclusionTracker:
    def __init__(self, mem, offs):
        self.mem = mem
        self.offs = offs
        self._boxes = np.zeros((_SCAN_CAP, 6), dtype=np.float64)
        self._count = 0
        self._queue = []
        self._next_scan = 0.0
        self._refresh = 4.0

    def drop(self):
        self._count = 0
        self._queue = []

    def set_refresh(self, seconds):
        self._refresh = max(0.5, float(seconds))

    def pump(self, now, ws):
        if now >= self._next_scan:
            self._next_scan = now + self._refresh
            self._queue = self._collect(ws)
            self._count = 0
        if not self._queue:
            return
        mem = self.mem
        offs = self.offs
        prim_off = roblox.O(offs, "BasePart", "Primitive")
        pos_off = roblox.O(offs, "Primitive", "Position")
        size_off = roblox.O(offs, "Primitive", "Size")
        rot_off = roblox.O(offs, "Primitive", "Rotation")
        box = []
        n = min(_BATCH, len(self._queue))
        for _ in range(n):
            addr = self._queue.pop(0)
            prim = mem.ptr(addr + prim_off)
            if not prim:
                continue
            pos = mem.vec3(prim + pos_off)
            if not pos:
                continue
            size = mem.vec3(prim + size_off)
            if not size:
                continue
            hx = size[0] * 0.5
            hy = size[1] * 0.5
            hz = size[2] * 0.5
            if min(hx, hy, hz) < 0.4 or max(hx, hy, hz) > 300.0:
                continue
            rot = mem.floats(prim + rot_off, 12) if rot_off else None
            corners = ((hx, hy, hz), (hx, hy, -hz), (hx, -hy, hz),
                       (hx, -hy, -hz), (-hx, hy, hz), (-hx, hy, -hz),
                       (-hx, -hy, hz), (-hx, -hy, -hz))
            mins = [1e18] * 3
            maxs = [-1e18] * 3
            for cx, cy, cz in corners:
                wx, wy, wz = cx, cy, cz
                if rot is not None and len(rot) >= 9:
                    wx = rot[0] * cx + rot[3] * cy + rot[6] * cz
                    wy = rot[1] * cx + rot[4] * cy + rot[7] * cz
                    wz = rot[2] * cx + rot[5] * cy + rot[8] * cz
                wx += pos[0]
                wy += pos[1]
                wz += pos[2]
                if wx < mins[0]:
                    mins[0] = wx
                if wy < mins[1]:
                    mins[1] = wy
                if wz < mins[2]:
                    mins[2] = wz
                if wx > maxs[0]:
                    maxs[0] = wx
                if wy > maxs[1]:
                    maxs[1] = wy
                if wz > maxs[2]:
                    maxs[2] = wz
            if mins[0] <= maxs[0] and mins[1] <= maxs[1] and mins[2] <= maxs[2]:
                box.append((mins[0], mins[1], mins[2],
                            maxs[0], maxs[1], maxs[2]))
        if box:
            total = self._count + len(box)
            if total > _SCAN_CAP:
                box = box[: _SCAN_CAP - self._count]
                total = _SCAN_CAP
            arr = np.asarray(box, dtype=np.float64)
            self._boxes[self._count:total] = arr[:total - self._count]
            self._count = total

    def _collect(self, ws):
        mem = self.mem
        offs = self.offs
        parts = []
        stack = [ws]
        guard = 0
        while stack and len(parts) < _SCAN_CAP and guard < _NODE_CAP:
            guard += 1
            inst = stack.pop()
            if not inst:
                continue
            cls = roblox.class_name(mem, inst, offs)
            if cls in _PART_CLASSES:
                parts.append(inst)
                continue
            if cls in ("Model", "Folder", "Workspace", "SpawnLocation",
                       "Backpack", "Tool", "Terrain"):
                stack.extend(roblox.get_children(mem, inst, offs))
        return parts

    def ready(self):
        return self._count > 0

    def raycast_many(self, a0, points):
        if not points or not self._count:
            return [False] * len(points)
        pts = np.asarray(points, dtype=np.float64)
        n = self._count
        m = pts.shape[0]
        boxes = self._boxes[:n]
        mn = boxes[:, 0:3]
        mx = boxes[:, 3:6]
        inside0 = np.all((a0 >= mn) & (a0 <= mx), axis=1)
        keep = ~inside0
        sub_mn = mn[keep]
        sub_mx = mx[keep]
        if sub_mn.shape[0] == 0:
            return [False] * m
        p = pts[None, :, :]
        inside1 = np.all((p >= sub_mn[:, None, :]) & (p <= sub_mx[:, None, :]),
                         axis=2)
        t0 = np.zeros((sub_mn.shape[0], m))
        t1 = np.ones((sub_mn.shape[0], m))
        d = p - a0
        for i in range(3):
            di = d[0, :, i]
            inv = 1.0 / np.where(np.abs(di) < 1e-9, 1e-9, di)
            lo = (sub_mn[:, i] - a0[i])[:, None]
            hi = (sub_mx[:, i] - a0[i])[:, None]
            ea = lo * inv[None, :]
            eb = hi * inv[None, :]
            lo2 = np.minimum(ea, eb)
            hi2 = np.maximum(ea, eb)
            t0 = np.maximum(t0, lo2)
            t1 = np.minimum(t1, hi2)
            if (t1 < t0).all():
                return [False] * m
        blocked = (t0 <= t1) & (t1 >= 0.0) & (t0 <= 1.0) & (~inside1)
        return blocked.any(axis=0).tolist()
