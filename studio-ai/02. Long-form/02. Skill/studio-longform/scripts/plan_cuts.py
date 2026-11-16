#!/usr/bin/env python3
"""Draft a cut list for a raw talking-head clip. Copy of studio-reel's plan_cuts.py with --no-zoom for long-form.

    python3 plan_cuts.py <raw-video> <raw-transcript.json> <out-dir> [--remove A-B ...] [--noise -30]

- trims every pause of 0.3 s or more down to ~0.16 s (cutting in the silence);
- removes the raw ranges given with --remove (false starts, retakes, outtakes),
  snapping each edge into the nearest silence so no word is clipped;
- starts just before the first word, ends 0.35 s after the last;
- alternates framing (1.3x, 1.0x, 1.22x, 1.0x, ...; landscape 1.15x, 1.0x, 1.1x, 1.0x) at a cut or a sentence start,
  roughly every 5-8 s, never mid-word.

Writes <out-dir>/edl.json and cut-report.txt for the person to approve.
"""
import argparse, json, re, subprocess
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("transcript"); ap.add_argument("out")
ap.add_argument("--remove", nargs="*", default=[], help="raw ranges to drop, e.g. 6.3-11.85")
ap.add_argument("--noise", type=float, default=-40.0, help="silence threshold in dB (stricter = safer for soft words)")
ap.add_argument("--min-gap", type=float, default=5.0, help="minimum seconds between framing changes")
ap.add_argument("--format", choices=["reel", "feed", "square", "landscape"], default="reel",
                help="reel 1080x1920, feed 4:5 1080x1350 (both 1.3/1.0/1.22 punch-ins), square 1080x1080 (1.2/1.0/1.12), "
                     "landscape 1920x1080 (1.15/1.0/1.1)")
ap.add_argument("--no-zoom", action="store_true", help="long-form: keep every segment at 1.0x (no punch-ins)")
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
FF = "/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "ffmpeg"
words = json.load(open(a.transcript))
PAD = 0.08

log = subprocess.run([FF, "-i", a.video, "-vn", "-af", f"silencedetect=noise={a.noise}dB:d=0.3", "-f", "null", "-"],
                     capture_output=True, text=True).stderr
st = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", log)]
en = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", log)]
sil = list(zip(st, en))
# never trust a "silence" a word starts inside (soft syllables, trailing words). Whisper word
# starts are reliable; its word ends run on to the next word, so they can't be used here.
sil = [(s, e) for s, e in sil if not any(s + 0.06 < w["start"] < e - 0.06 for w in words)]

def snap(t, side):
    """Move a removal edge into silence: start edges to a silence start, end edges to a silence end."""
    best = min(sil, key=lambda s: abs((s[0] if side == "start" else s[1]) - t), default=None)
    if best and abs((best[0] if side == "start" else best[1]) - t) < 0.6:
        return best[0] + PAD if side == "start" else best[1] - PAD
    return t

drops = []
for r in a.remove:
    x, y = map(float, r.split("-"))
    drops.append((snap(x, "start"), snap(y, "end")))
drops += [(s + PAD, e - PAD) for s, e in sil if e - s >= 0.3]
first, last = words[0]["start"] - 0.12, words[-1]["end"] + 0.35
drops.sort()

keep, t = [], max(0.0, first)
for s, e in drops:
    if e <= t:
        continue
    if s > t:
        keep.append([t, min(s, last)])
    t = max(t, e)
if t < last:
    keep.append([t, last])
keep = [k for k in keep if k[1] - k[0] > 0.12]

keep = [k for k in keep if k[1] - k[0] > 0.25 or any(k[0] <= w["start"] < k[1] for w in words)]

# framing: pick change points every ~5.5-8 s on the OUTPUT timeline. Prefer a cut, then a
# sentence start, then any gap between two words — never mid-word.
def to_out(t):
    o = 0.0
    for k0, k1 in keep:
        if k0 <= t <= k1:
            return o + t - k0
        o += k1 - k0
    return None
cuts_o, o = [], 0.0
for k0, k1 in keep[:-1]:
    o += k1 - k0; cuts_o.append(o)
total_o = sum(k1 - k0 for k0, k1 in keep)
sent_o = [x for x in (to_out(words[i]["start"] - 0.04) for i in range(1, len(words))
                      if re.search(r"[.?!]$", words[i - 1]["text"])) if x is not None]
gaps_o = [x for x in (to_out(words[i]["start"] - 0.03) for i in range(1, len(words))) if x is not None]
LO, HI = a.min_gap + 0.5, a.min_gap + 3.0
changes, t = [], 0.0
while t + LO < total_o - 2.0:
    for pool in (cuts_o, sent_o, gaps_o):
        c = [x for x in pool if t + LO <= x <= t + HI]
        if c:
            t = c[0]; changes.append(t); break
    else:
        t += HI

# split keep pieces at the change points and assign zooms
ZOOMS = {"landscape": [1.15, 1.0, 1.1, 1.0], "square": [1.2, 1.0, 1.12, 1.0]}.get(a.format, [1.3, 1.0, 1.22, 1.0])
if a.no_zoom:
    ZOOMS = [1.0]
OUT_W, OUT_H = {"landscape": (1920, 1080), "feed": (1080, 1350), "square": (1080, 1080)}.get(a.format, (1080, 1920))
segs, o = [], 0.0
for k0, k1 in keep:
    pts = [k0] + [k0 + (c - o) for c in changes if o < c < o + (k1 - k0) - 1e-6] + [k1]
    for p0, p1 in zip(pts, pts[1:]):
        zi = sum(1 for c in changes if c <= o + (p0 - k0) + 1e-6) % len(ZOOMS)
        segs.append({"in": round(p0, 3), "out": round(p1, 3), "zoom": ZOOMS[zi]})
    o += k1 - k0

# merge neighbours that share a zoom and touch (no cut between them)
merged = []
for s in segs:
    if merged and merged[-1]["zoom"] == s["zoom"] and abs(merged[-1]["out"] - s["in"]) < 1e-6:
        merged[-1]["out"] = s["out"]
    else:
        merged.append(dict(s))

json.dump({"segments": merged, "fps": 25, "width": OUT_W, "height": OUT_H}, open(out / "edl.json", "w"), indent=1)
total = sum(s["out"] - s["in"] for s in merged)
removed = [(round(merged[i]["out"], 2), round(merged[i + 1]["in"], 2)) for i in range(len(merged) - 1)
           if merged[i + 1]["in"] - merged[i]["out"] > 0.01]
def said(t0, t1):
    return " ".join(w["text"] for w in words if w["start"] >= t0 - 0.05 and w["end"] <= t1 + 0.05)
rep = [f"length {total:.1f}s (raw {words[-1]['end']:.1f}s) · {len(merged)} pieces · {len(removed)} cuts", ""]
o = 0.0
for s in merged:
    rep.append(f"out {o:6.2f}  raw {s['in']:7.2f}-{s['out']:7.2f}  zoom {s['zoom']:.2f}")
    o += s["out"] - s["in"]
rep += ["", "removed:"] + [f"  raw {x:.2f}-{y:.2f} ({y - x:.2f}s) {said(x, y)!r}" for x, y in removed if y - x > 0.5] \
       + [f"  + {sum(1 for x, y in removed if y - x <= 0.5)} short pauses tightened"]
(out / "cut-report.txt").write_text("\n".join(rep) + "\n")
print("\n".join(rep))
