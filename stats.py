"""Runtime auto-finder for the game's FPS frame-counter and ping value.

The offsets dump has no Stats/network entries, so this scans the live Roblox
process once per version (cached in stats_cache.json) to locate:

* a monotonic int32 frame counter that advances roughly once per rendered
  frame (game FPS is derived from its rate of change), and
* an int32 latency value that changes occasionally in a plausible ping range.

Both are heuristic scans - they run in a background thread, are validated on
each launch, and fall back to the overlay draw rate / "--" if they fail.
"""

import ctypes
import json
import os
import struct
import threading
import time

import config
import memory

try:
    import numpy as np
    HAVE_NUMPY = True
except Exception:
    np = None
    HAVE_NUMPY = False

_CACHE = os.path.join(config.app_dir(), "stats_cache.json")

_PAGE_READWRITE = 0x04
_PAGE_WRITECOPY = 0x08
_PAGE_EXECUTE_READWRITE = 0x40
_PAGE_EXECUTE_WRITECOPY = 0x80
_WRITABLE = (_PAGE_READWRITE, _PAGE_WRITECOPY,
             _PAGE_EXECUTE_READWRITE, _PAGE_EXECUTE_WRITECOPY)

CHUNK = 8 * 1024 * 1024
MAX_SCAN_BYTES = 192 * 1024 * 1024
SAMPLES = 5
SAMPLE_GAP = 0.15
FRAME_DELTA_MAX = 32
PING_MAX = 2500


def _writable_regions(mem):
    """Yield (addr, size) of committed, readable, writable memory."""
    handle = getattr(mem, "handle", 0)
    if not handle:
        return
    addr = 0
    mbi = memory.MEMORY_BASIC_INFORMATION()
    while addr < 0x7FFF00000000:
        got = memory.kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(addr), ctypes.byref(mbi),
            ctypes.sizeof(mbi))
        if not got or mbi.RegionSize == 0:
            break
        size = int(mbi.RegionSize)
        if (mbi.State == memory.MEM_COMMIT and size and
                (mbi.Protect & 0xFF) in _WRITABLE and
                not (mbi.Protect & memory.PAGE_GUARD)):
            yield (addr, size)
        addr += size


def _chunks(regions):
    """Split regions into bounded read-sized chunks for sampling."""
    out = []
    for addr, size in regions:
        done = 0
        while done < size:
            n = min(CHUNK, size - done)
            out.append((addr + done, n))
            done += n
    return out


def _read_flats(mem, chunks):
    """Sample every chunk once into a list of raw byte buffers."""
    out = []
    for addr, size in chunks:
        try:
            buf = mem.read(addr, size)
        except Exception:
            buf = None
        out.append(buf)
        time.sleep(0.001)
    return out


def _diff(prev_bufs, cur_bufs, frame_cands, ping_cands):
    """Accumulate candidates across one sampling pair.

    frame_cands[bi][i] -> list of deltas seen for that 4-byte slot
    ping_cands[bi][i]  -> {"jumps": [deltas], "stable": #observations in range}
    """
    P = PING_MAX
    for bi, (a, b) in enumerate(zip(prev_bufs, cur_bufs)):
        if not a or not b or len(a) != len(b):
            continue
        n = len(a) // 4
        if not n:
            continue
        fe = frame_cands.setdefault(bi, {})
        pe = ping_cands.setdefault(bi, {})
        prev_tracked = set(pe.keys())
        if HAVE_NUMPY:
            va = np.frombuffer(a, np.int32, count=n)
            vb = np.frombuffer(b, np.int32, count=n)
            d = vb - va
            idx = np.flatnonzero((d >= 0) & (d <= FRAME_DELTA_MAX))
            for j in idx.tolist():
                lst = fe.get(j)
                if lst is None:
                    lst = []
                    fe[j] = lst
                lst.append(int(d[j]))
            idx = np.flatnonzero((va >= 1) & (va <= P) & (vb >= 1) &
                                 (vb <= P) & (va != vb) & (np.abs(d) <= 60))
            for j in idx.tolist():
                rec = pe.get(j)
                if rec is None:
                    rec = {"jumps": [], "stable": 0}
                    pe[j] = rec
                rec["jumps"].append(int(d[j]))
            if prev_tracked:
                for j in prev_tracked:
                    if 1 <= int(va[j]) <= P and 1 <= int(vb[j]) <= P:
                        pe[j]["stable"] += 1
        else:
            ia = struct.iter_unpack("<i", a)
            ib = struct.iter_unpack("<i", b)
            for i, (pa, pb) in enumerate(zip(ia, ib)):
                v1, v2 = pa[0], pb[0]
                d = v2 - v1
                if 0 <= d <= FRAME_DELTA_MAX:
                    lst = fe.get(i)
                    if lst is None:
                        lst = []
                        fe[i] = lst
                    lst.append(d)
                if (1 <= v1 <= P and 1 <= v2 <= P and v1 != v2 and
                        abs(d) <= 60):
                    rec = pe.get(i)
                    if rec is None:
                        rec = {"jumps": [], "stable": 0}
                        pe[i] = rec
                    rec["jumps"].append(d)
                if i in prev_tracked and 1 <= v1 <= P and 1 <= v2 <= P:
                    pe[i]["stable"] += 1


def _addr_of(chunks, bi, i):
    return chunks[bi][0] + i * 4


def _pick_fps(chunks, frame_cands, hint=None):
    """Pick the counter whose derived per-sample FPS is most stable.

    Every candidate increased by 1..FRAME_DELTA_MAX on several samples; the
    render frame counter advances at a steady per-frame rate, so we keep the
    candidate with the smallest spread across sample-to-sample FPS readings.
    When a measured overlay FPS hint is available it is used as a tiebreaker.
    """
    best_addr = 0
    best_score = None
    gap = max(SAMPLE_GAP, 0.05)
    for bi, items in frame_cands.items():
        for i, deltas in items.items():
            if len(deltas) < SAMPLES - 2:
                continue
            rates = [d / gap for d in deltas]
            avg = sum(rates) / len(rates)
            if not (15.0 <= avg <= 600.0):
                continue
            dev = sum(abs(r - avg) for r in rates) / len(rates)
            if hint:
                dist = abs(avg - hint)

                if dist > max(15.0, hint * 0.35):
                    continue
                score = dist + dev * 0.2
            else:
                score = dev
            if best_score is None or score < best_score:
                best_score = score
                best_addr = _addr_of(chunks, bi, i)
    return best_addr


def _pick_ping(chunks, ping_cands, frame_cands):
    """Pick the candidate with the most stable plausible latency value.

    A real ping value stays within a small range for most samples and only
    occasionally jumps by a few ms - unlike heap garbage or monotonic counters.
    Strong monotonic (FPS) candidates are excluded up front.
    """
    excluded = set()
    for bi, items in frame_cands.items():
        for i, deltas in items.items():
            if len(deltas) >= SAMPLES - 2:
                excluded.add((bi, i))
    best_addr = 0
    best_score = None
    max_pairs = SAMPLES - 1
    for bi, items in ping_cands.items():
        for i, rec in items.items():
            if (bi, i) in excluded:
                continue
            jumps = rec["jumps"]
            stable = rec["stable"]
            if not jumps or len(jumps) > 3:
                continue
            if stable < 1:
                continue
            dev = sum(abs(d) for d in jumps) / len(jumps)

            score = dev + abs(len(jumps) - 2) * 10.0
            score += (max_pairs - min(max_pairs, stable)) * 25.0
            if best_score is None or score < best_score:
                best_score = score
                best_addr = _addr_of(chunks, bi, i)
    return best_addr


def _scan_once(mem, hint=None):
    regions = []
    scanned = 0
    max_bytes = MAX_SCAN_BYTES if HAVE_NUMPY else 32 * 1024 * 1024
    for addr, size in _writable_regions(mem):
        if scanned >= max_bytes:
            break
        size = min(size, max_bytes - scanned)
        regions.append((addr, size))
        scanned += size
    if not regions:
        return 0, 0
    chunks = _chunks(regions)

    prev = _read_flats(mem, chunks)
    frame_cands = {}
    ping_cands = {}
    for _ in range(SAMPLES - 1):
        time.sleep(SAMPLE_GAP)
        cur = _read_flats(mem, chunks)
        _diff(prev, cur, frame_cands, ping_cands)
        prev = cur

    return (_pick_fps(chunks, frame_cands, hint),
            _pick_ping(chunks, ping_cands, frame_cands))


class Finder:
    def __init__(self, mem):
        self.mem = mem
        self.fps_addr = 0
        self.ping_addr = 0
        self.state = "idle"
        self._fps_last = None
        self._fps_ts = None
        self._fps_hint = None



    def fps(self):
        """Live game FPS from the discovered frame counter (or None)."""
        if self.state != "done" or not self.fps_addr:
            return None
        try:
            count = self.mem.u32(self.fps_addr)
            now = time.monotonic()
            if self._fps_last is not None and now > self._fps_ts:
                dt = now - self._fps_ts
                d = count - self._fps_last
                if dt > 0.05 and 0 <= d <= 2000:
                    value = d / dt
                    if 1.0 <= value <= 1000.0:
                        self._fps_last = count
                        self._fps_ts = now
                        return round(value, 1)
            self._fps_last = count
            self._fps_ts = now
            return None
        except Exception:
            return None

    def ping(self):
        if self.state != "done" or not self.ping_addr:
            return None
        try:
            v = self.mem.u32(self.ping_addr)
            if 1 <= v <= PING_MAX:
                return v
        except Exception:
            pass
        return None



    def invalidate(self):
        self.state = "idle"
        self.fps_addr = 0
        self.ping_addr = 0
        self._fps_last = None
        self._fps_ts = None

    def scan_async(self, version, on_done=None, fps_hint=None):
        if self.state == "scanning":
            return
        self.state = "scanning"
        self._fps_hint = fps_hint

        def _run():
            try:
                import ctypes
                try:
                    ctypes.windll.kernel32.SetThreadPriority(
                        ctypes.windll.kernel32.GetCurrentThread(), -15)
                except Exception:
                    pass
                addrs = _load_cache(version)
                if addrs and self._validate(addrs):
                    self.fps_addr = addrs[0]
                    self.ping_addr = addrs[1]
                    self.state = "done"
                    if on_done:
                        on_done()
                    return
                hint = None
                if self._fps_hint is not None:
                    try:
                        hint = float(self._fps_hint() or 0.0) or None
                    except Exception:
                        hint = None
                fps, ping = _scan_once(self.mem, hint=hint)
                self.fps_addr = fps
                self.ping_addr = ping
                self.state = "done"
                _save_cache(version, (fps, ping))
            except Exception:
                self.state = "failed"
            if on_done:
                on_done()

        threading.Thread(target=_run, name="StatsScan", daemon=True).start()

    def _validate(self, addrs):
        fps, ping = addrs
        try:
            if fps and not (0 <= self.mem.u32(fps) < 2 ** 31):
                return False
        except Exception:
            return False
        try:
            if ping and not (1 <= self.mem.u32(ping) <= PING_MAX):
                return False
        except Exception:
            return False
        return True


def _load_cache(version):
    try:
        with open(_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") == version:
            return (data.get("fps") or 0, data.get("ping") or 0)
    except Exception:
        pass
    return None


def _save_cache(version, addrs):
    try:
        with open(_CACHE, "w", encoding="utf-8") as f:
            json.dump({"version": version, "fps": addrs[0],
                       "ping": addrs[1]}, f)
    except Exception:
        pass
