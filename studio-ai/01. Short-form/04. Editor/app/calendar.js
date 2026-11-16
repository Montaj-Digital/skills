// The content calendar and Social settings (ROADMAP phase 9.2-9.3). your brand's own channels only.
// Server side: social.py (settings) and posting.py (scheduled posts and the scheduler).
// Design: 07. Concepts/Planner - Calendar (concept).png.
"use strict";
(function () {
  const C = { view: "week", start: null, posts: [], tz: "Europe/London", sel: null, filter: "all", social: null, summary: null };
  const PF = { instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube", facebook: "Facebook", linkedin: "LinkedIn", x: "X",
    threads: "Threads", pinterest: "Pinterest", google: "Google Business", bluesky: "Bluesky" };
  const ORDER = Object.keys(PF);
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const H0 = 6, H1 = 23, ROW = 52;                     // the week view shows 06:00-23:00, 52 px an hour
  const post = (u, b) => fetch(u, { method: "POST", body: JSON.stringify(b || {}) }).then(async (r) => ({ ok: r.ok, ...(await r.json().catch(() => ({}))) }));
  const badge = (id, cls = "") => el("span", { class: `pfb pf-${id} ${cls}` }, el("img", { src: `/app/platforms/${id}.svg`, alt: "" }));
  const pad = (n) => String(n).padStart(2, "0");

  // ---------------------------------------------------------------- time, in the team's time zone
  // parts of an instant in the team's zone: {y, m, d, h, mi, wd (0 = Mon)}
  const fmtParts = (iso) => {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: C.tz, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", weekday: "short", hourCycle: "h23" }).formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
    return { y: +p.year, m: +p.month, d: +p.day, h: +p.hour, mi: +p.minute, wd: DAYS.indexOf(p.weekday) };
  };
  const dayKey = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
  const addDays = (key, n) => { const t = new Date(key + "T12:00:00Z"); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10); };
  const weekday = (key) => (new Date(key + "T12:00:00Z").getUTCDay() + 6) % 7;
  const today = () => { const p = fmtParts(new Date().toISOString()); return dayKey(p.y, p.m, p.d); };
  const mondayOf = (key) => addDays(key, -weekday(key));
  const nice = (iso) => new Intl.DateTimeFormat("en-GB", { timeZone: C.tz, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(iso));
  const short = (iso) => new Intl.DateTimeFormat("en-GB", { timeZone: C.tz, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(iso));
  const hm = (iso) => { const p = fmtParts(iso); return `${pad(p.h)}:${pad(p.mi)}`; };
  const localInput = (iso) => { const p = fmtParts(iso); return `${dayKey(p.y, p.m, p.d)}T${pad(p.h)}:${pad(p.mi)}`; };

  // ---------------------------------------------------------------- data
  async function load() {
    const from = C.view === "month" ? addDays(mondayOf(C.start.slice(0, 8) + "01"), -7) : addDays(C.start, -1);
    const to = C.view === "month" ? addDays(from, 50) : C.view === "list" ? addDays(C.start, 60) : addDays(C.start, 8);
    const r = await fetch(`/api/calendar/posts?from=${from}T00:00:00%2B00:00&to=${to}T00:00:00%2B00:00`).then((x) => x.json()).catch(() => ({ posts: [] }));
    C.posts = r.posts || []; C.tz = r.tz || C.tz; setDue(r.due || 0);
  }
  // posts scheduled together (same video, same minute) show as one card
  function groups() {
    const by = new Map();
    for (const p of C.posts.filter(shown)) {
      const k = `${p.group}|${p.when.slice(0, 16)}`;
      if (!by.has(k)) by.set(k, { key: k, when: p.when, video: p.video, posts: [] });
      by.get(k).posts.push(p);
    }
    for (const g of by.values()) g.posts.sort((a, b) => ORDER.indexOf(a.platform) - ORDER.indexOf(b.platform));
    return [...by.values()].sort((a, b) => a.when.localeCompare(b.when));
  }
  const kindOf = (fmt) => (fmt === "reel" ? "short" : fmt === "feed" || fmt === "square" ? "feed" : "wide");
  const shown = (p) => p.status !== "cancelled" && (C.filter === "all" || kindOf(p.video.format) === C.filter);
  const state = (g) => {
    const s = g.posts.map((p) => p.status);
    return s.includes("failed") ? ["fail", "Failed"] : s.includes("due") ? ["due", "Post by hand"] : s.includes("posting") ? ["posting", "Posting…"]
      : s.every((x) => x === "live" || x === "posted") ? ["live", "Live"] : ["sched", "Scheduled"];
  };

  // ---------------------------------------------------------------- the screen
  async function open() {
    let v = $("#calview");
    if (!v) { v = el("div", { id: "calview", class: "home bview" }); document.body.append(v); }
    v.hidden = false; $("#calBtn")?.classList.add("on");
    const [s, cs] = await Promise.all([fetch("/api/social").then((r) => r.json()).catch(() => ({})), fetch("/api/connect/state").then((r) => r.json()).catch(() => null)]);
    C.social = s.settings; C.tz = s.settings?.timezone || C.tz; C.conn = cs;
    if (!C.start) C.start = mondayOf(today());
    await load(); draw();
  }
  function close() { const v = $("#calview"); if (v) { v.hidden = true; v.innerHTML = ""; } $("#calBtn")?.classList.remove("on"); }

  function draw() {
    const v = $("#calview"); if (!v || v.hidden) return;
    v.innerHTML = "";
    const title = C.view === "month" ? new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(C.start.slice(0, 8) + "15T12:00:00Z"))
      : C.view === "list" ? "Coming up" : (() => { const a = new Date(C.start + "T12:00:00Z"), b = new Date(addDays(C.start, 6) + "T12:00:00Z");
        const f = (d, o) => new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", ...o }).format(d);
        return a.getUTCMonth() === b.getUTCMonth() ? `${f(a, { day: "numeric" })} – ${f(b, { day: "numeric", month: "long", year: "numeric" })}` : `${f(a, { day: "numeric", month: "short" })} – ${f(b, { day: "numeric", month: "short", year: "numeric" })}`; })();
    const step = (n) => { C.start = C.view === "month" ? (() => { const d = new Date(C.start.slice(0, 8) + "01T12:00:00Z"); d.setUTCMonth(d.getUTCMonth() + n); return d.toISOString().slice(0, 10); })() : addDays(C.start, 7 * n); load().then(draw); };
    const seg = el("div", { class: "cseg" }, ...[["week", "Week"], ["month", "Month"], ["list", "List"]].map(([k, l]) => el("button", { class: C.view === k ? "on" : "", onclick: () => {
      C.view = k; C.start = k === "month" ? today().slice(0, 8) + "01" : mondayOf(today()); load().then(draw); } }, l)));
    const due = C.posts.filter((p) => p.status === "due" || p.status === "failed").length;
    v.append(el("div", { class: "home-in cwrap" },
      el("div", { class: "chead" },
        el("h1", {}, "Content ", el("span", { class: "gt" }, "calendar")),
        el("span", { class: "cnav" }, el("button", { class: "icon", onclick: () => step(-1), "aria-label": "Earlier" }, ic("chevron-left")),
          el("button", { class: "icon", onclick: () => step(1), "aria-label": "Later" }, ic("chevron-right")), el("b", {}, title)),
        el("button", { class: "small", onclick: () => { C.start = C.view === "month" ? today().slice(0, 8) + "01" : mondayOf(today()); load().then(draw); } }, "Today"),
        el("span", { class: "csp" }), seg,
        window.openResults ? el("button", { onclick: () => { close(); window.openResults(); } }, ic("chart-column"), "Results") : null,
        el("button", { onclick: openSocial }, ic("settings"), "Social settings"),
        el("button", { class: "icon", onclick: close, title: "Close", "aria-label": "Close" }, ic("x"))),
      due ? el("div", { class: "cdue" }, ic("bell"), `${due} post${due === 1 ? " is" : "s are"} due. Until the channels are connected, post them by hand: open one to copy its post.`) : null,
      el("div", { class: "cgrid" }, side(), el("div", { class: "pcard cmain" }, C.view === "month" ? month() : C.view === "list" ? list() : week()), details())));
    if (C.view === "week") requestAnimationFrame(() => { const b = $(".cbody"); if (b && !b.dataset.scrolled) { b.scrollTop = (8 - H0) * ROW; b.dataset.scrolled = 1; } });
  }

  function side() {
    const all = C.posts.filter((p) => p.status !== "cancelled");
    const n = (k) => all.filter((p) => kindOf(p.video.format) === k).length;
    const filters = [["all", "Everything", all.length, "var(--grad)"], ["short", "Reels and Shorts", n("short"), "#5ce1f6"], ["feed", "Feed videos", n("feed"), "#22d3ee"], ["wide", "Landscape and long-form", n("wide"), "var(--text)"]];
    const s = C.social;
    const chans = s ? ORDER.filter((p) => s.channels[p].on) : [];
    const wk = C.view === "week" ? all.filter((p) => { const k = localInput(p.when).slice(0, 10); return k >= C.start && k <= addDays(C.start, 6); }) : all;
    const count = (f) => wk.filter((p) => f(p.status)).length;
    return el("div", { class: "cside" },
      el("div", { class: "pcard" }, el("div", { class: "plab" }, "Show"), ...filters.map(([k, l, c, col]) => el("button", { class: `cfil${C.filter === k ? " on" : ""}`, onclick: () => { C.filter = k; draw(); } },
        el("span", { class: "cdot", style: `background:${col}` }), l, el("small", {}, c)))),
      el("div", { class: "pcard" }, el("div", { class: "plab" }, "your brand's channels"),
        ...chans.map((p) => { const c = C.conn?.platforms?.[p]; return el("div", { class: "cch" }, badge(p), el("span", {}, PF[p], el("small", {}, c?.connected ? c.account : s.channels[p].account || "")),
          c?.connected ? el("em", { class: "ok" }, C.conn.test_platform ? "test" : "connected") : el("em", {}, "post by hand")); }),
        chans.length ? null : el("div", { class: "muted" }, "None chosen yet."),
        el("button", { class: "small", style: "margin-top:8px", onclick: openSocial }, "Channels and times…")),
      el("div", { class: "pcard" }, el("div", { class: "plab" }, C.view === "week" ? "This week" : "In view"),
        el("div", { class: "cstats" }, ...[["live", (x) => x === "live" || x === "posted"], ["scheduled", (x) => x === "scheduled" || x === "posting"], ["due", (x) => x === "due"], ["failed", (x) => x === "failed"]]
          .map(([l, f]) => el("div", {}, el("b", { class: l === "failed" && count(f) ? "bad" : "" }, String(count(f))), el("span", {}, l))))));
  }

  // ---------------------------------------------------------------- week
  function week() {
    const days = [...Array(7)].map((_, i) => addDays(C.start, i)), t = today();
    const head = el("div", { class: "cdays" }, el("div"), ...days.map((k) => el("div", { class: k === t ? "today" : "" }, DAYS[weekday(k)], el("b", {}, String(+k.slice(8))))));
    const body = el("div", { class: "cbody" });
    const hours = el("div", { class: "chours" }, ...[...Array(H1 - H0 + 1)].map((_, i) => el("div", { style: `height:${ROW}px` }, `${pad(H0 + i)}:00`)));
    const cols = days.map((k) => el("div", { class: `ccol${k === t ? " today" : ""}`, style: `height:${(H1 - H0 + 1) * ROW}px`, "data-day": k }));
    body.append(el("div", { class: "cbodyin" }, hours, ...cols));
    for (const g of groups()) {
      const p = fmtParts(g.when), k = dayKey(p.y, p.m, p.d), i = days.indexOf(k);
      if (i < 0) continue;
      const top = Math.max(0, (p.h + p.mi / 60 - H0) * ROW);
      cols[i].append(cardEl(g, top));
    }
    const np = fmtParts(new Date().toISOString()), ti = days.indexOf(dayKey(np.y, np.m, np.d));
    if (ti >= 0 && np.h >= H0) cols[ti].append(el("div", { class: "cnow", style: `top:${(np.h + np.mi / 60 - H0) * ROW}px` }));
    return el("div", { class: "cweek" }, head, body);
  }
  function cardEl(g, top) {
    const [cls, label] = state(g);
    const c = el("div", { class: `ccard${C.sel === g.key ? " sel" : ""}${cls === "due" || cls === "fail" ? " warn" : ""}`, style: `top:${top}px`, title: `${g.video.name} · ${nice(g.when)}` },
      el("img", { class: `ccov ${g.video.format === "reel" ? "" : "w"}`, draggable: false, src: g.posts[0].cover ? `/calendar/cover/${g.posts[0].id}.jpg` : "", alt: "" }),
      el("div", { class: "ctx" }, el("b", {}, g.video.name), el("div", { class: "cpf" }, ...g.posts.map((p) => badge(p.platform, "sm"))),
        el("div", { class: "ctm" }, hm(g.when)), el("span", { class: `cst ${cls}` }, label)));
    c.addEventListener("pointerdown", (e) => dragStart(e, c, g));
    c.addEventListener("dragstart", (e) => e.preventDefault());       // no browser image drag (it cancels the pointer)
    return c;
  }
  // drag a card to another day or time: it snaps to 15 minutes; a plain click selects it
  function dragStart(e, c, g) {
    if (e.button !== 0) return;
    e.preventDefault();
    const sx = e.clientX, sy = e.clientY, top0 = parseFloat(c.style.top);
    let moved = false, target = null, ghost = null;
    const mv = (ev) => {
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      if (!moved && Math.hypot(dx, dy) < 5) return;
      if (!moved && !g.posts.some((p) => p.status === "scheduled" || p.status === "due")) return;
      moved = true;
      if (!ghost) { ghost = c.cloneNode(true); ghost.classList.add("ghost"); document.body.append(ghost); c.classList.add("moving"); }
      const r = c.getBoundingClientRect(); ghost.style.cssText = `position:fixed;left:${r.left + dx}px;top:${r.top + dy}px;width:${r.width}px;z-index:99;pointer-events:none`;
      const col = document.elementsFromPoint(ev.clientX, ev.clientY).find((x) => x.classList?.contains("ccol"));
      if (col) {
        const y = top0 + dy, mins = Math.max(0, Math.round((y / ROW * 60) / 15) * 15) + H0 * 60;
        target = { day: col.dataset.day, h: Math.min(23, Math.floor(mins / 60)), mi: mins % 60 };
        ghost.querySelector(".ctm").textContent = `${pad(target.h)}:${pad(target.mi)}`;
      }
    };
    const up = async () => {
      window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); window.removeEventListener("pointercancel", up);
      ghost?.remove(); c.classList.remove("moving");
      if (!moved) { C.sel = g.key; draw(); return; }
      if (!target) return;
      const ids = g.posts.filter((p) => p.status === "scheduled" || p.status === "due").map((p) => p.id);
      const r = await post("/api/calendar/reschedule", { ids, when: `${target.day}T${pad(target.h)}:${pad(target.mi)}` });
      if (r.error) toast(r.error); else toast(`Moved to ${nice(r.posts[0].when)}`);
      C.sel = null; await load(); draw();
    };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up); window.addEventListener("pointercancel", up);
  }

  // ---------------------------------------------------------------- month and list
  function month() {
    const first = C.start.slice(0, 8) + "01", start = mondayOf(first), m = first.slice(0, 7), t = today();
    const gs = groups(), cells = [];
    for (let i = 0; i < 42; i++) {
      const k = addDays(start, i), items = gs.filter((g) => localInput(g.when).slice(0, 10) === k);
      cells.push(el("div", { class: `cmday${k.slice(0, 7) !== m ? " out" : ""}${k === t ? " today" : ""}` }, el("b", {}, String(+k.slice(8))),
        ...items.slice(0, 3).map((g) => { const [cls] = state(g); return el("button", { class: `cmit ${cls}`, onclick: () => { C.sel = g.key; draw(); } },
          el("span", {}, hm(g.when)), ...g.posts.slice(0, 3).map((p) => badge(p.platform, "xs")), el("i", {}, g.video.name)); }),
        items.length > 3 ? el("small", {}, `+${items.length - 3} more`) : null));
    }
    return el("div", { class: "cmonth" }, ...DAYS.map((d) => el("div", { class: "cmh" }, d)), ...cells);
  }
  function list() {
    const gs = groups();
    if (!gs.length) return el("div", { class: "pempty" }, "Nothing scheduled yet. Open a rendered default-brand video, press Posts, and schedule it.");
    return el("div", { class: "clist" }, ...gs.map((g) => { const [cls, label] = state(g); return el("button", { class: `clrow${C.sel === g.key ? " sel" : ""}`, onclick: () => { C.sel = g.key; draw(); } },
      el("span", { class: "clw" }, nice(g.when)), el("b", {}, g.video.name), el("span", { class: "cpf" }, ...g.posts.map((p) => badge(p.platform, "sm"))), el("span", { class: `cst ${cls}` }, label)); }));
  }

  // ---------------------------------------------------------------- the selected card
  function details() {
    const g = groups().find((x) => x.key === C.sel);
    const box = el("div", { class: "pcard cdet" });
    if (!g) {
      box.append(el("div", { class: "plab" }, "How it works"), el("p", { class: "muted" },
        "Schedule a rendered default-brand video from Posts. Each platform's post goes out at its time. Until the channels are connected (the developer adds them), the calendar tells you when a post is due and has its text ready to copy."),
        el("p", { class: "muted" }, "Drag a card to move it. Click it for its posts."));
      return box;
    }
    const [cls, label] = state(g);
    const p0 = g.posts[0];
    box.append(el("div", { class: "cdtop" },
      p0.cover ? el("img", { class: `cdcov${g.video.format === "reel" ? "" : " w"}`, src: `/calendar/cover/${p0.id}.jpg` }) : null,
      el("div", {}, el("span", { class: `cst ${cls}` }, label), el("h2", {}, g.video.name),
        el("div", { class: "muted" }, `${{ reel: "Reel 9:16", feed: "Feed 4:5", square: "Square 1:1", landscape: "Landscape 16:9", long: "Long-form 16:9" }[g.video.format] || ""}`),
        el("div", { class: "muted" }, nice(g.when)), el("div", { class: "muted" }, C.tz))));
    g.posts.forEach((p) => box.append(postRow(p)));
    const when = el("input", { type: "datetime-local", value: localInput(g.when) });
    const open = g.posts.filter((p) => p.status === "scheduled" || p.status === "due" || p.status === "failed").map((p) => p.id);
    const now = g.posts.filter((p) => p.status === "scheduled" || p.status === "failed").map((p) => p.id);     // due ones aren't connected
    box.append(el("div", { class: "cdact" },
      open.length ? el("div", { class: "cdrow" }, when, el("button", { class: "small", onclick: async () => { const r = await post("/api/calendar/reschedule", { ids: open, when: when.value }); if (r.error) return toast(r.error); toast("Moved"); C.sel = null; await load(); draw(); } }, "Move")) : null,
      el("div", { class: "cdrow" },
        now.length ? el("button", { class: "small primary", onclick: async () => {
          if (!confirm(`Post ${now.length === 1 ? `the ${PF[g.posts.find((p) => p.id === now[0]).platform]} post` : `${now.length} posts`} now?`)) return;
          const r = await post("/api/calendar/post-now", { ids: now }); if (r.error) return toast(r.error);
          toast("Posting now: it takes a minute"); await load(); draw(); setTimeout(async () => { await load(); draw(); }, 8000); } }, ic("send"), "Post now") : null,
        open.length ? el("button", { class: "small", onclick: async () => { if (!confirm(`Cancel ${open.length} post${open.length === 1 ? "" : "s"}?`)) return; await post("/api/calendar/cancel", { ids: open }); C.sel = null; await load(); draw(); } }, "Cancel") : null,
        el("button", { class: "small", onclick: () => openVideo(g.video) }, "Open video"))));
    return box;
  }
  function postRow(p) {
    const f = p.fields || {};
    const text = [f.title, f.text, (f.hashtags || []).join(" ")].filter(Boolean).join("\n\n");
    const st = { scheduled: ["sched", "Scheduled"], due: ["due", "Due"], posting: ["posting", "Posting…"], live: ["live", "Live"], posted: ["live", "Posted"], failed: ["fail", "Failed"] }[p.status] || ["sched", p.status];
    return el("div", { class: "cprow" }, badge(p.platform, "lg"),
      el("div", { class: "cpw" }, el("b", {}, PF[p.platform]), p.numbers ? el("span", { class: "cnums" }, numLine(p.numbers)) : null,
        el("small", {}, p.link ? p.link : p.error ? p.error : p.status === "due" && p.note ? p.note : `${hm(p.when)} · ${(f.text || f.title || "").slice(0, 70)}…`)),
      el("span", { class: `cst ${st[0]}` }, st[1]),
      p.status === "due" || p.status === "failed" ? el("span", { class: "cpact" },
        el("button", { class: "small", onclick: async () => { await navigator.clipboard.writeText(text).catch(() => {}); toast(`${PF[p.platform]} post copied`); } }, ic("copy"), "Copy"),
        el("button", { class: "small", onclick: async () => { const link = prompt(`Posted on ${PF[p.platform]}? Paste the link (optional):`, ""); if (link === null) return; await post("/api/calendar/posted", { ids: [p.id], link }); await load(); draw(); } }, "Mark posted")) : null);
  }
  // a live post's latest numbers, in a line ("1,240 views · 88 likes · 6 comments")
  function numLine(n) {
    const f = (x) => new Intl.NumberFormat("en-GB", { notation: x >= 10000 ? "compact" : "standard" }).format(x);
    return [["views", "views"], ["likes", "likes"], ["comments", "comments"], ["shares", "shares"]].filter(([k]) => typeof n[k] === "number")
      .map(([k, l]) => `${f(n[k])} ${n[k] === 1 ? l.slice(0, -1) : l}`).join(" · ");
  }
  async function openVideo(v) {
    close();
    if (v.kind === "long") { toast("Open it from Open → Long-form"); window.showHome?.(true); return; }
    const r = await fetch("/api/open", { method: "POST", body: JSON.stringify({ path: v.edit || v.root + "/edit" }) }).then((x) => x.json());
    if (!r.ok) return toast(r.error || "Couldn't open it");
    location.reload();
  }

  // ---------------------------------------------------------------- Social settings
  async function openSocial() {
    let v = $("#socview");
    if (!v) { v = el("div", { id: "socview", class: "home bview" }); document.body.append(v); }
    v.hidden = false; v.innerHTML = "";
    const [r, cs0] = await Promise.all([fetch("/api/social").then((x) => x.json()), fetch("/api/connect/state").then((x) => x.json()).catch(() => null)]);
    const s = r.settings; let t = 0; let cs = cs0;
    const status = el("span", { class: "muted" }, "Saved");
    const save = () => { clearTimeout(t); status.textContent = "Saving…"; t = setTimeout(async () => { const x = await post("/api/social", { settings: s }); status.textContent = x.error ? x.error : "Saved"; if (!x.error) { C.social = x.settings; } }, 600); };
    const tz = el("select", {}, ...[...new Set([s.timezone, ...r.zones])].map((z) => el("option", { value: z, selected: z === s.timezone }, z)));
    tz.onchange = () => { s.timezone = tz.value; save(); };
    const std = el("input", { type: "text", value: s.hashtags.join(" "), placeholder: "#yourbrand" });
    std.oninput = () => { s.hashtags = std.value.split(/[\s,]+/).filter(Boolean).map((x) => "#" + x.replace(/^#+/, "")); save(); };
    const conn = (p) => {
      const x = cs?.platforms?.[p], box = el("div", { class: "sconn" });
      if (!x) return box;
      if (x.connected) {
        const days = x.expires ? Math.floor((x.expires * 1000 - Date.now()) / 86400000) : null;
        const soon = days !== null && days < 15;
        box.append(...[el("span", { class: "ok" }, ic("check"), `Connected: ${x.account || ""}`),
          soon ? el("span", { class: "warn" }, days < 0 ? "Sign-in has run out: connect again" : `Sign-in runs out in ${days} day${days === 1 ? "" : "s"}`) : null,
          soon ? el("button", { class: "small primary", onclick: () => connectTo(p) }, "Connect again") : null,
          el("button", { class: "small", onclick: async () => { if (!confirm(`Disconnect ${PF[p]}? Scheduled posts become reminders again.`)) return; cs = await post("/api/connect/disconnect", { platform: p }); openSocial(); } }, "Disconnect")].filter(Boolean));
      }
      else if (!x.built) box.append(el("span", {}, "Not built yet: posts are reminders"));
      else if (!x.app_keys) box.append(el("span", {}, "App keys needed first (developer)"), el("button", { class: "small", onclick: () => appKeys(cs) }, "App keys…"));
      else box.append(el("span", {}, "Not connected: posts are reminders"), el("button", { class: "small primary", onclick: () => connectTo(p) }, "Connect"));
      const opts = (x.options || []).map((o) => {
        const sel = el("select", {}, ...o.choices.map(([v, l]) => el("option", { value: v, selected: v === o.value }, l)));
        sel.onchange = async () => { const r = await post("/api/connect/option", { platform: p, key: o.key, value: sel.value }); if (r.error) return toast(r.error); cs = r; openSocial(); };
        return el("div", { class: "pfield sopt" }, el("div", { class: "pfl" }, el("span", {}, o.label)), sel);
      });
      return opts.length ? el("div", {}, box, ...opts) : box;
    };
    const cards = ORDER.map((p) => {
      const c = s.channels[p];
      const on = el("button", { class: `pchip${c.on ? " on" : ""}`, onclick: () => { c.on = !c.on; on.classList.toggle("on", c.on); save(); } }, "We post here", el("span", { class: "ptg" }));
      const acct = el("input", { type: "text", value: c.account, placeholder: p === "youtube" ? "@yourbrand" : p === "linkedin" ? "your brand (company page)" : "@yourbrand" });
      acct.oninput = () => { c.account = acct.value; save(); };
      const url = el("input", { type: "text", value: c.url, placeholder: "Profile link" });
      url.oninput = () => { c.url = url.value; save(); };
      const times = el("div", { class: "stimes" });
      const drawTimes = () => { times.innerHTML = ""; c.times.forEach((x, i) => times.append(el("span", { class: "stime" }, x, el("button", { class: "icon tiny", onclick: () => { c.times.splice(i, 1); drawTimes(); save(); }, "aria-label": "Remove" }, ic("x"))))); };
      drawTimes();
      const day = el("select", {}, ...r.days.map((d) => el("option", { value: d }, d))), tm = el("input", { type: "time", value: "09:00" });
      const add = el("button", { class: "small", onclick: () => { const x = `${day.value} ${tm.value}`; if (!c.times.includes(x)) c.times.push(x); drawTimes(); save(); } }, ic("plus"), "Add");
      const tags = el("input", { type: "text", value: c.hashtags.join(" "), placeholder: "Extra hashtags for this platform" });
      tags.oninput = () => { c.hashtags = tags.value.split(/[\s,]+/).filter(Boolean).map((x) => "#" + x.replace(/^#+/, "")); save(); };
      return el("div", { class: "pcard scard" },
        el("div", { class: "pph" }, badge(p, "lg"), el("div", {}, el("b", {}, PF[p])), el("span", { class: "pacts" }, on)),
        conn(p),
        el("div", { class: "pfield" }, el("div", { class: "pfl" }, el("span", {}, "Account")), acct),
        el("div", { class: "pfield" }, el("div", { class: "pfl" }, el("span", {}, "Profile link")), url),
        el("div", { class: "pfield" }, el("div", { class: "pfl" }, el("span", {}, "Usual posting times")), times, el("div", { class: "cdrow" }, day, tm, add)),
        el("div", { class: "pfield" }, el("div", { class: "pfl" }, el("span", {}, "Hashtags")), tags));
    });
    v.append(el("div", { class: "home-in cwrap" },
      el("div", { class: "chead" }, el("h1", {}, "Social ", el("span", { class: "gt" }, "settings")), el("span", { class: "csp" }), status,
        el("button", { class: "icon", onclick: async () => { v.hidden = true; v.innerHTML = ""; if ($("#calview") && !$("#calview").hidden) { const x = await fetch("/api/social").then((y) => y.json()); C.social = x.settings; C.tz = x.settings.timezone; draw(); } }, title: "Close", "aria-label": "Close" }, ic("x"))),
      el("p", { class: "lib" }, "your brand's own channels. Clients publish their own way: give them the post pack from Posts."),
      el("div", { class: "pcard sglob" }, el("div", { class: "pfield" }, el("div", { class: "pfl" }, el("span", {}, "Time zone")), tz),
        el("div", { class: "pfield", style: "flex:1" }, el("div", { class: "pfl" }, el("span", {}, "Standard hashtags (Claude adds them to every post with hashtags)")), std)),
      notifications(s, save),
      cs ? el("div", { class: "pcard sglob" },
        el("button", { class: `psame${cs.test_platform ? " on" : ""}`, style: "width:auto", onclick: async () => { cs = await post("/api/connect/test-platform", { on: !cs.test_platform }); openSocial(); } },
          el("span", { class: "ptg" }), el("span", {}, "Use the test platform", el("small", {}, "Studio AI's stand-in for every platform: try connecting and posting with no real accounts"))),
        el("span", { class: "csp" }),
        el("span", { class: "muted" }, cs.store.ok ? `Sign-ins are kept in: ${cs.store.what}` : `Token store: ${cs.store.what}`),
        el("button", { onclick: () => appKeys(cs) }, ic("settings"), "App keys (developer)…")) : null,
      el("div", { class: "sgrid" }, ...cards)));
  }

  // who gets emailed (a post is due to be posted by hand, a post failed, optionally a post went live), and the mail server
  function notifications(s, save) {
    const n = s.notifications;
    const f = (label, input, wide) => el("div", { class: "pfield", style: wide ? "flex:2" : "flex:1" }, el("div", { class: "pfl" }, el("span", {}, label)), input);
    const emails = el("input", { type: "text", value: (n.emails || []).join(", "), placeholder: "team@example.com, you@example.com" });
    emails.oninput = () => { n.emails = emails.value.split(/[\s,;]+/).filter(Boolean); save(); };
    const live = el("button", { class: `psame${n.on_live ? " on" : ""}`, style: "width:auto", onclick: () => { n.on_live = !n.on_live; live.classList.toggle("on", n.on_live); save(); } },
      el("span", { class: "ptg" }), el("span", {}, "Also when a post goes live", el("small", {}, "due and failed posts are always emailed")));
    const inp = (k, ph, type = "text") => { const i = el("input", { type, value: n.smtp[k] ?? "", placeholder: ph }); i.oninput = () => { n.smtp[k] = type === "number" ? +i.value : i.value; save(); }; return i; };
    const sec = el("select", {}, ...[["starttls", "STARTTLS (587)"], ["ssl", "SSL (465)"], ["none", "None (25)"]].map(([v, l]) => el("option", { value: v, selected: n.smtp.security === v }, l)));
    sec.onchange = () => { n.smtp.security = sec.value; save(); };
    const pw = el("input", { type: "password", placeholder: n.password_set ? "•••••• saved (type to replace)" : "Password or app password" });
    const savePw = el("button", { class: "small", onclick: async () => { const r = await post("/api/social/smtp-password", { password: pw.value }); if (r.error) return toast(r.error);
      pw.value = ""; pw.placeholder = "•••••• saved (type to replace)"; toast("Mail password saved in the token store"); } }, "Save password");
    const test = el("button", { class: "small primary", onclick: async () => { test.disabled = true; test.textContent = "Sending…";
      const r = await post("/api/social/test-email", {}); test.disabled = false; test.textContent = "Send a test email"; toast(r.error || `Test email sent to ${(n.emails || []).join(", ")}`); } }, "Send a test email");
    return el("div", { class: "pcard snotes" },
      el("div", { class: "pph" }, el("span", { class: "pspark" }, ic("bell")), el("div", {}, el("b", {}, "Email notifications"),
        el("small", {}, "An email when a post is due to be posted by hand or fails, with the post's text ready to copy")), el("span", { class: "pacts" }, test)),
      el("div", { class: "cdrow", style: "align-items:flex-end" }, f("Send to", emails, true), live),
      el("div", { class: "plab", style: "margin-top:4px" }, "Mail server (SMTP)"),
      el("div", { class: "cdrow", style: "align-items:flex-end" }, f("Server", inp("host", "smtp.gmail.com")), f("Port", inp("port", "587", "number")), f("Security", sec)),
      el("div", { class: "cdrow", style: "align-items:flex-end" }, f("Username", inp("username", "notifications@example.com")), f("Password", pw), savePw, f("From", inp("from", "notifications@example.com"))),
      el("small", { class: "muted" }, "Google Workspace: smtp.gmail.com, STARTTLS 587, the account and an app password. Microsoft 365: smtp.office365.com, STARTTLS 587. The password is kept in the token store."));
  }

  // sign in on the platform's own page, in a small window; it tells us when it's done
  async function connectTo(p) {
    const r = await post("/api/connect/start", { platform: p });
    if (r.error) return toast(r.error);
    const w = window.open(r.url, "studio-connect", "width=520,height=720");
    if (!w) { toast("Allow pop-ups for Studio AI, then press Connect again"); return; }
    const done = (e) => { if (e.data && "studioConnect" in e.data) { window.removeEventListener("message", done); toast(e.data.studioConnect ? `${PF[p]} connected` : `${PF[p]} not connected`); openSocial(); } };
    window.addEventListener("message", done);
  }

  // the developer's app keys for each platform, and the callback address to register with it
  function appKeys(cs) {
    const rows = ORDER.map((p) => {
      const x = cs.platforms[p];
      const id = el("input", { type: "text", value: x.client_id || "", placeholder: "App / client ID" });
      const sec = el("input", { type: "password", placeholder: x.app_keys ? "•••••• saved (type to replace)" : "App secret" });
      const save = el("button", { class: "small primary", onclick: async () => {
        const keys = { client_id: id.value }; if (sec.value) keys.client_secret = sec.value;
        const r = await post("/api/connect/app", { platform: p, keys }); if (r.error) return toast(r.error);
        sec.value = ""; sec.placeholder = "•••••• saved (type to replace)"; toast(`${PF[p]} app keys saved`); } }, "Save");
      return el("div", { class: "akrow" }, badge(p, "lg"), el("div", { class: "akw" }, el("b", {}, PF[p]),
        el("div", { class: "akcb" }, el("small", {}, "Callback address: "), el("code", {}, x.callback),
          el("button", { class: "icon tiny", title: "Copy", onclick: () => navigator.clipboard.writeText(x.callback).then(() => toast("Copied")) }, ic("copy")))), id, sec, save);
    });
    openModal(el("div", { class: "box akbox" }, el("h3", {}, "App keys (for the developer)"),
      el("p", { class: "muted" }, "Each platform's app ID and secret, from the app the default brand registers with that platform (see SOCIAL.md). Secrets go into the token store, never into files. Register each callback address with its platform."),
      cs.test_platform ? el("div", { class: "cdue" }, "The test platform is on: it needs no keys. Turn it off to use these.") : null,
      el("div", { class: "aklist" }, ...rows),
      el("div", { class: "btns", style: "justify-content:flex-end;margin-top:12px" }, el("button", { onclick: () => { closeModal(); openSocial(); } }, "Done"))));
  }

  // ---------------------------------------------------------------- the header button, due count and Open's badges
  function setDue(n) { const b = $("#calBtn .cbadge"); if (b) { b.textContent = n; b.hidden = !n; } }
  async function refreshSummary() {
    const r = await fetch("/api/calendar/summary").then((x) => x.json()).catch(() => null);
    if (!r) return;
    C.summary = r.videos; setDue(r.due);
    document.querySelectorAll("[data-plan-root]").forEach(fillBadge);
  }
  function fillBadge(e) {
    const v = C.summary && C.summary[e.dataset.planRoot];
    e.innerHTML = ""; e.hidden = !v;
    if (!v) return;
    e.append(...v.platforms.slice(0, 5).map((p) => badge(p, "xs")),
      v.due ? el("span", { class: "due" }, `${v.due} due`) : v.next ? el("span", {}, `Next ${short(v.next)}`) : el("span", {}, `Live on ${v.live}`));
  }
  window.plannerBadge = (root) => { const e = el("div", { class: "planb", "data-plan-root": root }); fillBadge(e); return e; };
  window.openCalendar = open;
  window.closeCalendar = close;
  window.refreshPlanner = () => { refreshSummary(); if ($("#calview") && !$("#calview").hidden) load().then(draw); };
  window.openSocialSettings = openSocial;

  const btn = el("button", { id: "calBtn", title: "Content calendar: scheduled and live posts", onclick: () => ($("#calview") && !$("#calview").hidden ? close() : open()) },
    ic("calendar"), "Calendar", el("span", { class: "cbadge", hidden: true }, "0"));
  const place = () => { const a = $("#brandsBtn"); if (a && !$("#calBtn")) a.after(btn); };
  place(); setTimeout(place, 500);
  refreshSummary(); setInterval(refreshSummary, 60000);
  // the link in notification emails: …/#calendar opens the calendar
  if (location.hash === "#calendar") setTimeout(() => { window.closeSplash?.(); open(); }, 900);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#calview") && !$("#calview").hidden && !document.activeElement?.matches("input, textarea, select")) close(); });
})();
