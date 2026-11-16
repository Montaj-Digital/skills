#!/usr/bin/env python3
"""default reel timeline editor — local server.

    python3 server.py                     # opens on the home screen (New / Open)
    python3 server.py <reel project>      # opens that reel (the folder with edit/ or reel.json)
    python3 server.py --port 4322 --build path/to/build.py --no-open

Live preview builds go to <project>/.editor/preview (a shadow copy that shares the video,
transcript and assets), so reel.json is only written when you press Save. Every save keeps
the previous reel.json in <project>/.editor/backups. New reels are created in the library
folder (settings.json -> "library", default ./Reels).
"""
import argparse, json, os, re, shutil, subprocess, sys, threading, time, webbrowser
from array import array
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

import osutil             # macOS / Windows differences (phase 8); first, it sets up the tools' PATH on Windows
osutil.ensure_utf8()      # Windows: restart in Python's UTF-8 mode (a Mac: nothing happens)
import workspace          # whose videos, kits and settings a request is for (one on a Mac; per user on the portal)
import pipeline
import uploads            # resumable uploads from the browser (the portal has no Finder)
import claude_client
import cuts
import fill

# Long-form section (optional). Its code lives in ../02. Long-form/04. Editor/longform.py (Studio AI layout);
# an import error only disables long-form, never this editor.
LONG = None
_LF = next((d for d in (Path(__file__).resolve().parent.parent.parent / n / "04. Editor" for n in
                         ("02. Long-form", "02. Studio AI Long-form Video Editor", "Studio AI Long-form Video Editor")) if (d / "longform.py").exists()), None)
if _LF:
    try:
        sys.path.append(str(_LF))
        import longform as LONG
    except Exception as _e:
        LONG = None
        print(f"  (long-form is switched off: {_e})")

HERE = Path(__file__).resolve().parent          # 04. Editor
BASE = HERE.parent                                # the main folder: 01. Installation … 07. Packages
APP = HERE / "app"
PROJECTS, RENDERS = "05. Projects", "06. Renders"
# Studio AI uses its own copy of the skill (02. Skill/studio-reel), so changes here never reach the stable editor.
SKILL = Path(os.environ.get("STUDIO_REEL_SKILL", BASE / "02. Skill/studio-reel"))
# Brand kits (Studio AI: 03. Brands, the Brand screen). An import error only switches brands off.
try:
    import brands as BRANDS
    BRANDS.SKILL = SKILL
except Exception as _e:
    BRANDS = None
    print(f"  (brand kits are switched off: {_e})")
# tools' environment; on the portal it also points studio-reel at the team's brand kits (STUDIO_BRANDS)
ENV = workspace.Env(osutil.tool_env())


def settings():
    # one place for everything: projects and renders live in the main folder (or settings.json -> "library");
    # on the portal, the user's own storage (workspace.py)
    return workspace.current().settings("short")


def recent_file():
    return workspace.current().recent_file


# brand-guide import (brands.py -> brand_import.py) runs claude -p with this Mac's settings
if BRANDS:
    # client kits and the kit Bin follow the workspace (the team's folder on the portal)
    BRANDS.brandkit.root = lambda: workspace.current().brands
    BRANDS.brandkit.bin_dir = lambda: workspace.current().kit_trash
    BRANDS.brand_import.settings = settings
    BRANDS.brand_import.ENV = ENV

# Post it (phase 9.1): Claude writes a finished video's posts for each platform. An import error only switches it off.
try:
    import planner as PLANNER
    PLANNER.ENV, PLANNER.settings = ENV, settings
except Exception as _e:
    PLANNER = None
    print(f"  (Post it is switched off: {_e})")


# Social settings and the calendar (phase 9.2-9.3). An import error only switches them off.
try:
    import social as SOCIAL
    import posting as POSTING
except Exception as _e:
    SOCIAL = POSTING = None
    print(f"  (the calendar is switched off: {_e})")
# Platform connections and the test platform (phase 9.4). An import error only switches them off.
try:
    import connect as CONNECT
    import testplatform as TESTPLATFORM
    CONNECT.settings = settings
    CONNECT.install()
except Exception as _e:
    CONNECT = TESTPLATFORM = None
    print(f"  (platform connections are switched off: {_e})")
# Results (phase 9.6). An import error only switches them off.
try:
    import results as RESULTS
except Exception as _e:
    RESULTS = None
    print(f"  (results are switched off: {_e})")


def latest_render(edit_dir):
    """The newest finished MP4 of a short-form video (from .editor/renders.json), or None."""
    try:
        items = json.loads((Path(edit_dir) / ".editor/renders.json").read_text())
    except (OSError, ValueError, TypeError):
        return None
    files = [Path(x["path"]) for x in items if Path(x.get("path", "")).is_file()]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


# AI studio (phase 6): build a clip from several videos with Claude. An import error only switches it off.
try:
    import studio as STUDIO
    STUDIO.SKILL, STUDIO.ENV, STUDIO.settings = SKILL, ENV, settings
except Exception as _e:
    STUDIO = None
    print(f"  (the AI studio is switched off: {_e})")


# ------------------------------------------------------------- the library: Projects/ (working files) + Renders/<format>/
FORMAT_FOLDERS = {"reel": "Reel 9x16", "feed": "Feed 4x5", "square": "Square 1x1", "landscape": "Landscape 16x9"}


def lib():
    return Path(settings()["library"])


def renders_dir(fmt, brand=None):
    # a client's videos go to 06. Renders/<Client>/<format>/; the default brand keeps 06. Renders/<format>/
    client = BRANDS.brandkit.folder_name(brand) if BRANDS and brand else None
    return lib() / RENDERS / (client or "") / FORMAT_FOLDERS.get(fmt or "reel", "Reel 9x16")


def spec_brand(edit_dir):
    try:
        return json.loads((Path(edit_dir) / "reel.json").read_text()).get("brand")
    except (OSError, ValueError):
        return None


def spec_format(edit_dir):
    try:
        return json.loads((Path(edit_dir) / "reel.json").read_text()).get("format", "reel")
    except (OSError, ValueError):
        return "reel"


def record_render(edit_dir, path):
    f = Path(edit_dir) / ".editor/renders.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        items = json.loads(f.read_text())
    except (OSError, ValueError):
        items = []
    items = [x for x in items if x.get("path") != str(path)] + [{"path": str(path), "at": time.time()}]
    f.write_text(json.dumps(items, indent=1))


def migrate_library():
    """Once: projects sitting in the library root move into 05. Projects, and finished MP4s inside them into 06. Renders/<format>/."""
    root = lib()
    if not root.is_dir():
        return
    moved = {}
    for d in sorted(root.iterdir()):
        if d.name in ("Projects", "Renders", PROJECTS, RENDERS) or not (d / "edit/reel.json").exists():
            continue
        dest = root / PROJECTS / d.name
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(d), str(dest))
        moved[str(d)] = str(dest)
        fmt = spec_format(dest / "edit")
        for mp4 in dest.glob("*.mp4"):
            out = renders_dir(fmt) / mp4.name
            if out.exists():
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(mp4), str(out))
            record_render(dest / "edit", out)
        print(f"  moved {d.name} into {PROJECTS}")
    if moved:
        rec = recent()
        recent_file().write_text(json.dumps([next((v + r[len(k):] for k, v in moved.items() if r.startswith(k)), r) for r in rec]))


ap = argparse.ArgumentParser()
ap.add_argument("project", nargs="?")
ap.add_argument("--port", type=int, default=4322)
ap.add_argument("--build", help="build script (default: the skill's scripts/build.py, or ../work/build_fx.py when present)")
ap.add_argument("--no-open", action="store_true")
ap.add_argument("--host", default="127.0.0.1", help="address to listen on (the portal's server: its private network address)")
args = ap.parse_args()


# ------------------------------------------------------------- the open project
# one per workspace (so on the portal every user has their own open video)
P = workspace.Slot("p", proj=None, build=None, editor=None, shadow=None, backups=None)   # proj: .../edit (with reel.json)


def resolve_project(path):
    p = Path(path).expanduser().resolve()
    if not workspace.current().inside(p):
        raise ValueError("That folder isn't in your library")
    if not (p / "reel.json").exists() and (p / "edit/reel.json").exists():
        p = p / "edit"
    if not (p / "reel.json").exists():
        raise ValueError(f"No reel.json in {p}")
    if not (p / "transcript.json").exists():
        raise ValueError(f"No transcript.json in {p}. Run the transcribe step first")
    return p


def open_project(path):
    p = resolve_project(path)
    P.proj = p
    if args.build:
        P.build = Path(args.build).expanduser().resolve()
    elif (p.parent / "work/build_fx.py").exists():
        P.build = p.parent / "work/build_fx.py"
    else:
        P.build = SKILL / "scripts/build.py"
    P.editor = p / ".editor"; P.shadow = P.editor / "preview"; P.backups = P.editor / "backups"
    for d in (P.shadow, P.backups):
        d.mkdir(parents=True, exist_ok=True)
    rec = [r for r in recent() if r != str(p)]
    recent_file().write_text(json.dumps([str(p)] + rec[:29]))
    return p


def recent():
    try:
        return json.loads(recent_file().read_text())
    except (OSError, ValueError):
        return []


def project_root(p):
    """The reel's own folder: the parent of edit/ (or build/), else the folder itself."""
    return p.parent if p.name in ("edit", "build") else p


def project_name(p):
    return project_root(p).name


def link(name, target):
    p = P.shadow / name
    if osutil.is_link(p) or p.exists():
        if osutil.same_link(p, target):
            return
        osutil.remove(p)
    osutil.link(target, p)


def prepare_shadow(spec):
    link("transcript.json", P.proj / "transcript.json")
    (P.proj / "assets").mkdir(exist_ok=True)
    link("assets", P.proj / "assets")
    video = spec.get("video", "base-edit.mp4")
    if (P.proj / video).exists():
        link(video, P.proj / video)


build_lock = workspace.SlotLock("build")


def run_build(spec, where):
    with build_lock:
        (where / "reel.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
        r = subprocess.run([sys.executable, str(P.build), str(where)], capture_output=True, text=True, env=ENV, timeout=180)
        return r.returncode == 0, (r.stdout + r.stderr).strip()


def parse_build(where):
    """Caption groups as the build laid them out (so auto-grouping matches exactly)."""
    page = (where / "index.html").read_text()
    groups = []
    for m in re.finditer(r'<div class="cap clip" id="g(\d+)" data-start="([\d.]+)" data-duration="([\d.]+)"[^>]*>(.*?)</div>', page, re.S):
        idx = [int(i) for i in re.findall(r'id="w(\d+)"', m.group(4))]
        groups.append({"start": float(m.group(2)), "end": float(m.group(2)) + float(m.group(3)), "words": idx})
    return groups


# ------------------------------------------------------------- waveform + thumbnails
def peaks(spec, per_sec=100):
    video = P.proj / spec.get("video", "base-edit.mp4")
    key = [str(video), video.stat().st_mtime if video.exists() else 0]
    cache = P.editor / "peaks.json"
    if cache.exists():
        c = json.loads(cache.read_text())
        if c.get("key") == key:
            return c["peaks"]
    rate = 4000
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                       capture_output=True, env=ENV, timeout=300)
    a = array("h"); a.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    step = rate // per_sec
    out = [round(max((abs(x) for x in a[i:i + step]), default=0) / 32768, 3) for i in range(0, len(a), step)]
    cache.write_text(json.dumps({"key": key, "peaks": out}))
    return out


def thumb(edit_dir):
    import hashlib
    spec_mtime = (edit_dir / "reel.json").stat().st_mtime
    t = HERE / ".cache/thumbs" / (hashlib.sha1(str(edit_dir).encode()).hexdigest()[:16] + ".jpg")
    if t.exists() and t.stat().st_mtime >= spec_mtime:
        return t
    try:
        spec = json.loads((edit_dir / "reel.json").read_text())
    except (OSError, ValueError):
        return None
    video = edit_dir / spec.get("video", "base-edit.mp4")
    if not video.exists():
        return None
    t.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.5", "-i", str(video), "-frames:v", "1", "-vf", "scale='min(480,iw)':-2", "-q:v", "4", str(t)],
                   env=ENV, timeout=60)
    return t if t.exists() else None


# ------------------------------------------------------------- video track: zooms + filmstrip
VIDEO_EXT = (".mov", ".mp4", ".m4v", ".mkv", ".webm")


def find_raw():
    """The raw camera file this reel was cut from: work/source.json, else raw/ (reels made with New)."""
    root = project_root(P.proj)
    sf = root / "work/source.json"
    if sf.exists():
        p = Path(json.loads(sf.read_text()).get("raw", ""))
        if p.is_file():
            return p
    vids = sorted(f for f in (root / "raw").glob("*") if f.suffix.lower() in VIDEO_EXT) if (root / "raw").is_dir() else []
    return vids[0] if vids else None


def probe_duration(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, env=ENV).stdout.strip().splitlines()
    return float(out[0]) if out else 0.0


zoomjob = workspace.SlotDict("zoomjob", running=False, error=None, done=False, log=[], started=None, proj=None)


def apply_zooms(zooms):
    """Write new zoom levels into work/edl.json and re-render edit/base-edit.mp4 (cuts and timing unchanged)."""
    root = project_root(P.proj)
    edl_f, raw = root / "work/edl.json", find_raw()
    if zoomjob["running"]:
        raise ValueError("A zoom render is already running")
    if not edl_f.exists():
        raise ValueError("This reel has no cut list (work/edl.json), so its zooms can't be changed here")
    if not raw:
        raise ValueError("Locate the raw video first")
    edl = json.loads(edl_f.read_text())
    segs = edl.get("segments", [])
    for k, z in zooms.items():
        segs[int(k)]["zoom"] = round(max(1.0, min(2.0, float(z))), 3)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy(edl_f, root / f"work/edl-{stamp}.json")
    proj = P.proj
    spec = json.loads((proj / "reel.json").read_text())
    final = proj / spec.get("video", "base-edit.mp4")
    tmp = proj / "base-edit.rendering.mp4"
    new_edl = root / "work/edl.pending.json"
    new_edl.write_text(json.dumps(edl, indent=2))
    grade = root / "work/grade-cmds.txt"
    cmd = [sys.executable, str(SKILL / "scripts/edit.py"), str(raw), str(new_edl), str(tmp)] + (["--grade", str(grade)] if grade.exists() else [])
    zoomjob.update(running=True, error=None, done=False, log=[], started=time.time(), proj=str(proj), kind="zoom", report=None)

    def go():
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=3600)
            zoomjob["log"] = (r.stdout + r.stderr).strip().splitlines()[-20:]
            if r.returncode != 0 or not tmp.exists():
                raise RuntimeError("The re-render failed; the reel is unchanged")
            osutil.replace(tmp, final)
            osutil.replace(new_edl, edl_f)
            for f in (proj / ".editor/filmstrip.json", proj / ".editor/peaks.json"):
                f.unlink(missing_ok=True)
            zoomjob["done"] = True
        except Exception as e:
            zoomjob["error"] = str(e)
            for f in (tmp, new_edl):
                try:
                    f.unlink()
                except OSError:
                    pass
        finally:
            zoomjob["running"] = False
    workspace.Thread(target=go, daemon=True).start()


RAW_DUR = {}


def raw_duration(raw):
    key = (str(raw), raw.stat().st_mtime)
    if key not in RAW_DUR:
        RAW_DUR[key] = probe_duration(raw)
    return RAW_DUR[key]


def insert_len(src):
    """Length of an inserted file (a path relative to the project folder)."""
    f = project_root(P.proj) / src
    return round(probe_duration(f) or 0.0, 3) if f.exists() else 0.0


def insert_clip(file, t):
    """A true insert (Studio AI): copy `file` into edit/assets/inserts/ and put it in the cut list at edited time t.
    The camera clip under t is split there; everything after moves later by the clip's length (apply_cuts)."""
    root = project_root(P.proj)
    edl_f = root / "work/edl.json"
    if not edl_f.exists():
        raise ValueError("This video has no cut list (work/edl.json), so nothing can be inserted")
    dest = P.proj / "assets/inserts"; dest.mkdir(parents=True, exist_ok=True)
    name = f"{Path(file).parent.name or 'clip'}-{time.strftime('%Y%m%d-%H%M%S')}.mp4"   # its own name = its own range
    shutil.copy2(file, dest / name)
    src = (dest / name).relative_to(root).as_posix()     # kept with / in edl.json (same on a Mac and Windows)
    dur = insert_len(src)
    if dur < 0.2:
        raise ValueError("That clip has no length")
    raw = find_raw()
    old = cuts.clean_segments(cuts.to_virtual(json.loads(edl_f.read_text()).get("segments", []), insert_len), raw_duration(raw) if raw else None)
    tl = cuts.Timeline(old)
    t = max(0.0, min(float(t), tl.dur))
    b = cuts.vbase(src)
    seg = {"src": src, "in": b, "out": round(b + dur, 3), "vbase": b, "clip": dur}
    r = tl.to_raw(t); k = tl.find(r)
    new = [dict(x) for x in old]
    if k is None:                                           # at (or past) the very end
        new.append(seg)
    elif new[k].get("src") or r - new[k]["in"] < cuts.MIN_SEG:
        new.insert(k + (1 if new[k].get("src") else 0), seg)   # inside another insert: after it; at a clip's start: before it
    elif new[k]["out"] - r < cuts.MIN_SEG:
        new.insert(k + 1, seg)
    else:                                                   # split the camera clip at t
        a, z = dict(new[k], out=round(r, 3)), dict(new[k], **{"in": round(r, 3)})
        new[k:k + 1] = [a, seg, z]
    apply_cuts(new)
    return {"src": src, "dur": dur, "at": round(t, 3)}


def apply_cuts(segments):
    """Manual cuts: a new cut list (raw times) from the editor. Re-renders edit/base-edit.mp4 and moves the transcript,
    captions and every reel.json time onto the new timeline (nothing is transcribed or planned again)."""
    root = project_root(P.proj)
    edl_f, raw = root / "work/edl.json", find_raw()
    if zoomjob["running"]:
        raise ValueError("A re-render is already running")
    if not edl_f.exists():
        raise ValueError("This video has no cut list (work/edl.json), so its cuts can't be changed here")
    if not raw:
        raise ValueError("Locate the raw video first")
    edl = json.loads(edl_f.read_text())
    # inserts (segments with "src") are compared in their own virtual range; see cuts.py
    old = cuts.clean_segments(cuts.to_virtual(edl.get("segments", []), insert_len), raw_duration(raw))   # the plan can run past the end of the file
    new = cuts.clean_segments(segments, raw_duration(raw))   # from the editor / insert_clip: already in the virtual view
    proj = P.proj
    spec = json.loads((proj / "reel.json").read_text())
    words = json.loads((proj / "transcript.json").read_text())
    raw_tf = root / "work/transcript.json"
    raw_words = json.loads(raw_tf.read_text()) if raw_tf.exists() else []
    new_words, index = cuts.remap_words(words, raw_words, old, new)
    new_spec, removed = cuts.remap_spec(spec, old, new)
    if "captions" in spec:
        new_spec["captions"] = cuts.remap_captions(spec["captions"], index, len(new_words), int(spec["captions"].get("max_words", 3)))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bk = proj / f".editor/backups/cuts-{stamp}"
    bk.mkdir(parents=True, exist_ok=True)
    for f in (proj / "reel.json", proj / "transcript.json", edl_f):
        shutil.copy(f, bk / f.name)
    edl["segments"] = cuts.to_real(new)
    final = proj / spec.get("video", "base-edit.mp4")
    tmp = proj / "base-edit.rendering.mp4"
    new_edl = root / "work/edl.pending.json"
    new_edl.write_text(json.dumps(edl, indent=2))
    grade = root / "work/grade-cmds.txt"
    cmd = [sys.executable, str(SKILL / "scripts/edit.py"), str(raw), str(new_edl), str(tmp)] + (["--grade", str(grade)] if grade.exists() else [])
    report = {"removed": removed, "words_cut": len(words) - len(index), "words_added": len(new_words) - len(index),
              "old_dur": round(spec.get("duration", 0), 2), "new_dur": round(new_spec["duration"], 2), "backup": str(bk)}
    zoomjob.update(running=True, error=None, done=False, log=[], started=time.time(), proj=str(proj), kind="cuts", report=report)

    def go():
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=3600)
            zoomjob["log"] = (r.stdout + r.stderr).strip().splitlines()[-20:]
            if r.returncode != 0 or not tmp.exists():
                raise RuntimeError("The re-render failed; the video is unchanged")
            dur = probe_duration(tmp) or new_spec["duration"]
            new_spec["duration"] = round(dur, 3)
            for w in new_words:
                w["start"], w["end"] = min(w["start"], dur - 0.05), min(w["end"], dur)
            osutil.replace(tmp, final)
            osutil.replace(new_edl, edl_f)
            (proj / "transcript.json").write_text(json.dumps(new_words, indent=1))
            (proj / "reel.json").write_text(json.dumps(new_spec, indent=2))
            for f in (proj / ".editor/filmstrip.json", proj / ".editor/peaks.json"):
                f.unlink(missing_ok=True)
            zoomjob["done"] = True
        except Exception as e:
            zoomjob["error"] = str(e)
            for f in (tmp, new_edl):
                try:
                    f.unlink()
                except OSError:
                    pass
        finally:
            zoomjob["running"] = False
    workspace.Thread(target=go, daemon=True).start()


def edl_segments():
    """Zoom segments from work/edl.json, mapped onto the edited timeline (the cut list plays back to back)."""
    f = project_root(P.proj) / "work/edl.json"
    if not f.exists():
        return []
    out, t = [], 0.0
    for s in json.loads(f.read_text()).get("segments", []):
        d = float(s["out"]) - float(s["in"])
        out.append({"start": round(t, 3), "end": round(t + d, 3), "zoom": float(s.get("zoom", 1.0)), "pan": bool(s.get("pan"))})
        t += d
    return out


FILM_W, FILM_H = 64, 114        # one filmstrip frame, 9:16 (swapped for landscape)


def filmstrip(spec):
    video = P.proj / spec.get("video", "base-edit.mp4")
    meta_f, img = P.editor / "filmstrip.json", P.editor / "filmstrip.jpg"
    key = [str(video), video.stat().st_mtime]
    if meta_f.exists() and img.exists():
        meta = json.loads(meta_f.read_text())
        if meta.get("key") == key:
            return meta
    W, H = {"landscape": (1920, 1080), "feed": (1080, 1350), "square": (1080, 1080)}.get(spec.get("format"), (1080, 1920))
    fh = 96; fw = int(round(fh * W / H / 2) * 2)          # one frame in the reel's own shape
    dur = float(spec.get("duration", 0)) or 1
    step = max(0.5, round(dur / 240, 2))          # at most ~240 frames
    count = int(dur / step) + 1
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf",
                    f"fps=1/{step},scale={fw}:{fh}:force_original_aspect_ratio=increase,crop={fw}:{fh},tile={count}x1",
                    "-frames:v", "1", "-q:v", "6", str(img)], env=ENV, timeout=600)
    meta = {"key": key, "step": step, "count": count, "w": fw, "h": fh}
    meta_f.write_text(json.dumps(meta))
    return meta


# ------------------------------------------------------------- delete (to the Trash)
def trash_reel(path):
    p = resolve_project(path)
    root = project_root(p)
    home = Path.home().resolve()
    if root in (home, home / "Desktop", home / "Documents", home / "Movies") or len(root.parts) < 4:
        raise ValueError("Refusing to delete that folder")
    if any(j.running for k, j in jobs.items() if Path(k) == root):
        raise ValueError("That video is still being created")
    # straight into ~/.Trash (no Finder automation permission needed); restore by dragging it back out
    trash = workspace.current().trash; trash.mkdir(parents=True, exist_ok=True)
    dst = trash / root.name
    if dst.exists():
        dst = trash / f"{root.name} {time.strftime('%H.%M.%S')}"
    try:
        shutil.move(str(root), str(dst))
    except OSError as e:
        raise ValueError(f"Couldn't move it to the Trash: {e}")
    jobs.pop(str(root), None)
    recent_file().write_text(json.dumps([x for x in recent() if not x.startswith(str(root))]))
    if P.proj and str(P.proj).startswith(str(root)):
        P.proj = None
    return root


# ------------------------------------------------------------- the reel library ("Open")
def discover():
    """Every reel project on this Mac: the library, recently opened ones, and Spotlight's reel.json hits."""
    found = {}
    def add(p):
        p = Path(p)
        if p.name == "reel.json":
            p = p.parent
        if ".editor" in p.parts or "references" in p.parts or not (p / "reel.json").exists() or not (p / "transcript.json").exists():
            return
        found[str(p.resolve())] = p.resolve()
    L = lib()
    if L.exists():
        for pattern in (f"{PROJECTS}/*/edit/reel.json", "*/edit/reel.json"):
            for f in L.glob(pattern):
                add(f)
    ws = workspace.current()
    for r in recent():
        if ws.inside(r):
            add(r)
    try:
        if workspace.PORTAL or not osutil.can_search():
            raise OSError("no Spotlight here (the server, or Windows)")
        out = subprocess.run(["mdfind", "-name", "reel.json"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if line.endswith("/reel.json"):
                add(line)
    except (OSError, subprocess.TimeoutExpired):
        pass
    rec = recent()
    items = []
    for key, p in found.items():
        try:
            spec = json.loads((p / "reel.json").read_text())
        except (OSError, ValueError):
            continue
        root = project_root(p)
        try:
            recorded = [Path(x["path"]) for x in json.loads((p / ".editor/renders.json").read_text())]
        except (OSError, ValueError, KeyError):
            recorded = []
        finals = [f for f in reversed(recorded) if f.exists()] + sorted((f for f in root.glob("*.mp4") if f.name != "base-edit.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
        items.append({"path": key, "name": project_name(p), "folder": str(root.parent), "modified": (p / "reel.json").stat().st_mtime,
                      "duration": spec.get("duration"), "cards": len(spec.get("cards", [])), "format": spec.get("format", "reel"),
                      "brand": spec.get("brand") or "default",
                      "rendered_path": str(finals[0]) if finals else None, "template": spec.get("template") or ("takeover" if spec.get("takeovers") else "clean"), "rendered": finals[0].name if finals else None,
                      "recent": rec.index(key) if key in rec else None, "open": P.proj is not None and key == str(P.proj)})
    items.sort(key=lambda x: (x["recent"] is None, x["recent"] if x["recent"] is not None else 0, -x["modified"]))
    return items


def choose_folder():
    return osutil.pick_folder("Pick a video folder (the one with edit/ or reel.json)")


# ------------------------------------------------------------- new reels ("New")
jobs = {}   # root path -> pipeline.Job


def slug(name):
    s = re.sub(r"[^\w\- ]+", "", name).strip() or "Reel"
    return re.sub(r"\s+", " ", s)[:60]


def new_project_dir(name):
    projects = lib() / PROJECTS; projects.mkdir(parents=True, exist_ok=True)
    base = slug(name); root = projects / base; n = 2
    while root.exists():
        root = projects / f"{base} {n}"; n += 1
    (root / "raw").mkdir(parents=True)
    return root


def caps(headers=None):
    s = settings()
    if workspace.PORTAL:
        cr = claude_client.creds_from(headers or {}, s)
        claude = cr.label if cr.available else None
    else:
        claude = pipeline.find_claude(s)
    return {"claude": claude, "ffmpeg": shutil.which("ffmpeg", path=ENV["PATH"]), "npx": shutil.which(osutil.NPX, path=ENV["PATH"]),
            "whisper": shutil.which("whisper-cli", path=ENV["PATH"]), "library": workspace.current().shown(s["library"])}


# ------------------------------------------------------------- render
render = workspace.SlotDict("render", proc=None, log=[], output=None, started=None, code=None, proj=None)


def start_render(title):
    if render["proc"] and render["proc"].poll() is None:
        return False
    safe = re.sub(r'[\\/:*?"<>|]+', "-", title).strip() or "Video"
    out = renders_dir(spec_format(P.proj), spec_brand(P.proj)) / f"{safe}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():   # never overwrite a finished video: the earlier one moves to "Previous versions"
        prev = out.parent / "Previous versions" / f"{safe} — {time.strftime('%Y-%m-%d %H.%M', time.localtime(out.stat().st_mtime))}.mp4"
        prev.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(prev))
    render.update(log=[], output=str(out), started=time.time(), code=None, proj=str(P.proj))
    cmd = [osutil.NPX, "-y", "hyperframes@latest", "render", "-q", "delivery", "--output", str(out)]
    p = subprocess.Popen(cmd, cwd=P.proj, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    render["proc"] = p

    def pump():
        for line in p.stdout:
            render["log"].append(line.rstrip())
            del render["log"][:-400]
        render["code"] = p.wait()
        if render["code"] == 0 and out.exists():
            record_render(render["proj"], out)
    workspace.Thread(target=pump, daemon=True).start()
    return True


def skill_info():
    icons = sorted(p.stem for p in (SKILL / "template/assets/icons").glob("*.svg") if not p.stem.startswith("si-"))
    logos = ["ghl", "sm", "meta", "gads", "claude"] + sorted(p.stem for p in (SKILL / "template/assets/logos").iterdir())
    templates = {}
    ex = SKILL / "references/example-reel.json"
    if ex.exists():
        for c in json.loads(ex.read_text()).get("cards", []):
            templates.setdefault(c["type"], c)
    tko = SKILL / "references/example-takeovers.json"
    takeovers = json.loads(tko.read_text()).get("takeovers", []) if tko.exists() else []
    return {"icons": icons, "logos": logos, "templates": templates, "takeoverTemplates": takeovers}


def brand_mark():
    """Just the mark from the white logo (the paths left of the wordmark), in the brand gradient."""
    logo = (SKILL / "template/assets/brand/logo-white.svg").read_text()
    paths = [m for m in re.findall(r'<path[^>]*/>|<path[^>]*>.*?</path>', logo, re.S)
             if (d := re.search(r'd="M\s*([\d.]+)', m)) and float(d.group(1)) < 140]
    body = "".join(re.sub(r'fill="[^"]*"', 'fill="url(#mg)"', x) for x in paths)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 140 134.6"><defs><linearGradient id="mg" x1="0" y1="1" x2="1" y2="0">'
            '<stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#2563eb"/></linearGradient></defs>' + body + "</svg>").encode()


def brand_logo_light():
    """The logo for light backgrounds : gradient mark, charcoal wordmark."""
    logo = (SKILL / "template/assets/brand/logo-white.svg").read_text()
    def recolour(m):
        tag = m.group(0)
        d = re.search(r'd="M\s*([\d.]+)', tag)
        return re.sub(r'fill="[^"]*"', 'fill="url(#mgl)"' if d and float(d.group(1)) < 140 else 'fill="#2d3136"', tag)
    body = re.sub(r'<path[^>]*/>|<path[^>]*>.*?</path>', recolour, logo, flags=re.S)
    body = re.sub(r'(<(?:rect|polygon|circle|ellipse|text)\b[^>]*?)fill="#FFFFFF"', r'\1fill="#2d3136"', body, flags=re.I)  # the i-dots and stems
    grad = ('<linearGradient id="mgl" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#22d3ee"/>'
            '<stop offset="1" stop-color="#2563eb"/></linearGradient>')
    return re.sub(r"<defs>", "<defs>" + grad, body, count=1).encode()


def safe_path(base, rel, roots):
    # normalise without following symlinks (the preview links to the project's video and assets)
    p = Path(os.path.normpath(base / unquote(rel)))
    if not any(str(p).startswith(str(r) + os.sep) for r in roots if r):
        return None
    return p


TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".mp4": "video/mp4", ".mov": "video/quicktime",
         ".ttf": "font/ttf", ".woff2": "font/woff2", ".wav": "audio/wav", ".webm": "video/webm", ".m4v": "video/mp4"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def send_file(self, p, inject=None, cache="no-cache", replace=None, download=False, filename=None):
        if not p or not p.is_file():
            self.send_error(404); return
        ctype = TYPES.get(p.suffix.lower(), "application/octet-stream")
        if inject is not None:
            page = p.read_text()
            if replace:
                page = page.replace(*replace)
            data = page.replace("</body>", f"<script>\n{inject}\n</script>\n</body>").encode()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data); return
        size = p.stat().st_size
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", rng) if rng else None
        if m:
            if m.group(1):
                start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = size - int(m.group(2))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        if download:
            from urllib.parse import quote
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename or p.name)}")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        try:
            with open(p, "rb") as f:
                f.seek(start); left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk); left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def parse_request(self):
        """After the headers: pick the workspace this request is for (on the portal: the user it names)."""
        if not super().parse_request():
            return False
        try:
            workspace.use(workspace.for_request(self.headers))
        except workspace.Denied as e:
            workspace.use(None)
            self.send_json({"error": str(e)}, 401)
            return False
        return True

    def need_project(self):
        if P.proj is None:
            self.send_json({"error": "No video is open"}, 409); return False
        return True

    def do_GET(self):
        u = urlparse(self.path); path = u.path; q = parse_qs(u.query)
        if LONG and (path.startswith("/long/") or path.startswith("/api/long/")) and LONG.handle(self, "GET", path, q):
            return
        if STUDIO and path.startswith(("/studio/", "/api/studio/")) and STUDIO.handle(self, "GET", path, q, STUDIO.short_ctx(P.proj)):
            return
        if PLANNER and STUDIO and path.startswith(("/planner/", "/api/planner/")) and PLANNER.handle(self, "GET", path, q, STUDIO.short_ctx(P.proj), lambda: latest_render(P.proj)):
            return
        if SOCIAL and path.startswith("/api/social") and SOCIAL.handle(self, "GET", path, q):
            return
        if POSTING and path.startswith(("/api/calendar/", "/calendar/")) and POSTING.handle(self, "GET", path, q):
            return
        if RESULTS and path.startswith("/api/results") and RESULTS.handle(self, "GET", path, q):
            return
        if CONNECT and path.startswith(("/api/connect/", "/connect/callback/")) and CONNECT.handle(self, "GET", path, q):
            return
        if TESTPLATFORM and path.startswith("/testplatform") and TESTPLATFORM.handle(self, "GET", path, q):
            return
        if BRANDS and (path.startswith(("/brands/", "/brandstage/", "/api/brands", "/api/fonts/"))) and BRANDS.handle(self, "GET", path, q):
            return
        if path == "/api/sections":
            return self.send_json({"long": LONG is not None, "brands": BRANDS is not None, "studio": STUDIO is not None, "planner": PLANNER is not None,
                                   "calendar": POSTING is not None, "results": RESULTS is not None})
        if path == "/":
            # on the portal there's no Finder: the page uploads files and offers downloads instead (window.PORTAL)
            if workspace.PORTAL:
                return self.send_file(APP / "index.html", inject="", replace=("<head>", "<head>\n<script>window.PORTAL = true;</script>"))
            return self.send_file(APP / "index.html")
        if path.startswith("/brand/"):
            # the default brand logo, logo mark and brand fonts, straight from the skill's template
            name = Path(unquote(path[len("/brand/"):])).name
            if name == "mark.svg":
                return self.send_bytes(brand_mark(), "image/svg+xml")
            if name == "logo-light.svg":
                return self.send_bytes(brand_logo_light(), "image/svg+xml")
            for sub in ("brand", "fonts"):
                f = SKILL / "template/assets" / sub / name
                if f.is_file():
                    return self.send_file(f, cache="max-age=86400")
            return self.send_error(404)
        if path.startswith("/app/"):
            return self.send_file(safe_path(APP, path[5:], [APP]))
        if path.startswith("/preview/"):
            if P.proj is None:
                return self.send_error(404)
            rel = path[len("/preview/"):]
            p = safe_path(P.shadow, rel, [P.proj])
            if rel == "index.html":
                # version the video URL so a re-rendered base edit is never served from the browser's cache
                spec = json.loads((P.shadow / "reel.json").read_text()) if (P.shadow / "reel.json").exists() else {}
                vid = spec.get("video", "base-edit.mp4"); vp = P.proj / vid
                ver = int(vp.stat().st_mtime) if vp.exists() else 0
                return self.send_file(p, inject=(APP / "preview-shim.js").read_text(), replace=(f'src="{vid}"', f'src="{vid}?v={ver}"'))
            return self.send_file(p)
        if path == "/api/project":
            if P.proj is None:
                return self.send_json({"none": True, "caps": caps(self.headers)})
            spec = json.loads((P.proj / "reel.json").read_text())
            return self.send_json({"name": project_name(P.proj), "path": str(P.proj), "build": str(P.build), "spec": spec,
                                   "transcript": json.loads((P.proj / "transcript.json").read_text()), "caps": caps(self.headers), **skill_info()})
        if path == "/api/reels":
            ws = workspace.current()
            return self.send_json({"reels": discover(), "library": ws.shown(settings()["library"]), "renders": str(lib() / RENDERS), "projects": ws.shown(lib() / PROJECTS)})
        if path == "/api/download":
            # a finished video (or any file in the user's library) as a download: the portal's "Show in Finder"
            p = Path(q.get("path", [""])[0])
            ok = p.is_file() and workspace.current().inside(p) and (str(p.resolve()).startswith(str(lib().resolve())) or p.suffix.lower() in (".mp4", ".mov"))
            return self.send_file(p if ok else None, download=True)
        if path.startswith("/api/upload/"):
            uploads.handle(self, "GET", path); return
        if path == "/api/thumb":
            p = Path(q.get("path", [""])[0])
            if not (p / "reel.json").exists() or not workspace.current().inside(p):
                return self.send_error(404)
            return self.send_file(thumb(p), cache="max-age=3600")
        if path == "/api/peaks":
            if not self.need_project():
                return
            spec = json.loads((P.proj / "reel.json").read_text())
            try:
                return self.send_json({"perSec": 100, "peaks": peaks(spec)})
            except Exception as e:
                return self.send_json({"perSec": 100, "peaks": [], "error": str(e)})
        if path == "/api/edl":
            if not self.need_project():
                return
            raw = find_raw()
            ef = project_root(P.proj) / "work/edl.json"
            return self.send_json({"segments": edl_segments(), "raw": workspace.current().shown(raw) if raw else None,
                                   "raw_segments": cuts.to_virtual(json.loads(ef.read_text()).get("segments", []), insert_len) if ef.exists() else [],
                                   "raw_dur": raw_duration(raw) if raw else None,
                                   "editable": (project_root(P.proj) / "work/edl.json").exists(), "zoomjob": zoomjob.copy()})
        if path == "/api/zoom/status":
            return self.send_json({**zoomjob.copy(), "elapsed": time.time() - zoomjob["started"] if zoomjob["started"] else 0})
        if path == "/api/filmstrip":
            if not self.need_project():
                return
            try:
                return self.send_json(filmstrip(json.loads((P.proj / "reel.json").read_text())))
            except Exception as e:
                return self.send_json({"error": str(e)})
        if path == "/api/filmstrip.jpg":
            if not self.need_project():
                return
            return self.send_file(P.editor / "filmstrip.jpg", cache="max-age=3600")
        if path == "/api/new/status":
            j = jobs.get(q.get("root", [""])[0])
            j = j if j and workspace.current().inside(j.root) else None
            return self.send_json(j.status() if j else {"error": "No such job"}, 200 if j else 404)
        if path == "/api/new/raw":
            j = jobs.get(q.get("root", [""])[0])
            j = j if j and workspace.current().inside(j.root) else None
            return self.send_file(j.raw if j else None)
        if path == "/api/render/target":
            if not self.need_project():
                return
            fmt = spec_format(P.proj)
            return self.send_json({"folder": workspace.current().shown(renders_dir(fmt, spec_brand(P.proj))), "format": FORMAT_FOLDERS.get(fmt, "Reel 9x16"), "library": workspace.current().shown(lib()), "renders": RENDERS})
        if path == "/api/render":
            p = render["proc"]
            return self.send_json({"running": bool(p and p.poll() is None), "code": render["code"], "output": render["output"],
                                   "log": render["log"][-60:], "elapsed": time.time() - render["started"] if render["started"] else 0})
        self.send_error(404)

    def do_PUT(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if TESTPLATFORM and u.path.startswith("/testplatform") and TESTPLATFORM.handle(self, "PUT", u.path, q):
            return
        if STUDIO and u.path.startswith("/api/studio/") and STUDIO.handle(self, "PUT", u.path, q, STUDIO.short_ctx(P.proj)):
            return
        if u.path.startswith("/api/upload/"):
            uploads.handle(self, "PUT", u.path); return
        if u.path != "/api/new/upload":
            return self.send_error(404)
        name = q.get("name", ["Reel"])[0]
        fname = Path(q.get("file", ["raw.mp4"])[0]).name
        if Path(fname).suffix.lower() not in (".mp4", ".mov", ".m4v", ".webm", ".mkv"):
            return self.send_json({"error": "That doesn't look like a video file"}, 400)
        root = new_project_dir(name)
        dst = root / "raw" / fname
        left = int(self.headers.get("Content-Length", 0))
        with open(dst, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk); left -= len(chunk)
        if left > 0:
            shutil.rmtree(root, ignore_errors=True)
            return self.send_json({"error": "The upload was cut short"}, 400)
        return self.send_json({"root": str(root), "raw": str(dst)})

    def do_DELETE(self):
        u = urlparse(self.path)
        if TESTPLATFORM and u.path.startswith("/testplatform") and TESTPLATFORM.handle(self, "DELETE", u.path, parse_qs(u.query)):
            return
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if LONG and path.startswith("/api/long/") and LONG.handle(self, "POST", path, parse_qs(urlparse(self.path).query)):
            return
        if STUDIO and path.startswith("/api/studio/") and STUDIO.handle(self, "POST", path, {}, STUDIO.short_ctx(P.proj)):
            return
        if PLANNER and STUDIO and path.startswith("/api/planner/") and PLANNER.handle(self, "POST", path, {}, STUDIO.short_ctx(P.proj), lambda: latest_render(P.proj)):
            return
        if SOCIAL and path.startswith("/api/social") and SOCIAL.handle(self, "POST", path, {}):
            return
        if POSTING and path.startswith("/api/calendar/") and POSTING.handle(self, "POST", path, {}):
            return
        if RESULTS and path.startswith("/api/results") and RESULTS.handle(self, "POST", path, {}):
            return
        if CONNECT and path.startswith("/api/connect/") and CONNECT.handle(self, "POST", path, {}):
            return
        if TESTPLATFORM and path.startswith("/testplatform") and TESTPLATFORM.handle(self, "POST", path, parse_qs(urlparse(self.path).query)):
            return
        if BRANDS and path.startswith("/api/brands") and BRANDS.handle(self, "POST", path, parse_qs(urlparse(self.path).query)):
            return
        if path == "/api/open":
            try:
                p = open_project(self.body()["path"])
                return self.send_json({"ok": True, "path": str(p)})
            except (ValueError, KeyError) as e:
                return self.send_json({"ok": False, "error": str(e)}, 400)
        if path == "/api/delete":
            try:
                root = trash_reel(self.body()["path"])
                return self.send_json({"ok": True, "trashed": str(root), "wasOpen": P.proj is None})
            except (ValueError, KeyError) as e:
                return self.send_json({"ok": False, "error": str(e)}, 400)
        if path.startswith("/api/upload/"):
            uploads.handle(self, "POST", path); return
        if path == "/api/new/upload":
            # the portal's New: the camera file came up with /api/upload (resumable); it moves into a new project's raw/
            b = self.body()
            try:
                if Path(str(b.get("file", ""))).suffix.lower() not in VIDEO_EXT:
                    raise ValueError("That doesn't look like a video file")
                root = new_project_dir(b.get("name") or "Reel")
                try:
                    dst = uploads.take(b.get("upload"), root / "raw", b.get("file"))
                except ValueError:
                    shutil.rmtree(root, ignore_errors=True); raise
                return self.send_json({"root": str(root), "raw": str(dst)})
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
        if path == "/api/reveal":
            if workspace.PORTAL:          # no Finder on the server: the page offers a download instead
                return self.send_json({"ok": False, "error": "Not on the portal (use Download)"}, 400)
            target = Path(self.body().get("path", ""))
            if target == lib() / RENDERS:
                target.mkdir(parents=True, exist_ok=True)
                osutil.reveal(target)
                return self.send_json({"ok": True})
            # anything in the library, or a finished video anywhere (showing a file in Finder changes nothing)
            if target.exists() and (str(target).startswith(str(lib())) or (target.is_file() and target.suffix.lower() in (".mp4", ".mov"))):
                osutil.reveal(target)
                return self.send_json({"ok": True})
            return self.send_json({"ok": False}, 400)
        if path == "/api/browse":
            return self.send_json({"path": None if workspace.PORTAL else choose_folder()})
        if path == "/api/new/start":
            b = self.body()
            root = Path(b["root"]); raw = Path(b["raw"])
            if not str(root).startswith(settings()["library"]) or not raw.exists():
                return self.send_json({"error": "Unknown project"}, 400)
            j = jobs.get(str(root)) or pipeline.Job(root, raw, b.get("notes", ""), SKILL, ENV, settings(), b.get("format", "reel"), b.get("template", "clean"), b.get("brand"))
            jobs[str(root)] = j
            j.notes = b.get("notes", j.notes)
            cr = claude_client.creds_from(self.headers, settings())   # this request's Claude (portal: the user's key)
            j.claude = cr if cr.available else None
            j.start(b.get("from"))
            return self.send_json(j.status())
        if path == "/api/new/claude-check":
            return self.send_json(caps(self.headers))
        if not self.need_project():
            return
        if path == "/api/zoom/apply":
            try:
                apply_zooms(self.body().get("zooms", {}))
                return self.send_json({"ok": True})
            except (ValueError, IndexError, KeyError) as e:
                return self.send_json({"ok": False, "error": str(e)}, 400)
        if path == "/api/overlay/pick":
            # a clip to lay over the main video: picked in Finder (or uploaded, on the portal), copied into
            # edit/assets/overlays/ (renders need it there)
            b = self.body()
            if b.get("upload"):
                try:
                    src = uploads.take(b["upload"], P.proj / ".editor" / "incoming")
                except ValueError as e:
                    return self.send_json({"ok": False, "error": str(e)}, 400)
                if src.suffix.lower() not in VIDEO_EXT:
                    src.unlink(missing_ok=True)
                    return self.send_json({"ok": False, "error": "That isn't a video file"}, 400)
            elif workspace.PORTAL:
                return self.send_json({"ok": False, "error": "Upload the video"}, 400)
            else:
                got = osutil.pick_files("Choose a video to lay over this one (an insert, B-roll or a testimonial)", "video")
                src = Path(got[0]) if got else None
            if not src or not src.is_file():
                return self.send_json({"ok": False})
            dest_dir = P.proj / "assets" / "overlays"
            dest_dir.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^\w.-]+", "-", src.stem).strip("-")[:60] or "clip"
            dest = dest_dir / f"{name}{src.suffix.lower()}"
            k = 2
            while dest.exists() and dest.stat().st_size != src.stat().st_size:
                dest = dest_dir / f"{name}-{k}{src.suffix.lower()}"; k += 1
            if not dest.exists():
                shutil.copy2(src, dest)
            if b.get("upload"):
                src.unlink(missing_ok=True)
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                                  "-of", "json", str(dest)], capture_output=True, text=True, env=ENV).stdout
            try:
                d = json.loads(out or "{}"); st = (d.get("streams") or [{}])[0]
                info = {"dur": round(float(d["format"]["duration"]), 2), "w": st.get("width"), "h": st.get("height")}
            except (KeyError, ValueError):
                info = {"dur": 5.0, "w": None, "h": None}
            has_audio = bool(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(dest)],
                                            capture_output=True, text=True, env=ENV).stdout.strip())
            return self.send_json({"ok": True, "src": f"assets/overlays/{dest.name}", "name": src.stem, "audio": has_audio, **info})
        if path == "/api/takeover/suggest":
            b = self.body()
            spec = b.get("spec") or json.loads((P.proj / "reel.json").read_text())
            words = json.loads((P.proj / "transcript.json").read_text())
            s = settings()
            try:
                tk, how = fill.suggest(b.get("kind", "list"), float(b.get("t", 0)), words, spec, SKILL,
                                       claude_client.creds_from(self.headers, s), env=ENV, cwd=str(P.proj))
                return self.send_json({"ok": True, "takeover": tk, "how": how})
            except Exception as e:                       # never leave the editor waiting
                return self.send_json({"ok": False, "error": str(e)}, 500)
        if path == "/api/cuts/insert":
            try:
                b = self.body()
                if b.get("clip"):                               # an AI studio clip: <project>/studio/clips/<id>/clip.mp4
                    f = project_root(P.proj) / "studio/clips" / re.sub(r"[^a-f0-9]", "", b["clip"]) / "clip.mp4"
                else:
                    raise ValueError("Say which clip to insert")
                if not f.exists():
                    raise ValueError("That clip isn't finished")
                return self.send_json({"ok": True, **insert_clip(f, float(b.get("t", 0)))})
            except (ValueError, IndexError, KeyError, TypeError) as e:
                return self.send_json({"ok": False, "error": str(e)}, 400)
        if path == "/api/cuts/apply":
            try:
                apply_cuts(self.body().get("segments", []))
                return self.send_json({"ok": True})
            except (ValueError, IndexError, KeyError, TypeError) as e:
                return self.send_json({"ok": False, "error": str(e)}, 400)
        if path == "/api/zoom/locate":
            b = self.body()
            if b.get("upload"):                     # the portal: the camera file was uploaded; it's kept in the project's raw/
                try:
                    p = uploads.take(b["upload"], project_root(P.proj) / "raw")
                except ValueError as e:
                    return self.send_json({"ok": False, "error": str(e)})
            elif workspace.PORTAL:
                return self.send_json({"ok": False, "error": "Upload the camera video"})
            else:
                got = osutil.pick_files("Pick the raw camera video this reel was cut from", "any")
                p = Path(got[0]) if got else None
            if not p:
                return self.send_json({"ok": False})
            edl_f = project_root(P.proj) / "work/edl.json"
            need = max((s["out"] for s in json.loads(edl_f.read_text()).get("segments", [])), default=0) if edl_f.exists() else 0
            bad = ("That isn't a video file" if p.suffix.lower() not in VIDEO_EXT else
                   f"That video is too short ({probe_duration(p):.1f}s); the cut list needs {need:.1f}s" if probe_duration(p) + 0.2 < need else None)
            if bad:
                if b.get("upload"):
                    p.unlink(missing_ok=True)          # an uploaded file that can't be used isn't kept
                return self.send_json({"ok": False, "error": bad})
            (project_root(P.proj) / "work").mkdir(exist_ok=True)
            (project_root(P.proj) / "work/source.json").write_text(json.dumps({"raw": str(p)}))
            return self.send_json({"ok": True, "raw": workspace.current().shown(p)})
        if path == "/api/preview":
            spec = self.body()["spec"]
            prepare_shadow(spec)
            ok, log = run_build(spec, P.shadow)
            return self.send_json({"ok": ok, "log": log[-4000:], "groups": parse_build(P.shadow) if ok else None})
        if path == "/api/save":
            spec = self.body()["spec"]
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy(P.proj / "reel.json", P.backups / f"reel-{stamp}.json")
            ok, log = run_build(spec, P.proj)
            return self.send_json({"ok": ok, "log": log[-4000:], "backup": f"reel-{stamp}.json"})
        if path == "/api/render":
            ok = start_render(self.body().get("title", "Reel"))
            return self.send_json({"ok": ok}, 200 if ok else 409)
        if path == "/api/render/stop":
            if render["proc"] and render["proc"].poll() is None:
                osutil.stop_tree(render["proc"])
            return self.send_json({"ok": True})
        self.send_error(404)


if not workspace.PORTAL:
    try:
        migrate_library()
    except OSError as e:
        print(f"  (couldn't reorganise the library: {e})")

if args.project and not workspace.PORTAL:
    try:
        open_project(args.project)
    except ValueError as e:
        sys.exit(str(e))

# A page load fires dozens of requests at once (styles, scripts, preview frames, thumbnails). The standard queue of 5
# waiting connections overflowed and reset some of them (a page without its styles), so allow many more.
ThreadingHTTPServer.request_queue_size = 128
if CONNECT:
    CONNECT.PUBLIC = f"http://127.0.0.1:{args.port}"
if POSTING:
    POSTING.start()          # the scheduler: posts (or reminds about) scheduled posts on time
if workspace.PORTAL and args.host not in ("127.0.0.1", "localhost") and not workspace.SECRET:
    sys.exit("Set STUDIO_PORTAL_SECRET before listening beyond this machine (anyone could claim to be any user)")
srv = ThreadingHTTPServer((args.host, args.port), H)
url = f"http://127.0.0.1:{args.port}/"
if workspace.PORTAL:
    print(f"Studio AI (portal mode)\n  storage: {workspace.DATA}\n  listen:  {args.host}:{args.port}\n(Ctrl+C to stop)")
else:
    print(f"Studio AI short-form editor\n  video:   {P.proj or '(home screen)'}\n  library: {settings()['library']}\n  open:    {url}\n(Ctrl+C to stop)")
if not args.no_open and not workspace.PORTAL:
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
try:
    srv.serve_forever()
except KeyboardInterrupt:
    pass
