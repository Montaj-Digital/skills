// Long-form section of the Studio AI short-form editor: the library, the wizard (choose the video in place, details, create)
// and the project screen (a rough preview that plays the cuts, with chapters, lower-thirds, cards and captions).
// Loaded by the short-form app on demand (/long/app/long.js), so it shares its helpers: $, el, ic, toast, S, leave, claudeNote.
"use strict";

const LF = (() => {
  const get = (p) => fetch(p).then((r) => r.json());
  const post = (p, b) => fetch(p, { method: "POST", body: JSON.stringify(b || {}) }).then((r) => r.json());
  const W = { step: 1, brand: "default", path: null, info: null, name: "", notes: "", tmode: "none", ttext: "", tpath: null, tname: "", twords: 0, captions: true, root: null, timer: 0 };

  const mmss = (t) => { t = Math.max(0, Math.round(t)); const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`; };
  const nice = (t) => { const m = Math.round(t / 60); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`; };
  const gb = (b) => (b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`);
  const ago = (t) => { const s = Date.now() / 1000 - t; return s < 3600 ? `${Math.max(1, Math.round(s / 60))} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : s < 86400 * 14 ? `${Math.round(s / 86400)} days ago` : new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }); };

  function view() {
    let v = $("#lfview");
    if (!v) { v = el("div", { id: "lfview", class: "wizard lf" }); document.body.append(v); }
    v.className = "wizard lf"; v.hidden = false; return v;
  }
  function close() { const v = $("#lfview"); if (v) { v.hidden = true; v.innerHTML = ""; } document.getElementById("lf-brand")?.remove();
    if (window.LF_STUDIO) { delete window.LF_STUDIO; window.toggleStudio?.(false); } clearTimeout(W.timer); stopPlayer(); }

  // ---------------------------------------------------------------- library (Open, Long-form)
  async function renderHome(h, landing) {
    close();
    const search = el("input", { type: "text", class: "search", placeholder: "Search videos" });
    const clientSel = el("select", { class: "clientsel", title: "Show one client's videos", hidden: true });
    const chips = el("div", { class: "fchips" });
    const grid = el("div", { class: "grid" }, el("div", { class: "empty" }, "Finding your videos…"));
    h.append(el("div", { class: "home-in" },
      el("div", { class: "hh" },
        el("div", { class: "htitle" }, sectionSwitch(() => showHome(landing)),
          el("h1", {}, landing ? ["Your ", el("span", { class: "gt" }, "long-form videos")] : ["Open a ", el("span", { class: "gt" }, "long-form video")]),
          el("div", { class: "lib" }, "")),
        el("div", { class: "hact" }, clientSel, el("label", { class: "searchbox" }, ic("search"), search),
          window.PORTAL ? null : el("button", { onclick: () => post("/api/long/reveal", { root: lastRoot(), what: "renders" }), title: "Open 06. Renders in Finder" }, ic("folder-open"), "Finished videos"),
          !landing ? el("button", { class: "icon", onclick: hideHome, title: "Close", "aria-label": "Close" }, ic("x")) : null)),
      chips, grid));
    const { projects, folder } = await get("/api/long/projects");
    h.querySelector(".lib").textContent = `${projects.length} video${projects.length === 1 ? "" : "s"} · camera files stay where they are; projects are saved in 05. Projects, finished videos in 06. Renders`;
    let filter = "all", client = "all";
    try { client = sessionStorage.getItem("clientFilter") || "all"; } catch (e) {}
    if (window.brandsReady) await window.brandsReady;
    const bname = (id) => (window.brandName ? brandName(id) : id);
    const clients = [...new Set(projects.map((p) => p.brand || "default"))];
    if (clients.some((c) => c !== "default")) {
      clientSel.hidden = false;
      clientSel.append(el("option", { value: "all" }, "All clients"), ...clients.map((c) => el("option", { value: c }, `${bname(c)} (${projects.filter((p) => (p.brand || "default") === c).length})`)));
      if (!clients.includes(client)) client = "all";
      clientSel.value = client;
    } else client = "all";
    const ofClient = (p) => client === "all" || (p.brand || "default") === client;
    clientSel.onchange = () => { client = clientSel.value; try { sessionStorage.setItem("clientFilter", client); } catch (e) {} drawChips(); draw(); };
    const status = (p) => (p.running ? "work" : p.failed ? "fail" : p.done ? "ready" : "work");
    const drawChips = () => {
      chips.innerHTML = "";
      [["all", "All"], ["ready", "Ready"], ["work", "In progress"], ["fail", "Needs attention"]].forEach(([k, l]) => {
        const n = projects.filter((p) => ofClient(p) && (k === "all" || status(p) === k)).length;
        if (k !== "all" && !n) return;
        chips.append(el("button", { class: `fchip${filter === k ? " on" : ""}`, onclick: () => { filter = k; drawChips(); draw(); } }, l, el("b", {}, String(n))));
      });
    };
    const card = (p) => {
      const st = status(p);
      return el("div", { class: "reel lf-card", role: "button", tabindex: "0", title: p.root, onclick: () => openProject(p.root), onkeydown: (e) => { if (e.key === "Enter") openProject(p.root); } },
        el("div", { class: "th fit lf-th", style: `--img:url("/api/long/thumb?root=${encodeURIComponent(p.root)}")` }, el("div", { class: "thimg" }),
          el("div", { class: "badges" },
            st === "ready" ? el("span", { class: "badge ok" }, ic("check"), "Ready") : st === "fail" ? el("span", { class: "badge bad" }, ic("triangle-alert"), "Needs attention") : el("span", { class: "badge open" }, "In progress"),
            el("span", { class: "badge fmtb" }, "16:9")),
          p.brand && p.brand !== "default" ? el("span", { class: "clientb" }, bname(p.brand)) : null),
        el("button", { class: "del icon", title: "Delete this video", "aria-label": `Delete ${p.name}`, onclick: (e) => { e.stopPropagation(); confirmDelete(p, () => { projects.splice(projects.indexOf(p), 1); drawChips(); draw(); }); } }, ic("trash-2")),
        el("div", { class: "meta" }, el("b", {}, p.name),
          el("span", {}, `${p.duration ? nice(p.duration) : "?"} · ${p.chapters} chapters · ${p.cards} cards · ${ago(p.modified)}`),
          window.plannerBadge ? plannerBadge(p.root) : null));
    };
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      grid.innerHTML = "";
      const list = projects.filter((p) => ofClient(p) && (filter === "all" || status(p) === filter) && (!q || p.name.toLowerCase().includes(q)));
      if (!q) grid.append(el("button", { class: "reel newcard", onclick: openWizard }, el("span", { class: "plus" }, ic("plus")), el("b", {}, "New long-form video"), el("span", {}, "Pick a long recording")));
      list.forEach((p) => grid.append(card(p)));
      if (!list.length && (q || filter !== "all")) grid.append(el("div", { class: "empty" }, "No videos match."));
    };
    search.oninput = draw; drawChips(); draw(); search.focus();
    lastFolder = folder;
  }
  let lastFolder = "";
  let lastRootV = null;
  const lastRoot = () => lastRootV || "";

  function confirmDelete(p, done) {
    const go = el("button", { class: "primary", style: "background:var(--danger);border-color:var(--danger)" }, "Move to Trash");
    const errLine = el("div", { class: "err" });
    openModal(el("div", { class: "box" }, el("h3", {}, `Delete “${p.name}”?`),
      el("div", { class: "hint" }, "This moves the project folder to the Trash: the transcript, the cuts and the plan. Your camera file is only linked, so it stays exactly where it is. Finished videos in 06. Renders are kept."),
      errLine, el("div", { class: "btns", style: "justify-content:flex-end;margin-top:12px" }, el("button", { onclick: closeModal }, "Cancel"), go)));
    go.onclick = async () => {
      go.disabled = true;
      const r = await post("/api/long/delete", { root: p.root });
      if (!r.ok) { errLine.textContent = r.error || "Couldn't delete it."; go.disabled = false; return; }
      closeModal(); toast(`Moved “${p.name}” to the Trash`); done();
    };
  }

  // ---------------------------------------------------------------- wizard
  function openWizard() {
    leave(() => {
      S.leaving = false;
      Object.assign(W, { step: 1, brand: W.brand || "default", path: null, info: null, name: "", notes: "", tmode: "none", ttext: "", tpath: null, tname: "", twords: 0, captions: true, root: null });
      if (typeof closeWizard === "function") closeWizard();
      hideHome(); stopPlayer(); draw();
    });
  }
  function draw() {
    const v = view(); v.innerHTML = "";
    const labels = ["Who it's for", "Choose the video", "Details", "Create"];
    const stepper = el("ol", { class: "stepper" }, ...labels.map((l, i) =>
      el("li", { class: i + 1 === W.step ? "on" : i + 1 < W.step ? "done" : "" }, el("b", {}, i + 1 < W.step ? ic("check") : String(i + 1)), l)));
    const x = W.step < 4 ? el("button", { class: "icon ghost", title: "Close", "aria-label": "Close", onclick: () => { close(); showHome(true); } }, ic("x")) : null;
    const body = el("div", { class: "wz-body" });
    v.append(el("div", { class: "wz-in" }, el("div", { class: "wz-top" }, stepper, x), body));
    if (W.step === 1) { if (window.brandStep) brandStep(body, W.brand, (id) => { W.brand = id; W.step = 2; draw(); }); else { W.step = 2; draw(); } return; }
    (W.step === 2 ? stepChoose : W.step === 3 ? stepDetails : stepCreate)(body);
  }

  function stepChoose(b) {
    const err = el("div", { class: "err" });
    const pick = async (btn) => {
      btn.disabled = true; const old = btn.textContent; btn.textContent = window.PORTAL ? "Uploading…" : "Waiting for Finder…";
      let body = {};
      if (window.PORTAL) {                     // the portal: upload it (resumable); it moves into the project when it's created
        const [f] = await pickFiles("video/*");
        if (!f) { btn.disabled = false; btn.textContent = old; return; }
        try { body.upload = await uploadFile(f, (p) => { btn.textContent = `Uploading ${Math.floor(p * 100)}%`; }); }
        catch (e) { btn.disabled = false; btn.textContent = old; err.textContent = e.message; return; }
      }
      const r = await post("/api/long/choose-file", body).catch(() => ({}));
      btn.disabled = false; btn.textContent = old;
      if (r.error) { err.textContent = r.error; return; }
      if (!r.path) return;
      W.path = r.path; W.info = r; if (!W.name) W.name = (r.name || "").replace(/[_-]+/g, " ").trim();
      draw();
    };
    const I = W.info;
    const box = el("div", { class: "lf-pick" });
    if (!W.path) {
      const btn = el("button", { class: "primary big" }, ic(window.PORTAL ? "upload" : "film"), window.PORTAL ? "Upload the video" : "Choose the video in Finder");
      btn.onclick = () => pick(btn);
      box.append(el("div", { class: "dz-ic" }, ic("film")), el("b", {}, "Choose the long recording"),
        el("span", { class: "hint" }, "MP4 or MOV, 16:9 landscape, usually 60+ minutes."), btn);
    } else {
      const btn = el("button", {}, "Choose a different video"); btn.onclick = () => pick(btn);
      box.classList.add("has");
      box.append(el("div", { class: "dz-ic ok" }, ic("check")), el("b", {}, W.path.split(/[\\/]/).pop()),
        el("span", { class: "hint lf-path" }, W.path.replace(/^\/Users\/[^/]+/, "~")),
        el("div", { class: "lf-facts" }, ...[["Length", I.duration ? nice(I.duration) : "?"], ["Picture", I.width ? `${I.width}×${I.height}` : "?"], ["File size", I.size ? gb(I.size) : "?"]]
          .map(([k, v]) => el("div", {}, el("small", {}, k), el("b", {}, v)))),
        I.width && I.height && I.height > I.width ? el("div", { class: "note" }, "This video is portrait. Long-form is built for landscape 16:9, so it will be cropped.") : null,
        btn);
    }
    b.append(el("h2", { class: "wz-h" }, "Choose the ", el("span", { class: "gt" }, "video")),
      el("p", { class: "wz-sub" }, window.PORTAL ? "An hour of camera footage can be 20 to 100 GB. The upload carries on where it stopped if the connection drops; keep this tab open until it's done."
        : "An hour of camera footage can be 20 to 100 GB, so the editor doesn't copy it. It links the file where it already is."),
      box, err,
      el("div", { class: "wz-actions lf-actions" }, el("button", { onclick: () => { W.step = 1; draw(); } }, ic("arrow-left"), "Back"),
        el("button", { class: "primary big", disabled: !W.path, onclick: () => { W.step = 3; draw(); } }, "Continue", ic("chevron-right"))));
  }

  function stepDetails(b) {
    const err = el("div", { class: "err" });
    const name = el("input", { type: "text", placeholder: "AI Workshop, October", value: W.name });
    name.oninput = () => { W.name = name.value; err.textContent = ""; };
    const notes = el("textarea", { class: "notes", placeholder: "Who is speaking, the topic, names and brands to spell correctly, parts to cut, a different call to action…" });
    notes.value = W.notes; notes.oninput = () => (W.notes = notes.value);
    const opts = [["none", "No transcript", "Whisper listens to the video"], ["paste", "Paste text", "Corrects names and jargon"], ["srt", "SRT or VTT file", "Already has timings"]];
    const tsel = el("div", { class: "lf-opts" }, ...opts.map(([k, l, s]) => el("button", { class: `lf-opt${W.tmode === k ? " on" : ""}`, onclick: () => { W.tmode = k; draw(); } }, el("b", {}, l), el("small", {}, s))));
    const tbody = el("div", { class: "lf-tbody" });
    if (W.tmode === "paste") {
      const ta = el("textarea", { class: "notes lf-paste", placeholder: "Paste the transcript here (plain text, no timings)…" });
      ta.value = W.ttext; ta.oninput = () => { W.ttext = ta.value; };
      tbody.append(ta, el("div", { class: "hint" }, "Whisper still listens to get the timings; your text fixes its spelling of names, brands and jargon."));
    } else if (W.tmode === "srt") {
      const btn = el("button", {}, ic("folder-open"), W.tpath ? "Choose a different file" : "Choose the subtitle file…");
      btn.onclick = async () => {
        btn.disabled = true;
        let body = {};
        if (window.PORTAL) {
          const upload = await pickAndUpload(".srt,.vtt", "the subtitle file");
          if (!upload) { btn.disabled = false; return; }
          body = { upload };
        }
        const r = await post("/api/long/choose-transcript", body).catch(() => ({}));
        btn.disabled = false;
        if (!r.path) return;
        if (!r.ok) { err.textContent = "That file has no timed lines in it. Choose an SRT or VTT file."; return; }
        Object.assign(W, { tpath: r.path, tname: r.name, twords: r.words }); draw();
      };
      tbody.append(btn, W.tpath ? el("div", { class: "note ok" }, `${W.tname}: ${W.twords.toLocaleString()} words. Whisper is skipped, which saves 10 to 30 minutes. Word times are spread evenly across each line, so pause trimming is gentler.`)
        : el("div", { class: "hint" }, "An SRT or VTT file already has timings, so the video isn't transcribed again."));
    }
    const cap = el("label", { class: "switch lf-cap" }, el("input", { type: "checkbox", checked: W.captions }), el("span"),
      el("div", {}, el("b", {}, "Burn in word captions"), el("small", {}, "On by default. YouTube has its own captions, so switch this off if you'd rather use those. You can change it later too.")));
    cap.querySelector("input").onchange = (e) => { W.captions = e.target.checked; };
    const create = async () => {
      if (!W.path) { W.step = 2; draw(); return; }
      if (!W.name.trim()) { err.textContent = "Give the video a name."; name.focus(); return; }
      if (W.tmode === "paste" && !W.ttext.trim()) { err.textContent = "Paste the transcript, or choose “No transcript”."; return; }
      if (W.tmode === "srt" && !W.tpath) { err.textContent = "Choose the subtitle file, or choose “No transcript”."; return; }
      const transcript = W.tmode === "paste" ? { mode: "paste", text: W.ttext } : W.tmode === "srt" ? { mode: "srt", path: W.tpath } : { mode: "none" };
      const st = await post("/api/long/start", { path: W.path, name: W.name.trim(), notes: W.notes, captions: W.captions, transcript, brand: W.brand });
      if (st.error) { err.textContent = st.error; return; }
      W.root = st.root; W.step = 4; draw(); showJob(st, $("#lfJob"), true);
    };
    b.append(el("h2", { class: "wz-h" }, "Add the ", el("span", { class: "gt" }, "details")),
      el("p", { class: "wz-sub" }, el("span", { class: "tag" }, W.path.split(/[\\/]/).pop()), " Name it, tell Claude what to know, and say whether you have a transcript."),
      el("div", { class: "lf-form" },
        el("label", { class: "wz-l" }, "Video name"), name,
        el("label", { class: "wz-l" }, "Notes for Claude ", el("span", { class: "opt" }, "optional")), notes,
        el("label", { class: "wz-l" }, "Transcript"), tsel, tbody,
        cap, claudeNote(), err,
        el("div", { class: "wz-actions" },
          el("button", { onclick: () => { W.step = 2; draw(); } }, ic("arrow-left"), "Back"),
          el("button", { class: "primary big", onclick: create }, ic("sparkles"), "Create video"))));
  }

  function stepCreate(b) {
    b.append(el("h2", { class: "wz-h" }, "Creating your ", el("span", { class: "gt" }, "video")),
      el("p", { class: "wz-sub", id: "lfSub" }, "A long video takes a while: transcribing an hour is the slowest step. You can leave this tab open and come back."),
      el("div", { class: "lf-job", id: "lfJob" }));
  }

  // progress list, shared by the wizard and a project that isn't finished yet
  function showJob(st, box, fromWizard) {
    clearTimeout(W.timer);
    box = $("#lfJob") || box; if (!box || !st || !st.steps) return;
    box.innerHTML = "";
    const finished = st.steps.filter((s) => s.state === "done" || s.state === "skipped").length;
    const sub = $("#lfSub");
    if (sub) sub.textContent = st.done ? "Done. Opening the project…" : st.error ? "A step failed. Fix the cause, then retry from there." : "A long video takes a while: transcribing an hour is the slowest step. You can leave this tab open and come back.";
    box.append(el("div", { class: "progress" }, el("i", { style: `width:${Math.round((finished / st.steps.length) * 100)}%` })),
      el("ul", { class: "steps big" }, ...st.steps.map((s) => el("li", { class: s.state },
        el("span", { class: "ic" }, s.state === "done" ? ic("check") : s.state === "failed" ? ic("x") : s.state === "skipped" ? "–" : ""),
        el("span", { class: "lbl" }, s.label), s.info ? el("span", { class: "inf" }, s.info) : null))));
    const failed = st.steps.find((s) => s.state === "failed");
    if (st.error) box.append(el("div", { class: "err" }, st.error));
    if (failed) box.append(el("div", { class: "wz-actions" },
      el("button", { onclick: () => { close(); showHome(true); } }, "Back to videos"),
      el("button", { class: "primary", onclick: async () => showJob(await post("/api/long/retry", { root: st.root, from: failed.key }), box) }, `Retry from “${failed.label}”`)));
    if (!st.claude && !st.done) box.append(claudeNote());
    box.append(el("details", {}, el("summary", { class: "hint" }, "Details"), el("pre", { class: "log" }, (st.log || []).join("\n"))));
    if (st.done) { setTimeout(() => openProject(st.root), 700); return; }
    if (st.running) W.timer = setTimeout(async () => {
      const s2 = await get(`/api/long/status?root=${encodeURIComponent(st.root)}`).catch(() => null);
      showJob(s2 && s2.steps ? s2 : st, box);
    }, 1500);
  }

  // ---------------------------------------------------------------- project screen (the editor lives in editor.js)
  const loaded = {};
  function loadAsset(kind, src) {
    if (loaded[src]) return loaded[src];
    return (loaded[src] = new Promise((ok, no) => {
      const e = kind === "css" ? el("link", { rel: "stylesheet", href: src, onload: ok, onerror: no }) : el("script", { src, onload: ok, onerror: no });
      (kind === "css" ? document.head : document.body).append(e);
    }));
  }
  function stopPlayer() { if (typeof LFE !== "undefined") LFE.stop(); }
  function leaveToLibrary() { close(); showHome(true); }

  async function openProject(root) {
    clearTimeout(W.timer); stopPlayer(); lastRootV = root;
    hideHome(); if (typeof closeWizard === "function") closeWizard();
    const v = view(); v.innerHTML = "";
    const d = await get(`/api/long/project?root=${encodeURIComponent(root)}`).catch(() => null);
    if (!d || d.error) { toast("Couldn't open that video."); close(); showHome(true); return; }
    if (!d.status.done || !d.spec) {            // still being made, or stopped part-way
      W.step = 4; draw();
      return showJob(d.status, $("#lfJob"));
    }
    document.title = `${d.meta.name} · Studio AI`;
    try { await Promise.all([loadAsset("css", "/long/app/overlays.css"), loadAsset("js", "/long/app/overlays.js")]); await loadAsset("js", "/long/app/editor.js"); }
    catch (e) { toast("The editor didn't load."); close(); showHome(true); return; }
    LFE.show(root, d, v);
  }

  return { renderHome, openWizard, openProject, leaveToLibrary, loadAsset };
})();
