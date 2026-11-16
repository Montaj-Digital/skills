"""Long-form routes for the Studio AI short-form editor.

The short-form editor's server.py imports this file (when it exists) and hands it every /long/... and /api/long/...
request: `longform.handle(handler, "GET" | "POST", path, query)` returns True when it answered the request.
Everything long-form lives in this folder; the short-form server only calls this module.
Python 3.9 standard library only.
"""
import json, os, re, shutil, subprocess, time
from pathlib import Path
from urllib.parse import unquote

import pipeline_long
import render_long
import workspace
import osutil           # macOS / Windows differences (phase 8)
import cuts            # the short-form editor's cut helpers (same server process): inserts' virtual ranges

HERE = Path(__file__).resolve().parent          # 04. Editor
BASE = HERE.parent                               # 02. Studio AI Long-form Video Editor
APP = HERE / "app"
PROJECTS, RENDERS = "05. Projects", "06. Renders"
# Studio AI uses its own copy of the skill (02. Skill/studio-longform), so changes here never reach the stable editor.
SKILL = Path(os.environ.get("STUDIO_LONGFORM_SKILL", BASE / "02. Skill" / "studio-longform"))
ENV = osutil.tool_env()
VIDEO_EXT = (".mov", ".mp4", ".m4v", ".mkv", ".webm")
jobs = {}   # project root -> LongJob
renders = {}   # project root -> RenderJob (the latest)


def version():
    try:
        return (HERE / "VERSION").read_text().strip()
    except OSError:
        return "0"


def settings():
    # long-form's settings.json on a Mac; the user's settings on the portal (workspace.py)
    return workspace.current().settings("long")


def base():
    """Where 05. Projects and 06. Renders are: this folder on a Mac, the user's storage on the portal."""
    return workspace.current().long_base


def projects_dir():
    d = base() / PROJECTS; d.mkdir(parents=True, exist_ok=True); return d


def safe_root(p):
    """A project folder inside 05. Projects, or None."""
    try:
        r = Path(p).resolve()
    except (OSError, ValueError):
        return None
    pd = projects_dir().resolve()
    return r if r.parent == pd and (r / "project.json").exists() else None


def job_for(root):
    k = str(root)
    if k not in jobs:
        jobs[k] = pipeline_long.LongJob(root, SKILL, ENV, settings())
    return jobs[k]


def slug(name):
    s = re.sub(r"[^\w\- ]+", "", name).strip() or "Long video"
    return re.sub(r"\s+", " ", s)[:60]


def new_project_dir(name):
    base = slug(name); root = projects_dir() / base; n = 2
    while root.exists():
        root = projects_dir() / f"{base} {n}"; n += 1
    (root / "raw").mkdir(parents=True)
    return root


def uploaded(b, dest):
    """The portal: a file the page uploaded (/api/upload) moves into dest. A Mac: None (Finder is used instead)."""
    if b.get("upload"):
        import uploads
        return str(uploads.take(b["upload"], dest))
    if workspace.PORTAL:
        raise ValueError("Upload the file (there's no Finder on the portal)")
    return None


def finder_pick(prompt, types):
    got = osutil.pick_files(prompt, "subtitles" if "srt" in types else "video")
    return got[0] if got else None


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration,size",
                          "-of", "json", str(path)], capture_output=True, text=True, env=ENV).stdout
    try:
        d = json.loads(out or "{}"); st = (d.get("streams") or [{}])[0]
        return {"duration": float(d["format"]["duration"]), "width": st.get("width"), "height": st.get("height"), "size": int(d["format"].get("size", 0))}
    except (KeyError, ValueError):
        return {}


def thumb(root):
    jpg = root / "work" / "thumb.jpg"
    if not jpg.exists():
        meta = json.loads((root / "project.json").read_text())
        (root / "work").mkdir(exist_ok=True)
        d = probe(meta["raw"]).get("duration", 60)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(d * 0.12), "-i", meta["raw"], "-frames:v", "1", "-vf", "scale=640:-2", str(jpg)],
                       env=ENV, capture_output=True)
    return jpg if jpg.exists() else None


def peaks(root, per_sec=10):
    """Loudness of the camera file, one value (0-255) per 1/per_sec s of RAW time, cached in work/peaks.json."""
    f = root / "work" / "peaks.json"
    if f.exists():
        return json.loads(f.read_text())
    from array import array
    meta = json.loads((root / "project.json").read_text())
    rate = 4000
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", meta["raw"], "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"], stdout=subprocess.PIPE, env=ENV)
    n, out, buf = rate // per_sec, [], b""
    while True:
        chunk = p.stdout.read(n * 2 * 600)
        if not chunk:
            break
        buf += chunk
        k = (len(buf) // (n * 2)) * n * 2
        a = array("h"); a.frombytes(buf[:k]); buf = buf[k:]
        for i in range(0, len(a), n):
            out.append(min(255, max(map(abs, a[i:i + n])) // 128))
    p.wait()
    res = {"perSec": per_sec, "peaks": out}
    (root / "work").mkdir(exist_ok=True); f.write_text(json.dumps(res))
    return res


def save_cuts(root, segments):
    """Manual cuts from the editor: a new cut list (raw times). Writes work/edl.json (old one backed up) and maps the
    raw transcript onto the new timeline (work/words-edit.json). Returns the new edited duration.
    Inserts (Studio AI) arrive in their virtual range (cuts.py) and are written back in their own file's seconds; the
    list keeps the editor's order, since an insert sits between camera clips."""
    raw_dur = probe(Path(json.loads((root / "project.json").read_text())["raw"])).get("duration")
    segs = []
    has_ins = any(s.get("src") for s in segments)
    for s in (segments if has_ins else sorted(segments, key=lambda s: float(s["in"]))):
        a, b = float(s["in"]), float(s["out"])
        if s.get("src"):
            lo = cuts.vbase(s["src"]); hi = lo + float(s.get("clip") or (b - lo))
            a, b = max(lo, min(a, hi)), max(lo, min(b, hi))
        elif raw_dur:
            a, b = max(0.0, min(a, raw_dur)), max(0.0, min(b, raw_dur))
        if b - a >= 0.1:
            segs.append({**s, "in": round(a, 3), "out": round(b, 3)})
    if not segs:
        raise ValueError("That would remove the whole video")
    edl_f = root / "work" / "edl.json"
    edl = json.loads(edl_f.read_text()) if edl_f.exists() else {}
    bk = root / "work" / "backups"; bk.mkdir(parents=True, exist_ok=True)
    if edl_f.exists():
        shutil.copy(edl_f, bk / f"edl-{time.strftime('%Y%m%d-%H%M%S')}.json")
    edl["segments"] = cuts.to_real(segs)
    edl_f.write_text(json.dumps(edl, indent=1))
    tj = root / "work" / "transcript.json"
    if tj.exists():
        words = pipeline_long.map_to_edit(json.loads(tj.read_text()), segs)
        (root / "work" / "words-edit.json").write_text(json.dumps(words))
    return round(sum(s["out"] - s["in"] for s in segs), 3)


def with_creds(job, h):
    """The job uses this request's Claude: the portal's per-user API key, or Claude Code on this Mac."""
    import claude_client
    cr = claude_client.creds_from(h.headers, settings())
    job.claude = cr if cr.available else None


def insert_len(root, src):
    f = root / src
    return round(probe(f).get("duration") or 0.0, 3) if f.exists() else 0.0


def save_spec(root, spec, segments=None):
    """Write longform.json (keeping a backup) and refresh chapters.txt. With segments, the cut list changes too."""
    if not isinstance(spec, dict) or not isinstance(spec.get("chapters"), list) or not isinstance(spec.get("duration"), (int, float)):
        raise ValueError("That isn't a long-form plan")
    if segments:
        spec["duration"] = save_cuts(root, segments)
    f = root / "longform.json"
    bk = root / "work" / "backups"; bk.mkdir(parents=True, exist_ok=True)
    if f.exists():
        shutil.copy(f, bk / f"longform-{time.strftime('%Y%m%d-%H%M%S')}.json")
        for old in sorted(bk.glob("longform-*.json"))[:-30]:     # keep the last 30
            old.unlink()
    f.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
    ch = sorted(spec["chapters"], key=lambda c: c.get("start", 0))
    (root / "chapters.txt").write_text(pipeline_long.chapters_txt(ch, spec["duration"]) if ch else "")
    m = json.loads((root / "project.json").read_text()); m["captions"] = bool(spec.get("captions", {}).get("on"))
    (root / "project.json").write_text(json.dumps(m, indent=2))


def latest_render(root):
    """The newest full render of a long-form video (06. Renders/[<Client>/]Long-form 16x9/<name>*.mp4), or None."""
    if not root:
        return None
    try:
        meta = json.loads((root / "project.json").read_text())
        spec = json.loads((root / "longform.json").read_text()) if (root / "longform.json").exists() else {}
    except (OSError, ValueError):
        return None
    brand = spec.get("brand") or meta.get("brand") or "default"
    files = [f for f in render_long.renders_dir(base(), brand).glob(f"{root.name}*.mp4") if f.is_file()]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def library():
    items = []
    for p in sorted(projects_dir().iterdir()):
        if not (p / "project.json").exists():
            continue
        try:
            meta = json.loads((p / "project.json").read_text())
        except ValueError:
            continue
        spec = {}
        if (p / "longform.json").exists():
            try:
                spec = json.loads((p / "longform.json").read_text())
            except ValueError:
                pass
        j = job_for(p)
        brand = spec.get("brand") or meta.get("brand") or "default"
        rend = sorted((render_long.renders_dir(base(), brand)).glob(f"{p.name}*.mp4"))
        items.append({"root": str(p), "name": meta.get("name", p.name), "created": meta.get("created"), "modified": (p / "project.json").stat().st_mtime,
                      "duration": spec.get("duration"), "chapters": len(spec.get("chapters", [])), "cards": len(spec.get("cards", [])),
                      "done": j.done, "failed": any(v == "failed" for v in j.state.values()), "running": j.running,
                      "rendered": rend[-1].name if rend else None, "brand": brand})
    items.sort(key=lambda x: -(x["modified"] or 0))
    return items


def trash(root):
    t = workspace.current().trash; t.mkdir(parents=True, exist_ok=True); dst = t / root.name; n = 2
    while dst.exists():
        dst = t / f"{root.name} {n}"; n += 1
    shutil.move(str(root), str(dst))     # the camera file is only linked, so the original stays where it was
    jobs.pop(str(root), None)


def create_project(b):
    src = Path(b.get("path", "")).expanduser()
    if not src.is_file() or src.suffix.lower() not in VIDEO_EXT or not workspace.current().inside(src):
        raise ValueError("Choose the camera file first")
    name = (b.get("name") or "").strip() or src.stem
    root = new_project_dir(name)
    link = root / "raw" / src.name
    if workspace.PORTAL:
        shutil.move(str(src), str(link)); src = link     # the portal: the uploaded file moves into the project
    else:
        try:
            osutil.link(src, link)       # linked, never copied: a long recording can be 20-100 GB
        except OSError:
            link = src
    tr = b.get("transcript") or {}
    if tr.get("path") and not workspace.current().inside(tr["path"]):
        raise ValueError("Choose the subtitle file again")
    meta = {"name": name, "raw": str(link), "source": str(src), "notes": b.get("notes", ""), "captions": bool(b.get("captions", True)),
            **({"brand": b["brand"]} if b.get("brand") and b["brand"] != "default" else {}),
            "transcript": {"mode": tr.get("mode", "none"), **({"text": tr["text"]} if tr.get("text") else {}), **({"path": tr["path"]} if tr.get("path") else {})},
            "created": time.time(), "version": version()}
    (root / "project.json").write_text(json.dumps(meta, indent=2))
    return root


def handle(h, method, path, q):
    """Answer a /long/... or /api/long/... request. Returns True if it was ours."""
    # the AI studio (01. Short-form/04. Editor/studio.py, loaded by the server): same routes with ?root=<project>
    if path.startswith(("/api/long/studio/", "/long/studio/")):
        try:
            import studio
        except ImportError:
            return False
        root = safe_root(unquote(q.get("root", [""])[0]))
        inner = path.replace("/api/long/studio/", "/api/studio/", 1).replace("/long/studio/", "/studio/", 1)
        return studio.handle(h, method, inner, q, studio.long_ctx(root))
    # Post it (01. Short-form/04. Editor/planner.py): same routes with ?root=<project>
    if path.startswith(("/api/long/planner/", "/long/planner/")):
        try:
            import planner, studio
        except ImportError:
            return False
        root = safe_root(unquote(q.get("root", [""])[0]))
        inner = path.replace("/api/long/planner/", "/api/planner/", 1).replace("/long/planner/", "/planner/", 1)
        return planner.handle(h, method, inner, q, studio.long_ctx(root) if root else None, lambda: latest_render(root))
    if path.startswith("/long/app/") and method == "GET":
        rel = unquote(path[len("/long/app/"):])
        p = (APP / rel).resolve()
        if APP.resolve() not in p.parents:
            h.send_error(404); return True
        h.send_file(p); return True
    if not path.startswith("/api/long/"):
        return False
    route = path[len("/api/long/"):]
    first = lambda k, d="": q.get(k, [d])[0]
    try:
        if method == "GET":
            if route == "projects":
                ws = workspace.current()
                h.send_json({"projects": library(), "folder": ws.shown(base() / PROJECTS), "renders": ws.shown(base() / RENDERS), "version": version()}); return True
            root = safe_root(first("root"))
            if route == "overlay-file":
                # a clip picked for this project (not saved yet, so any video file on this Mac; this server only listens locally)
                src = Path(first("src"))
                ok = src.suffix.lower() in (".mov", ".mp4", ".m4v", ".mkv", ".webm") and src.is_file() and workspace.current().inside(src)
                h.send_file(src if ok else None); return True
            if route in ("status", "project", "video", "thumb", "words", "peaks", "render-status", "render-file"):
                if not root:
                    h.send_json({"error": "No such long-form project"}, 404); return True
                if route == "status":
                    h.send_json(job_for(root).status())
                elif route == "project":
                    spec = json.loads((root / "longform.json").read_text()) if (root / "longform.json").exists() else None
                    cj = root / "chapters.txt"
                    cut = root / "work" / "cut-report.txt"
                    edl = root / "work" / "edl.json"
                    h.send_json({"meta": json.loads((root / "project.json").read_text()), "spec": spec,
                                 "edl": cuts.to_virtual(json.loads(edl.read_text())["segments"], lambda src: insert_len(root, src)) if edl.exists() else [], "chapters_txt": cj.read_text() if cj.exists() else "",
                                 "cut_report": cut.read_text() if cut.exists() else "", "status": job_for(root).status()})
                elif route == "render-status":
                    r = renders.get(str(root))
                    h.send_json(r.status() if r else {"none": True})
                elif route == "render-file":
                    name = first("name")
                    f = root / "work" / "render" / name
                    h.send_file(f if name in ("preview.mp4",) and f.exists() else None)
                elif route == "peaks":
                    h.send_json(peaks(root))
                elif route == "words":
                    wf = root / "work" / ("transcript.json" if first("raw") == "1" else "words-edit.json")
                    h.send_file(wf if wf.exists() else None)
                elif route == "video":
                    h.send_file(Path(json.loads((root / "project.json").read_text())["raw"]))
                else:
                    h.send_file(thumb(root), cache="max-age=3600")
                return True
        else:
            b = h.body()
            if route == "choose-file":
                p = uploaded(b, base() / "Uploads") or finder_pick("Choose the long recording (it is linked, not copied)", ["public.movie"])
                if not p:
                    h.send_json({"path": None}); return True
                h.send_json({"path": p, "name": Path(p).stem, **probe(p)}); return True
            if route == "choose-overlay":
                # an insert, B-roll or testimonial to lay over the video; long clips are linked where they are, not copied
                r0 = safe_root(b.get("root", "")) if b.get("upload") else None
                if b.get("upload") and not r0:
                    raise ValueError("No such long-form project")
                p = (uploaded(b, r0 / "media") if r0 else uploaded(b, None)) or finder_pick("Choose a video to lay over this one (an insert, B-roll or a testimonial)", ["public.movie"])
                if not p:
                    h.send_json({"path": None}); return True
                a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", p],
                                   capture_output=True, text=True, env=ENV).stdout.strip()
                h.send_json({"path": p, "name": Path(p).stem, "audio": bool(a), **probe(p)}); return True
            if route == "choose-transcript":
                p = uploaded(b, base() / "Uploads") or finder_pick("Choose a subtitle file (SRT or VTT)", ["srt", "vtt"])
                if not p:
                    h.send_json({"path": None}); return True
                words = pipeline_long.parse_subtitles(Path(p).read_text(errors="replace"))
                h.send_json({"path": p, "name": Path(p).name, "words": len(words), "ok": bool(words)}); return True
            if route == "start":
                root = create_project(b)
                j = job_for(root); with_creds(j, h); j.start()
                h.send_json(j.status()); return True
            root = safe_root(b.get("root", ""))
            if not root:
                h.send_json({"error": "No such long-form project"}, 404); return True
            if route == "insert-clip":
                # an AI studio clip to insert: copied into work/inserts/ under its own name (= its own virtual range);
                # the editor puts it into the cut list at the playhead (undoable) and Save writes it to edl.json
                cid = re.sub(r"[^a-f0-9]", "", b.get("clip", ""))
                src_f = root / "studio" / "clips" / cid / "clip.mp4"
                if not cid or not src_f.exists():
                    h.send_json({"error": "That clip isn't finished"}, 400); return True
                dest = root / "work" / "inserts"; dest.mkdir(parents=True, exist_ok=True)
                name = f"{cid}-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
                shutil.copy2(src_f, dest / name)
                src = f"work/inserts/{name}"; d = insert_len(root, src); vb = cuts.vbase(src)
                plan = root / "studio" / "clips" / cid / "plan.json"
                h.send_json({"ok": True, "src": src, "abs": str(dest / name), "clip": d, "vbase": vb,
                             "name": json.loads(plan.read_text()).get("title", "AI clip") if plan.exists() else "AI clip"}); return True
            if route == "retry":
                j = job_for(root); with_creds(j, h); j.start(b.get("from")); h.send_json(j.status()); return True
            if route == "captions":
                f = root / "longform.json"; spec = json.loads(f.read_text())
                spec.setdefault("captions", {})["on"] = bool(b.get("on"))
                f.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
                m = json.loads((root / "project.json").read_text()); m["captions"] = bool(b.get("on"))
                (root / "project.json").write_text(json.dumps(m, indent=2))
                h.send_json({"ok": True, "on": spec["captions"]["on"]}); return True
            if route == "save":
                save_spec(root, b.get("spec"), b.get("segments")); h.send_json({"ok": True, "saved": time.time()}); return True
            if route == "render-start":
                old = renders.get(str(root))
                if old and old.running:
                    h.send_json({"error": "A render is already running for this video"}, 409); return True
                r = render_long.RenderJob(root, HERE, base(), SKILL, ENV, settings(), b.get("mode", "preview"), b.get("t0", 0), b.get("length", 60))
                renders[str(root)] = r; r.start()
                h.send_json(r.status()); return True
            if route == "render-stop":
                r = renders.get(str(root))
                if r:
                    r.stop()
                h.send_json({"ok": True}); return True
            if route == "reveal":
                if workspace.PORTAL:
                    raise ValueError("Not on the portal (use Download)")
                target = {"chapters": root / "chapters.txt", "renders": base() / RENDERS, "output": Path(b.get("path") or root), "raw": Path(json.loads((root / "project.json").read_text())["source"])}.get(b.get("what"), root)
                if b.get("what") == "renders":
                    (base() / RENDERS / "Long-form 16x9").mkdir(parents=True, exist_ok=True)
                osutil.reveal(target)
                h.send_json({"ok": True}); return True
            if route == "delete":
                trash(root); h.send_json({"ok": True}); return True
    except ValueError as e:
        h.send_json({"error": str(e)}, 400); return True
    except Exception as e:                      # never let a long-form bug take the short-form server down
        h.send_json({"error": f"{type(e).__name__}: {e}"}, 500); return True
    h.send_error(404); return True
