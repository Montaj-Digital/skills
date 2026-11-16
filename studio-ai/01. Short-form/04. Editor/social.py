"""Social settings (ROADMAP phase 9.2): your brand's own channels, their usual posting times, standard hashtags and the
time zone. The planner posts only to your brand's channels; clients publish their own way.

Stored in the workspace's planner folder (`<Studio AI>/08. Planner/social.json` on a Mac; the team's storage on the
portal). Connections (sign-in tokens) come with the platform connections (9.4); they never go in this file.

Routes (server.py):
  GET  /api/social                  the settings, filled in with defaults
  POST /api/social {settings}       save
  GET  /api/social/suggest?platform=&after=<ISO>   the next usual posting time after a moment
Python 3.9 standard library only (zoneinfo for time zones).
"""
import json, re, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, available_timezones

import workspace

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# usual times to start from (each can be changed in Social settings)
DEFAULT_TIMES = {
    "instagram": ["Tue 09:00", "Wed 12:00", "Thu 09:00", "Fri 18:00"],
    "tiktok": ["Tue 18:30", "Thu 18:30", "Sat 11:00"],
    "youtube": ["Wed 12:00", "Fri 12:00", "Sat 10:00"],
    "facebook": ["Mon 09:00", "Wed 09:00", "Fri 09:00"],
    "linkedin": ["Tue 08:30", "Wed 08:30", "Thu 08:30"],
    "x": ["Mon 09:00", "Wed 17:00", "Fri 09:00"],
    "threads": ["Tue 09:15", "Thu 09:15"],
    "pinterest": ["Fri 20:00", "Sat 20:00"],
    "google": ["Mon 10:00", "Thu 10:00"],
    "bluesky": ["Tue 09:00", "Thu 09:00"],
}
COMMON_ZONES = ["Europe/London", "Europe/Dublin", "Europe/Amsterdam", "Europe/Paris", "Europe/Berlin", "Africa/Johannesburg",
                "Asia/Dubai", "Asia/Singapore", "Australia/Sydney", "America/New_York", "America/Chicago", "America/Los_Angeles", "UTC"]


def path():
    d = workspace.current().planner
    d.mkdir(parents=True, exist_ok=True)
    return d / "social.json"


def platforms():
    import planner
    return planner.ORDER, planner.PLATFORMS


def raw():
    try:
        return json.loads(path().read_text())
    except (OSError, ValueError):
        return {}


def load():
    order, plats = platforms()
    s = raw()
    s.setdefault("timezone", "Europe/London")
    s.setdefault("hashtags", ["#yourbrand"])
    ch = s.setdefault("channels", {})
    for p in order:
        c = ch.setdefault(p, {})
        c.setdefault("on", p in ("instagram", "tiktok", "youtube", "facebook", "linkedin", "threads"))
        c.setdefault("account", "")
        c.setdefault("url", "")
        c.setdefault("times", list(DEFAULT_TIMES.get(p, ["Tue 09:00"])))
        c.setdefault("hashtags", [])
    import mailer
    n = mailer.load(path().parent)
    s["notifications"] = dict(n, password_set=bool(mailer.password(path().parent)), ready=mailer.ready(path().parent))
    return s


def clean_time(t):
    m = re.fullmatch(r"\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+(\d{1,2}):(\d{2})\s*", str(t), re.I)
    if not m or int(m.group(2)) > 23 or int(m.group(3)) > 59:
        return None
    return f"{m.group(1).title()} {int(m.group(2)):02d}:{m.group(3)}"


def tags(v):
    items = v if isinstance(v, list) else re.split(r"[\s,]+", str(v or ""))
    return ["#" + t.strip().lstrip("#") for t in items if str(t).strip().lstrip("#")][:30]


def save(data):
    order, _ = platforms()
    cur = load()
    tz = str(data.get("timezone") or cur["timezone"])
    if tz not in available_timezones():
        raise ValueError(f"Unknown time zone {tz}")
    keep = {k: v for k, v in raw().items() if k not in ("timezone", "hashtags", "channels", "notifications", "saved")}   # e.g. connections
    out = {**keep, "timezone": tz, "hashtags": tags(data.get("hashtags", cur["hashtags"])), "channels": {}, "saved": time.time()}
    n = data.get("notifications") or cur["notifications"]
    emails = [e.strip() for e in (n.get("emails") if isinstance(n.get("emails"), list) else re.split(r"[\s,;]+", str(n.get("emails") or ""))) if e.strip()]
    bad = [e for e in emails if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e)]
    if bad:
        raise ValueError(f"Not an email address: {bad[0]}")
    sm = n.get("smtp") or {}
    sec = sm.get("security") if sm.get("security") in ("starttls", "ssl", "none") else "starttls"
    try:
        port = int(sm.get("port") or (465 if sec == "ssl" else 587))
    except (TypeError, ValueError):
        raise ValueError("The mail server port should be a number (587, 465 or 25)")
    out["notifications"] = {"emails": emails[:20], "on_live": bool(n.get("on_live")),
                            "smtp": {"host": str(sm.get("host") or "").strip(), "port": port, "security": sec,
                                     "username": str(sm.get("username") or "").strip(), "from": str(sm.get("from") or "").strip()}}
    for p in order:
        c = (data.get("channels") or {}).get(p, cur["channels"][p])
        times = [x for x in (clean_time(t) for t in (c.get("times") or [])) if x]
        out["channels"][p] = {"on": bool(c.get("on")), "account": str(c.get("account") or "").strip()[:120],
                              "url": str(c.get("url") or "").strip()[:500], "times": sorted(set(times), key=lambda x: (DAYS.index(x[:3]), x[4:])),
                              "hashtags": tags(c.get("hashtags", []))}
    path().write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return load()


def suggest(platform, after=None, taken=()):
    """The next usual posting time for a platform after `after` (default: in 30 minutes), as an aware datetime in the
    team's time zone. `taken` (datetimes) are skipped so two posts don't land in the same slot on the same channel."""
    s = load()
    tz = ZoneInfo(s["timezone"])
    start = (after.astimezone(tz) if after else datetime.now(tz) + timedelta(minutes=30))
    times = (s["channels"].get(platform) or {}).get("times") or ["Tue 09:00"]
    taken = {t.astimezone(tz).replace(second=0, microsecond=0) for t in taken}
    for day in range(0, 60):
        d = (start + timedelta(days=day)).date()
        for t in sorted(times, key=lambda x: x[4:]):
            if DAYS.index(t[:3]) != d.weekday():
                continue
            h, m = int(t[4:6]), int(t[7:9])
            when = datetime(d.year, d.month, d.day, h, m, tzinfo=tz)
            if when > start and when not in taken:
                return when
    return start.replace(second=0, microsecond=0)


def handle(h, method, path_, q):
    if not path_.startswith("/api/social"):
        return False
    try:
        if method == "GET" and path_ == "/api/social":
            h.send_json({"settings": load(), "zones": COMMON_ZONES, "days": DAYS}); return True
        if method == "GET" and path_ == "/api/social/suggest":
            after = q.get("after", [None])[0]
            when = suggest(q.get("platform", ["instagram"])[0], datetime.fromisoformat(after) if after else None)
            h.send_json({"when": when.isoformat()}); return True
        if method == "POST" and path_ == "/api/social":
            h.send_json({"settings": save(h.body().get("settings") or {})}); return True
        if method == "POST" and path_ == "/api/social/smtp-password":
            import connect, vault
            d = path().parent
            pw = str(h.body().get("password") or "")
            (vault.set(d, f"{connect.team_of(d)}/smtp", {"password": pw}) if pw else vault.delete(d, f"{connect.team_of(d)}/smtp"))
            h.send_json({"settings": load()}); return True
        if method == "POST" and path_ == "/api/social/test-email":
            import connect, mailer
            try:
                mailer.test_email(path().parent, connect.public_url())
            except mailer.MailError as e:
                h.send_json({"error": str(e)}, 400); return True
            h.send_json({"ok": True}); return True
    except (ValueError, KeyError) as e:
        h.send_json({"error": str(e)}, 400); return True
    return False
