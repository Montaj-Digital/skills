// Post it (ROADMAP phase 9.1): a finished video's posts for each social platform, written by Claude in the brand's
// voice, with the cover frame and a post pack to download. Server side: 04. Editor/planner.py.
// Opens from **Posts** in the header (for the open short-form or long-form video) and **Prepare posts** after a render.
// The design is 07. Concepts/Planner - Post it (concept).png. Scheduling (9.3) comes next and plugs into the right column.
"use strict";
(function () {
  const P = { st: null, pack: null, saveT: 0, busy: null };
  // the open video: short-form built in; while the long-form editor is open its window.LF_STUDIO carries the root
  const isLong = () => !!(window.LF_STUDIO && window.LF_STUDIO.root && $("#lfview") && !$("#lfview").hidden);
  const api = (p) => isLong() ? `/api/long/planner/${p}?root=${encodeURIComponent(window.LF_STUDIO.root)}` : `/api/planner/${p}`;
  const file = (p) => isLong() ? `/long/planner/${p}?root=${encodeURIComponent(window.LF_STUDIO.root)}` : `/planner/${p}`;
  const post = (u, b) => fetch(u, { method: "POST", body: JSON.stringify(b || {}) }).then(async (r) => ({ ok: r.ok, ...(await r.json().catch(() => ({}))) }));
  const FMT = { reel: "Reel 9:16", feed: "Feed 4:5", square: "Square 1:1", landscape: "Landscape 16:9", long: "Long-form 16:9" };
  const SUB = { instagram: "Reels", tiktok: "", youtube: "", facebook: "", linkedin: "", x: "", threads: "", pinterest: "", google: "", bluesky: "" };
  const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const v = () => $("#postview");

  function badge(id, cls = "") {
    return el("span", { class: `pfb pf-${id} ${cls}` }, el("img", { src: `/app/platforms/${id}.svg`, alt: "" }));
  }

  async function open() {
    if (!S.spec && !isLong()) { toast("Open a video first"); return; }
    let view = v();
    if (!view) { view = el("div", { id: "postview", class: "home bview" }); document.body.append(view); }
    view.hidden = false; view.innerHTML = ""; view.classList.toggle("over-long", isLong());
    view.append(el("div", { class: "empty", style: "padding:40px" }, "Loading…"));
    $("#postsBtn")?.classList.add("on");
    const st = await fetch(api("state")).then((r) => r.json()).catch((e) => ({ error: e.message }));
    if (st.error) { view.innerHTML = ""; view.append(el("div", { class: "empty", style: "padding:40px" }, st.error)); return; }
    P.st = st; P.pack = st.pack; P.cover = st.cover;
    draw();
  }
  function close() { if (v()) { v().hidden = true; v().innerHTML = ""; } $("#postsBtn")?.classList.remove("on"); }

  function draw() {
    const st = P.st, view = v(); view.innerHTML = "";
    const b = st.brand;
    const head = el("div", { class: "hh" },
      el("div", {}, el("h1", {}, "Post ", el("span", { class: "gt" }, "it")),
        el("div", { class: "lib" }, `${st.name} · ${FMT[st.format] || st.format} · ${b.name}` +
          (b.client ? `. A client video: download the post pack for ${b.name}. Scheduling is for your brand's own channels.` : ""))),
      el("button", { class: "icon", onclick: close, title: "Close", "aria-label": "Close" }, ic("x")));
    view.append(el("div", { class: "home-in pwrap" }, head, el("div", { class: "pgrid" }, left(), middle(), right())));
  }

  // ---------------------------------------------------------------- the video and its cover
  function left() {
    const st = P.st, box = el("div", { class: "pcard pvid" });
    if (!st.video) {
      box.append(el("div", { class: "pnovid" }, ic("clapperboard"), el("b", {}, "Not rendered yet"),
        el("span", {}, "Claude can write the posts now. Render the video to add it to the post pack and choose its cover.")));
      return box;
    }
    const shape = st.format === "reel" ? "9 / 16" : st.format === "feed" ? "4 / 5" : st.format === "square" ? "1 / 1" : "16 / 9";
    const vid = el("video", { src: file("video"), controls: true, preload: "metadata", playsInline: true, style: `aspect-ratio:${shape}` });
    P.vid = vid;
    const cover = el("img", { class: "pcov", alt: "Cover", style: `aspect-ratio:${shape}`, src: P.cover ? file("cover.jpg") + (file("").includes("?") ? "&" : "?") + "v=" + Date.now() : "" });
    const strip = el("div", { class: "pstrip" });
    const use = el("button", { class: "small", onclick: () => setCover(vid.currentTime) }, ic("image"), "Use this frame");
    box.append(el("div", { class: "pplayer" }, vid, el("span", { class: "ptag" }, st.video.rendered ? "Rendered" : "Not rendered: the edit")),
      el("div", { class: "plab" }, "Cover"), el("div", { class: "pcovrow" }, P.cover ? cover : el("div", { class: "pcov empty", style: `aspect-ratio:${shape}` }, "None yet"), el("div", { class: "pcovtxt" },
        el("span", {}, "Pause on a good frame, then"), use, strip)),
      el("div", { class: "pmeta" }, `${FMT[st.format]} · ${mmss(st.video.dur)} · ${st.video.name}`));
    thumbs(strip, st.video.dur, shape);
    return box;
  }
  async function thumbs(strip, dur, shape) {
    // four candidate frames, taken in the browser from the video itself
    const tv = el("video", { src: file("video"), muted: true, preload: "auto", crossOrigin: "anonymous" });
    await new Promise((r) => { tv.onloadeddata = r; tv.onerror = r; });
    for (const f of [0.15, 0.35, 0.6, 0.85]) {
      const t = dur * f;
      await new Promise((r) => { tv.onseeked = r; tv.currentTime = t; setTimeout(r, 2500); });
      const c = document.createElement("canvas"), w = 120; c.width = w; c.height = Math.round(w * (tv.videoHeight / tv.videoWidth || 16 / 9));
      try { c.getContext("2d").drawImage(tv, 0, 0, c.width, c.height); } catch (e) { continue; }
      const img = el("img", { src: c.toDataURL("image/jpeg", 0.8), title: `Use the frame at ${mmss(t)}`, style: `aspect-ratio:${shape}`,
        onclick: () => { if (P.vid) P.vid.currentTime = t; setCover(t); } });
      strip.append(img);
    }
  }
  async function setCover(t) {
    const r = await post(api("cover"), { t });
    if (r.error) return toast(r.error);
    P.cover = true; P.pack.cover_t = r.t; draw(); toast(`Cover set at ${mmss(t)}`);
  }

  // ---------------------------------------------------------------- channels and posts
  function middle() {
    const st = P.st, pk = P.pack, box = el("div", { class: "pmid" });
    const on = new Set(pk.channels);
    box.append(el("div", { class: "prow" }, el("span", { class: "plab" }, `Where it goes · ${on.size} of ${st.order.length} channels`)));
    box.append(el("div", { class: "pchips" }, ...st.order.map((id) => el("button", {
      class: `pchip${on.has(id) ? " on" : ""}`, onclick: () => { on.has(id) ? on.delete(id) : on.add(id); pk.channels = st.order.filter((x) => on.has(x)); changed(); draw(); } },
      badge(id), `${st.platforms[id].name}${SUB[id] ? " " + SUB[id] : ""}`, el("span", { class: "ptg" })))));
    const note = el("input", { type: "text", class: "pnote", placeholder: 'Anything Claude should know? e.g. "mention the workshop on 30 October"', value: pk.note || "" });
    note.oninput = () => { pk.note = note.value; changed(); };
    const write = el("button", { class: "primary", onclick: () => draft(null, write) }, ic("sparkles"), P.busy === "all" ? "Claude is writing…" : "Write with Claude");
    write.disabled = !!P.busy || !pk.channels.length;
    box.append(el("div", { class: "pcard pclaude" }, el("span", { class: "pspark" }, ic("sparkles")), note, write));
    const list = el("div", { class: "pposts" });
    pk.channels.forEach((id) => list.append(card(id)));
    if (!pk.channels.length) list.append(el("div", { class: "pempty" }, "Choose where this video goes."));
    box.append(list);
    return box;
  }

  function card(id) {
    const st = P.st, pk = P.pack, spec = st.platforms[id], p = (pk.posts[id] = pk.posts[id] || {});
    const has = spec.fields.some((f) => (Array.isArray(p[f.key]) ? p[f.key].length : p[f.key]));
    const rew = el("button", { class: "small", onclick: () => draft(id, rew), disabled: !!P.busy }, P.busy === id ? "Writing…" : has ? "Rewrite" : "Write");
    const copyAll = el("button", { class: "small", onclick: () => copy(spec.fields.map((f) => fieldText(p[f.key], f)).filter(Boolean).join("\n\n"), spec.name) }, ic("copy"), "Copy");
    const c = el("div", { class: "pcard ppost" },
      el("div", { class: "pph" }, badge(id, "lg"), el("div", {}, el("b", {}, `${spec.name}${SUB[id] ? " " + SUB[id] : ""}`), el("small", {}, has ? `in ${st.brand.name}'s voice` : "not written yet")),
        el("span", { class: "pacts" }, rew, copyAll)));
    spec.fields.forEach((f) => c.append(field(p, f)));
    return c;
  }
  const fieldText = (val, f) => (Array.isArray(val) ? val.join(f.key === "hashtags" ? " " : ", ") : val || "");

  function field(p, f) {
    const count = el("span", { class: "pcount" });
    const show = () => {
      const n = f.tags ? (p[f.key] || []).length : (p[f.key] || "").length;
      count.textContent = `${n.toLocaleString()} / ${f.limit.toLocaleString()}`;
      count.classList.toggle("over", n > f.limit);
    };
    let input;
    if (f.tags) {
      input = el("input", { type: "text", class: "ptags", value: fieldText(p[f.key], f), placeholder: f.key === "hashtags" ? "#one #two" : "one, two" });
      input.oninput = () => { p[f.key] = input.value.split(f.key === "hashtags" ? /[\s,]+/ : /,/).map((t) => t.trim()).filter(Boolean)
        .map((t) => (f.key === "hashtags" ? "#" + t.replace(/^#+/, "") : t)); show(); changed(); };
    } else if (f.limit <= 120 || f.key === "button") {
      input = el("input", { type: "text", value: p[f.key] || "" });
      input.oninput = () => { p[f.key] = input.value; show(); changed(); };
    } else {
      input = el("textarea", { rows: 3 }); input.value = p[f.key] || "";
      const fit = () => { input.style.height = "auto"; input.style.height = Math.min(260, input.scrollHeight + 2) + "px"; };
      input.oninput = () => { p[f.key] = input.value; show(); fit(); changed(); };
      requestAnimationFrame(fit);
    }
    show();
    return el("div", { class: "pfield" }, el("div", { class: "pfl" }, el("span", {}, f.label), count,
      el("button", { class: "icon tiny", title: `Copy the ${f.label.toLowerCase()}`, onclick: () => copy(fieldText(p[f.key], f), f.label) }, ic("copy"))), input);
  }

  async function copy(text, what) {
    try { await navigator.clipboard.writeText(text || ""); toast(`${what} copied`); }
    catch (e) { toast("Couldn't copy (the browser blocked it)"); }
  }

  async function draft(only, btn) {
    if (P.busy) return;
    P.busy = only || "all"; draw();
    const r = await post(api("draft"), { channels: P.pack.channels, note: P.pack.note, only });
    P.busy = null;
    if (r.error || !r.pack) { draw(); return toast(r.error || "Claude couldn't write the posts"); }
    P.pack = r.pack; draw();
    toast(only ? `${P.st.platforms[only].name} rewritten` : `${P.pack.channels.length} posts written`);
  }

  function changed() {
    clearTimeout(P.saveT);
    const s = $("#pstatus"); if (s) s.textContent = "Saving…";
    P.saveT = setTimeout(async () => {
      const r = await post(api("save"), { pack: P.pack });
      const s2 = $("#pstatus"); if (s2) s2.textContent = r.error ? "Not saved" : "Saved";
    }, 700);
  }

  // ---------------------------------------------------------------- the right column: when (9.3), the pack
  const tzParts = (iso) => Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: P.st.tz || "UTC", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  const localInput = (iso) => { const p = tzParts(iso); return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`; };
  const niceLocal = (v) => new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(v + ":00Z"));
  const niceIso = (iso) => niceLocal(localInput(iso));
  const written = (id) => { const p = P.pack.posts[id]; return p && Object.values(p).some((x) => (Array.isArray(x) ? x.length : x)); };

  function right() {
    const st = P.st, pk = P.pack, box = el("div", { class: "pside" });
    const ready = pk.channels.filter(written);
    if (st.brand.client) {
      box.append(el("div", { class: "pcard" }, el("div", { class: "plab" }, "When"),
        el("div", { class: "psoon" }, `${st.brand.name} publishes their own posts: hand them the post pack. The calendar is for your brand's own channels.`)));
    } else if (!st.video || !st.video.rendered) {
      box.append(el("div", { class: "pcard" }, el("div", { class: "plab" }, "When"),
        el("div", { class: "psoon" }, "Render the video first: scheduled posts use the finished MP4. You can write the posts and download the pack now.")));
    } else {
      P.times = P.times || {};
      ready.forEach((id) => { if (!P.times[id]) P.times[id] = localInput(st.suggest[id]); });
      const rows = ready.map((id) => {
        const inp = el("input", { type: "datetime-local", value: P.times[id] });
        inp.onchange = () => { if (P.same) ready.forEach((x) => (P.times[x] = inp.value)); else P.times[id] = inp.value; draw(); };
        const suggested = P.times[id] === localInput(st.suggest[id]);
        return el("div", { class: "pwhen" }, badge(id), el("div", { class: "pww" }, el("b", {}, st.platforms[id].name), el("small", { class: suggested ? "ok" : "" }, suggested ? "Suggested: a usual slot" : "Your time")), inp);
      });
      const same = el("button", { class: `psame${P.same ? " on" : ""}`, onclick: () => { P.same = !P.same; if (P.same && ready.length) ready.forEach((x) => (P.times[x] = P.times[ready[0]])); draw(); } },
        el("span", { class: "ptg" }), el("span", {}, "Same time everywhere", el("small", {}, "or a time per channel")));
      box.append(el("div", { class: "pcard" }, el("div", { class: "plab" }, "When"), same, ...rows,
        ready.length ? null : el("div", { class: "psoon" }, "Write the posts first, then choose when each goes out."),
        el("div", { class: "ptz" }, `Times in ${st.tz}`, " · ", el("a", { href: "#", onclick: (e) => { e.preventDefault(); window.openSocialSettings?.(); } }, "usual times"))));
    }
    const sched = (st.scheduled || []);
    if (sched.length) box.append(el("div", { class: "pcard" }, el("div", { class: "plab" }, "Already scheduled"),
      ...sched.map((p) => el("div", { class: "pwhen" }, badge(p.platform), el("div", { class: "pww" }, el("b", {}, st.platforms[p.platform].name),
        el("small", {}, niceIso(p.when))), el("span", { class: `cst ${({ live: "live", posted: "live", due: "due", failed: "fail", posting: "posting" })[p.status] || "sched"}` }, p.status))),
      el("button", { class: "small", style: "margin-top:6px", onclick: () => { close(); window.openCalendar?.(); } }, ic("calendar"), "Open the calendar")));
    const times = ready.map((id) => P.times?.[id]).filter(Boolean).sort();
    const can = !st.brand.client && st.video && st.video.rendered && ready.length;
    box.append(el("div", { class: "psum" }, can
      ? [el("b", {}, `${ready.length} post${ready.length === 1 ? "" : "s"}`), " from one video. ", times.length ? `The first goes out ${niceLocal(times[0])}${times.length > 1 && times.at(-1) !== times[0] ? `, the last ${niceLocal(times.at(-1))}` : ""}.` : ""]
      : [el("b", {}, `${ready.length} post${ready.length === 1 ? "" : "s"}`), ` written for ${pk.channels.length} channel${pk.channels.length === 1 ? "" : "s"}.`]));
    if (can) box.append(el("button", { class: "primary pbig", onclick: schedule, disabled: !!P.busy }, ic("send"), `Schedule ${ready.length} post${ready.length === 1 ? "" : "s"}`));
    box.append(el("div", { class: "pbtns" },
      el("a", { class: `btn${can ? "" : " primary"} pbig2`, href: api("download"), download: "" }, ic("download"), "Post pack"),
      !st.brand.client && window.openCalendar ? el("button", { onclick: () => { close(); window.openCalendar(); } }, ic("calendar"), "Calendar") : null));
    box.append(el("div", { class: "pstat" }, el("span", { id: "pstatus" }, "Saved"), " · edits save on their own"));
    return box;
  }

  async function schedule() {
    const ready = P.pack.channels.filter(written);
    if (P.saveT) { clearTimeout(P.saveT); await post(api("save"), { pack: P.pack }); }
    const r = await post(api("schedule"), { items: ready.map((id) => ({ platform: id, when: P.times[id] })) });
    if (r.error) return toast(r.error);
    toast(`${r.posts.length} post${r.posts.length === 1 ? "" : "s"} scheduled`);
    P.times = {};
    const st = await fetch(api("state")).then((x) => x.json()); P.st = st; P.pack = st.pack; draw();
    window.refreshPlanner?.();
  }

  window.openPosts = open;
  // header button (works for the open short-form or long-form video)
  const btn = el("button", { id: "postsBtn", title: "Post it: posts for each social platform, written by Claude", onclick: () => (v() && !v().hidden ? close() : open()) }, ic("send"), "Posts");
  const place = () => { const a = $("#aiBtn") || $("#brandsBtn"); if (a && !$("#postsBtn")) a.after(btn); };
  place(); setTimeout(place, 500);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && v() && !v().hidden && !document.activeElement?.matches("input, textarea")) close(); });
})();
