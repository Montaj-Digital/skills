// Results (ROADMAP phase 9.6): how your brand's posts do, from the numbers results.py pulls from each platform.
// Opened from the calendar's header (Results) or …/#results. Server side: results.py.
"use strict";
(function () {
  const R = { days: 30, platform: "", kind: "", data: null, busy: false };
  const PF = { instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube", facebook: "Facebook", linkedin: "LinkedIn", x: "X",
    threads: "Threads", pinterest: "Pinterest", google: "Google Business", bluesky: "Bluesky" };
  const COL = { instagram: "#3d24d6", tiktok: "#00c2c7", youtube: "#ff2d2d", facebook: "#0866ff", linkedin: "#5aa9e6", x: "#7c8591",
    threads: "#a3a3a3", pinterest: "#ff7a90", google: "#34a853", bluesky: "#1185fe" };
  const KINDS = ["Reels and Shorts", "Feed videos", "Landscape", "Long-form"];
  const badge = (id, cls = "") => el("span", { class: `pfb pf-${id} ${cls}` }, el("img", { src: `/app/platforms/${id}.svg`, alt: "" }));
  const n = (x) => (typeof x === "number" ? new Intl.NumberFormat("en-GB", { notation: x >= 100000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(x) : "–");
  const dur = (s) => { if (typeof s !== "number" || !s) return "–"; const t = Math.round(s / 60), h = Math.floor(t / 60), m = t % 60; return h ? `${n(h)} h ${m} min` : `${m} min`; };
  const day = (iso) => new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(iso + "T12:00:00Z"));
  const when = (iso) => new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: R.data?.tz || undefined }).format(new Date(iso));

  async function load() {
    const q = new URLSearchParams({ days: R.days, platform: R.platform, kind: R.kind });
    R.data = await fetch(`/api/results?${q}`).then((r) => r.json()).catch(() => null);
  }
  async function open() {
    let v = $("#resview");
    if (!v) { v = el("div", { id: "resview", class: "home bview" }); document.body.append(v); }
    v.hidden = false; v.innerHTML = "";
    v.append(el("div", { class: "home-in cwrap" }, el("p", { class: "muted" }, "Adding up the numbers…")));
    await load(); draw();
  }
  function close() { const v = $("#resview"); if (v) { v.hidden = true; v.innerHTML = ""; } }

  function draw() {
    const v = $("#resview"); if (!v || v.hidden) return;
    v.innerHTML = "";
    const d = R.data;
    const seg = (items, cur, set) => el("div", { class: "cseg" }, ...items.map(([k, l]) => el("button", { class: String(cur) === String(k) ? "on" : "", onclick: async () => { set(k); await load(); draw(); } }, l)));
    const chanSel = el("select", {}, el("option", { value: "" }, "Every channel"), ...Object.keys(PF).map((p) => el("option", { value: p, selected: R.platform === p }, PF[p])));
    chanSel.onchange = async () => { R.platform = chanSel.value; await load(); draw(); };
    const kindSel = el("select", {}, el("option", { value: "" }, "Every format"), ...KINDS.map((k) => el("option", { value: k, selected: R.kind === k }, k)));
    kindSel.onchange = async () => { R.kind = kindSel.value; await load(); draw(); };
    const refresh = el("button", { onclick: async () => {
      refresh.disabled = true; refresh.lastChild.textContent = "Updating…";
      const r = await fetch("/api/results/refresh", { method: "POST", body: "{}" }).then((x) => x.json()).catch(() => ({}));
      toast(r.error || `Updated ${r.pulled || 0} post${r.pulled === 1 ? "" : "s"}${r.errors?.length ? ` (${r.errors.length} couldn't be read)` : ""}`);
      await load(); draw(); } }, ic("refresh-cw"), el("span", {}, "Update now"));
    v.append(el("div", { class: "home-in cwrap rwrap" },
      el("div", { class: "chead" },
        el("h1", {}, "Your ", el("span", { class: "gt" }, "results")),
        seg([[7, "7 days"], [30, "30 days"], [90, "90 days"], [0, "All"]], R.days, (k) => { R.days = k; }),
        chanSel, kindSel, el("span", { class: "csp" }), refresh,
        el("button", { onclick: () => { close(); window.openCalendar?.(); } }, ic("calendar"), "Calendar"),
        el("button", { class: "icon", onclick: close, title: "Close", "aria-label": "Close" }, ic("x"))),
      !d ? el("p", { class: "muted" }, "Couldn't read the results.") : d.totals.posts === 0 ? empty() : body(d)));
  }

  function empty() {
    return el("div", { class: "pcard rempty" }, el("span", { class: "pspark" }, ic("chart-column")),
      el("h2", {}, "No posts in this range yet"),
      el("p", { class: "muted" }, "Once your brand's videos go live through Studio AI, their views, likes, comments, shares and watch time are pulled from each platform: an hour after posting, again at 6 and 24 hours, then daily for a month and weekly to three months."),
      el("p", { class: "muted" }, "Posts marked as posted by hand have no numbers: the platform can't tell us which post is ours."));
  }

  function body(d) {
    const t = d.totals;
    const cards = [["Views", n(t.views)], ["Likes", n(t.likes)], ["Comments", n(t.comments)], ["Shares", n(t.shares)], ["Watch time", dur(t.watch_time_s)],
      ["Engagement", t.engagement == null ? "–" : `${t.engagement}%`, "likes, comments and shares per view"], ["Posts", n(t.posts), t.measured < t.posts ? `${t.measured} with numbers` : "all with numbers"]];
    return el("div", { class: "rbody" },
      el("div", { class: "rtot" }, ...cards.map(([l, val, sub]) => el("div", { class: "pcard" }, el("span", {}, l), el("b", {}, val), sub ? el("small", {}, sub) : null))),
      el("div", { class: "rgrid" },
        el("div", { class: "pcard rchart" }, el("div", { class: "plab" }, "Views gained each day"), chart(d.timeline)),
        best(d.best)),
      el("div", { class: "rgrid r3" }, channels(d.channels), works(d.works), top(d.top)),
      posts(d.posts));
  }

  // stacked bars: views gained per day, coloured by channel
  function chart(rows) {
    const plats = [...new Set(rows.flatMap((r) => Object.keys(r).filter((k) => k !== "day")))];
    const tot = rows.map((r) => plats.reduce((s, p) => s + (r[p] || 0), 0));
    const max = Math.max(1, ...tot);
    const W = 900, H = 220, L = 46, B = 24, bw = (W - L) / rows.length;
    const NS = "http://www.w3.org/2000/svg";
    const mk = (tag, a) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); return e; };
    const svgEl = document.createElementNS(NS, "svg"); svgEl.setAttribute("viewBox", `0 0 ${W} ${H}`); svgEl.setAttribute("class", "rsvg");
    for (let i = 0; i <= 4; i++) {
      const y = (H - B) - (H - B - 10) * i / 4;
      svgEl.append(mk("line", { x1: L, x2: W, y1: y, y2: y, class: "rgl" }));
      const tx = mk("text", { x: L - 6, y: y + 4, class: "rax", "text-anchor": "end" }); tx.textContent = n(Math.round(max * i / 4)); svgEl.append(tx);
    }
    rows.forEach((r, i) => {
      let y = H - B;
      const x = L + i * bw + bw * 0.15, w = Math.max(1, bw * 0.7);
      for (const p of plats) {
        const v = r[p] || 0; if (!v) continue;
        const h = (H - B - 10) * v / max; y -= h;
        const rect = mk("rect", { x, y, width: w, height: Math.max(0.5, h), fill: COL[p] || "#888", rx: Math.min(3, w / 3) });
        const ti = document.createElementNS(NS, "title"); ti.textContent = `${day(r.day)} · ${PF[p] || p}: ${n(v)} views`; rect.append(ti);
        svgEl.append(rect);
      }
      const every = Math.ceil(rows.length / 10);
      if (i % every === 0) { const tx = mk("text", { x: x + w / 2, y: H - 6, class: "rax", "text-anchor": "middle" }); tx.textContent = day(r.day); svgEl.append(tx); }
    });
    const legend = el("div", { class: "rleg" }, ...plats.map((p) => el("span", {}, el("i", { style: `background:${COL[p] || "#888"}` }), PF[p] || p)));
    return el("div", {}, plats.length ? svgEl : el("p", { class: "muted" }, "No views counted in this range yet."), legend);
  }

  // per channel: the slots whose posts did best in their first day, and a button to make one a usual time
  function best(b) {
    const box = el("div", { class: "pcard rbest" }, el("div", { class: "plab" }, ic("clock"), " Best times to post"),
      el("small", { class: "muted" }, "From each post's views in its first 24 hours, by weekday and hour (team's time zone). Uses every post, not just this range."));
    const plats = Object.keys(b || {}).sort();
    if (!plats.length) box.append(el("p", { class: "muted" }, "Needs posts that are at least a day old."));
    for (const p of plats) {
      const x = b[p];
      const row = el("div", { class: "rbrow" }, badge(p), el("b", {}, PF[p]));
      if (!x.slots.length) row.append(el("span", { class: "muted" }, `${x.posts} of ${x.need} posts needed to say`));
      else row.append(el("div", { class: "rslots" }, ...x.slots.map((s, i) => el("span", { class: `rslot${i === 0 ? " best" : ""}`, title: `${s.posts} post${s.posts === 1 ? "" : "s"}, ${n(s.avg_views)} views on average in the first day` },
        s.slot, el("small", { class: s.vs_average < 0 ? "neg" : "" }, s.vs_average > 0 ? `+${s.vs_average}%` : `${s.vs_average}%`),
        el("button", { class: "icon tiny", title: `Add ${s.slot} to ${PF[p]}'s usual times`, onclick: () => addTime(p, s.slot) }, ic("plus"))))));
      box.append(row);
    }
    return box;
  }
  async function addTime(p, slot) {
    const r = await fetch("/api/social").then((x) => x.json());
    const s = r.settings, c = s.channels[p];
    if (c.times.includes(slot)) return toast(`${slot} is already one of ${PF[p]}'s usual times`);
    c.times.push(slot);
    const x = await fetch("/api/social", { method: "POST", body: JSON.stringify({ settings: s }) }).then((y) => y.json());
    toast(x.error || `${slot} added to ${PF[p]}'s usual times`);
  }

  function channels(rows) {
    return el("div", { class: "pcard" }, el("div", { class: "plab" }, "Each channel"),
      el("table", { class: "rtab" }, el("tr", {}, el("th", {}, ""), el("th", {}, "Posts"), el("th", {}, "Views"), el("th", {}, "Per post"), el("th", {}, "Engagement")),
        ...rows.map((c) => el("tr", {}, el("td", {}, badge(c.platform, "sm"), " ", PF[c.platform]), el("td", {}, String(c.posts)), el("td", {}, n(c.views)),
          el("td", {}, n(c.avg_views)), el("td", {}, c.engagement == null ? "–" : `${c.engagement}%`)))));
  }

  function works(w) {
    const bars = (rows) => { const m = Math.max(1, ...rows.map((r) => r.avg_views));
      return rows.length ? rows.map((r) => el("div", { class: "rbar" }, el("span", {}, r.label), el("i", { style: `--w:${Math.max(2, 100 * r.avg_views / m)}%` }),
        el("b", {}, n(r.avg_views)), el("small", {}, `${r.posts} post${r.posts === 1 ? "" : "s"}`))) : [el("p", { class: "muted" }, "Not enough numbers yet.")]; };
    return el("div", { class: "pcard" }, el("div", { class: "plab" }, "What works (views per post)"),
      el("div", { class: "rsub" }, "By format"), ...bars(w.format), el("div", { class: "rsub" }, "By length"), ...bars(w.length));
  }

  function top(rows) {
    return el("div", { class: "pcard" }, el("div", { class: "plab" }, ic("trending-up"), " Top videos"),
      ...rows.slice(0, 6).map((v, i) => el("div", { class: "rtop" }, el("em", {}, String(i + 1)),
        v.cover ? el("img", { class: v.fmt === "reel" ? "" : "w", src: `/calendar/cover/${v.cover}.jpg`, alt: "" }) : el("span", { class: "rnocov" }),
        el("div", {}, el("b", {}, v.name), el("div", { class: "rpl" }, ...v.platforms.map((p) => badge(p, "xs")))),
        el("div", { class: "rv" }, el("b", {}, n(v.views)), el("small", {}, "views")))));
  }

  function posts(rows) {
    return el("div", { class: "pcard" }, el("div", { class: "plab" }, "Every post"),
      el("table", { class: "rtab rposts" },
        el("tr", {}, el("th", {}, "Posted"), el("th", {}, "Video"), el("th", {}, ""), el("th", {}, "Views"), el("th", {}, "Likes"), el("th", {}, "Comments"),
          el("th", {}, "Shares"), el("th", {}, "Watch time"), el("th", {}, "")),
        ...rows.map((r) => el("tr", {}, el("td", {}, when(r.posted_at)), el("td", {}, r.video.name), el("td", {}, badge(r.platform, "sm")),
          ...["views", "likes", "comments", "shares"].map((k) => el("td", {}, r.numbers ? n(r.numbers[k]) : "–")),
          el("td", {}, r.numbers ? dur(r.numbers.watch_time_s) : "–"),
          el("td", { class: "muted" }, r.status === "posted" ? "posted by hand" : r.error && !r.numbers ? el("span", { title: r.error }, "couldn't read") :
            r.link ? el("a", { href: r.link, target: "_blank", rel: "noopener" }, "See it") : "")))));
  }

  window.openResults = open;
  if (location.hash === "#results") setTimeout(() => { window.closeSplash?.(); open(); }, 900);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#resview") && !$("#resview").hidden && !document.activeElement?.matches("input, textarea, select")) close(); });
})();
