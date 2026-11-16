#!/usr/bin/env python3
"""Even out lighting across a locked-off talking-head clip.

    python3 grade.py <raw-video> <out-dir> [--start S] [--end E] [--target-window A B]

Finds the parts of the frame that never move (walls, ceiling, table: low
variance once each frame is normalised by its own brightness), tracks their
colour over time, and writes per-frame RGB gains that pull every frame back to
the brightest, most neutral stretch. Gains are capped so highlights never clip;
any shortfall is made up with a gentle midtone lift (gamma <= 1.25).

Writes <out-dir>/grade-cmds.txt (ffmpeg sendcmd, times on the RAW clip) and
grade-report.txt. edit.py applies the commands. Assumes a tripod shot; on a
moving camera the static mask is small and the script says so.
"""
import argparse, math, subprocess, sys
from pathlib import Path
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("out")
ap.add_argument("--start", type=float, default=0.0)
ap.add_argument("--end", type=float, default=None)
ap.add_argument("--target-window", type=float, nargs=2, default=None, help="seconds (raw) to use as the look to match")
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
FFMPEG = "/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "ffmpeg"

fps = 25
W, H = 135, 240
cmd = [FFMPEG, "-v", "error", "-ss", str(a.start)]
if a.end:
    cmd += ["-t", str(a.end - a.start)]
cmd += ["-i", a.video, "-vf", f"fps={fps},scale={W}:{H},format=rgb24", "-f", "rawvideo", "-"]
raw = subprocess.run(cmd, capture_output=True, check=True).stdout
f = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.float32)
n = len(f)
lum = f.mean(3)

# ---- static, mid-bright reference pixels
norm = lum / (np.median(lum.reshape(n, -1), 1)[:, None, None] + 1e-6)
sd = norm.std(0)
mean = lum.mean(0)
border = np.zeros((H, W), bool); border[4:-4, 4:-4] = True
ok = border & (mean > np.percentile(mean, 35)) & (mean < 235)
mask = ok & (sd < np.percentile(sd[ok], 30))
cover = mask.mean() * 100
pix = f[:, mask]                          # (n, k, 3)
col = pix.mean(1)                         # per-frame RGB of the static area

# ---- target look: a chosen window, else the brightest 25% of frames
if a.target_window:
    i0, i1 = [int((t - a.start) * fps) for t in a.target_window]
    tgt = col[i0:i1].mean(0)
else:
    br = col.mean(1)
    tgt = col[br >= np.percentile(br, 75)].mean(0)

def smooth(x, k):
    p = np.pad(x, ((k // 2, k // 2), (0, 0)), mode="edge")
    med = np.array([np.median(p[i:i + k], 0) for i in range(len(x))])
    p = np.pad(med, ((k // 2, k // 2), (0, 0)), mode="edge")
    return np.stack([np.convolve(p[:, c], np.ones(k) / k, "valid") for c in range(3)], 1)

g = np.clip(smooth(tgt[None, :] / col, 15), 0.85, 1.9)

# ---- cap so the brightest 0.3% never clips; hold the cap over +/-1 s
cap = np.array([min(1.0, 240 / np.percentile((f[i] * g[i]).max(2), 99.7)) for i in range(n)])
p = np.pad(cap, (25, 25), mode="edge"); cap = np.array([p[i:i + 51].min() for i in range(n)])
cap = np.convolve(np.pad(cap, (12, 12), mode="edge"), np.ones(25) / 25, "valid")
g = g * cap[:, None]

# ---- residual midtone lift where the cap held exposure back
t_lum = tgt.mean() / 255
gam = []
for i in range(n):
    w = np.clip(pix[i] * g[i], 0, 255).mean() / 255
    gam.append(min(max(math.log(max(w, 1e-3)) / math.log(t_lum), 1.0), 1.25))
gam = np.convolve(np.pad(gam, (12, 12), mode="edge"), np.ones(25) / 25, "valid")

lines = [f"{a.start + i / fps:.3f} colorchannelmixer@wb rr {g[i, 0]:.4f}, colorchannelmixer@wb gg {g[i, 1]:.4f}, "
         f"colorchannelmixer@wb bb {g[i, 2]:.4f}, eq@ex gamma {gam[i]:.4f};" for i in range(n)]
(out / "grade-cmds.txt").write_text("\n".join(lines) + "\n")

rep = [f"static reference area: {cover:.1f}% of frame" + ("  (LOW — camera may be moving; check results)" if cover < 3 else ""),
       f"target RGB {tgt.round(0).astype(int).tolist()}", "", "time   static RGB before     gain R/G/B        gamma"]
for i in range(0, n, fps):
    rep.append(f"{a.start + i / fps:6.1f}s {col[i].round(0).astype(int).tolist()!s:18} {g[i, 0]:.2f}/{g[i, 1]:.2f}/{g[i, 2]:.2f}   {gam[i]:.2f}")
(out / "grade-report.txt").write_text("\n".join(rep) + "\n")
print("\n".join(rep[:2]))
print(f"max gain {g.max():.2f}, max gamma {max(gam):.2f} -> {out / 'grade-cmds.txt'}")
