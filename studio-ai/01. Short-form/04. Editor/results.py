"""Results (ROADMAP phase 9.6): how your brand's posts do, pulled from each platform and kept in Studio AI.

Each live post's numbers (views, likes, comments, shares, watch time) are pulled by the scheduler's thread from the
platform that posted it (connectors.py `results()`): 1, 6 and 24 hours after posting, then daily for 30 days, then
weekly until 90 days. Every pull is kept, so the numbers can be shown over time.
  <planner>/results/<post id>.json   {"post", "platform", "mode", "dur", "samples": [{"at", "views", …}], "error", "tried"}
Posts marked as posted by hand (and TikTok inbox posts) have no numbers: the platform can't tell us which post is ours.

report() adds them up for the Results screen:
  totals; views gained per day per channel; each channel; top videos; what works (by format and by length);
  best times: per channel, the posting slots (weekday + hour, in the team's time zone) whose posts got the most views
  in their first 24 hours, once a channel has enough posts to say.

Routes (server.py):
  GET  /api/results?days=30|90|365|0&platform=&kind=     the report (days=0: everything)
  POST /api/results/refresh {ids?}                        pull now (all live posts, or these)
Python 3.9 standard library only.
"""
import json, threading, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import osutil
import posting

KEYS = ("views", "likes", "comments", "shares", "watch_time_s")
EVERY = 600                       # the scheduler looks for pulls that are due this often (seconds)
_last = {}
_lock = threading.Lock()
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def rdir(d):
    p = Path(d) / "results"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load(d, pid):
    try:
        return json.loads((rdir(d) / f"{pid}.json").read_text())
    except (OSError, ValueError):
        return None


def save(d, rec):
    f = rdir(d) / f"{rec['post']}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1))
    osutil.replace(tmp, f)


def latest(d, pid):
    rec = load(d, pid)
    return (rec or {}).get("samples", [None])[-1] if rec and rec.get("samples") else None


def posted_at(p):
    return posting.parse(p.get("posted_at") or p["when"])


# hours after posting when numbers are pulled: 1, 6, 24, then daily to 30 days, then weekly to 90 days
TARGETS = [1, 6] + [24 * i for i in range(1, 31)] + [24 * i for i in range(37, 91, 7)] + [90 * 24]


def due(p, rec, now):
    """Is a pull due for this post?"""
    at = posted_at(p)
    age = (now - at).total_seconds() / 3600
    if age < 1 or age > 90 * 24 + 12:
        return False
    if rec and rec.get("tried") and now.timestamp() - rec["tried"] < 1800:
        return False                                  # tried in the last half hour (e.g. the platform said no)
    done = max([(s["at"] - at.timestamp()) / 3600 for s in (rec or {}).get("samples") or []], default=-1)
    nxt = next((t for t in TARGETS if t > done + 0.5), None)
    return nxt is not None and age >= nxt


def _dur(p):
    try:
        import connectors
        return round(connectors._probe(p["video"].get("render"))["dur"], 1) or None
    except Exception:
        return None


def pull(d, p):
    """Pull one post's numbers now. Never raises: a problem is kept in the record."""
    con = posting.CONNECTORS.get(p["platform"])
    rec = load(d, p["id"]) or {"post": p["id"], "platform": p["platform"], "mode": p.get("mode"), "samples": []}
    if rec.get("dur") is None:
        rec["dur"] = _dur(p)
    rec["tried"] = time.time()
    try:
        import connect
        mode = "test" if connect.test_mode(d) else "live"
        if p.get("mode") and p["mode"] != mode:
            raise RuntimeError(f"posted with the {p['mode']} connection; the {mode} one is on now")
        nums = con.results(d, p) if con else None
        if nums is None:
            raise RuntimeError("not connected, or the platform has no numbers for this post")
        if all(nums.get(k) is None for k in KEYS):
            raise RuntimeError("the platform gave no numbers for this post (deleted, or not visible yet)")
        rec["samples"].append({"at": time.time(), **{k: nums.get(k) for k in KEYS}})
        rec["error"] = None
    except Exception as e:
        rec["error"] = str(e)[:300]
    save(d, rec)
    return rec


def collect(d, ids=None, force=False):
    """Pull the numbers that are due (or, with force, every live post's / these posts')."""
    now = posting.now()
    out = []
    for p in posting.all_posts(d):
        if p.get("status") != "live" or not p.get("remote_id"):
            continue
        if ids is not None and p["id"] not in ids:
            continue
        if force or due(p, load(d, p["id"]), now):
            out.append(pull(d, p))
    return out


def maybe_collect(d):
    """Called by the scheduler on every tick; pulls at most every EVERY seconds per planner folder."""
    with _lock:
        if time.time() - _last.get(str(d), 0) < EVERY:
            return
        _last[str(d)] = time.time()
    collect(d)


# ---------------------------------------------------------------- the report
def _num(s, k):
    v = (s or {}).get(k)
    return v if isinstance(v, (int, float)) else 0


def _at(samples, t):
    """The numbers as they stood at time t (the last pull at or before t)."""
    best = None
    for s in samples:
        if s["at"] <= t:
            best = s
    return best


def length_bucket(dur):
    if not dur:
        return None
    return "under 30 s" if dur < 30 else "30-60 s" if dur < 60 else "1-3 min" if dur < 180 else "3-10 min" if dur < 600 else "over 10 min"


KIND = {"reel": "Reels and Shorts", "feed": "Feed videos", "square": "Feed videos", "landscape": "Landscape", "long": "Long-form"}


def report(days=30, platform=None, kind=None, d=None):
    d = posting.pdir(d)
    tz = ZoneInfo(posting.team_tz())
    now = posting.now()
    start = now - timedelta(days=days) if days else None
    rows = []
    for p in posting.all_posts(d):
        if p.get("status") not in ("live", "posted"):
            continue
        if platform and p["platform"] != platform:
            continue
        fmt = "long" if p["video"].get("kind") == "long" else p["video"].get("format")
        if kind and KIND.get(fmt) != kind:
            continue
        at = posted_at(p)
        if start and at < start:
            continue
        rec = load(d, p["id"]) or {}
        samples = rec.get("samples") or []
        last = samples[-1] if samples else None
        rows.append({"id": p["id"], "platform": p["platform"], "video": p["video"], "fmt": fmt, "kind": KIND.get(fmt, "Other"),
                     "posted_at": at.isoformat(), "link": p.get("link"), "cover": bool(p.get("cover")), "status": p["status"],
                     "dur": rec.get("dur"), "numbers": {k: (last or {}).get(k) for k in KEYS} if last else None,
                     "pulled": last["at"] if last else None, "error": rec.get("error"), "_samples": samples, "_at": at})
    with_nums = [r for r in rows if r["numbers"]]
    tot = {k: sum(_num(r["numbers"], k) for r in with_nums) for k in KEYS}
    tot.update(posts=len(rows), measured=len(with_nums))
    eng = tot["likes"] + tot["comments"] + tot["shares"]
    tot["engagement"] = round(eng / tot["views"] * 100, 1) if tot["views"] else None

    # views gained per day (team's time zone), per channel
    span = days or max(1, min(365, (now - min((r["_at"] for r in rows), default=now)).days + 1))
    day0 = (now.astimezone(tz) - timedelta(days=span - 1)).date()
    keys = [(day0 + timedelta(days=i)).isoformat() for i in range(span)]
    timeline = {k: {} for k in keys}
    for r in with_nums:
        prev = 0
        for k in keys:
            end = datetime.fromisoformat(k).replace(tzinfo=tz) + timedelta(days=1)
            s = _at(r["_samples"], end.timestamp())
            v = _num(s, "views")
            if v > prev:
                timeline[k][r["platform"]] = timeline[k].get(r["platform"], 0) + v - prev
                prev = v
    timeline = [{"day": k, **timeline[k]} for k in keys]

    # each channel
    chans = {}
    for r in rows:
        c = chans.setdefault(r["platform"], {"platform": r["platform"], "posts": 0, "measured": 0, **{k: 0 for k in KEYS}})
        c["posts"] += 1
        if r["numbers"]:
            c["measured"] += 1
            for k in KEYS:
                c[k] += _num(r["numbers"], k)
    for c in chans.values():
        c["avg_views"] = round(c["views"] / c["measured"]) if c["measured"] else None
        e = c["likes"] + c["comments"] + c["shares"]
        c["engagement"] = round(e / c["views"] * 100, 1) if c["views"] else None
    channels = sorted(chans.values(), key=lambda c: -c["views"])

    # top videos (all channels together)
    vids = {}
    for r in rows:
        v = vids.setdefault(r["video"]["root"], {"root": r["video"]["root"], "name": r["video"].get("name"), "fmt": r["fmt"], "platforms": [],
                                                  "cover": None, "posted_at": r["posted_at"], **{k: 0 for k in KEYS}})
        if r["platform"] not in v["platforms"]:
            v["platforms"].append(r["platform"])
        if r["cover"] and not v["cover"]:
            v["cover"] = r["id"]
        v["posted_at"] = min(v["posted_at"], r["posted_at"])
        for k in KEYS:
            v[k] += _num(r["numbers"], k)
    top = sorted(vids.values(), key=lambda v: -v["views"])[:10]

    # what works: average views per post, by format and by length
    def avg_by(fn):
        g = {}
        for r in with_nums:
            k = fn(r)
            if k:
                x = g.setdefault(k, [0, 0]); x[0] += _num(r["numbers"], "views"); x[1] += 1
        return [{"label": k, "posts": n, "avg_views": round(s / n)} for k, (s, n) in g.items()]
    order = ["under 30 s", "30-60 s", "1-3 min", "3-10 min", "over 10 min"]
    works = {"format": sorted(avg_by(lambda r: r["kind"]), key=lambda x: -x["avg_views"]),
             "length": sorted(avg_by(lambda r: length_bucket(r["dur"])), key=lambda x: order.index(x["label"]))}

    out_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in sorted(rows, key=lambda r: r["posted_at"], reverse=True)]
    return {"days": days, "totals": tot, "timeline": timeline, "channels": channels, "top": top, "works": works, "posts": out_rows,
            "best": best_times(d, tz), "tz": str(tz)}


def first_day_views(rec, at):
    """Views 24 hours after posting (from the pull nearest that moment), or None if the post isn't a day old yet."""
    samples = (rec or {}).get("samples") or []
    later = [s for s in samples if s["at"] >= at + 20 * 3600]
    if not later:
        return None
    s = min(samples, key=lambda s: abs(s["at"] - (at + 24 * 3600)))
    return _num(s, "views")


MIN_POSTS = 4                     # a channel needs this many measured posts before Studio AI suggests times


def best_times(d, tz):
    """Per channel: the slots whose posts did best in their first day. Uses every post ever (not the screen's range)."""
    per = {}
    for p in posting.all_posts(d):
        if p.get("status") != "live":
            continue
        at = posted_at(p)
        v = first_day_views(load(d, p["id"]), at.timestamp())
        if v is None:
            continue
        lt = at.astimezone(tz)
        per.setdefault(p["platform"], []).append((f"{DAYS[lt.weekday()]} {lt.hour:02d}:00", v))
    out = {}
    for plat, xs in per.items():
        avg = sum(v for _, v in xs) / len(xs)
        if len(xs) < MIN_POSTS:
            out[plat] = {"posts": len(xs), "need": MIN_POSTS, "slots": []}
            continue
        g = {}
        for slot, v in xs:
            g.setdefault(slot, []).append(v)
        slots = [{"slot": s, "posts": len(vs), "avg_views": round(sum(vs) / len(vs)), "vs_average": round((sum(vs) / len(vs) / avg - 1) * 100) if avg else 0}
                 for s, vs in g.items()]
        slots = [x for x in slots if x["posts"] >= 2] or slots       # one post alone says little
        slots.sort(key=lambda x: (-x["avg_views"], -x["posts"]))
        out[plat] = {"posts": len(xs), "need": MIN_POSTS, "average": round(avg), "slots": slots[:3]}
    return out


def handle(h, method, path, q):
    if not path.startswith("/api/results"):
        return False
    try:
        if method == "GET" and path == "/api/results":
            days = int(q.get("days", ["30"])[0] or 0)
            h.send_json(report(days, q.get("platform", [""])[0] or None, q.get("kind", [""])[0] or None)); return True
        if method == "POST" and path == "/api/results/refresh":
            b = h.body()
            got = collect(posting.pdir(), b.get("ids"), force=True)
            h.send_json({"pulled": len(got), "errors": [r["error"] for r in got if r.get("error")]}); return True
    except (ValueError, KeyError) as e:
        h.send_json({"error": str(e)}, 400); return True
    return False
