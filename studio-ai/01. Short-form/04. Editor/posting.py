"""Scheduled posts, the calendar's data and the scheduler (ROADMAP phase 9.3). your brand's own channels only.

Each post is one video on one platform at one time: `<planner>/posts/<id>.json` (planner = the workspace's planner
folder: `<Studio AI>/08. Planner` on a Mac, the team's storage on the portal), with its cover in `covers/<id>.jpg`.
Posts scheduled together from Post it share a `group`, which the calendar shows as one card.
  status: scheduled → due (the time has come and nobody is connected: post it by hand) / posting → live, or failed;
          posted (marked as posted by hand); cancelled
The scheduler (a server thread) wakes every 30 seconds, takes posts whose time has come and hands each to its
platform's connection (`CONNECTORS`). Without a connection the post becomes "due": a reminder in the calendar, and
an email to the team (mailer.py; also when a post fails, and when one goes live if chosen). Everything is on disk, so a restart loses nothing.

Routes (server.py):
  GET  /api/calendar/posts?from=&to=   posts in a range (ISO dates), the time zone, how many are due
  GET  /api/calendar/summary           per video: the next scheduled time, platforms, live/due counts (Open's badges)
  POST /api/calendar/reschedule {ids, when}     POST /api/calendar/cancel {ids}
  POST /api/calendar/posted {ids, link}         POST /api/calendar/post-now {ids}
  GET  /calendar/cover/<id>.jpg
Python 3.9 standard library only.
"""
import json, os, re, shutil, socket, subprocess, threading, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import osutil
import workspace

TICK = 30                 # seconds between scheduler checks
CONNECTORS = {}           # platform -> connector (9.5): .connected() and .publish(post) -> {"link": …}
_locks, _locks_lock = {}, threading.Lock()


def lock(d):
    with _locks_lock:
        return _locks.setdefault(str(d), threading.Lock())


def pdir(base=None):
    d = Path(base) if base else workspace.current().planner
    (d / "posts").mkdir(parents=True, exist_ok=True); (d / "covers").mkdir(exist_ok=True)
    return d


def now():
    return datetime.now(timezone.utc)


def parse(ts, tz=None):
    """An ISO time. One without a zone (the page's date-time fields) is in the team's time zone (`tz`), else UTC."""
    t = datetime.fromisoformat(str(ts))
    if t.tzinfo:
        return t
    return t.replace(tzinfo=ZoneInfo(tz) if tz else timezone.utc)


def team_tz():
    try:
        import social
        return social.load()["timezone"]
    except Exception:
        return "UTC"


def read(d, pid):
    try:
        return json.loads((d / "posts" / f"{pid}.json").read_text())
    except (OSError, ValueError):
        return None


def write(d, p, what=None):
    p["updated"] = time.time()
    if what:
        p.setdefault("history", []).append({"at": time.time(), "what": what})
    tmp = d / "posts" / f"{p['id']}.json.tmp"
    tmp.write_text(json.dumps(p, indent=1, ensure_ascii=False))
    osutil.replace(tmp, d / "posts" / f"{p['id']}.json")


def all_posts(d=None):
    d = pdir(d)
    out = []
    for f in (d / "posts").glob("*.json"):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return out


def public(p):
    """What the page gets (no internal fields), with a live post's latest numbers (results.py)."""
    out = {k: v for k, v in p.items() if k not in ("history",)} | {"history": p.get("history", [])[-6:]}
    if p.get("status") == "live":
        try:
            import results
            out["numbers"] = results.latest(pdir(), p["id"])
        except Exception:
            out["numbers"] = None
    return out


# ---------------------------------------------------------------- making and changing posts
def schedule(video, pack, items, cover_file, tz):
    """video: {kind, root, name, format, brand, render}; items: [{platform, when (ISO)}]; copies each platform's post from
    the pack and the cover. Returns the new posts."""
    import planner
    d = pdir()
    group = uuid.uuid4().hex[:10]
    made = []
    with lock(d):
        for it in items:
            plat = it.get("platform")
            if plat not in planner.PLATFORMS:
                raise ValueError(f"Unknown platform {plat}")
            when = parse(it["when"], tz)
            if when < now() - timedelta(minutes=5):
                raise ValueError(f"{planner.PLATFORMS[plat]['name']}: that time has passed")
            fields = (pack.get("posts") or {}).get(plat) or {}
            if not any((v if not isinstance(v, list) else len(v)) for v in fields.values()):
                raise ValueError(f"{planner.PLATFORMS[plat]['name']} has no post yet: write it first")
            pid = uuid.uuid4().hex[:12]
            if cover_file and Path(cover_file).exists():
                shutil.copy2(cover_file, d / "covers" / f"{pid}.jpg")
            p = {"id": pid, "group": group, "video": video, "platform": plat, "fields": fields, "when": when.isoformat(), "tz": tz,
                 "status": "scheduled", "link": None, "error": None, "tries": 0, "created": time.time(),
                 "cover": (d / "covers" / f"{pid}.jpg").exists()}
            write(d, p, f"scheduled for {when.astimezone(ZoneInfo(tz)).strftime('%a %d %b %H:%M')}")
            made.append(p)
    return made


def change(ids, fn, what):
    d = pdir(); out = []
    with lock(d):
        for pid in ids or []:
            p = read(d, re.sub(r"[^a-f0-9]", "", str(pid)))
            if not p:
                continue
            fn(p)
            write(d, p, what(p) if callable(what) else what)
            out.append(p)
    return out


def reschedule(ids, when):
    when = parse(when, team_tz())
    if when < now() - timedelta(minutes=1):
        raise ValueError("That time has passed")
    def fn(p):
        if p["status"] in ("live", "posted", "posting"):
            raise ValueError("A post that's already out can't be moved")
        p["when"], p["status"], p["error"], p["notified"] = when.isoformat(), "scheduled", None, False
    return change(ids, fn, lambda p: f"moved to {when.astimezone(ZoneInfo(p.get('tz') or 'UTC')).strftime('%a %d %b %H:%M')}")


def cancel(ids):
    def fn(p):
        if p["status"] in ("live", "posted"):
            raise ValueError("A post that's already out can't be cancelled here: delete it on the platform")
        if p["status"] == "posting":
            raise ValueError("It's being posted right now: wait a moment")
        p["status"] = "cancelled"
    return change(ids, fn, "cancelled")


def mark_posted(ids, link=None):
    def fn(p):
        p["status"], p["link"], p["error"] = "posted", (link or p.get("link")), None
        p["posted_at"] = now().isoformat()
    return change(ids, fn, "marked as posted by hand")


def post_now(ids):
    def fn(p):
        if p["status"] in ("live", "posted"):
            raise ValueError("Already out")
        if p["status"] == "posting":
            raise ValueError("It's being posted right now")
        p["when"], p["status"], p["notified"] = now().isoformat(), "scheduled", False
    out = change(ids, fn, "post now")
    threading.Thread(target=tick, args=(pdir(),), daemon=True).start()
    return out


# ---------------------------------------------------------------- the scheduler
def email(d, posts, kind):
    """Email the team about posts of one video and moment: due (post by hand), failed, or live. Never raises: a mail
    problem is written into the posts' history instead."""
    import mailer, planner
    if not posts or not mailer.ready(d) or (kind == "live" and not mailer.load(d)["on_live"]):
        return
    try:
        import connect
        url = connect.public_url()
    except Exception:
        url = "http://127.0.0.1:4322"
    p0 = posts[0]
    when_text = parse(p0["when"]).astimezone(ZoneInfo(p0.get("tz") or "UTC")).strftime("%a %d %b, %H:%M")
    try:
        mailer.send(d, *mailer.post_email(d, posts, kind, url, planner.PLATFORMS, when_text))
        note = f"email sent ({kind})"
    except Exception as e:
        note = f"email not sent: {e}"
    with lock(d):
        for p in posts:
            cur = read(d, p["id"]) or p
            write(d, cur, note)


# ---------------------------------------------------------------- claims: one post, one poster
# On the portal several server processes (machines) can share the storage folder. Before a scheduler touches a post
# whose time has come, it creates <posts>/<id>.claim with O_EXCL (atomic, also on network storage), re-reads the post,
# and only then posts it; the claim stays until the post's new status is written. A claim left by a process that
# stopped (its pid is gone on this machine, or it's older than CLAIM_STALE) is cleared, and a post it left "posting"
# is marked failed: it may or may not have gone out, so a person checks.
CLAIM_STALE = 3 * 3600


def _claim_file(d, pid):
    return Path(d) / "posts" / f"{pid}.claim"


def _stale(f):
    try:
        info = json.loads(f.read_text() or "{}")
        age = time.time() - f.stat().st_mtime
    except (OSError, ValueError):
        return True
    if age > CLAIM_STALE:
        return True
    if info.get("host") == socket.gethostname() and info.get("pid") and info["pid"] != os.getpid() and not osutil.WINDOWS:
        try:
            os.kill(info["pid"], 0)
        except ProcessLookupError:
            return True                              # that server process has stopped
        except OSError:
            pass
    return False


def claim(d, pid):
    f = _claim_file(d, pid)
    for _ in (1, 2):
        try:
            fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if _stale(f):
                try:
                    f.unlink()
                except OSError:
                    pass
                continue
            return False
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps({"host": socket.gethostname(), "pid": os.getpid(), "at": time.time()}))
        return True
    return False


def release(d, pid):
    try:
        _claim_file(d, pid).unlink()
    except OSError:
        pass


def scheduler_on():
    """STUDIO_SCHEDULER=0 turns the scheduler off in this process (on the portal, only one process should run it per team)."""
    return os.environ.get("STUDIO_SCHEDULER", "1") != "0"


def tick(d):
    """Post (or email a reminder about) everything whose time has come in one planner folder."""
    d = Path(d)
    due_now, reminders, stuck = [], [], []
    with lock(d):
        for p in all_posts(d):
            if p.get("status") == "posting" and claim(d, p["id"]):
                # nobody is posting it (the process that was stopped): it may or may not have gone out
                cur = read(d, p["id"]) or p
                if cur.get("status") == "posting":
                    cur.update(status="failed", error="Studio AI stopped while posting this. Check the platform: if it's there, press "
                                                     "Mark posted; if not, Post now.")
                    write(d, cur, "failed: stopped while posting"); stuck.append(cur)
                release(d, p["id"])
                continue
            if p.get("status") != "scheduled" or parse(p["when"]) > now():
                continue
            if not claim(d, p["id"]):
                continue                             # another server process has it
            p = read(d, p["id"]) or p                # as it is now, after the claim
            if p.get("status") != "scheduled" or parse(p["when"]) > now():
                release(d, p["id"]); continue
            con = CONNECTORS.get(p["platform"])
            if con and con.connected(d):
                p["status"] = "posting"; write(d, p, "posting"); due_now.append((p, con))     # claimed until it's done
            else:
                p["status"] = "due"
                if not p.get("notified"):
                    p["notified"] = True; reminders.append(p)
                write(d, p, "due: not connected, post it by hand")
                release(d, p["id"])
    done = {"failed": [], "live": [], "due": []}
    for p, con in due_now:              # the uploads happen outside the lock
        try:
            res = con.publish(d, p) or {}
            if res.get("handoff"):     # e.g. TikTok's inbox: uploaded, but someone finishes it in the app
                p.update(status="due", error=None, note=res["handoff"], notified=True)
                msg = "sent: " + res["handoff"]; done["due"].append(p)
            else:
                p.update(status="live", link=res.get("link"), error=None, posted_at=now().isoformat())
                msg = "live"; done["live"].append(p)
        except Exception as e:          # a connection failure never stops the scheduler
            p["tries"] = p.get("tries", 0) + 1
            if p["tries"] < 4:
                p.update(status="scheduled", error=str(e), when=(now() + timedelta(minutes=5 * 2 ** p["tries"])).isoformat())
                msg = f"failed ({e}); trying again"
            else:
                p.update(status="failed", error=str(e)); msg = f"failed: {e}"; done["failed"].append(p)
        with lock(d):
            write(d, p, msg)
        release(d, p["id"])
    # one email per video and moment
    for kind, posts in (("due", reminders + done["due"]), ("failed", done["failed"] + stuck), ("live", done["live"])):
        groups = {}
        for p in posts:
            groups.setdefault((p["group"], p["when"][:16]), []).append(p)
        for g in groups.values():
            email(d, g, kind)


def planner_dirs():
    """Every planner folder this server serves: the Mac's, or each team's on the portal."""
    if workspace.PORTAL:
        only = {t.strip() for t in os.environ.get("STUDIO_SCHEDULER_TEAMS", "").split(",") if t.strip()}   # this machine's teams
        return [t / "Planner" for t in (workspace.DATA / "teams").glob("*") if (t / "Planner" / "posts").is_dir() and (not only or t.name in only)]
    return [workspace.LOCAL.planner]


def run_forever():
    while True:
        for d in planner_dirs():
            try:
                tick(d)
            except Exception as e:           # keep going whatever happens
                print(f"  (scheduler: {e})")
            try:
                import results
                results.maybe_collect(d)     # the posts' numbers (9.6)
            except Exception as e:
                print(f"  (results: {e})")
        time.sleep(TICK)


def start():
    if not scheduler_on():
        print("  (the scheduler is off in this process: STUDIO_SCHEDULER=0)")
        return
    threading.Thread(target=run_forever, daemon=True, name="scheduler").start()


# ---------------------------------------------------------------- reading for the page
def in_range(frm, to):
    a, b = parse(frm), parse(to)
    return [public(p) for p in all_posts() if a <= parse(p["when"]) < b]


def summary():
    """Per video (its folder): the next scheduled post, the platforms, how many are live and how many are due."""
    out = {}
    for p in all_posts():
        if p.get("status") == "cancelled":
            continue
        v = out.setdefault(p["video"]["root"], {"next": None, "platforms": [], "live": 0, "due": 0, "scheduled": 0})
        if p["platform"] not in v["platforms"]:
            v["platforms"].append(p["platform"])
        st = p["status"]
        if st in ("live", "posted"):
            v["live"] += 1
        elif st == "due" or st == "failed":
            v["due"] += 1
        elif st in ("scheduled", "posting"):
            v["scheduled"] += 1
            if not v["next"] or parse(p["when"]) < parse(v["next"]):
                v["next"] = p["when"]
    return out


def for_video(root):
    return sorted((public(p) for p in all_posts() if p["video"]["root"] == str(root) and p["status"] != "cancelled"),
                  key=lambda p: p["when"])


def due_count():
    return sum(1 for p in all_posts() if p.get("status") in ("due", "failed"))


def handle(h, method, path, q):
    if not path.startswith(("/api/calendar/", "/calendar/")):
        return False
    try:
        if method == "GET" and path.startswith("/calendar/cover/"):
            pid = re.sub(r"[^a-f0-9]", "", path.rsplit("/", 1)[-1].replace(".jpg", ""))
            h.send_file(pdir() / "covers" / f"{pid}.jpg", cache="max-age=3600"); return True
        if method == "GET" and path == "/api/calendar/posts":
            import social
            h.send_json({"posts": in_range(q.get("from", ["1970-01-01T00:00:00+00:00"])[0], q.get("to", ["2100-01-01T00:00:00+00:00"])[0]),
                         "tz": social.load()["timezone"], "due": due_count()}); return True
        if method == "GET" and path == "/api/calendar/summary":
            h.send_json({"videos": summary(), "due": due_count()}); return True
        if method != "POST":
            return False
        b = h.body()
        if path == "/api/calendar/reschedule":
            h.send_json({"posts": [public(p) for p in reschedule(b.get("ids"), b["when"])]}); return True
        if path == "/api/calendar/cancel":
            h.send_json({"posts": [public(p) for p in cancel(b.get("ids"))]}); return True
        if path == "/api/calendar/posted":
            h.send_json({"posts": [public(p) for p in mark_posted(b.get("ids"), b.get("link"))]}); return True
        if path == "/api/calendar/post-now":
            h.send_json({"posts": [public(p) for p in post_now(b.get("ids"))]}); return True
    except (ValueError, KeyError) as e:
        h.send_json({"error": str(e)}, 400); return True
    return False
