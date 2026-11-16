"""Post it (ROADMAP phase 9.1): Claude writes a finished video's posts for each social platform; pick a cover; download
the post pack. Scheduling and the calendar (9.3) build on the same pack.

Per project, in <project>/planner/:
  pack.json      the channels, Claude's posts (edited by hand), the note for Claude, the cover time
  cover.jpg      the cover frame, from the rendered video (or the edit before it's rendered)
  post-pack.zip  made on download: the MP4, the cover, one text file per platform, README.txt

Routes (server.py: the open short-form video; longform.py forwards /api/long/planner/…?root= and /long/planner/…):
  GET  /api/planner/state                platforms, defaults for the format, the rendered video, the pack
  POST /api/planner/draft {channels, note, only}   Claude writes the posts (only: one platform, "Rewrite")
  POST /api/planner/save {pack}
  POST /api/planner/cover {t}            the frame at t seconds → cover.jpg
  GET  /api/planner/download             the post pack (zip)
  GET  /planner/video                    the rendered MP4 (or the edit), for the player
  GET  /planner/cover.jpg
Only default-brand videos will be scheduled (9.3); a client video gets the post pack to hand over.
Python 3.9 standard library only.
"""
import json, re, shutil, subprocess, time, zipfile
from pathlib import Path

import brandkit
import claude_client
import osutil

ENV = None          # set by server.py
settings = dict     # set by server.py

# Each platform: what a post has. kind text | tags (a list); limit in characters (tags: how many).
PLATFORMS = {
    "instagram": {"name": "Instagram", "fields": [("text", "Caption", 2200), ("hashtags", "Hashtags", 30), ("first_comment", "First comment", 2200)],
                  "style": "Hook in the first line (it shows before 'more'), short paragraphs, then the call to action. 3-8 hashtags."},
    "tiktok": {"name": "TikTok", "fields": [("text", "Caption", 2200), ("hashtags", "Hashtags", 10)],
               "style": "One or two short, punchy lines that make people watch. 3-5 hashtags."},
    "youtube": {"name": "YouTube", "fields": [("title", "Title", 100), ("text", "Description", 5000), ("tags", "Tags", 15)],
                "style": "A clear, searchable title (under 70 characters works best). Description: 2-3 short paragraphs, the call to "
                         "action and the website. Tags: plain search phrases, no #."},
    "facebook": {"name": "Facebook", "fields": [("text", "Post", 5000), ("hashtags", "Hashtags", 5)],
                 "style": "Conversational, 1-3 short paragraphs, the call to action. 0-3 hashtags."},
    "linkedin": {"name": "LinkedIn", "fields": [("text", "Post", 3000), ("hashtags", "Hashtags", 5)],
                 "style": "Professional and specific: a hook line, short paragraphs or a short list of takeaways, the call to action. 3 hashtags."},
    "x": {"name": "X", "fields": [("text", "Post", 280)],
          "style": "One sharp line with the point of the video; fits in 280 characters including any hashtag (0-1)."},
    "threads": {"name": "Threads", "fields": [("text", "Post", 500)],
                "style": "Conversational, an opinion or a question that starts a conversation. No hashtags."},
    "pinterest": {"name": "Pinterest", "fields": [("title", "Title", 100), ("text", "Description", 500), ("link", "Link", 2000)],
                  "style": "A descriptive, searchable title and description with keywords people search for. Link: the website."},
    "google": {"name": "Google Business", "fields": [("text", "Update", 1500), ("button", "Button", 30)],
               "style": "A short update for people searching for the business: what it is, why it matters, the call to action. "
                        "Button: one of Learn more, Book, Sign up, Call now."},
    "bluesky": {"name": "Bluesky", "fields": [("text", "Post", 300)],
                "style": "One or two lines, conversational, fits in 300 characters. 0-1 hashtag."},
}
ORDER = list(PLATFORMS)
DEFAULTS = {"reel": ["instagram", "tiktok", "youtube", "facebook", "threads"],
            "feed": ["instagram", "facebook", "linkedin", "threads"], "square": ["instagram", "facebook", "linkedin", "threads"],
            "landscape": ["youtube", "linkedin", "facebook", "x"], "long": ["youtube", "linkedin", "facebook"]}
TAG_FIELDS = {"hashtags", "tags"}


# ---------------------------------------------------------------- the project
def folder(ctx):
    d = ctx.root / "planner"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fmt_key(ctx):
    return "long" if ctx.kind == "long" else ctx.fmt


def load_pack(ctx):
    f = ctx.root / "planner" / "pack.json"
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return {"channels": list(DEFAULTS.get(fmt_key(ctx), DEFAULTS["reel"])), "posts": {}, "note": "", "cover_t": None}


def save_pack(ctx, pack):
    clean = {"channels": [c for c in pack.get("channels", []) if c in PLATFORMS],
             "posts": {k: clean_post(k, v) for k, v in (pack.get("posts") or {}).items() if k in PLATFORMS},
             "note": str(pack.get("note") or "")[:2000], "cover_t": pack.get("cover_t"),
             "drafted": pack.get("drafted"), "edited": time.time()}
    (folder(ctx) / "pack.json").write_text(json.dumps(clean, indent=1, ensure_ascii=False))
    return clean


def clean_post(platform, post):
    out = {}
    for key, _, limit in PLATFORMS[platform]["fields"]:
        v = (post or {}).get(key)
        if key in TAG_FIELDS:
            items = v if isinstance(v, list) else re.split(r"[\s,]+", str(v or ""))
            items = [t.strip().lstrip("#").strip() for t in items if str(t).strip().lstrip("#").strip()]
            out[key] = [("#" + t.replace(" ", "")) if key == "hashtags" else t for t in items]
        else:
            out[key] = str(v or "").strip()
    return out


def brand_id(ctx):
    """The video's brand: in reel.json, or (long-form) longform.json, else project.json."""
    bid = ctx.spec.get("brand")
    if not bid and ctx.kind == "long":
        try:
            bid = json.loads((ctx.root / "project.json").read_text()).get("brand")
        except (OSError, ValueError):
            pass
    return bid or brandkit.DEFAULT


def brand_info(ctx):
    """Who the video is for: is it a client, the brand's name, its website, tone of voice and call to action."""
    bid = brand_id(ctx)
    client = brandkit.client(bid) if bid != brandkit.DEFAULT else None
    try:
        kit = client or brandkit.load(brandkit.DEFAULT)
    except (OSError, ValueError):
        kit = {}
    v, e = kit.get("voice") or {}, kit.get("endscreen") or {}
    return {"client": bool(client), "name": kit.get("name") or ("Your brand" if not client else bid), "website": kit.get("website", ""),
            "tone": v.get("tone", ""), "cta": v.get("cta") or e.get("cta") or ""}


def transcript_text(ctx):
    f = ctx.edit / "transcript.json" if ctx.kind != "long" else ctx.root / "work" / "words-edit.json"
    try:
        words = json.loads(f.read_text())
    except (OSError, ValueError):
        return ""
    return " ".join(w.get("text", "") for w in words if isinstance(w, dict)).strip()


def on_screen(ctx):
    """Short texts shown in the video (cards, takeovers, lower-thirds, chapters): what the video says it's about."""
    out = []
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("title", "kicker", "word", "text", "label", "subtitle", "value") and isinstance(v, str) and 2 < len(v) < 90:
                    out.append(v.replace("*", ""))
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    spec = ctx.spec
    for key in ("cards", "takeovers", "lowerThirds", "chapters", "items"):
        walk(spec.get(key))
    seen, uniq = set(), []
    for t in out:
        if t.lower() not in seen:
            seen.add(t.lower()); uniq.append(t)
    return uniq[:40]


def chapters(ctx):
    f = ctx.root / "chapters.txt"
    if ctx.kind != "long" or not f.exists():
        return []
    lines = [l.strip() for l in f.read_text().splitlines() if re.match(r"^\d+:\d\d", l.strip())]
    return lines


def duration(ctx):
    try:
        return float(ctx.spec.get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- Claude writes the posts
def prompt(ctx, channels, note, info):
    plat = "\n".join(f"- {p} ({PLATFORMS[p]['name']}): fields " +
                     ", ".join(f"{k} (max {lim} {'items' if k in TAG_FIELDS else 'characters'})" for k, _, lim in PLATFORMS[p]["fields"]) +
                     f". {PLATFORMS[p]['style']}" for p in channels)
    fmt = {"reel": "a vertical 9:16 Reel / Short", "feed": "a 4:5 feed video", "square": "a 1:1 square video",
           "landscape": "a 16:9 landscape video", "long": "a long-form 16:9 video (YouTube / webinar)"}[fmt_key(ctx)]
    words = transcript_text(ctx).split()
    text = " ".join(words[:9000]) + (" …" if len(words) > 9000 else "")
    voice = brandkit.voice_note(brand_id(ctx)) if info["client"] else (
        f"This video is your brand's own ({info['website']}). your brand's tone of voice: {info['tone']}\nCall to action: {info['cta']}")
    ch = chapters(ctx)
    extra = ""
    if not info["client"]:          # your brand's own standard hashtags (Social settings)
        try:
            import social
            s = social.load()
            std = {p: s["hashtags"] + s["channels"][p].get("hashtags", []) for p in channels}
            std = {p: t for p, t in std.items() if t and any(k == "hashtags" for k, _, _ in PLATFORMS[p]["fields"])}
            if std:
                extra += "\nAlways include your brand's standard hashtags where a platform has hashtags: " + \
                         "; ".join(f"{p}: {' '.join(t)}" for p, t in std.items())
        except Exception:
            pass
    if "youtube" in channels and ch:
        extra = ("\nThe video has chapters (they are added to the YouTube description automatically after your text, so don't list "
                 "them): " + "; ".join(ch))
    if fmt_key(ctx) == "reel" and "youtube" in channels:
        extra += "\nOn YouTube this is a Short: end the title with #Shorts."
    return f"""You write social media posts for a finished video. Reply with one JSON object only.

{voice}

THE VIDEO: {fmt}, {duration(ctx):.0f} seconds, called "{project_name(ctx)}".
Shown on screen: {"; ".join(on_screen(ctx)) or "(nothing listed)"}
What is said (transcript):
{text or "(no transcript)"}
{extra}
{("NOTE FROM THE TEAM: " + note) if note else ""}

Write one post for each of these platforms, in the voice above, true to what the video actually says (don't invent
facts, numbers or offers that aren't in the video or the call to action). Each platform reads differently: don't paste
the same text everywhere.
{plat}

Reply exactly like this (only the platforms above, only their fields; hashtags and tags as lists, hashtags with #):
{{"posts": {{"<platform>": {{"<field>": "…", "hashtags": ["#…"]}}}}}}"""


def project_name(ctx):
    root = ctx.root
    try:
        return json.loads((root / "project.json").read_text()).get("name") or root.name
    except (OSError, ValueError):
        return root.name


def draft(ctx, channels, note, creds, only=None):
    pack = load_pack(ctx)
    channels = [c for c in (channels or pack.get("channels") or []) if c in PLATFORMS]
    want = [only] if only in PLATFORMS else channels
    if not want:
        raise ValueError("Choose at least one platform")
    info = brand_info(ctx)
    got = claude_client.ask_json(creds, prompt(ctx, want, note, info), cwd=str(ctx.root), tools="Read", env=ENV,
                                 timeout=420, effort="medium", what="posts")
    posts = got.get("posts") or {}
    pack["channels"], pack["note"] = channels, note
    pack.setdefault("posts", {})
    for p in want:
        if p in posts:
            post = clean_post(p, posts[p])
            if p == "youtube" and chapters(ctx):
                post["text"] = (post["text"].rstrip() + "\n\nChapters\n" + "\n".join(chapters(ctx))).strip()
            if p == "pinterest" and not post.get("link") and info["website"]:
                post["link"] = "https://" + info["website"].removeprefix("https://").removeprefix("http://")
            pack["posts"][p] = post
    pack["drafted"] = time.time()
    return save_pack(ctx, pack)


# ---------------------------------------------------------------- the video, the cover and the pack
def video_file(ctx, find_render):
    """The rendered MP4 (what gets posted), else the edit (for drafting and choosing a cover before the render)."""
    r = find_render()
    if r and Path(r).is_file():
        return Path(r), True
    if ctx.kind != "long":
        base = ctx.edit / (ctx.spec.get("video") or "base-edit.mp4")
        if base.is_file():
            return base, False
    return None, False


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, env=ENV).stdout
    try:
        d = json.loads(out or "{}"); st = (d.get("streams") or [{}])[0]
        return {"dur": round(float(d["format"]["duration"]), 2), "w": st.get("width"), "h": st.get("height")}
    except (KeyError, ValueError):
        return {"dur": 0, "w": None, "h": None}


def make_cover(ctx, video, t):
    out = folder(ctx) / "cover.jpg"
    tmp = out.with_suffix(".tmp.jpg")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, float(t)):.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(tmp)],
                       capture_output=True, text=True, env=ENV, timeout=60)
    if r.returncode or not tmp.exists():
        raise RuntimeError("Couldn't take that frame: " + r.stderr[-200:])
    osutil.replace(tmp, out)
    return out


def post_text(platform, post):
    lines = []
    for key, label, limit in PLATFORMS[platform]["fields"]:
        v = post.get(key)
        if not v:
            continue
        v = " ".join(v) if isinstance(v, list) and key == "hashtags" else ", ".join(v) if isinstance(v, list) else v
        lines += [f"{label}:", v, ""]
    return "\n".join(lines).strip() + "\n"


def make_zip(ctx, video, rendered):
    pack, info = load_pack(ctx), brand_info(ctx)
    name = re.sub(r'[\\/:*?"<>|]+', "-", project_name(ctx)).strip() or "Video"
    z = folder(ctx) / "post-pack.zip"
    tmp = z.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        if video:
            zf.write(video, f"{name}.mp4", compress_type=zipfile.ZIP_STORED)
        cover = ctx.root / "planner" / "cover.jpg"
        if cover.exists():
            zf.write(cover, "cover.jpg", compress_type=zipfile.ZIP_STORED)
        posted = [p for p in ORDER if p in pack.get("channels", []) and p in pack.get("posts", {})]
        for p in posted:
            zf.writestr(f"{PLATFORMS[p]['name']}.txt", post_text(p, pack["posts"][p]))
        readme = [f"{project_name(ctx)}", f"For: {info['name']}", "",
                  f"Video: {name}.mp4" + ("" if rendered else " (NOT RENDERED YET: this is the edit without its graphics; render it first)") if video else "Video: not rendered yet",
                  "Cover: cover.jpg" if cover.exists() else "Cover: none chosen", "",
                  "Posts (one text file each): " + (", ".join(PLATFORMS[p]["name"] for p in posted) or "none yet"), "",
                  f"Made by Studio AI on {time.strftime('%d %B %Y at %H:%M')}"]
        zf.writestr("README.txt", "\n".join(readme) + "\n")
    osutil.replace(tmp, z)
    return z, f"{name} - post pack.zip"


# ---------------------------------------------------------------- scheduling (9.3: posting.py)
def schedule_state(ctx):
    """What Post it's When column needs: this video's scheduled posts, a suggested time per platform, the time zone."""
    try:
        import posting, social
    except ImportError:
        return {}
    s = social.load()
    taken = [posting.parse(p["when"]) for p in posting.all_posts() if p["status"] in ("scheduled", "due")]
    return {"scheduled": posting.for_video(ctx.root), "tz": s["timezone"],
            "suggest": {p: social.suggest(p, taken=taken).isoformat() for p in ORDER},
            "channels_on": [p for p in ORDER if s["channels"][p]["on"]]}


def schedule(ctx, video, rendered, items):
    import posting, social
    if brand_info(ctx)["client"]:
        raise ValueError("Only default-brand videos are scheduled: hand a client the post pack")
    if not video or not rendered:
        raise ValueError("Render the video first: the scheduled post uses the finished MP4")
    if not items:
        raise ValueError("Choose when each post goes out")
    v = {"kind": ctx.kind, "root": str(ctx.root), "name": project_name(ctx), "format": fmt_key(ctx), "brand": brand_id(ctx),
         "render": str(video), "edit": str(ctx.edit) if ctx.edit else None}
    made = posting.schedule(v, load_pack(ctx), items, ctx.root / "planner" / "cover.jpg", social.load()["timezone"])
    return [posting.public(p) for p in made]


# ---------------------------------------------------------------- routes
def platforms_info():
    return {p: {"name": d["name"], "fields": [{"key": k, "label": l, "limit": n, "tags": k in TAG_FIELDS} for k, l, n in d["fields"]]}
            for p, d in PLATFORMS.items()}


def handle(h, method, path, q, ctx, find_render):
    """find_render(): the newest rendered MP4 of this video, or None."""
    if ctx is None:
        h.send_json({"error": "Open a video first"}, 409); return True
    try:
        video, rendered = video_file(ctx, find_render)
        if method == "GET" and path == "/planner/video":
            h.send_file(video); return True
        if method == "GET" and path == "/planner/cover.jpg":
            h.send_file(ctx.root / "planner" / "cover.jpg", cache="no-cache"); return True
        if method == "GET" and path == "/api/planner/state":
            info = brand_info(ctx)
            h.send_json({"platforms": platforms_info(), "order": ORDER, "defaults": DEFAULTS.get(fmt_key(ctx), DEFAULTS["reel"]),
                         "format": fmt_key(ctx), "kind": ctx.kind, "name": project_name(ctx), "brand": info,
                         "video": dict(probe(video), rendered=rendered, name=video.name) if video else None,
                         "chapters": chapters(ctx), "pack": load_pack(ctx), **schedule_state(ctx),
                         "cover": (ctx.root / "planner" / "cover.jpg").exists()}); return True
        if method == "GET" and path == "/api/planner/download":
            z, name = make_zip(ctx, video, rendered)
            h.send_file(z, download=True, filename=name); return True
        if method != "POST":
            return False
        b = h.body()
        if path == "/api/planner/draft":
            creds = claude_client.creds_from(h.headers, settings())
            h.send_json({"pack": draft(ctx, b.get("channels"), str(b.get("note") or ""), creds, b.get("only"))}); return True
        if path == "/api/planner/schedule":
            h.send_json({"posts": schedule(ctx, video, rendered, b.get("items") or [])}); return True
        if path == "/api/planner/save":
            h.send_json({"pack": save_pack(ctx, b.get("pack") or {})}); return True
        if path == "/api/planner/cover":
            if not video:
                raise ValueError("Render the video first (or there's no edit to take a frame from)")
            make_cover(ctx, video, b.get("t", 0))
            pack = load_pack(ctx); pack["cover_t"] = float(b.get("t", 0)); save_pack(ctx, pack)
            h.send_json({"ok": True, "t": pack["cover_t"]}); return True
    except claude_client.NotSignedIn as e:
        h.send_json({"error": str(e)}, 401); return True
    except (ValueError, KeyError, RuntimeError, claude_client.ClaudeError) as e:
        h.send_json({"error": str(e)}, 400); return True
    return False
