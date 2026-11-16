"""Email notifications (ROADMAP phase 9): the planner emails the team when a post is due to be posted by hand, when a post
fails, and (if chosen) when one goes live. Sent through the team's own mail server (SMTP): Google Workspace, Microsoft
365, or a sending service such as Postmark, Resend or SendGrid.

Settings (Social settings → Email notifications), in the planner's social.json "notifications":
  {"emails": ["…"], "on_live": false, "smtp": {"host", "port", "security": "starttls"|"ssl"|"none", "username", "from"}}
The mail server password is in the token store ("<team>/smtp"), never in a file.
On the portal, STUDIO_SMTP_HOST / _PORT / _SECURITY / _USERNAME / _PASSWORD / _FROM can set the server for every team.
Python 3.9 standard library only (smtplib, email).
"""
import html, json, os, smtplib, ssl, time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

import vault

DEFAULTS = {"emails": [], "on_live": False, "smtp": {"host": "", "port": 587, "security": "starttls", "username": "", "from": ""}}


class MailError(RuntimeError):
    pass


def load(d):
    """The notification settings of a planner folder, with defaults and the portal's server settings."""
    try:
        s = json.loads((Path(d) / "social.json").read_text()).get("notifications") or {}
    except (OSError, ValueError):
        s = {}
    out = {"emails": list(s.get("emails") or []), "on_live": bool(s.get("on_live")), "smtp": dict(DEFAULTS["smtp"], **(s.get("smtp") or {}))}
    env = {k: os.environ.get(f"STUDIO_SMTP_{k.upper()}") for k in ("host", "port", "security", "username", "from")}
    for k, v in env.items():
        if v:
            out["smtp"][k] = int(v) if k == "port" else v
    return out


def team_of(d):
    import connect
    return connect.team_of(d)


def password(d):
    return os.environ.get("STUDIO_SMTP_PASSWORD") or (vault.get(d, f"{team_of(d)}/smtp") or {}).get("password")


def ready(d):
    s = load(d)
    return bool(s["emails"] and s["smtp"]["host"] and (s["smtp"]["from"] or s["smtp"]["username"]))


def send(d, subject, text, html_body=None, to=None):
    """Send one email to the team (or `to`). Raises MailError with a plain reason."""
    s = load(d); m = s["smtp"]
    rcpt = to or s["emails"]
    if not rcpt:
        raise MailError("No email addresses to send to (Social settings → Email notifications)")
    if not m["host"]:
        raise MailError("No mail server set (Social settings → Email notifications)")
    sender = m["from"] or m["username"]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, formataddr(("Studio AI", sender)), ", ".join(rcpt)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    port, sec = int(m["port"] or (465 if m["security"] == "ssl" else 587)), m["security"]
    try:
        ctx = ssl.create_default_context()
        if sec == "ssl":
            server = smtplib.SMTP_SSL(m["host"], port, timeout=30, context=ctx)
        else:
            server = smtplib.SMTP(m["host"], port, timeout=30)
            if sec == "starttls":
                server.starttls(context=ctx)
        with server:
            pw = password(d)
            if m["username"] and pw:
                server.login(m["username"], pw)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise MailError("The mail server refused the username or password")
    except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
        raise MailError(f"Couldn't send the email: {e}")


# ---------------------------------------------------------------- the emails
def _wrap(title, intro, rows_html, cta_url, cta_label):
    """A simple branded email (inline styles, as email needs)."""
    return f"""<!doctype html><html><body style="margin:0;background:#f5f3f3;font:15px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#2d3136">
<div style="max-width:560px;margin:0 auto;padding:28px 16px">
 <div style="background:linear-gradient(255deg,#22d3ee,#2563eb);border-radius:16px 16px 0 0;padding:20px 24px;color:#fff">
  <div style="font-weight:800;font-size:13px;letter-spacing:.12em;text-transform:uppercase;opacity:.85">Studio AI</div>
  <div style="font-weight:800;font-size:22px;margin-top:4px">{html.escape(title)}</div></div>
 <div style="background:#fff;border-radius:0 0 16px 16px;padding:22px 24px">
  <p style="margin:0 0 14px">{intro}</p>{rows_html}
  {f'<p style="margin:20px 0 0"><a href="{html.escape(cta_url)}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;font-weight:700;padding:11px 20px;border-radius:99px">{html.escape(cta_label)}</a></p>' if cta_url else ''}
 </div>
 <p style="color:#8d9298;font-size:12px;text-align:center;margin-top:14px">Sent by Studio AI's planner. Change who gets these in Social settings.</p>
</div></body></html>"""


def _post_block(p, platform_name, when_text):
    f = p.get("fields") or {}
    body = "\n\n".join(x for x in [f.get("title"), f.get("text"), " ".join(f.get("hashtags") or []), f.get("first_comment") and "First comment: " + f["first_comment"]] if x)
    return (f'<div style="border:1px solid #ebe6e9;border-radius:12px;padding:14px 16px;margin:10px 0">'
            f'<div style="font-weight:700">{html.escape(platform_name)} <span style="color:#8d9298;font-weight:500">· {html.escape(when_text)}</span></div>'
            f'<div style="white-space:pre-wrap;margin-top:8px;font-size:14px">{html.escape(body)}</div></div>'), body


def post_email(d, posts, kind, public_url, platforms, when_text):
    """kind: due | failed | live. posts: one or more posts of the same video and moment."""
    v = posts[0]["video"]
    names = [platforms[p["platform"]]["name"] for p in posts]
    blocks, texts = [], []
    for p in posts:
        b, t = _post_block(p, platforms[p["platform"]]["name"], when_text)
        if kind == "failed" and p.get("error"):
            b = b.replace("</div></div>", f'</div><div style="color:#c8312b;margin-top:8px;font-size:13px">{html.escape(p["error"])}</div></div>', 1)
        if kind == "due" and p.get("note"):
            b = b.replace("</div></div>", f'</div><div style="color:#2563eb;margin-top:8px;font-size:13px">{html.escape(p["note"])}</div></div>', 1)
        if kind == "live" and p.get("link"):
            b = b.replace("</div></div>", f'</div><div style="margin-top:8px;font-size:13px"><a href="{html.escape(p["link"])}">See it live</a></div></div>', 1)
        blocks.append(b); texts.append(f"{platforms[p['platform']]['name']} ({when_text})\n{t}" + (f"\nError: {p['error']}" if kind == "failed" and p.get("error") else "")
                                       + (f"\n{p['note']}" if kind == "due" and p.get("note") else "") + (f"\nLive: {p['link']}" if kind == "live" and p.get("link") else ""))
    on = ", ".join(names)
    subject, title, intro, cta = {
        "due": (f"Time to post: {v['name']} on {on}", "Time to post",
                (f"<b>{html.escape(v['name'])}</b> is waiting in the {html.escape(on)} app: finish posting it there (below), then press <b>Mark posted</b> in the calendar."
                 if all(p.get("note") for p in posts) else
                 f"<b>{html.escape(v['name'])}</b> is due on {html.escape(on)}. These channels aren't connected yet, so post it by hand, then press <b>Mark posted</b> in the calendar."),
                "Open the calendar"),
        "failed": (f"A post failed: {v['name']} on {on}", "A post failed",
                   f"<b>{html.escape(v['name'])}</b> couldn't be posted on {html.escape(on)}, after trying again. Open the calendar to post it now or move it.",
                   "Open the calendar"),
        "live": (f"Live: {v['name']} on {on}", "It's live", f"<b>{html.escape(v['name'])}</b> is now live on {html.escape(on)}.", "Open the calendar"),
    }[kind]
    text = f"{title}\n\n" + html.unescape(intro.replace("<b>", "").replace("</b>", "")) + "\n\n" + "\n\n---\n\n".join(texts) + f"\n\nThe calendar: {public_url}/#calendar\n"
    return subject, text, _wrap(title, intro, "".join(blocks), f"{public_url}/#calendar", cta)


def test_email(d, public_url):
    s = load(d)
    send(d, "Studio AI: test email",
         f"This is a test from Studio AI's planner. Notifications go to: {', '.join(s['emails'])}.\n\nThe calendar: {public_url}/#calendar\n",
         _wrap("Email notifications work", f"This is a test. When a post is due to be posted by hand, or a post fails, an email like this goes to: <b>{html.escape(', '.join(s['emails']))}</b>.",
               "", f"{public_url}/#calendar", "Open the calendar"))
