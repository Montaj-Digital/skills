#!/usr/bin/env python3
"""Recover an editor's cut list and punch-ins from a finished reel.

    python3 match_reference.py <raw-video> <reference-edit> <out-dir>

1. Audio: slides 0.4 s windows of the reference over the raw audio to find
   where each stretch came from, groups windows with the same offset into
   segments, then refines each offset to the sample and each cut to 10 ms.
2. Picture: for every half second of the reference, searches zoom 1.00-1.60x
   and position against the matching raw frame (gradient images of the top
   44% of frame, so captions and cards don't confuse it). Zoom changes inside
   a segment are split at the exact frame (largest frame-to-frame jump).
   A drifting crop becomes pan keyframes.

Writes <out-dir>/edl.json (ready for edit.py) and match-report.txt.
Check the report: segments under ~0.3 s or low match scores need a look.
"""
import json, subprocess, sys, wave
from pathlib import Path
import numpy as np

raw_v, ref_v, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
FF = "/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "ffmpeg"
FP = FF.replace("ffmpeg", "ffprobe")
SR = 16000

def probe(v, entries):
    return subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", entries, "-of", "csv=p=0", v],
                          capture_output=True, text=True).stdout.strip().splitlines()[0]  # .mov stream groups print twice

def audio(v):
    p = out / (Path(v).stem + ".wav")
    subprocess.run([FF, "-v", "error", "-y", "-i", v, "-vn", "-ac", "1", "-ar", str(SR), str(p)], check=True)
    w = wave.open(str(p)); return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768

ref, raw = audio(ref_v), audio(raw_v)
REF_DUR = len(ref) / SR

# ---------------------------------------------------------------- 1. audio alignment
win, step = int(0.4 * SR), int(0.1 * SR)
hits, prev = [], 0.0
for i in range(0, len(ref) - win, step):
    seg = ref[i:i + win]; t = i / SR
    if np.sqrt((seg ** 2).mean()) < 0.004:
        continue
    lo = int(max(0, t + prev - 1.5) * SR); hi = min(len(raw), int((t + prev + 6.0) * SR) + win)
    r = raw[lo:hi]
    if len(r) <= win:
        continue
    n = len(r) + win
    c = np.fft.irfft(np.fft.rfft(r, n) * np.conj(np.fft.rfft(seg, n)), n)[:len(r) - win + 1]
    cs = np.cumsum(np.concatenate([[0], r ** 2])); en = np.sqrt(cs[win:] - cs[:-win])[:len(c)] + 1e-9
    nc = c / (en * np.linalg.norm(seg)); k = int(np.argmax(nc))
    if nc[k] > 0.8:
        prev = (lo + k) / SR - t
        hits.append((t, prev))
segs = []
for t, o in hits:
    if segs and abs(o - segs[-1][2]) < 0.03:
        segs[-1][1] = t + 0.4
    else:
        segs.append([t, t + 0.4, o])
segs = [s for s in segs if s[1] - s[0] >= 0.3]

fine = []
for a, b, o in segs:  # sample-accurate offset from a 1 s window mid-segment
    m = (a + b) / 2 - 0.5; i = int(m * SR); seg = ref[i:i + SR]
    lo = int((m + o - 0.05) * SR); r = raw[lo:lo + SR + int(0.1 * SR)]
    fine.append((lo + int(np.argmax(np.correlate(r, seg, "valid")))) / SR - m)

cuts = []
for j in range(len(segs) - 1):  # cut time where switching offsets minimises the error
    o1, o2, b = fine[j], fine[j + 1], (segs[j][1] + segs[j + 1][0]) / 2
    best = None; w = int(0.02 * SR)
    for t in np.arange(b - 0.5, b + 0.5, 0.01):
        e = 0
        for x in np.arange(b - 0.55, b + 0.55, 0.02):
            i = int(x * SR); k = int((x + (o1 if x < t else o2)) * SR)
            if 0 <= i and i + w <= len(ref) and 0 <= k and k + w <= len(raw):
                e += np.sum((ref[i:i + w] - raw[k:k + w]) ** 2)
        if best is None or e < best[0]:
            best = (e, t)
    cuts.append(round(best[1], 3))
bounds = [0.0] + cuts + [REF_DUR]
pieces = [{"ref_in": bounds[j], "ref_out": bounds[j + 1], "offset": fine[j]} for j in range(len(segs))]

# ---------------------------------------------------------------- 2. zoom / framing
RW, RH = map(int, probe(raw_v, "stream=width,height").split(",")[:2])
raw_end = max(p["ref_out"] + p["offset"] for p in pieces) + 1
def frames(v, fps, w, h, t=None):
    cmd = [FF, "-v", "error"] + (["-t", str(t)] if t else []) + ["-i", v, "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.uint8).reshape(-1, h, w).astype(np.float32)
refg = frames(ref_v, 4, 135, 240)
rawg = frames(raw_v, 10, 540, 960, raw_end)

def resize(img, h, w):
    H, W = img.shape; ys = np.linspace(0, H - 1, h); xs = np.linspace(0, W - 1, w)
    y0 = np.floor(ys).astype(int); x0 = np.floor(xs).astype(int); y1 = np.minimum(y0 + 1, H - 1); x1 = np.minimum(x0 + 1, W - 1)
    fy = (ys - y0)[:, None]; fx = (xs - x0)[None, :]
    return img[y0][:, x0] * (1 - fy) * (1 - fx) + img[y0][:, x1] * (1 - fy) * fx + img[y1][:, x0] * fy * (1 - fx) + img[y1][:, x1] * fy * fx
def grad(i):
    gx = np.zeros_like(i); gy = np.zeros_like(i); gx[:, 1:] = i[:, 1:] - i[:, :-1]; gy[1:] = i[1:] - i[:-1]; return np.hypot(gx, gy)
def offset_at(t):
    for p in pieces:
        if p["ref_in"] <= t < p["ref_out"]:
            return p["offset"]
    return pieces[-1]["offset"]

TH = 105
samples = []
for k in range(0, len(refg), 2):
    t = k / 4; fi = int(round((t + offset_at(t)) * 10))
    if fi >= len(rawg):
        break
    Tm = grad(refg[k][:TH]); Tm = (Tm - Tm.mean()) / (Tm.std() + 1e-6)
    best = (-1, 1.0, 0, 0)
    for s in np.arange(1.0, 1.62, 0.02):
        h, w = int(round(240 * s)), int(round(135 * s))
        R = grad(resize(rawg[fi], h, w)); th, tw = Tm.shape; n0, n1 = R.shape
        c = np.fft.irfft2(np.fft.rfft2(R) * np.conj(np.fft.rfft2(Tm, (n0, n1))), (n0, n1))[:n0 - th + 1, :n1 - tw + 1]
        c1 = np.cumsum(np.cumsum(np.pad(R, ((1, 0), (1, 0))), 0), 1); c2 = np.cumsum(np.cumsum(np.pad(R * R, ((1, 0), (1, 0))), 0), 1)
        box = lambda cc: cc[th:, tw:] - cc[:-th, tw:] - cc[th:, :-tw] + cc[:-th, :-tw]
        sm = box(c1)[:c.shape[0], :c.shape[1]]; sq = box(c2)[:c.shape[0], :c.shape[1]]; N = th * tw
        nc = c / (np.sqrt(np.maximum(sq - sm * sm / N, 1e-6)) * np.sqrt(N))
        y, x = np.unravel_index(np.argmax(nc), nc.shape)
        if y <= h - 240 + 1 and nc[y, x] > best[0]:
            best = (float(nc[y, x]), round(float(s), 2), x / s, y / s)
    cx = (best[2] * 4 + 540 / best[1] / 2) - 270   # crop-centre offset, 540-wide raw space
    samples.append({"t": t, "zoom": best[1], "cx": cx, "score": best[0]})

# frame-accurate change points inside the reference (hard punches)
ref25 = frames(ref_v, 25, 108, 192)
jump = np.abs(np.diff(ref25, axis=0)).mean((1, 2))
def exact_change(t0, t1):
    a, b = int(t0 * 25), int(t1 * 25) + 1
    return (a + 1 + int(np.argmax(jump[a:b]))) / 25 if b > a else t1

segments, report = [], []
for p in pieces:
    ss = [s for s in samples if p["ref_in"] <= s["t"] < p["ref_out"]]
    zs = [s["zoom"] for s in ss] or [1.0]
    # 3-point median (odd windows only, so a change never averages into a fake in-between zoom),
    # then fold runs shorter than 0.75 s into their neighbour
    zs = [float(np.median(zs[i - 1:i + 2])) if 0 < i < len(zs) - 1 else zs[i] for i in range(len(zs))]
    runs = []
    for z in zs:
        if runs and abs(z - runs[-1][0]) < 0.06:
            runs[-1][1] += 1
        else:
            runs.append([z, 1])
    k = 0
    while k < len(runs):
        if runs[k][1] < 2 and len(runs) > 1:
            j = k - 1 if k > 0 else k + 1
            runs[j][1] += runs[k][1]; runs.pop(k); k = 0
        else:
            k += 1
    zs = [z for z, c in runs for _ in range(c)]
    starts = [p["ref_in"]]; zooms = [zs[0]]
    for i in range(1, len(ss)):
        if abs(zs[i] - zooms[-1]) >= 0.06:
            starts.append(exact_change(ss[i - 1]["t"], ss[i]["t"])); zooms.append(zs[i])
    starts.append(p["ref_out"])
    for j, z in enumerate(zooms):
        a, b = starts[j], starts[j + 1]
        part = [s for s in ss if a <= s["t"] < b]
        seg = {"in": max(0.0, round(a + p["offset"], 3)), "out": round(b + p["offset"], 3), "zoom": round(z, 2)}
        cxs = [s["cx"] for s in part]
        if z >= 1.03 and cxs and (max(cxs) - min(cxs) > 8 or abs(np.median(cxs)) > 6):  # no room to pan at 1.0x
            sm = [float(np.median(cxs[max(0, i - 1):i + 2])) for i in range(len(cxs))]
            seg["pan"] = [[round(s["t"] - a, 2), round(v * RW / 540)] for s, v in zip(part, sm)]
        segments.append(seg)
        sc = min([s["score"] for s in part], default=0)
        report.append(f"ref {a:6.2f}-{b:6.2f}  raw {seg['in']:7.3f}-{seg['out']:7.3f}  zoom {z:.2f}"
                      f"{'  pan' if 'pan' in seg else ''}  min match {sc:.2f}")

removed = [f"raw {segments[i]['out']:.2f}-{segments[i + 1]['in']:.2f} removed" for i in range(len(segments) - 1)
           if segments[i + 1]["in"] - segments[i]["out"] > 0.02]
json.dump({"segments": segments, "fps": round(eval(probe(ref_v, "stream=r_frame_rate"))), "width": 1080, "height": 1920},
          open(out / "edl.json", "w"), indent=1)
(out / "match-report.txt").write_text("\n".join(report + [""] + removed) + "\n")
print("\n".join(report + [""] + removed))
print(f"-> {out / 'edl.json'}")
