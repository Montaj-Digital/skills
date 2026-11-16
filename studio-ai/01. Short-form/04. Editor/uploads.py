"""Resumable uploads (ROADMAP phase 7): on the portal's server there are no Finder dialogs, so files come from the browser.

A big camera file (20-100 GB for long-form) goes up in chunks; a dropped connection only re-sends from where it stopped.
    POST /api/upload/start {name, size}       → {id}
    PUT  /api/upload/<id>?offset=<bytes>      raw chunk body; accepted only at the current size → {size, total, done}
                                              (a wrong offset → 409 with the current size, so the page can carry on)
    GET  /api/upload/<id>                     → {size, total, done, name}
The finished file is then handed to the route that needs it with {"upload": "<id>"} (New, overlays, the raw camera file,
AI studio media, long-form's video and subtitles), which moves it where it belongs with take().
Parts live in the workspace's uploads folder (users/<user>/.uploads on the portal); ones untouched for 3 days are removed.
"""
import json, os, re, shutil, time, uuid
from pathlib import Path

import workspace

CHUNK_MAX = 64 * 1024 ** 2          # one PUT at most (the page sends 8 MB)
STALE = 3 * 86400


def folder():
    d = workspace.current().uploads
    d.mkdir(parents=True, exist_ok=True)
    return d


def _files(uid):
    if not re.fullmatch(r"[a-f0-9]{32}", uid or ""):
        raise ValueError("Unknown upload")
    d = folder()
    return d / f"{uid}.part", d / f"{uid}.json"


def _meta(uid):
    part, meta = _files(uid)
    if not meta.exists():
        raise ValueError("Unknown upload (it may have expired)")
    m = json.loads(meta.read_text())
    m["size"] = part.stat().st_size if part.exists() else 0
    m["done"] = m["size"] == m["total"]
    return m


def clean():
    now = time.time()
    for f in folder().glob("*"):
        try:
            if now - f.stat().st_mtime > STALE:
                f.unlink()
        except OSError:
            pass


def start(name, size):
    name = Path(str(name or "file")).name[:200] or "file"
    size = int(size)
    if size < 0:
        raise ValueError("Bad size")
    clean()
    uid = uuid.uuid4().hex
    part, meta = _files(uid)
    part.touch()
    meta.write_text(json.dumps({"name": name, "total": size, "started": time.time()}))
    return {"id": uid}


def put(h, uid, offset):
    m = _meta(uid)
    part, _ = _files(uid)
    n = int(h.headers.get("Content-Length", 0))
    if offset != m["size"] or n > CHUNK_MAX or m["size"] + n > m["total"]:
        return 409, {k: m[k] for k in ("size", "total", "done")}
    left = n
    with open(part, "ab") as f:
        while left > 0:
            chunk = h.rfile.read(min(1 << 20, left))
            if not chunk:
                break
            f.write(chunk); left -= len(chunk)
    m = _meta(uid)
    return (200 if left == 0 else 400), {k: m[k] for k in ("size", "total", "done")}


def take(uid, dest_dir, name=None):
    """Move a finished upload into dest_dir (under its own name, never over another file). Returns the new path."""
    m = _meta(uid)
    if not m["done"]:
        raise ValueError(f"The upload of {m['name']} isn't finished ({m['size']} of {m['total']} bytes)")
    part, meta = _files(uid)
    dest_dir = Path(dest_dir); dest_dir.mkdir(parents=True, exist_ok=True)
    fname = Path(name or m["name"]).name
    dest, k = dest_dir / fname, 2
    while dest.exists():
        dest = dest_dir / f"{Path(fname).stem}-{k}{Path(fname).suffix}"; k += 1
    shutil.move(str(part), str(dest))
    meta.unlink(missing_ok=True)
    return dest


def handle(h, method, path):
    """The /api/upload routes. Returns True if it was ours."""
    if not path.startswith("/api/upload"):
        return False
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(h.path).query)
    try:
        if method == "POST" and path == "/api/upload/start":
            b = h.body()
            h.send_json(start(b.get("name"), b.get("size", 0))); return True
        uid = path[len("/api/upload/"):]
        if method == "GET":
            h.send_json(_meta(uid)); return True
        if method == "PUT":
            code, out = put(h, uid, int(q.get("offset", ["0"])[0]))
            h.send_json(out, code); return True
    except (ValueError, OSError) as e:
        h.send_json({"error": str(e)}, 400); return True
    h.send_error(404); return True
