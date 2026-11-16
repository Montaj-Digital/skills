// AI studio panel (ROADMAP phase 6): a media bin, a prompt, and the clip Claude builds from the videos.
// Server side: 04. Editor/studio.py. Opens from the "AI studio" button in the header, over the left of the editor.
"use strict";
(function () {
  const A = { open: false, st: null, show: null, timer: 0, uploads: [], pick: null };
  const $p = () => $("#aipanel");
  const fmtS = (s) => (s == null ? "?" : s < 60 ? `${(+s).toFixed(1)} s` : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);
  const FMT_LABEL = { reel: "Reel 9:16", feed: "Feed 4:5", square: "Square 1:1", landscape: "Landscape 16:9" };
  const post = (u, b) => fetch(u, { method: "POST", body: JSON.stringify(b || {}) }).then((r) => r.json());
  // The editor the panel works for. Short-form is built in; the long-form editor registers window.LF_STUDIO while it's
  // open: {kind, api(path), file(path), pickMedia: true, overlay(clipResponse), insert: null}.
  const SHORT = { kind: "short", api: (p) => `/api/studio/${p}`, file: (p) => `/studio/${p}`, pickMedia: false };
  const H = () => (window.LF_STUDIO && $("#lfview") && !$("#lfview").hidden ? window.LF_STUDIO : SHORT);

  function toggle(force) {
    A.open = force ?? !A.open;
    let p = $p();
    if (!p) { p = el("aside", { id: "aipanel", class: "aipanel" }); document.body.append(p); }
    p.hidden = !A.open;
    $("#aiBtn")?.classList.toggle("on", A.open);
    if (A.open) refresh(); else clearTimeout(A.timer);
  }

  async function refresh() {
    clearTimeout(A.timer);
    if (!A.open) return;
    const st = await fetch(H().api("state")).then((r) => r.json()).catch((e) => ({ error: e.message }));
    A.st = st;
    if (!A.show && st.clips?.length) A.show = st.clips[0].id;
    draw();
    const busy = st.media?.some((m) => m.state === "running") || st.clips?.some((c) => c.state === "running") || A.uploads.length;
    if (busy) A.timer = setTimeout(refresh, 2000);
  }

  // ---------------------------------------------------------------- drawing
  function draw() {
    const p = $p(); if (!p) return;
    const st = A.st || {};
    const keepPrompt = p.querySelector("#aiPrompt")?.value, keepChange = p.querySelector("#aiChange")?.value;
    p.innerHTML = "";
    p.append(el("div", { class: "ai-head" },
      el("div", {}, el("h2", {}, "AI ", el("span", { class: "gt" }, "studio")),
        el("small", {}, st.error ? st.error : `Clips in the ${st.brand_name || "Your brand"} look · ${FMT_LABEL[st.format] || st.format || ""}`)),
      el("button", { class: "icon ghost", title: "Close", "aria-label": "Close", onclick: () => toggle(false) }, ic("x"))));
    if (st.error) return;
    p.append(binSection(st), askSection(st, keepPrompt), resultSection(st, keepChange));
  }

  function binSection(st) {
    const files = el("input", { type: "file", multiple: true, accept: "video/*,.mov,.mp4,.m4v", hidden: true, onchange: (e) => upload([...e.target.files]) });
    const list = el("div", { class: "ai-bin" });
    const sel = A.pick || new Set((st.media || []).map((m) => m.id));
    (st.media || []).forEach((m) => {
      const ready = m.state === "done";
      list.append(el("div", { class: `ai-m${ready ? "" : " busy"}` },
        el("label", { class: "ai-chk", title: "Use this video in the next clip" },
          el("input", { type: "checkbox", checked: sel.has(m.id), disabled: !ready, onchange: (e) => { A.pick = new Set(sel); e.target.checked ? A.pick.add(m.id) : A.pick.delete(m.id); } })),
        el("div", { class: "ai-th", style: ready ? `background-image:url("${H().file(`media/${m.id}/thumb.jpg`)}")` : "" }, ready ? null : el("span", { class: "spin" })),
        el("div", { class: "ai-mt" }, el("b", {}, m.name),
          el("small", {}, m.state === "failed" ? (m.error || "Couldn't analyse it") : ready ? `${fmtS(m.dur)} · ${m.audio ? `${m.words} words` : "no sound"}` : m.step || "Analysing…")),
        el("button", { class: "icon ghost small", title: "Remove from the bin", onclick: async () => { await post(H().api("media/delete"), { id: m.id }); refresh(); } }, ic("x"))));
    });
    A.uploads.forEach((u) => list.append(el("div", { class: "ai-m busy" }, el("span", {}), el("div", { class: "ai-th" }, el("span", { class: "spin" })),
      el("div", { class: "ai-mt" }, el("b", {}, u.name), el("small", {}, `Uploading ${u.pct}%`)))));
    if (!list.childElementCount) list.append(el("div", { class: "ai-empty" }, "Add the videos to build from: inserts, testimonials, B-roll, other takes. Each one is transcribed once."));
    return el("section", { class: "ai-sec" }, el("div", { class: "ai-sh" }, el("h3", {}, "Media bin"),
      el("button", { class: "small", title: H().pickMedia ? "Pick videos in Finder: they're linked where they are, not copied" : "Upload videos into this project",
      onclick: () => (H().pickMedia ? pickMedia() : files.click()) }, ic("plus"), "Add videos"), files), list);
  }

  function askSection(st, keep) {
    const prompt = el("textarea", { id: "aiPrompt", rows: 3, placeholder: "e.g. Use these videos to make a trailer-like clip, end on the testimonial" });
    prompt.value = keep ?? A.lastPrompt ?? "";
    const len = el("input", { type: "number", min: 5, max: 180, step: 1, value: A.lastLen || 20, class: "ai-len" });
    const titles = el("input", { type: "checkbox", checked: A.titles ?? true, onchange: (e) => (A.titles = e.target.checked) });
    const music = el("select", { onchange: (e) => { if (e.target.value === "__up") { e.target.value = A.music || ""; mup.click(); } else A.music = e.target.value; } },
      el("option", { value: "" }, "No music"), ...(st.music || []).map((n) => el("option", { value: n, selected: A.music === n }, n.replace(/\.[^.]+$/, ""))),
      el("option", { value: "__up" }, "Upload music…"));
    const mup = el("input", { type: "file", accept: "audio/*,.mp3,.m4a,.wav,.aac,.aiff,.flac", hidden: true, onchange: (e) => uploadMusic(e.target.files[0]) });
    const ready = (st.media || []).filter((m) => m.state === "done");
    const go = el("button", { class: "primary", disabled: !ready.length, onclick: () => ask({ prompt: prompt.value, length: +len.value }) }, ic("sparkles"), "Make the clip");
    return el("section", { class: "ai-sec" }, el("h3", {}, "Ask"), prompt,
      el("div", { class: "ai-opts" },
        el("label", {}, "Length", len, "s"),
        el("label", { class: "tool" }, titles, "Title cards"),
        el("label", {}, ic("music"), music, mup)),
      el("div", { class: "ai-go" }, go, !ready.length ? el("small", {}, "Add a video first") : el("small", {}, `Claude uses ${(A.pick ? [...A.pick].filter((i) => ready.some((m) => m.id === i)).length : ready.length)} of ${ready.length} videos`)));
  }

  function resultSection(st, keepChange) {
    const sec = el("section", { class: "ai-sec" }, el("h3", {}, "Clip"));
    const clips = st.clips || [];
    const c = clips.find((x) => x.id === A.show) || clips[0];
    if (!c) { sec.append(el("div", { class: "ai-empty" }, "Your clip appears here, with what Claude made and why.")); return sec; }
    if (c.state === "running") {
      sec.append(el("div", { class: "ai-run" }, el("span", { class: "spin" }), el("b", {}, c.step || "Working…"),
        el("small", {}, `“${(c.req?.prompt || "").slice(0, 90)}”`)));
    } else if (c.state === "failed") {
      sec.append(el("div", { class: "err" }, c.error || "It stopped"));
    } else {
      const p = c.plan || {};
      const v = el("video", { class: "ai-video", controls: true, playsInline: true, src: H().file(`clips/${c.id}/clip.mp4`) + `${H().kind === "long" ? "&" : "?"}v=${c.created}` });
      const names = Object.fromEntries((st.media || []).map((m) => [m.id, m.name]));
      const change = el("input", { id: "aiChange", type: "text", placeholder: "Change it: e.g. faster, end on the testimonial" });
      change.value = keepChange || "";
      sec.append(el("div", { class: `ai-clip ${st.format}` }, v),
        el("div", { class: "ai-ct" }, el("b", {}, p.title || "AI clip"), el("small", {}, `${fmtS(c.dur)} · ${p.parts?.length || 0} parts${p.titles?.length ? ` · ${p.titles.length} title cards` : ""}${c.req?.music ? " · music" : ""}`)),
        p.summary ? el("p", { class: "ai-sum" }, p.summary) : null,
        el("details", { class: "ai-parts" }, el("summary", {}, "The cut list"),
          el("ol", {}, ...(p.parts || []).map((x) => el("li", {}, el("b", {}, names[x.video] || x.video), ` ${x.in.toFixed(1)}–${x.out.toFixed(1)} s`, x.why ? el("small", {}, x.why) : null)))),
        el("div", { class: "ai-acts" },
          el("button", { class: "primary", title: "Lay it over the video at the playhead (its sound plays, the speaker drops out)", onclick: () => (H().overlay ? H().overlay(c) : asOverlay(c)) }, ic("list-video"), "Add at playhead"),
          H().kind === "short" || H().insert ? el("button", { title: "Put it into the video at the playhead: the video pauses while the clip plays, and everything after moves later", onclick: () => (H().insert ? H().insert(c) : insert(c)) }, ic("scissors"), "Insert at playhead") : null,
          el("button", { onclick: () => ask({ ...c.req, base: null }) }, ic("sparkles"), "Make another"),
          el("a", { class: "button", href: H().file(`clips/${c.id}/clip.mp4`), download: `${p.title || "AI clip"}.mp4` }, "Download")),
        el("div", { class: "ai-change" }, change, el("button", { onclick: () => change.value.trim() && ask({ ...c.req, prompt: change.value.trim(), base: c.id }) }, "Change it")));
    }
    if (clips.length > 1) {
      sec.append(el("div", { class: "ai-hist" }, el("small", {}, "Earlier clips"), el("div", {}, ...clips.map((x) => el("button", {
        class: `ai-hc${x.id === c.id ? " on" : ""}`, title: x.plan?.title || x.req?.prompt || "", onclick: () => { A.show = x.id; draw(); },
        style: x.state === "done" ? `background-image:url("${H().file(`clips/${x.id}/thumb.jpg`)}${H().kind === "long" ? "&" : "?"}v=${x.created}")` : "" }, x.state === "running" ? el("span", { class: "spin" }) : x.state === "failed" ? "!" : null)))));
      sec.append(el("button", { class: "small ghost ai-del", onclick: async () => { if (!confirm("Delete this clip?")) return; await post(H().api("clip/delete"), { id: c.id }); A.show = null; refresh(); } }, ic("trash-2"), "Delete this clip"));
    }
    return sec;
  }

  // ---------------------------------------------------------------- actions
  async function upload(files) {
    for (const f of files) {
      const u = { name: f.name.replace(/\.[^.]+$/, ""), pct: 0 }; A.uploads.push(u); draw();
      if (window.PORTAL) {                 // resumable, and works for long-form projects too
        try {
          const upload = await uploadFile(f, (p) => { const n = Math.round(p * 100); if (n !== u.pct) { u.pct = n; draw(); } });
          const r = await post(H().api("media/add"), { upload, name: f.name });
          if (r.error) toast(r.error);
        } catch (e) { toast(e.message); }
        A.uploads.splice(A.uploads.indexOf(u), 1);
        continue;
      }
      await new Promise((ok) => {
        const x = new XMLHttpRequest();
        x.open("PUT", `/api/studio/media?name=${encodeURIComponent(f.name)}`);
        x.upload.onprogress = (e) => { if (e.lengthComputable) { u.pct = Math.round((e.loaded / e.total) * 100); draw(); } };
        x.onload = () => { const r = JSON.parse(x.responseText || "{}"); if (r.error) toast(r.error); ok(); };
        x.onerror = () => { toast("The upload failed"); ok(); };
        x.send(f);
      });
      A.uploads.splice(A.uploads.indexOf(u), 1);
    }
    refresh();
  }
  async function pickMedia() {
    toast("Choose videos in the Finder window…");
    const r = await post(H().api("media/pick"), {});
    if (r.error) return toast(r.error);
    if (r.ids?.length) toast(`${r.ids.length} video${r.ids.length === 1 ? "" : "s"} linked; analysing…`);
    refresh();
  }
  async function uploadMusic(f) {
    if (!f) return;
    toast(`Adding ${f.name} to 05. Music…`);
    const r = await fetch(`/api/studio/music?name=${encodeURIComponent(f.name)}`, { method: "PUT", body: f }).then((x) => x.json());
    if (r.error) return toast(r.error);
    A.music = r.name; refresh();
  }
  async function ask(req) {
    if (!(req.prompt || "").trim()) return toast("Say what to make");
    A.lastPrompt = req.base ? A.lastPrompt : req.prompt; A.lastLen = req.length;
    const body = { prompt: req.prompt, length: req.length || 20, titles: A.titles ?? true, music: A.music || null, base: req.base || null,
      media: A.pick ? [...A.pick] : null };
    const r = await post(H().api("ask"), body);
    if (r.error) return toast(r.error);
    A.show = r.id; refresh();
  }
  // ---------------------------------------------------------------- where an insert can go
  // Everything on screen as [start, end] on the edited timeline: cards (incl. text and chips), takeovers, effects,
  // overlays and blurs. Sounds are instants, so they never span.
  function items() {
    const out = [];
    (S.spec.cards || []).forEach((c) => { const [a, b] = span(c); out.push({ a, b, what: `“${label(c) || c.type}”` }); });
    (S.spec.takeovers || []).forEach((c) => { const [a, b] = span(c); out.push({ a, b, what: `the takeover “${label(c) || "…"}”` }); });
    (S.spec.fx || []).forEach((f) => { const [a, b] = fxSpan(f); out.push({ a, b, what: `a ${f.kind} effect` }); });
    (S.spec.overlays || []).forEach((o) => out.push({ a: o.t, b: o.t + o.dur, what: `the overlay “${o.name || "video"}”` }));
    (S.spec.redactions || []).forEach((r) => out.push({ a: r.t, b: r.t + (r.dur || 3), what: "a blur" }));
    return out.filter((x) => x.b > x.a);
  }
  // the nearest moment between two words (so the insert never splits a word); dir -1 = at or before, +1 = at or after
  function wordGap(t, dir) {
    const W = S.words || [];
    const gaps = [0];
    for (let i = 0; i + 1 < W.length; i++) if (W[i + 1].start > W[i].end - 1e-3) gaps.push((W[i].end + W[i + 1].start) / 2);
    gaps.push(S.dur);
    const ok = gaps.filter((g) => (dir < 0 ? g <= t + 1e-3 : dir > 0 ? g >= t - 1e-3 : true));
    if (!ok.length) return t;
    return ok.reduce((best, g) => (Math.abs(g - t) < Math.abs(best - t) ? g : best));
  }
  // the items an insert at T would stretch across, and the clean spots just before and after them
  function insertPlan(T) {
    const all = items();
    const across = all.filter((x) => x.a < T - 0.05 && x.b > T + 0.05);
    if (!across.length) return { T: r2(wordGap(T, 0)), across };
    let A = Math.min(...across.map((x) => x.a)), B = Math.max(...across.map((x) => x.b));
    for (let grew = true; grew;) {                    // anything overlapping the block widens it
      grew = false;
      for (const x of all) if (x.a < B - 0.05 && x.b > A + 0.05 && (x.a < A - 1e-3 || x.b > B + 1e-3)) { A = Math.min(A, x.a); B = Math.max(B, x.b); grew = true; }
    }
    const before = r2(wordGap(A, -1)), after = r2(wordGap(B + 0.05, 1));
    return { T, across, before: before > 0.05 || A < 0.05 ? before : null, after: after < S.dur - 0.1 ? after : null };
  }
  function chooseSpot(c, plan) {
    return new Promise((res) => {
      const done = (v) => { closeModal(); res(v); };
      const names = plan.across.map((x) => x.what);
      const what = names.length > 2 ? `${names.slice(0, 2).join(", ")} and ${names.length - 2} more` : names.join(" and ");
      const opts = [plan.after != null && ["after", plan.after], plan.before != null && ["before", plan.before]].filter(Boolean)
        .sort((x, y) => Math.abs(x[1] - plan.T) - Math.abs(y[1] - plan.T));
      openModal(el("div", { class: "box" }, el("h3", {}, "Something is on screen here"),
        el("p", { class: "hint", style: "font-size:13px;line-height:1.5" },
          `At ${fmtT(plan.T)}, ${what} ${plan.across.length > 1 ? "are" : "is"} on screen. Inserting the clip there would keep ${plan.across.length > 1 ? "them" : "it"} ` +
          `on screen over the whole clip. Put the clip just ${opts.map((o) => o[0]).join(" or ")} instead?`),
        el("div", { class: "btns", style: "justify-content:flex-end;margin-top:14px;flex-wrap:wrap" },
          el("button", { onclick: () => done(null) }, "Cancel"),
          el("button", { title: "Insert here: what's on screen stays over the clip", onclick: () => done(plan.T) }, "Insert here anyway"),
          ...opts.map(([w, t], i) => el("button", { class: i === 0 ? "primary" : "", onclick: () => done(t) }, `Insert at ${fmtT(t)} (${w} ${plan.across.length > 1 ? "them" : "it"})`)))));
    });
  }

  async function insert(c) {
    if (!S.spec) return;
    if (S.cut) return toast("Apply or discard the cut that's waiting first.");
    if (S.zoomJob?.running) return toast("Wait for the re-render to finish.");
    if (!S.edlInfo?.editable) return toast("This video has no cut list, so a clip can't be inserted. Add it at the playhead instead.");
    const plan = insertPlan(S.t);
    const at = plan.across.length ? await chooseSpot(c, plan) : plan.T;
    if (at == null) return;
    const ok = await confirmBox("Insert the clip?", `“${c.plan?.title || "AI clip"}” (${fmtS(c.dur)}) goes into the video at ${fmtT(at)}. The video pauses while it plays, ` +
      `and everything after it moves ${fmtS(c.dur)} later. The base edit is re-rendered (a minute or two); the clip has no captions. Undo isn't possible after this, but the ` +
      "previous version is kept as a backup and the clip can be deleted from the Video track like any other clip.", "Insert");
    if (!ok) return;
    if (S.dirty && !(await save())) return;
    const r = await post("/api/cuts/insert", { clip: c.id, t: at });
    if (!r.ok) return toast(r.error || "Couldn't insert it");
    toast(`Inserting at ${fmtT(r.at)}…`); toggle(false);
    pollZoomJob();
  }
  async function asOverlay(c) {
    if (!S.spec) return;
    const r = await post(H().api("overlay"), { id: c.id });
    if (!r.ok) return toast(r.error || "Couldn't add it");
    const t = r2(Math.max(0, Math.min(S.t, S.dur - 0.5))), dur = r2(Math.min(r.dur || 5, S.dur - t));
    const busy = (k) => (S.spec.overlays || []).some((o) => (o.track || 1) === k && o.t < t + dur && o.t + o.dur > t);
    let track = 1; while (busy(track)) track++;
    snapshot();                                     // before touching the spec, so one undo removes it all
    const list = (S.spec.overlays = S.spec.overlays || []);
    list.push({ src: r.src, name: r.name, t, dur, in: 0, clip: r.dur, track, mode: "full", opacity: 1, fade: 0.2, muted: false, volume: 1, duck: 0, has_audio: r.audio });
    S.sel = { kind: "ov", i: list.length - 1 };
    change();
    toast(dur < (r.dur || 0) - 0.05 ? `Added at ${fmtT(t)}; trimmed to the end of the video` : `Added at ${fmtT(t)}: the speaker is muted while it plays`);
  }

  // header button (only when the server has the studio)
  sectionsReady.then(() => {
    if (!SECTIONS.studio) return;
    const b = el("button", { id: "aiBtn", title: "AI studio: build a clip from several videos with Claude", onclick: () => toggle() }, ic("sparkles"), "AI studio");
    $("#brandsBtn")?.after(b);
  });
  window.toggleStudio = toggle;
  window.studioApi = (p) => H().api(p);     // for a host's overlay(): the same URLs the panel uses
})();
