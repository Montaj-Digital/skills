"""Manual cut editing: move a reel from one cut list (work/edl.json segments, raw camera times) to another.

The editor sends a new segment list; this module works out where every edited-timeline time lands
afterwards and rewrites the transcript, captions and reel.json timings to match, so nothing has to be
transcribed or planned again. Pure functions: server.py does the file handling and the re-render.
"""
import copy, zlib

MIN_SEG = 0.1          # shortest clip worth keeping (s)

# Inserts (Studio AI): a segment with "src" plays another file. Its in/out are seconds in that file. In memory (here and
# in the editor) they're moved into a "virtual camera time" range of their own, far past any real camera file, so every
# function that compares camera-time ranges (find, split, trim, the remapping below) works unchanged and an insert can
# never overlap the camera. Each inserted file is copied under its own name, so two inserts never share a range.


def vbase(src):
    return 100000.0 * (1 + zlib.crc32(str(src).encode()) % 9000)


def to_virtual(segs, clip_len=None):
    """Segments as stored in edl.json -> the editor's view (inserts shifted to their own range; `clip` = file length)."""
    out = []
    for s in segs:
        if s.get("src"):
            b = vbase(s["src"])
            s = dict(s, vbase=b, **{"in": round(float(s["in"]) + b, 3), "out": round(float(s["out"]) + b, 3)})
            if clip_len and "clip" not in s:
                s["clip"] = clip_len(s["src"])
        out.append(s)
    return out


def to_real(segs):
    """The editor's view -> edl.json (inserts back to seconds in their own file)."""
    out = []
    for s in segs:
        if s.get("src"):
            b = vbase(s["src"])
            s = {k: v for k, v in s.items() if k not in ("vbase", "zoom", "pan")}
            s["in"], s["out"] = round(float(s["in"]) - b, 3), round(float(s["out"]) - b, 3)
        out.append(s)
    return out


def clean_segments(segs, raw_dur=None):
    """Validate and tidy a segment list from the editor (raw in/out seconds, other keys kept)."""
    out = []
    for s in segs:
        a, b = float(s["in"]), float(s["out"])
        if s.get("src"):                                    # an insert: keep it inside its own file
            lo = vbase(s["src"]); hi = lo + float(s.get("clip") or (b - lo))
            a, b = max(lo, min(a, hi)), max(lo, min(b, hi))
        elif raw_dur:
            a, b = max(0.0, min(a, raw_dur)), max(0.0, min(b, raw_dur))
        if b - a < MIN_SEG:
            continue
        n = dict(s)
        n["in"], n["out"] = round(a, 3), round(b, 3)
        out.append(n)
    if not out:
        raise ValueError("That would remove the whole video")
    return out


class Timeline:
    """Edited time <-> raw time for one cut list (segments play back to back)."""

    def __init__(self, segs):
        self.segs, self.acc, t = segs, [], 0.0
        for s in segs:
            self.acc.append(t)
            t += float(s["out"]) - float(s["in"])
        self.dur = t

    def to_raw(self, t):
        for s, a in zip(self.segs, self.acc):
            d = float(s["out"]) - float(s["in"])
            if t < a + d:
                return float(s["in"]) + max(0.0, t - a)
        s = self.segs[-1]
        return float(s["out"]) + (t - self.dur)          # past the end (end screen)

    def find(self, r):
        """Index of the segment that plays raw time r, or None if r was cut."""
        for k, s in enumerate(self.segs):
            if float(s["in"]) - 1e-6 <= r < float(s["out"]) - 1e-6:
                return k
        return None

    def to_edit(self, r):
        """(edited time, kept?). A cut raw time lands where playback carries on after the gap."""
        k = self.find(r)
        if k is not None:
            return self.acc[k] + r - float(self.segs[k]["in"]), True
        space = int(r // 100000)                            # 0 = the camera file; an insert's own range otherwise
        nxt = [(float(s["in"]), a) for s, a in zip(self.segs, self.acc) if float(s["in"]) >= r and int(float(s["in"]) // 100000) == space]
        return (min(nxt)[1] if nxt else self.dur), False


def remapper(old_segs, new_segs):
    old, new = Timeline(old_segs), Timeline(new_segs)

    def f(t):
        if t >= old.dur - 1e-6:                            # end screen and beyond keep their offset from the end
            return round(new.dur + (t - old.dur), 3), True
        r = old.to_raw(t)
        if r >= 100000 and new.find(r) is None:            # inside an insert that was taken out: land where it was
            k = old.find(r)
            after = [float(s["in"]) for s in old.segs[(k if k is not None else -1) + 1:] if not s.get("src")]
            return round(new.to_edit(after[0])[0] if after else new.dur, 3), False
        e, kept = new.to_edit(r)
        return round(e, 3), kept
    return f, old, new


# ------------------------------------------------------------------ words
def remap_words(old_words, raw_words, old_segs, new_segs):
    """Words for the new edit, plus old index -> new index (None when the word was cut).

    Old words keep their (corrected) text; raw material brought back by a trim takes its words from the raw
    transcript, mapped onto the new timeline."""
    f, old, new = remapper(old_segs, new_segs)
    keep = []                                              # (start, end, word, old index or None)
    for i, w in enumerate(old_words):
        mid = (w["start"] + w["end"]) / 2
        r = old.to_raw(mid)
        if new.find(r) is None:
            continue
        k = new.find(r)
        lo, hi = new.acc[k], new.acc[k] + float(new_segs[k]["out"]) - float(new_segs[k]["in"])
        s = min(max(new.to_edit(old.to_raw(w["start"]))[0], lo), hi)
        e = min(max(new.to_edit(old.to_raw(max(w["start"], w["end"] - 1e-4)))[0], lo), hi)
        if new.find(old.to_raw(w["start"])) != k:
            s = lo
        keep.append((s, max(e, s + 0.02), w, i))
    # raw material that wasn't in the old edit at all
    for w in raw_words or []:
        mid = (float(w["start"]) + float(w["end"])) / 2
        if old.find(mid) is not None:
            continue
        k = new.find(mid)
        if k is None:
            continue
        s = new.to_edit(max(float(w["start"]), float(new_segs[k]["in"])))[0]
        e = new.to_edit(min(float(w["end"]), float(new_segs[k]["out"]) - 1e-4))[0]
        keep.append((s, max(e, s + 0.02), w, None))
    keep.sort(key=lambda x: x[0])
    words, index, n_new = [], {}, 0
    for j, (s, e, w, i) in enumerate(keep):
        nw = {k: v for k, v in w.items() if k not in ("start", "end")}
        nw["start"], nw["end"] = round(s, 3), round(e, 3)
        if i is None:
            n_new += 1
            nw["id"] = f"r{n_new}"
        else:
            index[i] = j
        words.append(nw)
    return words, index


def remap_captions(cap, index, n_words, max_words=3):
    """Move caption word indices (fix, drop, keywords, groups) onto the new word list."""
    cap = copy.deepcopy(cap or {})
    if "fix" in cap:
        cap["fix"] = {str(index[int(k)]): v for k, v in cap["fix"].items() if int(k) in index}
    for key in ("drop", "keywords"):
        if key in cap:
            cap[key] = sorted(index[i] for i in cap[key] if i in index)
    if cap.get("groups"):
        groups = []
        for a, b in cap["groups"]:
            got = [index[i] for i in range(a, b + 1) if i in index]
            if got:
                groups.append([min(got), max(got)])
        covered = set()
        for a, b in groups:
            covered.update(range(a, b + 1))
        run = []                                           # words brought back by a trim get groups of their own
        for j in range(n_words + 1):
            if j < n_words and j not in covered:
                run.append(j)
                continue
            for k in range(0, len(run), max_words):
                chunk = run[k:k + max_words]
                groups.append([chunk[0], chunk[-1]])
            run = []
        cap["groups"] = sorted(groups)
    return cap


# ------------------------------------------------------------------ reel.json timings
def _refs(c):
    """Every time on an item: (getter, setter) pairs, mirroring refs() in app.js, plus out/until."""
    out = []
    for k in list(c.keys()):
        if (k == "t" or k.startswith("t_") or k in ("dim_at", "out", "until")) and isinstance(c[k], (int, float)) and not isinstance(c[k], bool):
            out.append((k, (lambda k=k: c[k]), (lambda v, k=k: c.__setitem__(k, v))))
    if isinstance(c.get("times"), list):
        for i, v in enumerate(c["times"]):
            if isinstance(v, (int, float)):
                out.append(("times", (lambda i=i: c["times"][i]), (lambda v, i=i: c["times"].__setitem__(i, v))))
    for key in ("leads", "items"):
        if isinstance(c.get(key), list):
            for it in c[key]:
                if isinstance(it, dict) and isinstance(it.get("t"), (int, float)):
                    out.append((key, (lambda it=it: it["t"]), (lambda v, it=it: it.__setitem__("t", v))))
    if isinstance(c.get("stat"), dict):
        st = c["stat"]
        for k in ("t", "t_label"):
            if isinstance(st.get(k), (int, float)):
                out.append(("stat", (lambda k=k: st[k]), (lambda v, k=k: st.__setitem__(k, v))))
    return out


def remap_spec(spec, old_segs, new_segs, new_dur=None):
    """New reel.json for the new cut list. Items whose every time was cut are removed (counted in the report)."""
    f, old, new = remapper(old_segs, new_segs)
    spec = copy.deepcopy(spec)
    removed = {}
    for key in ("cards", "takeovers", "fx", "sfx"):
        items = spec.get(key)
        if not isinstance(items, list):
            continue
        keep = []
        for c in items:
            refs = _refs(c)
            starts = [r for r in refs if r[0] not in ("out", "until")]
            moved = [(k, g, s, *f(g())) for k, g, s in refs]
            if starts and not any(kept for k, g, s, v, kept in moved if k not in ("out", "until")):
                # it began inside a removed part: keep it from the cut only if enough of it is left to read
                first_new = min(v for k, g, s, v, kept in moved if k not in ("out", "until"))
                ends = [v for k, g, s, v, kept in moved if k in ("out", "until") and kept]
                if not ends or max(ends) - first_new < 0.8:
                    removed[key] = removed.get(key, 0) + 1
                    continue
            for k, g, s, v, kept in moved:
                s(v)
            first = min((g() for k, g, s in starts), default=None)
            for k in ("out", "until"):
                if first is not None and isinstance(c.get(k), (int, float)) and c[k] < first + 0.3:
                    c[k] = round(first + 0.3, 3)
            keep.append(c)
        spec[key] = keep
    if isinstance(spec.get("redactions"), list):            # blur regions: {t, dur}
        keep = []
        for r in spec["redactions"]:
            a, b = f(float(r["t"]))[0], f(float(r["t"]) + float(r.get("dur", 3)))[0]
            if b - a < 0.3:
                removed["redactions"] = removed.get("redactions", 0) + 1
                continue
            r["t"], r["dur"] = a, round(b - a, 3)
            keep.append(r)
        spec["redactions"] = keep
    if isinstance(spec.get("overlays"), list):              # overlay videos: {t, dur, in}; a cut start moves the clip's start point on
        keep = []
        for o in spec["overlays"]:
            t0, d = float(o["t"]), float(o.get("dur", 3))
            (a, ka), (b, kb) = f(t0), f(t0 + d)
            if b - a < 0.3:
                removed["overlays"] = removed.get("overlays", 0) + 1
                continue
            if not ka:                                       # its start was cut: skip that much of the clip too
                o["in"] = round(float(o.get("in", 0)) + max(0.0, d - (b - a)), 3)
            o["t"], o["dur"] = a, round(b - a, 3)
            keep.append(o)
        spec["overlays"] = keep
    spec["duration"] = round(new_dur if new_dur else new.dur, 3)
    return spec, removed
