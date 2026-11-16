#!/usr/bin/env python3
"""Cut, punch in and grade the raw clip into the base edit (one ffmpeg pass).

    python3 edit.py <raw-video> <edl.json> <out.mp4> [--grade grade-cmds.txt]

edl.json:
  {"segments": [
     {"in": 0.0, "out": 5.4, "zoom": 1.32},
     {"in": 13.275, "out": 20.185, "zoom": 1.3, "pan": [[0, -150], [2.9, 20], [4.4, -90]]},
     ...],
   "fps": 25, "width": 1080, "height": 1920}

in/out are seconds on the raw clip. zoom is a centred punch-in. pan keyframes
are [seconds into the segment, horizontal offset in SOURCE pixels], eased.
A segment with "src" is an INSERT from another file (in/out are seconds in that file; a relative path is from the
project folder, the one above work/): it fills the frame, keeps its own sound (silence if it has none), and gets no
zoom or grade. A cut list without inserts renders exactly as before.
Every joint gets a 12 ms audio fade so cuts never click. The output has a
keyframe every second so the HyperFrames renderer can seek it.
"""
import argparse, json, subprocess
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("edl"); ap.add_argument("out")
ap.add_argument("--grade", default=None)
a = ap.parse_args()
FF = "/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "ffmpeg"
FP = FF.replace("ffmpeg", "ffprobe")
edl = json.load(open(a.edl))
segs = edl["segments"]
OW, OH, FPS = edl.get("width", 1080), edl.get("height", 1920), edl.get("fps", 25)
cam = [i for i, s in enumerate(segs) if not s.get("src")]           # segments from the camera file
ins = [i for i, s in enumerate(segs) if s.get("src")]               # inserts from other files
ROOT = Path(a.edl).resolve().parent.parent                          # the project folder (edl.json lives in work/)
def src_path(s):
    p = Path(s["src"]).expanduser()
    return p if p.is_absolute() else ROOT / p
def has_audio(f):
    return bool(subprocess.run([FP, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(f)],
                               capture_output=True, text=True).stdout.strip())
NORM = ",aformat=sample_rates=48000:channel_layouts=stereo" if ins else ""   # concat needs one audio format when files differ
W, H = map(int, subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                "-of", "csv=p=0", a.video], capture_output=True, text=True).stdout.strip().splitlines()[0].split(",")[:2])

def ease(u):
    return f"(({u})*({u})*(3-2*({u})))"

def pan_expr(keys, x0, xmax):
    keys = sorted(keys)
    e = f"{keys[-1][1]}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:]))):
        e = f"if(lt(t,{t1}),{v0}+({v1 - v0})*{ease(f'clip((t-{t0})/{t1 - t0},0,1)')},{e})"
    return f"clip({x0}+{e},0,{xmax})"

pre = "[0:v]"
if a.grade:
    pre += (f"sendcmd=f='{Path(a.grade).resolve()}',scale=in_color_matrix=bt709:in_range=tv,format=gbrp,colorchannelmixer@wb,"
            "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,eq@ex=gamma=1,")
fc = [pre + f"split={len(cam)}" + "".join(f"[v{i}]" for i in cam),
      "[0:a]asplit=%d" % len(cam) + "".join(f"[a{i}]" for i in cam)]
extra = []                                                          # input files for the inserts: -i …
for i in ins:
    s = segs[i]; k = len(extra) // 2 + 1; f = src_path(s); extra += ["-i", str(f)]
    d = s["out"] - s["in"]
    fc.append(f"[{k}:v]trim={s['in']}:{s['out']},setpts=PTS-STARTPTS,scale={OW}:{OH}:force_original_aspect_ratio=increase,"
              f"crop={OW}:{OH},setsar=1,fps={FPS},format=yuv420p[vv{i}]")
    fc.append(f"[{k}:a]atrim={s['in']}:{s['out']},asetpts=PTS-STARTPTS{NORM},afade=t=in:d=0.012,afade=t=out:st={d - 0.012:.3f}:d=0.012[aa{i}]"
              if has_audio(f) else f"aevalsrc=0:c=stereo:s=48000:d={d:.3f}[aa{i}]")
for i in cam:
    s = segs[i]
    z = s.get("zoom", 1.0)
    # crop the largest window of the output's shape (so a landscape source isn't squeezed into 9:16 or back)
    if W / H > OW / OH:
        h = int(round(H / z / 2) * 2); w = int(round(h * OW / OH / 2) * 2)
    else:
        w = int(round(W / z / 2) * 2); h = int(round(w * OH / OW / 2) * 2)
    x0, y0 = (W - w) // 2, (H - h) // 2
    x = pan_expr(s["pan"], x0, W - w) if s.get("pan") else str(x0)
    d = s["out"] - s["in"]
    fc.append(f"[v{i}]trim={s['in']}:{s['out']},setpts=PTS-STARTPTS,crop={w}:{h}:'{x}':{y0},"
              f"scale={OW}:{OH}:flags=lanczos,setsar=1{',format=yuv420p' if ins else ''}[vv{i}]")
    fc.append(f"[a{i}]atrim={s['in']}:{s['out']},asetpts=PTS-STARTPTS{NORM},afade=t=in:d=0.012,"
              f"afade=t=out:st={d - 0.012:.3f}:d=0.012[aa{i}]")
fc.append("".join(f"[vv{i}][aa{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][a]")
script = Path(a.out).with_suffix(".ffscript")
script.write_text(";\n".join(fc))
subprocess.run([FF, "-v", "error", "-y", "-i", a.video, *extra, "-/filter_complex", str(script), "-map", "[v]", "-map", "[a]",
                "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-g", str(FPS), "-keyint_min", str(FPS),
                "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", a.out], check=True)
dur = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.out],
                     capture_output=True, text=True).stdout.strip()
print(f"{a.out}: {float(dur):.2f}s from {len(segs)} segments")
