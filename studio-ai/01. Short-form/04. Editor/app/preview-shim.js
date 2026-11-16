// Injected into the preview build only (never into the real index.html). Lets the editor
// seek and play the composition: the video plays natively and the GSAP timeline follows it.
(function () {
  var root = document.getElementById("root");
  var TOTAL = parseFloat(root.dataset.duration);
  var DUR = window.__DUR || TOTAL;
  var v = document.getElementById("a-roll");
  var clips = Array.prototype.slice.call(document.querySelectorAll(".clip"))
    .filter(function (e) { return e !== v && e.tagName !== "AUDIO"; })
    .map(function (e) { return { e: e, s: parseFloat(e.dataset.start), d: parseFloat(e.dataset.duration) }; });
  var tl = function () { return window.__timelines && window.__timelines.main; };
  var t = 0, playing = false, clockFrom = 0, clockAt = 0, raf = 0;
  // sound effects (<audio class="clip">) only play in the render; the preview fires them as the playhead crosses them
  var sounds = Array.prototype.slice.call(document.querySelectorAll("audio.clip")).map(function (a) {
    return { a: a, s: parseFloat(a.dataset.start), vol: parseFloat(a.dataset.volume || "1") };
  });
  var lastT = 0;
  function fireSounds(x) {
    if (x > lastT && x - lastT < 0.5) sounds.forEach(function (o) {
      if (o.s > lastT && o.s <= x) { o.a.volume = Math.min(1, o.vol); o.a.currentTime = 0; o.a.muted = v.muted; o.a.play().catch(function () {}); }
    });
    lastT = x;
  }

  // Chrome can stop compositing a large, scaled video inside an iframe after a seek (it goes black),
  // so the frame is mirrored onto a canvas in the video's place; cards above still blur it.
  var cv = document.createElement("canvas");
  var CWd = parseFloat(root.dataset.width) || 1080, CHd = parseFloat(root.dataset.height) || 1920;
  cv.width = Math.round(CWd * 2 / 3); cv.height = Math.round(CHd * 2 / 3);   // same shape as the composition
  cv.style.cssText = "position:absolute;inset:0;width:100%;height:100%;pointer-events:none";
  v.after(cv);
  var g = cv.getContext("2d");
  var zp = [];   // editor's unapplied zoom-ins: [{start, end, ratio}] on the edited timeline
  function blit() {
    if (v.readyState < 2) return;
    var r = 1, ct = v.currentTime;
    for (var i = 0; i < zp.length; i++) if (ct >= zp[i].start && ct < zp[i].end) { r = zp[i].ratio; break; }
    var vw = v.videoWidth, vh = v.videoHeight, k = Math.max(cv.width / vw, cv.height / vh) * r;
    var w = vw * k, h = vh * k;
    g.drawImage(v, (cv.width - w) / 2, (cv.height - h) / 2, w, h);
  }
  ["loadeddata", "seeked", "timeupdate"].forEach(function (e) { v.addEventListener(e, blit); });
  if (v.requestVideoFrameCallback) {
    var onFrame = function () { blit(); v.requestVideoFrameCallback(onFrame); };
    v.requestVideoFrameCallback(onFrame);
  }
  // overlay videos: each one plays in step with the timeline and is mirrored onto its own canvas (same Chrome bug)
  var ovs = Array.prototype.slice.call(document.querySelectorAll("video.overlay")).map(function (e) {
    var c = document.createElement("canvas");
    c.style.cssText = "position:absolute;pointer-events:none;object-fit:cover";
    e.after(c); e.style.clipPath = "inset(50%)"; e.preload = "auto"; e.muted = true;
    var o = { e: e, c: c, g: c.getContext("2d"), s: parseFloat(e.dataset.start), d: parseFloat(e.dataset.duration),
      m: parseFloat(e.dataset.mediaStart || "0"), vol: parseFloat(e.dataset.volume || "1"), sound: e.dataset.hasAudio === "true" };
    var draw = function () { ovDraw(o); };
    ["loadeddata", "seeked", "timeupdate"].forEach(function (ev) { e.addEventListener(ev, draw); });
    if (e.requestVideoFrameCallback) { var f = function () { ovDraw(o); e.requestVideoFrameCallback(f); }; e.requestVideoFrameCallback(f); }
    return o;
  });
  function ovDraw(o) {
    var e = o.e; if (e.readyState < 2 || !e.videoWidth) return;
    var w0 = parseFloat(e.style.width) || CWd, h0 = parseFloat(e.style.height) || CHd;
    var tw = Math.round(w0 * 2 / 3), th = Math.round(h0 * 2 / 3);
    if (o.c.width !== tw || o.c.height !== th) { o.c.width = tw; o.c.height = th; }
    var k = Math.max(tw / e.videoWidth, th / e.videoHeight), w = e.videoWidth * k, h = e.videoHeight * k;
    o.g.drawImage(e, (tw - w) / 2, (th - h) / 2, w, h);
  }
  function ovSync(x) {
    for (var i = 0; i < ovs.length; i++) {
      var o = ovs[i], e = o.e, on = x >= o.s && x < o.s + o.d;
      ["left", "top", "width", "height", "borderRadius", "boxShadow", "zIndex", "opacity"].forEach(function (k) { if (o.c.style[k] !== e.style[k]) o.c.style[k] = e.style[k]; });
      o.c.style.visibility = on ? "" : "hidden";
      if (!on) { if (!e.paused) e.pause(); continue; }
      var target = x - o.s + o.m;
      e.muted = !o.sound || v.muted; e.volume = Math.min(1, o.vol);
      if (playing) {
        if (e.paused) { e.currentTime = target; var pr = e.play(); if (pr && pr.catch) pr.catch(function () {}); }
        else if (Math.abs(e.currentTime - target) > 0.3) e.currentTime = target;
      } else {
        if (!e.paused) e.pause();
        if (Math.abs(e.currentTime - target) > 0.02) e.currentTime = target;
      }
    }
  }
  // the speaker's volume lane (dips under an overlay with its own sound), as the render applies it
  var lane = null;
  try { var au = JSON.parse(v.dataset.automation || "null"); lane = au && au.lanes && au.lanes.filter(function (l) { return l.target === "volume"; })[0]; } catch (e) {}
  function laneVol(x) {
    if (!lane) return 1;
    var p = lane.points, j;
    if (x <= p[0].t) return p[0].v;
    for (j = 1; j < p.length; j++) if (x <= p[j].t) return p[j - 1].v + (p[j].v - p[j - 1].v) * (x - p[j - 1].t) / Math.max(0.001, p[j].t - p[j - 1].t);
    return p[p.length - 1].v;
  }
  var report = function (x) { try { parent.__previewTime && parent.__previewTime(x, playing); } catch (e) {} };

  function paint(x) {
    for (var i = 0; i < clips.length; i++) {
      var c = clips[i];
      c.e.style.visibility = x >= c.s && x < c.s + c.d ? "" : "hidden";
    }
    if (tl()) tl().seek(Math.min(x, TOTAL - 0.001), false);
    ovSync(x);
    if (lane) v.volume = Math.max(0, Math.min(1, laneVol(x)));
    // effects (punch / push) and takeovers (pip shrinks the footage into a window) move the video element;
    // the canvas copy follows, and is redrawn at its new shape so the footage stays "cover"-fitted
    var changed = false;
    ["transform", "transformOrigin", "left", "top", "width", "height", "borderRadius", "zIndex"].forEach(function (k) {
      if (v.style[k] && cv.style[k] !== v.style[k]) { cv.style[k] = v.style[k]; changed = true; }
    });
    if (changed) {
      var bw = parseFloat(cv.style.width) || CWd, bh = parseFloat(cv.style.height) || CHd;
      if (cv.style.width.indexOf("%") > -1) { bw = CWd; bh = CHd; }
      var tw = Math.round(bw * 2 / 3), th = Math.round(bh * 2 / 3);
      if (tw > 0 && th > 0 && (cv.width !== tw || cv.height !== th)) { cv.width = tw; cv.height = th; blit(); }
    }
  }

  var skips = [];
  function seekVideo(x) {
    var target = Math.min(x, DUR - 0.04);
    if (Math.abs(v.currentTime - target) > 0.001) v.currentTime = target;
  }

  function loop() {
    if (!playing) return;
    if (!v.paused && v.currentTime < DUR - 0.06) {
      t = v.currentTime;
    } else {
      if (!v.paused) v.pause();
      if (!clockAt) { clockAt = performance.now(); clockFrom = Math.max(t, DUR - 0.06); }
      t = clockFrom + (performance.now() - clockAt) / 1000;
    }
    for (var k = 0; k < skips.length; k++) {            // parts marked for removal are jumped over (cut preview)
      if (t >= skips[k].s && t < skips[k].e - 0.02) { t = skips[k].e; seekVideo(t); lastT = t; break; }
    }
    if (t >= TOTAL) { t = TOTAL; pause(); paint(t); report(t); return; }
    paint(t); report(t); fireSounds(t);
    if (!v.requestVideoFrameCallback) blit();
    raf = requestAnimationFrame(loop);
  }

  function play(from) {
    if (from != null) t = from;
    lastT = t;
    if (t >= TOTAL - 0.05) t = 0;
    playing = true; clockAt = 0;
    if (t < DUR - 0.06) {
      seekVideo(t);
      var p = v.play();
      if (p && p.catch) p.catch(function () { v.muted = true; v.play(); });
    }
    cancelAnimationFrame(raf); raf = requestAnimationFrame(loop);
  }

  function pause() {
    playing = false; cancelAnimationFrame(raf); v.pause(); ovSync(t); report(t);
  }

  function seek(x) {
    var wasPlaying = playing;
    if (wasPlaying) pause();
    t = Math.max(0, Math.min(TOTAL, x));
    seekVideo(t); paint(t);
    if (wasPlaying) play();
  }

  // ready once fonts are in (cards are centred from real text widths) and the first frame is decoded
  function whenReady(x) {
    return new Promise(function (resolve) {
      var fonts = document.fonts ? document.fonts.ready : Promise.resolve();
      fonts.then(function () {
        t = Math.max(0, Math.min(TOTAL, x)); paint(t);
        var target = Math.min(t, DUR - 0.04);
        var done = function () { v.removeEventListener("seeked", done); blit(); resolve(); };
        if (v.readyState >= 2 && Math.abs(v.currentTime - target) < 0.02) return done();
        v.addEventListener("seeked", done);
        v.currentTime = target;
        setTimeout(done, 4000);
      });
    });
  }

  v.preload = "auto";
  v.removeAttribute("muted"); v.muted = false;
  window.__editor = { play: play, pause: pause, seek: seek, ready: whenReady, isPlaying: function () { return playing; },
    time: function () { return t; },
    setZoomPreview: function (list) { zp = list || []; blit(); }, setSkips: function (list) { skips = list || []; }, restyle: function () { ovSync(t); ovs.forEach(ovDraw); }, total: TOTAL, dur: DUR, setMuted: function (m) { v.muted = m; } };
})();
