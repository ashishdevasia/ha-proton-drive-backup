/* =========================================================================
   Proton Drive Backup — single page app (vanilla JS, zero build)
   Driven by /getstatus polling. Ingress-safe (all URLs relative to the
   current path). Fully offline / self-contained.
   ========================================================================= */
(function () {
  "use strict";

  // --- Bootstrap context (from index.jinja2) -------------------------------
  var BOOT = {};
  try { BOOT = JSON.parse(document.getElementById("bootstrap").textContent); } catch (e) {}
  var VERSION = BOOT.version || "";

  // Translations (i18n.js): t(key, params) for every user-visible string.
  var I18n = window.I18n;  // missing if i18n.js didn't load; see the end of this file
  var t = I18n ? I18n.t : null;

  // Ingress serves us under an opaque path prefix; build everything relative
  // to the current directory so nothing is hard-coded to "/".
  var BASE = location.pathname.replace(/\/(index(\.html)?)?$/, "").replace(/\/$/, "");
  function u(path) { return BASE + path; }

  var MOCK = (typeof window.MockServer !== "undefined") && /[?&]mock=1/.test(location.search);

  // ------------------------------------------------------------------------
  // Tiny DOM helpers
  // ------------------------------------------------------------------------
  function el(sel) { return document.querySelector(sel); }
  function ce(tag, props, children) {
    var node = document.createElement(tag);
    if (props) {
      for (var k in props) {
        if (k === "class") node.className = props[k];
        else if (k === "html") node.innerHTML = props[k];
        else if (k === "text") node.textContent = props[k];
        else if (k.slice(0, 2) === "on" && typeof props[k] === "function") node.addEventListener(k.slice(2), props[k]);
        else if (props[k] === true) node.setAttribute(k, "");
        else if (props[k] != null && props[k] !== false) node.setAttribute(k, props[k]);
      }
    }
    (children || []).forEach(function (c) {
      if (c == null || c === false) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ------------------------------------------------------------------------
  // Inline SVG icons (no icon font / no CDN)
  // ------------------------------------------------------------------------
  var P = {
    shield: '<path d="M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5z"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    x: '<path d="M18 6L6 18M6 6l12 12"/>',
    cloud: '<path d="M17.5 19a4.5 4.5 0 000-9 6 6 0 00-11.6 1.5A4 4 0 006 19z"/>',
    home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
    download: '<path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 21h16"/>',
    upload: '<path d="M12 21V9m0 0l-4 4m4-4l4 4"/><path d="M4 3h16"/>',
    restore: '<path d="M3 12a9 9 0 109-9 9 9 0 00-6.4 2.6L3 8"/><path d="M3 3v5h5"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3m-8 0l1 13h8l1-13"/>',
    pin: '<path d="M12 2l3 7 7 .5-5.5 4.5L18 21l-6-3.8L6 21l1.5-7L2 9.5 9 9z"/>',
    note: '<path d="M5 4h14v16l-4-3H5z"/><path d="M9 9h6M9 13h4"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeoff: '<path d="M3 3l18 18"/><path d="M10.6 5.1A10.5 10.5 0 0112 5c6.5 0 10 7 10 7a16 16 0 01-3.4 4.2M6.5 6.6A16 16 0 002 12s3.5 7 10 7a10 10 0 003.5-.6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    sync: '<path d="M21 12a9 9 0 01-15.5 6.3L3 16"/><path d="M3 12a9 9 0 0115.5-6.3L21 8"/><path d="M21 3v5h-5M3 21v-5h5"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-2.7 1.1V21a2 2 0 11-4 0v-.1A1.6 1.6 0 005 19.4l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.6 1.6 0 003 14H3a2 2 0 110-4h.1A1.6 1.6 0 004.6 5L4.5 4.9a2 2 0 112.8-2.8l.1.1A1.6 1.6 0 0010 3.6V3a2 2 0 114 0v.1A1.6 1.6 0 0016.5 5l.1-.1a2 2 0 112.8 2.8l-.1.1A1.6 1.6 0 0021 10h0a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    doc: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/>',
    warn: '<path d="M12 3l9 16H3z"/><path d="M12 10v4m0 3h.01"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5m0 3h.01"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    bug: '<path d="M8 6a4 4 0 018 0M5 10h14M6 13H3m18 0h-3M6 17l-2 1m16-1l2 1M6 9l-2-1m16 1l2-1"/><rect x="8" y="6" width="8" height="12" rx="4"/>',
    link: '<path d="M10 14a5 5 0 007 0l3-3a5 5 0 00-7-7l-1 1"/><path d="M14 10a5 5 0 00-7 0l-3 3a5 5 0 007 7l1-1"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/>',
    dots: '<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>',
    chev: '<path d="M9 6l6 6-6 6"/>',
    refresh: '<path d="M21 12a9 9 0 11-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    ignore: '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>',
    folder: '<path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>',
    archive: '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 001 1h12a1 1 0 001-1V8M10 12h4"/>'
  };
  function icon(name, cls) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"' + (cls ? ' class="' + cls + '"' : "") +
      ' aria-hidden="true">' + (P[name] || "") + "</svg>";
  }
  function iconNode(name, cls) { var s = ce("span"); s.innerHTML = icon(name, cls); return s.firstChild; }

  // ------------------------------------------------------------------------
  // API layer
  // ------------------------------------------------------------------------
  function api(path, opts) {
    if (MOCK) return window.MockServer.handle(path, opts || {});
    opts = opts || {};
    return fetch(u(path), opts).then(function (r) {
      return r.text().then(function (txt) {
        var data = {}, json = true;
        try { data = txt ? JSON.parse(txt) : {}; } catch (e) { data = { message: txt }; json = false; }
        if (!r.ok) {
          if (!json || !txt) data = plainError(r.status, txt);
          data.http_status = data.http_status || r.status;
          return Promise.reject(data);
        }
        return data;
      });
    });
  }
  // A failed request whose body isn't the add-on's JSON. The add-on's own
  // plain-text errors ("400: the request body isn't JSON", the extra server's
  // 403 about require_login) are shown as they are. Home Assistant's and
  // proxies' error pages aren't, so errText gives translated text instead:
  // a 401 comes from ingress when its session has expired, or from the extra
  // server's sign-in (require_login); ingress sends a bare 403 when it refuses
  // access; 5xx and HTML pages come from a proxy while the add-on is down (the
  // add-on never sends plain-text 5xx).
  function plainError(status, txt) {
    var body = (txt || "").trim();
    if (status === 401) return { message_key: "error.session_expired" };
    if (body === "403: Forbidden") return { message_key: "error.forbidden" };
    if (!body || status >= 500 || body.charAt(0) === "<") return {};
    return { message: body };
  }
  function apiJson(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }
  function qs(params) {
    return Object.keys(params).filter(function (k) { return params[k] != null && params[k] !== ""; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]); }).join("&");
  }

  // ------------------------------------------------------------------------
  // Toast notifications
  // ------------------------------------------------------------------------
  var toastHost;
  // A live region only announces content inserted *after* it is in the DOM, so
  // create it up-front (at init) rather than lazily on the first toast.
  function ensureToastHost() {
    if (!toastHost) { toastHost = ce("div", { class: "toasts", "aria-live": "polite", "aria-atomic": "false" }); document.body.appendChild(toastHost); }
    return toastHost;
  }
  function toast(msg, kind, ms) {
    ensureToastHost();
    kind = kind || "info";
    var ic = kind === "ok" ? "check" : (kind === "bad" || kind === "warn") ? "alert" : "info";
    var node = ce("div", { class: "toast " + kind, role: "status" }, [iconNode(ic, "t-ico"), ce("div", { text: msg })]);
    toastHost.appendChild(node);
    setTimeout(function () {
      node.classList.add("out");
      setTimeout(function () { if (node.parentNode) node.parentNode.removeChild(node); }, 260);
    }, ms || 4200);
  }
  // Friendly wrapper: run an API call, show the global activity bar while it is
  // in flight, then toast its message / error. The bar gives immediate feedback
  // so actions never look like nothing is happening.
  function action(promise, okMsg) {
    setBusy(true);
    return promise.then(function (d) {
      setBusy(false);
      if (okMsg !== false) toast(okMsg || (d && d.message) || t("common.done"), "ok");
      scheduleRefresh(400);
      return d;
    }, function (e) {
      setBusy(false);
      if (e && e.error_type === "please_wait") {
        toast(t("toast.sync_busy_retry"), "info");
      } else {
        toast(errText(e, "toast.something_went_wrong"), "bad");
      }
      throw e;
    });
  }

  // --- Global activity (top loading) bar -----------------------------------
  // Shown whenever a user-initiated request is in flight (not background polls).
  var busyCount = 0, busyBar = null;
  function setBusy(on) {
    if (!busyBar) { busyBar = ce("div", { class: "load-bar", "aria-hidden": "true" }); document.body.appendChild(busyBar); }
    busyCount = Math.max(0, busyCount + (on ? 1 : -1));
    busyBar.classList.toggle("active", busyCount > 0);
  }
  // Run a non-action() request with the activity bar (used for loads/saves).
  function withBusy(promise) {
    setBusy(true);
    return promise.then(function (d) { setBusy(false); return d; }, function (e) { setBusy(false); throw e; });
  }

  // --- Connection-lost banner ----------------------------------------------
  // The first failed load shows the full-page fatal screen. Once we have booted
  // (i.e. shown real data at least once) a dropped backend would otherwise be
  // invisible — the UI would keep showing stale data — so surface a persistent
  // reconnecting bar instead.
  var offlineBar = null;
  function setOffline(on, msg) {
    if (on) {
      if (!offlineBar) {
        offlineBar = ce("div", { class: "offline-bar", role: "status", "aria-live": "polite" });
        document.body.appendChild(offlineBar);
      }
      offlineBar.innerHTML = "";
      offlineBar.appendChild(iconNode("alert"));
      offlineBar.appendChild(ce("span", { text: msg || t("offline.reconnecting") }));
    } else if (offlineBar) {
      offlineBar.remove(); offlineBar = null;
    }
  }

  // --- Number formatting ----------------------------------------------------
  // upload_info from the backend carries raw numbers (progress = float percent,
  // total = bytes, speed = bytes/sec). Pre-formatted strings (mock / older
  // payloads) pass through untouched.
  function clampPct(p) {
    var n = typeof p === "number" ? p : parseFloat(p);
    if (isNaN(n)) n = 0;
    return Math.max(0, Math.min(100, Math.round(n)));
  }
  function fmtBytes(v) {
    if (v == null || v === "") return "";
    if (typeof v !== "number") return String(v);
    var n = v, units = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)) + " " + units[i];
  }
  function fmtSpeed(v) {
    if (v == null || v === "") return "";
    if (typeof v !== "number") return String(v);
    return fmtBytes(v) + "/s";
  }
  function uploadFoot(up) {
    var parts = [];
    var sp = fmtSpeed(up.speed);
    if (sp) parts.push(sp);
    var when = I18n.relTime(up.started_timestamp) || up.started;
    if (when) parts.push(t("upload.started", { when: when }));
    return parts.join(" · ");
  }

  // Dates: the backend sends epoch seconds (null = no date), rendered here in
  // the viewer's language, next to English text kept for older payloads.
  function whenText(ts, text, noneKey) {
    if (ts === null) return t(noneKey);
    return I18n.relTime(ts) || text;
  }
  function whenDetail(ts, text) {
    if (ts === null) return null;
    return I18n.dateTime(ts) || text;
  }

  // ------------------------------------------------------------------------
  // App state
  // ------------------------------------------------------------------------
  var state = {
    status: null,
    config: null,        // { config, defaults, addons, folders }
    configDraft: {},     // unsaved settings edits, keyed by setting; survives
                         //   tab switches / advanced toggle until save or reset
    badNumbers: {},      // setting -> true: its number field holds text the
                         //   browser can't read as a number (see renderField)
    tab: "dashboard",
    pendingLogin: false,
    lastUploads: {},     // slug -> destination title (to detect transfer completion)
    pendingOutcome: {},  // slug -> destination title: transfer ended, copy not
                         //   yet visible; wait one more poll before calling it
                         //   failed (the backend attaches the copy just after
                         //   clearing the transfer indicators)
    booted: false
  };

  // ------------------------------------------------------------------------
  // Polling
  // ------------------------------------------------------------------------
  var refreshTimer = null;
  function scheduleRefresh(ms) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refresh, ms);
  }
  function pollInterval(s) {
    if (!s) return 4000;
    if (state.pendingLogin || s.proton_login_in_progress) return 2000;
    if (s.syncing) return 1500;
    if ((s.backups || []).some(isActive)) return 1500;
    return 10000;
  }
  function isActive(b) {
    return b.isPending || (b.upload_info && typeof b.upload_info.progress === "number");
  }

  function refresh() {
    api("/getstatus").then(function (s) {
      var prev = state.status;
      state.status = s;
      I18n.setTimeZone(s.time_zone);
      I18n.setServerTime(s.now_timestamp);
      // Detect login completion.
      if (state.pendingLogin && s.proton_authenticated) {
        state.pendingLogin = false;
        toast(t("toast.signed_in"), "ok");
        closeModal();
        api("/protonauth", { method: "POST" }).catch(function () {});
      }
      if (s.proton_login_error && state.pendingLogin) {
        toast(s.proton_login_error, "bad");
      }
      if (!s.proton_authenticated && (state.pendingLogin || s.proton_login_in_progress) && s.proton_login_url) {
        state.pendingLogin = true;
        if (loginModalOpen()) updateLoginModal(s.proton_login_url);
      }
      // Detect finished uploads to celebrate visibly.
      detectUploadCompletion(prev, s);
      setOffline(false);
      render();
      scheduleRefresh(pollInterval(s));
    }).catch(function (e) {
      if (!state.booted) { renderFatal(e); }
      else { setOffline(true, errText(e, "offline.reconnecting")); }
      scheduleRefresh(8000);
    });
  }

  function detectUploadCompletion(prev, s) {
    var nowUploading = {};
    (s.backups || []).forEach(function (b) {
      if (b.upload_info && typeof b.upload_info.progress === "number") nowUploading[b.slug] = b.upload_info.name || "Proton Drive";
    });
    function outcome(slug, dest) {
      var key = dest === "Home Assistant" ? "HomeAssistant" : "ProtonDrive";
      var b = (s.backups || []).filter(function (x) { return x.slug === slug; })[0];
      if (!b) return "gone";
      return (b.sources || []).some(function (x) { return x.key === key; }) ? "ok" : "missing";
    }
    // dest is the backend's destination title ("Home Assistant" / "Proton Drive").
    function done(dest) { return dest === "Home Assistant" ? t("toast.download_to_ha_done") : t("toast.upload_done", { dest: dest }); }
    function failed(dest) { return dest === "Home Assistant" ? t("toast.download_to_ha_failed") : t("toast.upload_failed", { dest: dest }); }
    var nextPending = {};
    Object.keys(state.lastUploads).forEach(function (slug) {
      if (nowUploading[slug]) return;
      var dest = state.lastUploads[slug];
      var out = outcome(slug, dest);
      if (out === "ok") toast(done(dest), "ok");
      // The HA direction clears its transfer indicators one supervisor call
      // before the copy is attached, so "missing" right after the transfer
      // can still be a success — give it one more poll before judging.
      else if (out === "missing") nextPending[slug] = dest;
    });
    Object.keys(state.pendingOutcome || {}).forEach(function (slug) {
      if (nowUploading[slug] || nextPending[slug]) return; // transfer restarted
      var dest = state.pendingOutcome[slug];
      var out = outcome(slug, dest);
      if (out === "ok") toast(done(dest), "ok");
      else if (out === "missing") toast(failed(dest), "bad");
    });
    state.pendingOutcome = nextPending;
    state.lastUploads = nowUploading;
  }

  // ------------------------------------------------------------------------
  // Render — shell
  // ------------------------------------------------------------------------
  // Labels: t("tab.<id>").
  var TABS = [
    { id: "dashboard", icon: "shield" },
    { id: "backups", icon: "archive" },
    { id: "settings", icon: "settings" },
    { id: "logs", icon: "doc" },
    { id: "about", icon: "info" }
  ];

  // Tracks what is currently rendered so polling doesn't needlessly rebuild the
  // DOM (which would restart animations and wipe in-progress form edits).
  var renderedTab = null, lastSig = null, lastChipKey = null;

  function render() {
    state.booted = true;
    var app = el("#app");
    app.removeAttribute("aria-busy");

    // #view exists only in the real layout; the error screens also use .shell.
    if (!el("#view")) {
      app.innerHTML = "";
      app.appendChild(renderTopbar());
      var shell = ce("div", { class: "shell" });
      shell.appendChild(renderTabs());
      shell.appendChild(ce("main", { id: "view", role: "tabpanel", tabindex: "-1" }));
      app.appendChild(shell);
      renderedTab = null; lastSig = null; lastChipKey = null;
    }
    updateTopbar();
    updateTabs();
    renderActiveView();
  }

  // Decide whether the active view needs a full rebuild, or just an in-place
  // live update. Settings & logs are user-driven and only rebuilt on explicit
  // navigation; data views rebuild only when their structural signature changes.
  function renderActiveView() {
    var tab = state.tab;
    var tabChanged = (tab !== renderedTab);
    if (tab === "settings" || tab === "logs") {
      if (tabChanged) { renderView(); renderedTab = tab; }
      return;
    }
    var sig = viewSignature();
    if (tabChanged || sig !== lastSig) {
      renderView(); renderedTab = tab; lastSig = sig;
    }
    updateLiveBits();
  }

  // A cheap structural fingerprint of everything that affects view layout.
  // Deliberately excludes rapidly-changing upload numbers (progress/speed/bytes)
  // so an active upload updates in place instead of rebuilding every poll.
  function viewSignature() {
    var s = state.status;
    if (!s) return "null";
    var parts = [
      state.tab, s.syncing ? 1 : 0, s.proton_authenticated ? 1 : 0, s.enable_proton_upload ? 1 : 0,
      s.backup_cooldown_active ? 1 : 0, s.proton_login_in_progress ? 1 : 0, s.proton_auth_warning || "",
      s.last_error ? s.last_error.error_type : "", s.last_error_count || 0,
      // The text shown, not the server's English, which changes on its own
      // schedule: "in 2 minutes" must be redrawn when it becomes "in 1 minute".
      whenText(s.next_backup_timestamp, s.next_backup_text, "dashboard.disabled"),
      whenText(s.last_backup_timestamp, s.last_backup_text, "dashboard.never"), s.proton_folder || ""
    ];
    ["HomeAssistant", "ProtonDrive"].forEach(function (k) {
      var src = (s.sources || {})[k] || {};
      parts.push(k + (src.backups || 0) + "/" + (src.retained || 0) + "/" + (src.size || ""));
    });
    (s.backups || []).forEach(function (b) {
      var up = isActive(b) && !b.isPending;
      // Staging vs CLI-upload phase flips the bar between determinate and
      // indeterminate, so include it (but not the changing % itself).
      var phase = up ? (clampPct(b.upload_info.progress) >= 100 ? "UC" : "US") : "";
      parts.push([
        b.slug, b.isPending ? 1 : 0, phase, b.note || "", b.ignored ? 1 : 0,
        b.uploadable ? 1 : 0, b.restorable ? 1 : 0,
        (b.sources || []).map(function (x) { return x.key + (x.retained ? "R" : "") + (x.delete_next ? "D" : ""); }).join(","),
        up ? "" : (b.status || "")
      ].join("~"));
    });
    return parts.join("|");
  }

  // In-place updates for fast-changing values, so animations keep running.
  function updateLiveBits() {
    var s = state.status; if (!s) return;
    (s.backups || []).forEach(function (b) {
      var up = b.upload_info;
      if (!up || typeof up.progress !== "number") return;
      var box = document.querySelector('[data-upload-slug="' + b.slug + '"]');
      if (!box) return;
      var pct = clampPct(up.progress);
      // Only the determinate (staging) bar has a width / % / live speed to push;
      // the indeterminate CLI-phase bar animates on its own.
      var i = box.querySelector(".bar:not(.indeterminate) > i"); if (i) i.style.width = pct + "%";
      var p = box.querySelector(".u-pct"); if (p) p.textContent = I18n.percent(pct);
      var tot = box.querySelector(".u-total"); if (tot) tot.textContent = fmtBytes(up.total);
      var sp = box.querySelector(".u-speed"); if (sp) sp.textContent = uploadFoot(up);
    });
    var am = el("#activity-msg"); if (am) am.textContent = activityMessage(s);
    var at = el("#activity-title"); if (at) at.textContent = activityTitle(s);
  }

  function renderTopbar() {
    return ce("header", { class: "topbar" }, [
      ce("div", { class: "topbar-inner" }, [
        ce("div", { class: "brand" }, [
          (function () { var l = ce("div", { class: "logo" }); l.innerHTML = icon("shield"); return l; })(),
          ce("div", {}, [ce("div", { text: "Proton Drive Backup" }), ce("small", { id: "tb-version", text: "v" + VERSION })])
        ]),
        ce("div", { class: "spacer" }),
        ce("div", { id: "tb-sync" })
      ])
    ]);
  }
  function updateTopbar() {
    var s = state.status; if (!s) return;
    var host = el("#tb-sync"); if (!host) return;
    var label, live = false, idle = false;
    var uploading = (s.backups || []).filter(isActive);
    if (s.syncing) { label = t("topbar.syncing"); live = true; }
    else if (uploading.length) { label = t("topbar.working"); live = true; }
    else { label = t("topbar.idle"); idle = true; }
    // Only rewrite when the chip actually changes, so its blink animation
    // doesn't restart on every poll.
    var key = label + "|" + live + "|" + idle;
    if (key === lastChipKey) return;
    lastChipKey = key;
    host.innerHTML = "";
    host.appendChild(ce("span", { class: "sync-chip " + (live ? "live" : "") + (idle ? "idle" : "") }, [
      ce("span", { class: "dot" }), ce("span", { text: label })
    ]));
  }

  function selectTab(id, focus) {
    state.tab = id; render();
    if (id === "settings") loadConfig(); if (id === "logs") loadLogs();
    if (focus) { var btn = el("#tab-" + id); if (btn) try { btn.focus(); } catch (e) {} }
  }
  function renderTabs() {
    var nav = ce("nav", { class: "tabs", role: "tablist", "aria-label": t("tab.aria_label") });
    TABS.forEach(function (tab, idx) {
      var selected = state.tab === tab.id;
      var btn = ce("button", {
        // Roving tabindex: only the selected tab is in the tab order; arrow keys
        // move between the rest (ARIA tablist pattern).
        class: "tab", role: "tab", id: "tab-" + tab.id, "data-tab": tab.id,
        "aria-controls": "view", tabindex: selected ? "0" : "-1",
        "aria-selected": selected ? "true" : "false",
        onclick: function () { selectTab(tab.id); },
        onkeydown: function (e) {
          var next = null;
          if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (idx + 1) % TABS.length;
          else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (idx - 1 + TABS.length) % TABS.length;
          else if (e.key === "Home") next = 0;
          else if (e.key === "End") next = TABS.length - 1;
          if (next != null) { e.preventDefault(); selectTab(TABS[next].id, true); }
        }
      }, [iconNode(tab.icon), ce("span", { text: t("tab." + tab.id) }), ce("span", { class: "badge hidden", id: "tabbadge-" + tab.id })]);
      nav.appendChild(btn);
    });
    return nav;
  }
  function updateTabs() {
    TABS.forEach(function (tab) {
      var btn = el("#tab-" + tab.id); if (!btn) return;
      var selected = state.tab === tab.id;
      btn.setAttribute("aria-selected", selected ? "true" : "false");
      btn.setAttribute("tabindex", selected ? "0" : "-1");
    });
    var view = el("#view"); if (view) view.setAttribute("aria-labelledby", "tab-" + state.tab);
    var s = state.status;
    var b = el("#tabbadge-backups");
    if (b && s) { var n = (s.backups || []).length; b.textContent = n; b.classList.toggle("hidden", !n); }
  }

  function renderView() {
    var host = el("#view"); if (!host) return;
    host.innerHTML = "";
    if (state.tab === "dashboard") viewDashboard(host);
    else if (state.tab === "backups") viewBackups(host);
    else if (state.tab === "settings") viewSettings(host);
    else if (state.tab === "logs") viewLogs(host);
    else if (state.tab === "about") viewAbout(host);
  }

  function renderFatal(e) {
    var app = el("#app");
    app.removeAttribute("aria-busy");
    app.innerHTML = "";
    app.appendChild(ce("div", { class: "shell" }, [
      ce("div", { class: "banner bad", style: "margin-top:40px" }, [
        iconNode("alert", "b-ico"),
        ce("div", { class: "b-body" }, [
          ce("div", { class: "b-title", text: t("fatal.title") }),
          ce("div", { class: "b-msg", text: errText(e, "fatal.message") }),
          ce("div", { class: "b-actions" }, [ce("button", { class: "btn", text: t("common.retry"), onclick: refresh })])
        ])
      ])
    ]));
  }

  // ------------------------------------------------------------------------
  // View: Dashboard
  // ------------------------------------------------------------------------
  function viewDashboard(host) {
    var s = state.status;

    // ---- Banners (priority order) ----
    renderErrorBanner(host, s);
    renderActivityBanner(host, s);
    renderCooldownBanner(host, s);
    renderAuthBanner(host, s);

    // ---- Quick actions + status grid ----
    var canBackup = s.proton_authenticated || !s.enable_proton_upload;
    var actions = ce("div", { class: "card" }, [
      ce("div", { class: "card-head" }, [
        ce("h2", { text: t("dashboard.overview") }), ce("div", { class: "spacer" }),
        ce("button", { class: "btn", onclick: openCreateBackup }, [iconNode("plus"), ce("span", { text: t("common.back_up_now") })]),
        ce("button", { class: "btn ghost", onclick: doSync }, [iconNode("sync"), ce("span", { text: s.syncing ? t("topbar.syncing") : t("dashboard.sync_now") })])
      ]),
      ce("div", { class: "grid cols-3" }, [
        statTile(t("dashboard.next_backup"), whenText(s.next_backup_timestamp, s.next_backup_text, "dashboard.disabled"),
          whenDetail(s.next_backup_timestamp, s.next_backup_detail), "clock"),
        statTile(t("dashboard.last_backup"), whenText(s.last_backup_timestamp, s.last_backup_text, "dashboard.never"),
          whenDetail(s.last_backup_timestamp, s.last_backup_detail), "check"),
        statTile("Proton Drive",
          !s.proton_authenticated ? (s.proton_auth_warning ? t("dashboard.proton.unavailable") : t("common.signed_out")) : s.proton_auth_warning ? t("dashboard.proton.connected_unverified") : t("dashboard.proton.connected"),
          !s.proton_authenticated ? (s.proton_auth_warning ? t("dashboard.proton.cli_problem") : t("dashboard.proton.sign_in_required")) : s.proton_auth_warning ? t("dashboard.proton.unverified") : t("common.folder", { folder: s.proton_folder || "—" }), "cloud")
      ])
    ]);
    // disable backup button if can't
    var bbtn = actions.querySelector(".btn");
    if (!canBackup) { bbtn.setAttribute("disabled", ""); bbtn.title = t("common.sign_in_first"); }
    host.appendChild(actions);

    // ---- Destinations ----
    var src = s.sources || {};
    var dests = ce("div", { class: "card" }, [
      ce("h2", { text: t("dashboard.where_title") }),
      ce("div", { class: "grid cols-2" }, [
        destTile("home", "ha", "Home Assistant", src.HomeAssistant),
        destTile("cloud", "proton", "Proton Drive", src.ProtonDrive)
      ])
    ]);
    host.appendChild(dests);

    // ---- Recent backups peek ----
    var recent = (s.backups || []).slice().reverse().slice(0, 3);
    var peek = ce("div", { class: "card" }, [
      ce("div", { class: "card-head" }, [
        ce("h2", { text: t("dashboard.recent") }), ce("div", { class: "spacer" }),
        ce("button", { class: "btn subtle sm", text: t("dashboard.view_all"), onclick: function () { state.tab = "backups"; render(); } })
      ])
    ]);
    if (!recent.length) peek.appendChild(emptyState("archive", t("common.no_backups"), t("dashboard.empty")));
    else recent.forEach(function (b) { peek.appendChild(backupCard(b, true)); });
    host.appendChild(peek);
  }

  function statTile(label, value, detail, ic) {
    return ce("div", { class: "stat" }, [
      ce("div", { class: "label" }, [iconNode(ic, "ico"), ce("span", { text: label })]),
      ce("div", { class: "value", text: value || "—" }),
      detail ? ce("div", { class: "detail", text: detail }) : null
    ]);
  }
  function destTile(ic, cls, name, info) {
    info = info || {};
    var count = info.backups != null ? info.backups : 0;
    var retained = info.retained || 0;
    var sub = [];
    if (info.size) sub.push(info.size);
    if (info.max) sub.push(t("dashboard.dest.max", { n: info.max }));
    if (retained) sub.push(t("dashboard.dest.kept", { n: retained }));
    var badge = ce("div", { class: "badge-ico " + cls }); badge.innerHTML = icon(ic);
    return ce("div", { class: "dest" }, [
      badge,
      ce("div", {}, [ce("div", { class: "name", text: name }), ce("div", { class: "meta", text: sub.join(" · ") || "—" })]),
      ce("div", { class: "count" }, [ce("b", { text: String(count) }), ce("span", { text: t("dashboard.dest.backups", { n: count }) })])
    ]);
  }

  // ---- Banners ----
  function activityTitle(s) {
    if ((s.backups || []).some(function (b) { return b.isPending; })) return t("activity.creating");
    var active = (s.backups || []).filter(isActive)[0];
    if (active) {
      var dest = (active.upload_info && active.upload_info.name) || "Proton Drive";
      return dest === "Home Assistant" ? t("activity.downloading_to_ha") : t("activity.uploading_to", { dest: dest });
    }
    return t("activity.syncing");
  }
  function activityMessage(s) {
    var pending = (s.backups || []).filter(function (b) { return b.isPending; });
    if (pending.length) return t("activity.building");
    var uploading = (s.backups || []).filter(isActive);
    if (uploading.length) {
      var b = uploading[0], up = b.upload_info, pct = clampPct(up.progress);
      var toHA = up.name === "Home Assistant";
      if (pct >= 100) {
        return toHA ? t("activity.finishing_download", { name: b.name })
                    : t("activity.uploading_slow", { name: b.name, dest: up.name || "Proton Drive" });
      }
      var sp = fmtSpeed(up.speed);
      var msg = t(toHA ? "activity.downloading_pct" : "activity.preparing_pct", { name: b.name, pct: I18n.percent(pct) });
      return sp ? msg + " · " + sp : msg;
    }
    return t("activity.checking");
  }
  function renderActivityBanner(host, s) {
    if (!s.syncing && !(s.backups || []).some(isActive)) return;
    host.appendChild(ce("div", { class: "banner live" }, [
      iconNode("sync", "b-ico"),
      ce("div", { class: "b-body" }, [
        ce("div", { class: "b-title", id: "activity-title", text: activityTitle(s) }),
        ce("div", { class: "b-msg", id: "activity-msg", text: activityMessage(s) }),
        ce("div", { class: "activity-strip" })
      ])
    ]));
  }

  function renderCooldownBanner(host, s) {
    if (!s.backup_cooldown_active) return;
    host.appendChild(banner("warn", "clock", t("cooldown.title"), t("cooldown.message"),
      [{ label: t("cooldown.action"), cls: "btn", fn: function () { action(api("/ignorestartupcooldown", { method: "POST" }), t("toast.cooldown_skipped")); } }]));
  }

  function renderAuthBanner(host, s) {
    if (!s.enable_proton_upload) return;
    if (s.proton_authenticated && s.proton_auth_warning) {
      host.appendChild(banner("warn", "cloud", t("auth.unverified.title"),
        t("auth.unverified.message", { warning: sentence(s.proton_auth_warning) }),
        [{ label: t("common.sign_in_again"), cls: "btn", fn: openLogin },
         { label: t("common.sign_out"), cls: "btn ghost", fn: openProtonLogout }]));
      return;
    }
    if (s.proton_authenticated) return;
    if (s.proton_auth_warning) {
      // e.g. the CLI binary crashing before it can even answer: signing in
      // isn't the fix, so don't lead with it.
      host.appendChild(banner("warn", "cloud", t("auth.broken.title"),
        s.proton_auth_warning,
        [{ label: t("common.sign_in_to_proton"), cls: "btn ghost", fn: openLogin }]));
      return;
    }
    host.appendChild(banner("warn", "cloud", t("auth.signed_out.title"), t("auth.signed_out.message"),
      [{ label: t("common.sign_in_to_proton"), cls: "btn", fn: openLogin }]));
  }

  function renderErrorBanner(host, s) {
    var e = s.last_error;
    if (!e) return;
    if (e.error_type === "please_wait") {
      host.appendChild(banner("info", "clock", t("error.please_wait.title"), t("error.please_wait.queued"), []));
      return;
    }
    var actions = resolutionsFor(e);
    var b = ce("div", { class: "banner bad" }, [
      iconNode("alert", "b-ico"),
      ce("div", { class: "b-body" }, [
        ce("div", { class: "b-title", text: errorTitle(e) }),
        ce("div", { class: "b-msg", text: errText(e, "error.generic.message") }),
        s.last_error_count > 1 ? ce("div", { class: "muted", style: "font-size:.8rem;margin-top:6px", text: t("error.repeated", { n: s.last_error_count }) }) : null,
        ce("div", { class: "b-actions" }, actions.map(function (a) {
          return ce("button", { class: a.cls || "btn ghost", text: a.label, onclick: a.fn });
        }).concat([
          ce("button", { class: "btn subtle", text: t("common.details"), onclick: function () { openErrorDetails(e); } })
        ]))
      ])
    ]);
    host.appendChild(b);
  }

  // Errors share a title per kind; the rest get the generic one.
  var ERROR_TITLE_ALIASES = { proton_timeout: "proton_cant_connect", drive_full: "low_space" };
  function errorTitle(e) {
    var type = ERROR_TITLE_ALIASES[e.error_type] || e.error_type;
    return I18n.has("error." + type + ".title") ? t("error." + type + ".title") : t("error.generic.title");
  }
  // The text for a backend error: translated by error_type when its message is
  // fixed (error.<type>.message, filled from the error's data), otherwise the
  // backend's own English message. Error pages from Home Assistant or a proxy
  // (plainError) and browser exceptions (fetch failures) get translated text
  // instead of e.g. "401: Unauthorized" or "Failed to fetch".
  // Backend text dropped into the middle of a translated sentence needs its own
  // full stop; the Proton CLI's warnings don't always end with one.
  function sentence(text) {
    text = String(text == null ? "" : text).trim();
    return !text || /[.!?…]$/.test(text) ? text : text + ".";
  }
  function errText(e, fallbackKey) {
    if (e && e.error_type) {
      var key = "error." + e.error_type + ".message";
      var data = e.data || {};
      if (e.error_type === "illegal_config") {
        // A rejected setting: name it as the settings form does.
        var label = "setting." + data.key + ".label";
        data = { value: data.value, setting: I18n.has(label) ? t(label) : data.key };
      }
      if (I18n.has(key)) return t(key, data);
    }
    if (e && e.message_key) return t(e.message_key);
    // The add-on's own plain-text errors (see plainError).
    if (e && !(e instanceof Error) && e.message) return e.message;
    return t(fallbackKey);
  }
  function resolutionsFor(e) {
    var out = [];
    switch (e.error_type) {
      case "proton_not_authenticated":
        out.push({ label: t("common.sign_in_to_proton"), cls: "btn", fn: openLogin }); break;
      case "proton_cant_connect": case "proton_timeout":
        out.push({ label: t("common.retry_now"), cls: "btn", fn: doSync }); break;
      case "multiple_deletes":
        out.push({ label: t("error.multiple_deletes.once"), cls: "btn", fn: function () { action(api("/confirmdelete", { method: "POST" }), t("toast.deletes_confirmed")); } });
        out.push({ label: t("error.multiple_deletes.always"), cls: "btn ghost", fn: function () { action(api("/confirmdelete?always=true", { method: "POST" }), t("toast.deletes_always")); } });
        break;
      case "low_space": case "drive_full":
        out.push({ label: t("error.low_space.skip"), cls: "btn", fn: function () { action(api("/skipspacecheck", { method: "POST" }), t("toast.space_check_skipped")); } });
        break;
      default:
        out.push({ label: t("common.retry_now"), cls: "btn", fn: doSync });
        out.push({ label: t("common.report_bug"), cls: "btn ghost", fn: openBugReport });
    }
    return out;
  }

  function banner(kind, ic, title, msg, actions) {
    return ce("div", { class: "banner " + kind }, [
      iconNode(ic, "b-ico"),
      ce("div", { class: "b-body" }, [
        ce("div", { class: "b-title", text: title }),
        ce("div", { class: "b-msg", text: msg }),
        (actions && actions.length) ? ce("div", { class: "b-actions" }, actions.map(function (a) {
          return ce("button", { class: a.cls || "btn ghost", text: a.label, onclick: a.fn });
        })) : null
      ])
    ]);
  }

  // ------------------------------------------------------------------------
  // View: Backups
  // ------------------------------------------------------------------------
  function viewBackups(host) {
    var s = state.status;
    renderErrorBanner(host, s);
    renderActivityBanner(host, s);

    var card = ce("div", { class: "card" }, [
      ce("div", { class: "card-head" }, [
        ce("h2", { text: t("backups.title", { n: (s.backups || []).length }) }),
        ce("div", { class: "spacer" }),
        ce("button", { class: "btn", onclick: openCreateBackup }, [iconNode("plus"), ce("span", { text: t("common.back_up_now") })])
      ])
    ]);
    var list = (s.backups || []).slice().reverse();
    if (!list.length) card.appendChild(emptyState("archive", t("common.no_backups"), t("backups.empty")));
    else list.forEach(function (b) { card.appendChild(backupCard(b, false)); });
    host.appendChild(card);
  }

  // The backend's backup statuses (Backup.status() and the overrides set on
  // transfers) are English; known ones are translated, anything else is shown
  // as sent.
  var STATUS_KEYS = {
    "Backed Up": "status.backed_up",
    "Proton Drive Only": "status.proton_only",
    "HA Only": "status.ha_only",
    "Created": "status.created",
    "Deleted": "status.deleted",
    "Pending": "status.pending",
    "Failed!": "status.failed",
    "Uploading to Proton Drive": "status.uploading",
    "Upload to Proton Drive failed": "status.upload_failed",
    "Upload to Proton Drive didn't start — try again": "status.upload_not_started"
  };
  function statusText(status) {
    if (!status) return status;
    if (STATUS_KEYS[status]) return t(STATUS_KEYS[status]);
    var m = /^(Loading|Downloading) (\d+(?:\.\d+)?)%$/.exec(status);
    if (m) return t(m[1] === "Loading" ? "status.loading_pct" : "status.downloading_pct", { pct: I18n.percent(Number(m[2])) });
    return status;
  }
  function typeText(type) {
    return type && I18n.has("backups.type." + type) ? t("backups.type." + type) : (type || t("backups.type.backup"));
  }

  function backupCard(b, compact) {
    var cls = "backup";
    if (b.isPending) cls += " pending";
    if (b.ignored) cls += " ignored";
    if (b.upload_info && typeof b.upload_info.progress === "number") cls += " uploading";

    var sub = [];
    sub.push(I18n.dateTime(b.timestamp) || b.date);
    if (b.size) sub.push(b.size);
    if (b.haVersion) sub.push(t("backups.ha_version", { version: b.haVersion }));
    var subRow = ce("div", { class: "backup-sub" }, sub.map(function (x) { return ce("span", { text: x }); }));

    // Badges: type, locations, retained, status, delete-next
    var badges = ce("div", { class: "backup-badges" });
    badges.appendChild(pill(b.type === "full" ? "accent" : "neutral", null, typeText(b.type)));
    (b.sources || []).forEach(function (src) {
      var isHa = src.key === "HomeAssistant";
      var loc = ce("span", { class: "loc " + (isHa ? "ha" : "proton") }, [
        iconNode(isHa ? "home" : "cloud"),
        ce("span", { text: isHa ? "Home Assistant" : "Proton Drive" })
      ]);
      if (src.retained) loc.appendChild(ce("span", { class: "tag", text: t("backups.tag.kept") }));
      if (src.delete_next) loc.appendChild(ce("span", { class: "tag", text: t("backups.tag.next_to_delete") }));
      badges.appendChild(loc);
    });
    if (b.protected) badges.appendChild(pill("neutral", "shield", t("backups.pill.encrypted")));
    if (b.ignored) badges.appendChild(pill("neutral", "ignore", t("backups.pill.ignored")));
    if (b.isPending) badges.appendChild(pill("info", "clock", t("backups.pill.creating")));
    else if (b.status && !(b.upload_info && b.upload_info.progress != null)) badges.appendChild(pill("info", null, statusText(b.status)));

    var card = ce("div", { class: cls }, [
      ce("div", { class: "backup-top" }, [
        ce("div", { style: "min-width:0;flex:1" }, [
          ce("div", { class: "backup-title", text: b.name }),
          subRow
        ]),
        backupMenu(b)
      ]),
      badges
    ]);

    // Note
    if (b.note) card.appendChild(ce("div", { class: "backup-note" }, [ce("span", { class: "q", html: icon("note") }), ce("span", { text: b.note })]));

    // Upload progress
    if (b.upload_info && typeof b.upload_info.progress === "number") card.appendChild(uploadProgress(b.slug, b.upload_info));
    else if (b.isPending) card.appendChild(uploadIndeterminate(t("backups.creating")));

    // Primary action row (only on full list, not compact peek)
    if (!compact) card.appendChild(backupActions(b));
    return card;
  }

  function uploadProgress(slug, up) {
    var pct = clampPct(up.progress);
    var dest = up.name || "Proton Drive";
    var toHA = dest === "Home Assistant";
    // The backend can track the Home-Assistant -> local staging read (real
    // progress + speed), but the proton-drive CLI reports nothing while it
    // uploads the staged file. Once staging hits 100% we therefore show an
    // honest indeterminate state instead of a frozen 100% and a decaying
    // (total ÷ elapsed) "speed".
    if (pct >= 100) {
      return ce("div", { class: "upload", "data-upload-slug": slug }, [
        ce("div", { class: "u-head" }, [ce("span", { text: toHA ? t("upload.finishing_to_ha") : t("upload.uploading_to", { dest: dest }) }), ce("b", { html: '<span class="spinner-inline"></span>' })]),
        ce("div", { class: "bar indeterminate" }, [ce("i")]),
        ce("div", { class: "u-foot" }, [
          ce("span", { class: "u-total", text: fmtBytes(up.total) }),
          ce("span", { text: toHA ? t("upload.almost_done") : t("upload.can_take_minutes") })
        ])
      ]);
    }
    return ce("div", { class: "upload", "data-upload-slug": slug }, [
      ce("div", { class: "u-head" }, [ce("span", { text: toHA ? t("upload.downloading_to_ha") : t("upload.preparing_for", { dest: dest }) }), ce("b", { class: "u-pct", text: I18n.percent(pct) })]),
      ce("div", { class: "bar" }, [ce("i", { style: "width:" + pct + "%" })]),
      ce("div", { class: "u-foot" }, [
        ce("span", { class: "u-total", text: fmtBytes(up.total) }),
        ce("span", { class: "u-speed", text: uploadFoot(up) })
      ])
    ]);
  }
  function uploadIndeterminate(label) {
    return ce("div", { class: "upload" }, [
      ce("div", { class: "u-head" }, [ce("span", { text: label }), ce("b", { html: '<span class="spinner-inline"></span>' })]),
      ce("div", { class: "bar indeterminate" }, [ce("i")])
    ]);
  }

  function backupActions(b) {
    var row = ce("div", { class: "backup-actions" });
    if (b.restorable) {
      row.appendChild(ce("button", { class: "btn sm", onclick: function () { downloadBackup(b); } }, [iconNode("download"), ce("span", { text: t("common.download") })]));
      row.appendChild(ce("button", { class: "btn ghost sm", onclick: function () { openRestore(b); } }, [iconNode("restore"), ce("span", { text: t("backups.restore") })]));
    }
    if (b.uploadable) {
      var ub = ce("button", { class: "btn ghost sm", onclick: function () { uploadBackup(b); } }, [iconNode("download"), ce("span", { text: t("backups.download_to_ha") })]);
      if (!state.status.proton_authenticated) { ub.setAttribute("disabled", ""); ub.title = t("common.sign_in_first"); }
      row.appendChild(ub);
    }
    var inProton = (b.sources || []).some(function (s) { return s.key === "ProtonDrive"; });
    if (b.restorable && !inProton && !isActive(b) && state.status.enable_proton_upload) {
      var pb = ce("button", { class: "btn ghost sm", onclick: function () { uploadBackupToProton(b); } }, [iconNode("upload"), ce("span", { text: t("backups.upload_to_proton") })]);
      if (!state.status.proton_authenticated) { pb.setAttribute("disabled", ""); pb.title = t("common.sign_in_first"); }
      row.appendChild(pb);
    }
    return row;
  }

  function backupMenu(b) {
    var wrap = ce("div", { class: "backup-menu" });
    var btn = ce("button", { class: "btn subtle icon", "aria-label": t("backups.menu.more"), "aria-haspopup": "menu", "aria-expanded": "false", html: icon("dots") });
    var open = false, menu = null;
    function close(restoreFocus) {
      if (menu) { menu.remove(); menu = null; }
      open = false;
      btn.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", outside, true);
      if (restoreFocus) try { btn.focus(); } catch (e) {}
    }
    function outside(ev) { if (menu && !wrap.contains(ev.target)) close(); }
    function items() { return menu ? Array.prototype.slice.call(menu.querySelectorAll("button")) : []; }
    function openMenu(focusFirst) {
      menu = ce("div", { class: "menu", role: "menu" });
      addItem(menu, "note", b.note ? t("backups.menu.edit_note") : t("backups.menu.add_note"), function () { openNote(b); });
      // Retain toggles per source
      (b.sources || []).forEach(function (src) {
        var place = src.key === "HomeAssistant" ? "Home Assistant" : "Proton Drive";
        var label = t(src.retained ? "backups.menu.stop_keeping" : "backups.menu.keep", { place: place });
        addItem(menu, "pin", label, function () { toggleRetain(b, src.key, !src.retained); });
      });
      addItem(menu, b.ignored ? "eye" : "ignore", b.ignored ? t("backups.menu.unignore") : t("backups.menu.ignore"), function () { toggleIgnore(b, !b.ignored); });
      addItem(menu, "info", t("common.details"), function () { openDetails(b); });
      menu.appendChild(ce("hr"));
      addItem(menu, "trash", t("backups.menu.delete"), function () { openDelete(b); }, true);
      // Arrow-key navigation + Escape, per the ARIA menu pattern.
      menu.addEventListener("keydown", function (ev) {
        var list = items(), i = list.indexOf(document.activeElement);
        if (ev.key === "Escape") { ev.preventDefault(); close(true); }
        else if (ev.key === "ArrowDown") { ev.preventDefault(); (list[i + 1] || list[0]).focus(); }
        else if (ev.key === "ArrowUp") { ev.preventDefault(); (list[i - 1] || list[list.length - 1]).focus(); }
        else if (ev.key === "Home") { ev.preventDefault(); list[0].focus(); }
        else if (ev.key === "End") { ev.preventDefault(); list[list.length - 1].focus(); }
      });
      wrap.appendChild(menu);
      open = true;
      btn.setAttribute("aria-expanded", "true");
      if (focusFirst) { var f = items()[0]; if (f) f.focus(); }
      setTimeout(function () { document.addEventListener("click", outside, true); }, 0);
    }
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (open) { close(); return; }
      openMenu(false);
    });
    // Keyboard: open with Enter/Space/ArrowDown and land on the first item.
    btn.addEventListener("keydown", function (ev) {
      if (open) return;
      if (ev.key === "ArrowDown" || ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openMenu(true); }
    });
    function addItem(m, ic, label, fn, danger) {
      m.appendChild(ce("button", { class: danger ? "danger" : "", role: "menuitem", onclick: function () { close(); fn(); } }, [iconNode(ic), ce("span", { text: label })]));
    }
    wrap.appendChild(btn);
    return wrap;
  }

  // ---- Backup operations ----
  function downloadBackup(b) {
    var href = u("/download?slug=" + encodeURIComponent(b.slug));
    if (MOCK) { toast("Download started (mock)", "info"); return; }
    var a = ce("a", { href: href, download: "" }); document.body.appendChild(a); a.click(); a.remove();
  }
  function uploadBackup(b) { action(api("/upload?slug=" + encodeURIComponent(b.slug), { method: "POST" }), t("toast.downloading_to_ha")); }
  function uploadBackupToProton(b) { action(api("/uploadToProton?slug=" + encodeURIComponent(b.slug), { method: "POST" }), t("toast.uploading_to_proton")); }
  function toggleRetain(b, sourceKey, value) {
    var sources = {}; (b.sources || []).forEach(function (s) { sources[s.key] = !!s.retained; });
    sources[sourceKey] = value;
    action(apiJson("/retain", { slug: b.slug, sources: sources }), value ? t("toast.kept") : t("toast.unkept"));
  }
  function toggleIgnore(b, value) {
    action(apiJson("/ignore", { slug: b.slug, ignore: value }), t(value ? "toast.ignored" : "toast.included", { name: b.name }));
  }
  function doSync() {
    if (state.status && state.status.syncing) { toast(t("toast.sync_already_running"), "info"); return; }
    action(api("/startSync", { method: "POST" }), t("toast.sync_started")).catch(function () {});
  }

  // ------------------------------------------------------------------------
  // View: Settings
  // ------------------------------------------------------------------------
  // getconfig sends this in place of a saved backup password, and saveconfig
  // maps it back (PASSWORD_PLACEHOLDER in uiserver.py).
  var PASSWORD_PLACEHOLDER = "<unchanged>";

  // Text comes from the catalogs, by key: settings.group.<id>.title/.desc and
  // setting.<key>.label/.help/.placeholder (help and placeholder optional).
  var SETTINGS_GROUPS = [
    {
      id: "schedule", icon: "clock",
      fields: [
        // step "any": a value from the Configuration tab like 0.25 failed
        // step 0.1's check, so the browser refused to submit the whole form.
        { key: "days_between_backups", type: "number", step: "any", min: 0 },
        { key: "backup_time_of_day", type: "time" },
        { key: "max_backups_in_ha", type: "number", min: 0 },
        { key: "max_backups_in_proton_drive", type: "number", min: 0 },
        { key: "backup_name", type: "text", template: true },
        { key: "backup_password", type: "password" },
        { key: "delete_before_new_backup", type: "bool" },
        { key: "call_backup_snapshot", type: "bool" }
      ]
    },
    {
      id: "proton", icon: "cloud",
      fields: [
        { key: "enable_proton_upload", type: "bool" },
        { key: "proton_folder_name", type: "text" },
        { key: "delete_after_upload", type: "bool" },
        { key: "permanently_delete", type: "bool" },
        { key: "proton_drive_timeout_seconds", type: "number", step: "any", min: 1, advanced: true },
        { key: "proton_transfer_timeout_seconds", type: "number", step: "any", min: 1, advanced: true }
      ]
    },
    {
      id: "contents", icon: "folder",
      fields: [
        { key: "exclude_folders", type: "folders" },
        { key: "exclude_addons", type: "addons" },
        { key: "exclude_ha_database", type: "bool" }
      ]
    },
    {
      id: "generational", icon: "archive",
      advanced: true,
      dynamicNote: generationalWarningText,
      fields: [
        { key: "generational_days", type: "number", min: 0 },
        { key: "generational_weeks", type: "number", min: 0 },
        { key: "generational_months", type: "number", min: 0 },
        { key: "generational_years", type: "number", min: 0 },
        { key: "generational_day_of_week", type: "select", options: weekdayOpts },
        { key: "generational_day_of_month", type: "number", min: 1, max: 31 },
        { key: "generational_day_of_year", type: "number", min: 1, max: 365 },
        { key: "generational_delete_early", type: "bool" }
      ]
    },
    {
      id: "stop_addons", icon: "bolt",
      advanced: true,
      fields: [
        { key: "stop_addons", type: "addons" }
      ]
    },
    {
      id: "notifications", icon: "info",
      fields: [
        { key: "notify_for_stale_backups", type: "bool" },
        { key: "enable_backup_stale_sensor", type: "bool" },
        { key: "enable_backup_state_sensor", type: "bool" }
      ]
    },
    {
      id: "retention", icon: "list", advanced: true,
      fields: [
        { key: "ignore_other_backups", type: "bool" },
        { key: "ignore_upgrade_backups", type: "bool" },
        { key: "delete_ignored_after_days", type: "text" }
      ]
    },
    {
      id: "appearance", icon: "eye",
      fields: [
        { key: "background_color", type: "color" },
        { key: "accent_color", type: "color" }
      ]
    },
    {
      id: "server", icon: "settings", advanced: true,
      fields: [
        { key: "expose_extra_server", type: "bool" },
        { key: "require_login", type: "bool" },
        { key: "use_ssl", type: "bool" },
        { key: "certfile", type: "text" },
        { key: "keyfile", type: "text" },
        { key: "port", type: "number", min: 0 }
      ]
    },
    {
      id: "advanced", icon: "bug", advanced: true,
      fields: [
        { key: "confirm_multiple_deletes", type: "bool" },
        { key: "warn_for_low_space", type: "bool" },
        { key: "watch_backup_directory", type: "bool" },
        { key: "log_level", type: "select", options: enumOpts(["DEBUG", "TRACE", "INFO", "WARN", "WARNING", "CRITICAL"]) },
        { key: "console_log_level", type: "select", options: enumOpts(["DEBUG", "TRACE", "INFO", "WARN", "WARNING", "CRITICAL"]) },
        { key: "proton_cli_path", type: "text" },
        { key: "proton_data_path", type: "text" },
        { key: "max_sync_interval_seconds", type: "text" }
      ]
    }
  ];
  function enumOpts(arr) { return arr.map(function (x) { return [x, x]; }); }
  // Weekday names in the UI's language, built when the field renders.
  function weekdayOpts() {
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map(function (d, i) { return [d, I18n.weekday(i)]; });
  }

  // Effective (draft > saved > default) value of a setting being edited.
  function effVal(key) {
    var draft = state.configDraft || {};
    var cfg = (state.config && state.config.config) || {};
    var defs = (state.config && state.config.defaults) || {};
    if (key in draft) return draft[key] === "" ? defs[key] : draft[key];
    return cfg[key] != null && cfg[key] !== "" ? cfg[key] : defs[key];
  }
  function effNum(key) { return Number(effVal(key)) || 0; }
  function effBool(key) { var v = effVal(key); return v === true || v === "true"; }

  // Mirrors Config.generationalSlotCount + the caps check on the backend.
  function generationalWarningText() {
    var days = effNum("generational_days"), weeks = effNum("generational_weeks");
    var months = effNum("generational_months"), years = effNum("generational_years");
    if (days + weeks + months + years === 0) return null;
    var slots = Math.max(days, 1) + weeks + months + years;
    var caps = ["max_backups_in_proton_drive"];
    // With delete-after-upload the HA cap never applies.
    if (!effBool("delete_after_upload")) caps.unshift("max_backups_in_ha");
    var tight = [];
    caps.forEach(function (key) {
      var cap = effNum(key);
      if (cap > 0 && cap < slots) tight.push(t("settings.generational_warning.limit", { label: t("setting." + key + ".label"), n: cap }));
    });
    if (!tight.length) return null;
    return t("settings.generational_warning.text", { n: slots, limits: I18n.list(tight) });
  }

  var showAdvanced = false;

  function viewSettings(host) {
    if (!state.config) {
      host.appendChild(ce("div", { class: "card" }, [centerSpinner(t("settings.loading"))]));
      return;
    }
    var cfg = state.config.config || {};
    var card = ce("div", { class: "card" });
    card.appendChild(ce("div", { class: "card-head" }, [
      ce("h2", { text: t("tab.settings") }), ce("div", { class: "spacer" }),
      switchControl(t("settings.show_advanced"), showAdvanced, function (v) { showAdvanced = v; renderView(); })
    ]));

    var form = ce("form", { id: "settings-form", onsubmit: function (e) { e.preventDefault(); saveConfig(); } });

    SETTINGS_GROUPS.forEach(function (g) {
      var fields = g.fields.filter(function (f) { return showAdvanced || !f.advanced; });
      if (!showAdvanced && g.advanced) return;
      if (!fields.length) return;
      var body = ce("div", { class: "group-body" });
      var descKey = "settings.group." + g.id + ".desc";
      if (I18n.has(descKey)) body.appendChild(ce("div", { class: "group-desc", text: t(descKey) }));
      if (g.dynamicNote) {
        var note = ce("div", { class: "group-warning", style: "display:none" });
        note._compute = g.dynamicNote;
        body.appendChild(note);
      }
      fields.forEach(function (f) { body.appendChild(renderField(f, cfg)); });
      var grp = ce("details", { class: "settings-group", open: true }, [
        ce("summary", {}, [iconNode(g.icon), ce("span", { text: t("settings.group." + g.id + ".title") }), ce("span", { class: "chev", html: icon("chev") })]),
        body
      ]);
      form.appendChild(grp);
    });

    form.appendChild(ce("div", { class: "settings-actions" }, [
      ce("button", { class: "btn", type: "submit" }, [iconNode("check"), ce("span", { text: t("settings.save") })]),
      ce("button", { class: "btn ghost", type: "button", text: t("settings.reset"), onclick: function () { state.configDraft = {}; state.badNumbers = {}; renderView(); } })
    ]));
    // Field listeners fire on the target first, so drafts are current here.
    function refreshNotes() {
      form.querySelectorAll(".group-warning").forEach(function (note) {
        var txt = note._compute ? note._compute() : null;
        note.textContent = txt || "";
        note.style.display = txt ? "" : "none";
      });
    }
    form.addEventListener("input", refreshNotes);
    form.addEventListener("change", refreshNotes);
    refreshNotes();
    card.appendChild(form);
    host.appendChild(card);
  }

  function renderField(f, cfg) {
    // Prefer an unsaved draft value so edits survive view rebuilds (tab
    // switches, the advanced toggle). Falls back to the saved config value.
    var draft = state.configDraft || {};
    var val = (f.key in draft) ? draft[f.key] : cfg[f.key];
    var defs = (state.config && state.config.defaults) || {};
    var wrap = ce("div", { class: "field" });
    var id = "set-" + f.key;
    var label = t("setting." + f.key + ".label");
    var helpKey = "setting." + f.key + ".help", placeholderKey = "setting." + f.key + ".placeholder";
    var help = I18n.has(helpKey) ? t(helpKey) : null;

    if (f.type === "bool") {
      wrap.appendChild(ce("div", {}, [switchControl(label, !!val, function (v) { draft[f.key] = v; }, id, f.key)]));
      if (help) wrap.appendChild(ce("div", { class: "help", text: help }));
      return wrap;
    }

    wrap.appendChild(ce("label", { for: id, text: label }));
    if (help) wrap.appendChild(ce("div", { class: "help", text: help }));

    if (f.type === "select") {
      var sel = ce("select", { id: id, "data-key": f.key });
      sel.appendChild(ce("option", { value: "", text: t("settings.default_option") }));
      (typeof f.options === "function" ? f.options() : f.options).forEach(function (o) { sel.appendChild(ce("option", { value: o[0], text: o[1] })); });
      sel.value = val != null ? String(val) : "";
      sel.addEventListener("change", function () { draft[f.key] = sel.value; });
      wrap.appendChild(sel);
    } else if (f.type === "color") {
      var def = defs[f.key] || (f.key === "accent_color" ? "#1a5fb4" : "#0b1020");
      var cur = (val && /^#/.test(val)) ? val : def;
      var color = ce("input", { type: "color", value: cur, id: id });
      var text = ce("input", { type: "text", value: val || "", placeholder: def, "data-key": f.key, "data-color": id });
      color.addEventListener("input", function () { text.value = color.value; draft[f.key] = text.value; });
      text.addEventListener("input", function () { if (/^#[0-9a-fA-F]{6}$/.test(text.value)) color.value = text.value; draft[f.key] = text.value; });
      wrap.appendChild(ce("div", { class: "color-field" }, [color, text]));
    } else if (f.type === "folders" || f.type === "addons") {
      var box = multiCheck(f, val);
      box.addEventListener("change", function () {
        var vals = [];
        box.querySelectorAll("input[type=checkbox]").forEach(function (c) { if (c.checked) vals.push(c.value); });
        draft[f.key] = vals.join(",");
      });
      wrap.appendChild(box);
    } else {
      var attrs = { id: id, "data-key": f.key, type: f.type === "password" ? "password" : f.type === "number" ? "number" : f.type === "time" ? "time" : "text", value: val == null ? "" : val };
      if (f.min != null) attrs.min = f.min;
      if (f.max != null) attrs.max = f.max;
      if (f.step != null) attrs.step = f.step;
      if (I18n.has(placeholderKey)) attrs.placeholder = t(placeholderKey);
      else if (defs[f.key] != null && defs[f.key] !== "") attrs.placeholder = t("settings.default_placeholder", { value: defs[f.key] });
      var input = ce("input", attrs);
      // Rebuilt from the draft or saved value, which is a number.
      delete state.badNumbers[f.key];
      // Empty = "use the default": drafted as "" (never Number("") = 0, which
      // fields with a minimum reject), and collectConfig doesn't send it.
      input.addEventListener("input", function () {
        // Text the browser can't read as a number ("0,5" where the decimal
        // mark is a point, "1e400") also reads as "", but isn't "use the
        // default": keep the draft and refuse to save (saveConfig).  While the
        // field is shown, the browser refuses too; hidden by "Show advanced",
        // it would otherwise have been reset to its default.
        if (f.type === "number" && input.validity.badInput) { state.badNumbers[f.key] = true; return; }
        delete state.badNumbers[f.key];
        draft[f.key] = f.type === "number" && input.value !== "" ? Number(input.value) : input.value;
      });
      if (f.type === "password" && val === PASSWORD_PLACEHOLDER) {
        // The field stands in for the saved password; the first edit replaces
        // the placeholder instead of extending it.
        input.addEventListener("beforeinput", function () {
          if (input.value === PASSWORD_PLACEHOLDER) input.value = "";
        });
      }
      wrap.appendChild(input);
      if (f.template) wrap.appendChild(templateHints());
    }
    return wrap;
  }

  function templateHints() {
    var keys = (state.status && state.status.backup_name_keys) || {};
    var box = ce("div", { class: "row", style: "margin-top:8px;gap:6px" });
    Object.keys(keys).forEach(function (k) {
      box.appendChild(ce("button", {
        class: "pill neutral", type: "button", title: keys[k], text: "{" + k + "}",
        onclick: function () {
          var inp = el('[data-key="backup_name"]'); if (inp) { inp.value += "{" + k + "}"; state.configDraft["backup_name"] = inp.value; inp.focus(); }
        }
      }));
    });
    return box;
  }

  // The backend sends folder names and descriptions in English (FOLDERS in
  // backup/const.py); translate them by slug.
  var FOLDER_TEXT = {
    "homeassistant": ["folder.homeassistant.name", "folder.homeassistant.desc"],
    "media": ["folder.media.name", "folder.media.desc"],
    "ssl": ["folder.ssl.name", "folder.ssl.desc"],
    "share": ["folder.share.name", "folder.share.desc"],
    "addons/local": ["folder.addons_local.name", "folder.addons_local.desc"]
  };
  function multiCheck(f, val) {
    var items = f.type === "folders" ? (state.config.folders || []) : (state.config.addons || []);
    var selected = parseCsv(val);
    var box = ce("div", { class: "checks", "data-multi": f.key, "data-kind": f.type });
    if (!items.length) { box.appendChild(ce("div", { class: "help", text: f.type === "addons" ? t("settings.no_addons") : t("settings.no_folders") })); return box; }
    items.forEach(function (it) {
      var slug = it.slug;
      var text = f.type === "folders" ? FOLDER_TEXT[slug] : null;
      var name = text ? t(text[0]) : (it.name || it.slug);
      var desc = text ? t(text[1]) : it.description;
      var lbl = ce("label", {}, [
        ce("input", { type: "checkbox", value: slug, checked: selected.indexOf(slug) >= 0 }),
        ce("div", {}, [ce("div", { class: "cx-name", text: name }), desc ? ce("div", { class: "cx-desc", text: desc }) : (it.version ? ce("div", { class: "cx-desc", text: "v" + it.version }) : null)])
      ]);
      box.appendChild(lbl);
    });
    return box;
  }
  function parseCsv(v) {
    if (v == null) return [];
    if (Array.isArray(v)) return v.slice();
    return String(v).split(",").map(function (x) { return x.trim(); }).filter(Boolean);
  }

  function loadConfig() {
    withBusy(api("/getconfig")).then(function (d) { state.config = d; if (state.tab === "settings") renderView(); })
      .catch(function (e) { toast(errText(e, "settings.load_failed"), "bad"); });
  }

  // A save that reloads the page (reload_page: the colours, for one) should
  // come back to Settings, not the dashboard. The note is only good for a few
  // seconds, so a reload that never came back doesn't redirect a later visit.
  // sessionStorage throws where storage is blocked; the dashboard is fine then.
  var RETURN_KEY = "protonDriveBackup.returnToSettings";
  function returnToSettings() {
    try { sessionStorage.setItem(RETURN_KEY, String(Date.now())); } catch (e) {}
  }
  function returningToSettings() {
    try {
      var since = Date.now() - Number(sessionStorage.getItem(RETURN_KEY));
      sessionStorage.removeItem(RETURN_KEY);
      return since >= 0 && since < 30000;
    } catch (e) { return false; }
  }

  function collectConfig() {
    var out = {};
    // The backend replaces every option on save, so start from the saved
    // values, then drafted edits: fields hidden by the advanced toggle aren't
    // in the DOM and would otherwise reset to their defaults.  Visible fields
    // are then overridden from the live DOM below.  "" = use the default.
    [(state.config && state.config.config) || {}, state.configDraft || {}].forEach(function (src) {
      Object.keys(src).forEach(function (k) {
        if (src[k] == null || src[k] === "") delete out[k]; else out[k] = src[k];
      });
    });
    var form = el("#settings-form"); if (!form) return out;
    // scalar inputs
    form.querySelectorAll("[data-key]").forEach(function (inp) {
      // The <input type=color> swatch has no data-key (only its paired text
      // input does), so each setting is collected exactly once.
      var key = inp.getAttribute("data-key");
      if (inp.type === "checkbox") { out[key] = inp.checked; return; }
      var v = inp.value;
      // Empty = "use the default": omit it. The backend drops default-valued
      // settings anyway, and submitting 0 / "" can violate a field's minimum
      // (e.g. max_sync_interval_seconds, which wants a duration string).
      if (v === "") { delete out[key]; return; }
      if (inp.tagName === "SELECT") { out[key] = v; return; }
      if (inp.type === "number") { out[key] = Number(v); return; }
      out[key] = v;
    });
    // multi-checks -> comma string
    form.querySelectorAll("[data-multi]").forEach(function (box) {
      var key = box.getAttribute("data-multi");
      var vals = [];
      box.querySelectorAll("input[type=checkbox]").forEach(function (c) { if (c.checked) vals.push(c.value); });
      out[key] = vals.join(",");
    });
    return out;
  }

  function saveConfig() {
    var bad = Object.keys(state.badNumbers);
    if (bad.length) { toast(t("settings.bad_number", { setting: t("setting." + bad[0] + ".label") }), "bad"); return; }
    var cfg = collectConfig();
    var btn = el('#settings-form button[type="submit"]');
    if (btn) { btn.setAttribute("disabled", ""); btn.querySelector("span").textContent = t("settings.saving"); }
    setBusy(true);
    apiJson("/saveconfig", { config: cfg }).then(function (d) {
      toast(t("settings.saved"), "ok");
      // The backend's warning is English; this view computes the same check
      // (generationalWarningText) from the values just saved.
      if (d && d.warning) toast(generationalWarningText() || d.warning, "warn", 12000);
      state.configDraft = {};   // edits are now persisted server-side
      if (d && d.reload_page) { returnToSettings(); setTimeout(function () { location.reload(); }, 600); return; }
      loadConfig();
      scheduleRefresh(400);
    }).catch(function (e) {
      toast(errText(e, "settings.save_failed"), "bad");
    }).then(function () {
      setBusy(false);
      if (btn) { btn.removeAttribute("disabled"); btn.querySelector("span").textContent = t("settings.save"); }
    });
  }

  // ------------------------------------------------------------------------
  // View: Logs
  // ------------------------------------------------------------------------
  var logState = { text: "", loading: false };
  function viewLogs(host) {
    var card = ce("div", { class: "card" });
    card.appendChild(ce("div", { class: "card-head" }, [
      ce("h2", { text: t("logs.title") }), ce("div", { class: "spacer" }),
      ce("button", { class: "btn ghost sm", onclick: loadLogs }, [iconNode("refresh"), ce("span", { text: t("logs.refresh") })]),
      ce("button", { class: "btn subtle sm", onclick: function () {
        if (MOCK) { toast("Download (mock)", "info"); return; }
        var a = ce("a", { href: u("/log?format=download") }); document.body.appendChild(a); a.click(); a.remove();
      } }, [iconNode("download"), ce("span", { text: t("common.download") })])
    ]));
    var view = ce("pre", { class: "log-view", id: "log-view" });
    if (logState.loading) view.appendChild(centerSpinner(t("logs.loading")));
    else view.innerHTML = colorizeLog(logState.text || t("logs.empty"));
    card.appendChild(view);
    host.appendChild(card);
  }
  function loadLogs() {
    logState.loading = true; if (state.tab === "logs") renderView();
    var p = MOCK ? window.MockServer.log() : fetch(u("/log?format=view")).then(function (r) { return r.text(); });
    Promise.resolve(p).then(function (txt) {
      logState.text = txt; logState.loading = false;
      if (state.tab === "logs") { renderView(); var v = el("#log-view"); if (v) v.scrollTop = v.scrollHeight; }
    }).catch(function () { logState.loading = false; logState.text = t("logs.load_failed"); if (state.tab === "logs") renderView(); });
  }
  function colorizeLog(txt) {
    return esc(txt).replace(/\b(ERROR|CRITICAL|WARNING|WARN|DEBUG|TRACE)\b/g, '<span class="lvl-$1">$1</span>');
  }

  // ------------------------------------------------------------------------
  // View: About
  // ------------------------------------------------------------------------
  function viewAbout(host) {
    var s = state.status || {};
    host.appendChild(ce("div", { class: "card" }, [
      ce("h2", { text: t("tab.about") }),
      ce("p", { class: "dim", text: t("about.intro") }),
      ce("div", { class: "grid cols-2 mt" }, [
        statTile(t("about.version"), "v" + VERSION, null, "info"),
        statTile("Proton Drive", s.proton_authenticated ? t("common.signed_in") : t("common.signed_out"), s.proton_folder ? t("common.folder", { folder: s.proton_folder }) : null, "cloud")
      ]),
      ce("div", { class: "btn-row mt" }, [
        ce("button", { class: "btn ghost", onclick: openBugReport }, [iconNode("bug"), ce("span", { text: t("about.bug_report") })]),
        ce("button", { class: "btn subtle", onclick: function () { state.tab = "logs"; render(); loadLogs(); } }, [iconNode("doc"), ce("span", { text: t("about.view_logs") })])
      ])
    ]));
    if (!s.proton_authenticated) {
      host.appendChild(ce("div", { class: "card" }, [
        ce("h2", { text: t("about.signin.title") }),
        s.proton_auth_warning ? ce("p", { class: "dim", text: t("about.last_check", { warning: s.proton_auth_warning }) }) : null,
        ce("p", { class: "dim", text: t("about.signin.help") }),
        ce("p", { class: "dim", text: t("common.third_party") }),
        ce("button", { class: "btn", onclick: openLogin }, [iconNode("link"), ce("span", { text: t("common.sign_in_to_proton") })])
      ]));
    } else {
      host.appendChild(ce("div", { class: "card" }, [
        ce("h2", { text: t("about.account.title") }),
        // Signed out with uploads on, the add-on makes no backups at all
        // (renderAuthBanner); with uploads off, signing out changes nothing.
        ce("p", { class: "dim", text: s.proton_auth_warning ? t("about.account.unverified")
          : t(s.enable_proton_upload ? "about.account.signed_in" : "about.account.signed_in_upload_off") }),
        ce("div", { class: "btn-row" }, [
          s.proton_auth_warning ? ce("button", { class: "btn", onclick: openLogin }, [iconNode("link"), ce("span", { text: t("common.sign_in_again") })]) : null,
          ce("button", { class: "btn ghost", onclick: openProtonLogout }, [iconNode("x"), ce("span", { text: t("common.sign_out") })])
        ])
      ]));
    }
  }

  // ------------------------------------------------------------------------
  // Reusable controls
  // ------------------------------------------------------------------------
  function pill(kind, ic, text) {
    return ce("span", { class: "pill " + kind }, [ic ? iconNode(ic) : null, ce("span", { text: text })]);
  }
  function switchControl(label, checked, onChange, id, dataKey) {
    var input = ce("input", { type: "checkbox" });
    if (checked) input.checked = true;
    if (id) input.id = id;
    if (dataKey) input.setAttribute("data-key", dataKey);
    if (onChange) input.addEventListener("change", function () { onChange(input.checked); });
    return ce("label", { class: "switch" }, [input, ce("span", { class: "track" }), ce("span", { class: "switch-label", text: label })]);
  }
  function emptyState(ic, title, msg) {
    var e = ce("div", { class: "empty" });
    var i = ce("div", { class: "e-ico" }); i.innerHTML = icon(ic); e.appendChild(i);
    e.appendChild(ce("div", { style: "font-weight:700;font-size:1.05rem", text: title }));
    e.appendChild(ce("div", { text: msg }));
    return e;
  }
  function centerSpinner(label) {
    return ce("div", { class: "row", style: "justify-content:center;padding:30px;color:var(--text-dim)" }, [
      ce("span", { class: "spinner-inline" }), ce("span", { text: label || t("common.loading") })
    ]);
  }

  // ------------------------------------------------------------------------
  // Modals
  // ------------------------------------------------------------------------
  var modalHost = null, modalOnClose = null, modalLastFocus = null;
  var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  function openModal(node, opts) {
    closeModal();
    modalOnClose = (opts && opts.onClose) || null;
    // Remember where focus was so we can restore it when the dialog closes.
    modalLastFocus = document.activeElement;
    modalHost = ce("div", { class: "modal-backdrop", onclick: function (e) { if (e.target === modalHost && (!opts || opts.dismissable !== false)) closeModal(); } }, [node]);
    document.body.appendChild(modalHost);
    document.addEventListener("keydown", escClose, true);
    document.addEventListener("keydown", trapFocus, true);
    var f = node.querySelector(FOCUSABLE); if (f) try { f.focus(); } catch (e) {}
  }
  function escClose(e) { if (e.key === "Escape") closeModal(); }
  // Keep Tab focus inside the open dialog (wrap at both ends).
  function trapFocus(e) {
    if (e.key !== "Tab" || !modalHost) return;
    var f = modalHost.querySelectorAll(FOCUSABLE);
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1], active = document.activeElement;
    if (e.shiftKey && (active === first || !modalHost.contains(active))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (active === last || !modalHost.contains(active))) { e.preventDefault(); first.focus(); }
  }
  function closeModal() {
    if (!modalHost) return;
    modalHost.remove(); modalHost = null;
    document.removeEventListener("keydown", escClose, true);
    document.removeEventListener("keydown", trapFocus, true);
    var cb = modalOnClose; modalOnClose = null;
    var prev = modalLastFocus; modalLastFocus = null;
    if (prev && prev.focus) try { prev.focus(); } catch (e) {}
    if (cb) cb();   // e.g. cancel an abandoned Proton login
  }
  function modal(title, ic, bodyChildren, footChildren, wide) {
    return ce("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true", "aria-label": title }, [
      ce("div", { class: "modal-head" }, [iconNode(ic), ce("h3", { text: title }), ce("button", { class: "btn subtle icon x", "aria-label": t("common.close"), html: icon("x"), onclick: closeModal })]),
      ce("div", { class: "modal-body" }, bodyChildren),
      footChildren ? ce("div", { class: "modal-foot" }, footChildren) : null
    ]);
  }

  // ---- Create backup ----
  function openCreateBackup() {
    var s = state.status || {};
    var nameInput = ce("input", { type: "text", placeholder: s.backup_name_template || t("create.name_placeholder") });
    var noteInput = ce("textarea", { placeholder: t("create.note_placeholder") });
    var retainHa = ce("input", { type: "checkbox" });
    var retainProton = ce("input", { type: "checkbox" });
    var body = [
      ce("div", { class: "field" }, [ce("label", { text: t("common.name") }), ce("div", { class: "help", text: t("create.name_help") }), nameInput]),
      ce("div", { class: "field" }, [ce("label", { text: t("common.note") }), noteInput]),
      ce("div", { class: "field" }, [
        ce("label", { id: "create-keep-label", text: t("create.keep") }),
        ce("div", { class: "checks", role: "group", "aria-labelledby": "create-keep-label" }, [
          ce("label", {}, [retainHa, ce("div", {}, [ce("div", { class: "cx-name", text: t("create.keep_in", { place: "Home Assistant" }) })])]),
          ce("label", {}, [retainProton, ce("div", {}, [ce("div", { class: "cx-name", text: t("create.keep_in", { place: "Proton Drive" }) })])])
        ])
      ])
    ];
    var foot = [
      ce("button", { class: "btn ghost", text: t("common.cancel"), onclick: closeModal }),
      ce("button", { class: "btn", onclick: function () {
        var query = qs({ custom_name: nameInput.value, note: noteInput.value, retain_ha: retainHa.checked, retain_proton: retainProton.checked });
        closeModal();
        action(api("/backup" + (query ? "?" + query : ""), { method: "POST" }), t("toast.backup_requested"));
      } }, [iconNode("plus"), ce("span", { text: t("create.submit") })])
    ];
    openModal(modal(t("create.title"), "plus", body, foot));
  }

  // ---- Delete ----
  function openDelete(b) {
    var sources = (b.sources || []).map(function (s) { return s.key; });
    var picks = {};
    var rows = (b.sources || []).map(function (src) {
      var input = ce("input", { type: "checkbox", checked: true, value: src.key });
      picks[src.key] = true;
      input.addEventListener("change", function () { picks[src.key] = input.checked; updateBtn(); });
      var isHa = src.key === "HomeAssistant";
      return ce("label", {}, [input, ce("div", {}, [
        ce("div", { class: "cx-name", text: isHa ? "Home Assistant" : "Proton Drive" }),
        ce("div", { class: "cx-desc", text: fmtBytes(src.size) })
      ])]);
    });
    var warn = ce("div", { class: "banner warn", style: "margin:0 0 4px" }, [
      iconNode("warn", "b-ico"),
      ce("div", { class: "b-body" }, [ce("div", { class: "b-msg", text: t("delete.warning") })])
    ]);
    var body = [warn, ce("div", { class: "field" }, [ce("label", { text: t("delete.from") }), ce("div", { class: "checks" }, rows)])];
    var delBtn = ce("button", { class: "btn danger", onclick: function () {
      var chosen = Object.keys(picks).filter(function (k) { return picks[k]; });
      if (!chosen.length) return;
      closeModal();
      action(apiJson("/deleteSnapshot", { slug: b.slug, sources: chosen }), t("toast.deleted"));
    } }, [iconNode("trash"), ce("span", { text: t("common.delete") })]);
    function updateBtn() {
      var n = Object.keys(picks).filter(function (k) { return picks[k]; }).length;
      delBtn.querySelector("span").textContent = n ? t("delete.from_places", { n: n }) : t("common.delete");
      delBtn.toggleAttribute("disabled", n === 0);
    }
    updateBtn();
    openModal(modal(t("delete.title", { name: b.name }), "trash", body, [ce("button", { class: "btn ghost", text: t("common.cancel"), onclick: closeModal }), delBtn]));
  }

  // ---- Restore ----
  function openRestore(b) {
    var s = state.status || {};
    // ha_url_base is a template like "https://{host}:8123/" — the backend
    // doesn't know the address the user browses HA from, so fill in the
    // current hostname and drop the trailing slash before appending a path.
    // Per the URL spec location.hostname keeps an IPv6 address's brackets
    // (e.g. "[::1]"); add them only if an engine ever returns it bare, since
    // the template appends ":<port>".
    var host = location.hostname;
    if (host.indexOf(":") !== -1 && host.charAt(0) !== "[") host = "[" + host + "]";
    var haBase = (s.ha_url_base || "").replace("{host}", host).replace(/\/+$/, "");
    var body = [
      ce("p", { class: "dim", text: t("restore.intro") }),
      ce("div", { class: "banner info", style: "margin:0" }, [
        iconNode("info", "b-ico"),
        ce("div", { class: "b-body" }, [
          ce("div", { class: "b-title", text: t("restore.how_title") }),
          // tHtml keeps the message's own <b> markup and escapes the name.
          ce("div", { class: "b-msg", html: I18n.tHtml("restore.how_html", { name: b.name }) })
        ])
      ])
    ];
    var foot = [
      ce("button", { class: "btn ghost", text: t("common.close"), onclick: closeModal }),
      ce("button", { class: "btn", onclick: function () { downloadBackup(b); } }, [iconNode("download"), ce("span", { text: t("restore.download") })])
    ];
    if (haBase) foot.unshift(ce("a", { class: "btn subtle", href: haBase + "/config/backup/backups", target: "_blank", rel: "noopener", text: t("restore.open_ha") }));
    openModal(modal(t("restore.title"), "restore", body, foot));
  }

  // ---- Note ----
  function openNote(b) {
    var ta = ce("textarea", { placeholder: t("note.placeholder") }); ta.value = b.note || "";
    var foot = [
      ce("button", { class: "btn ghost", text: t("common.cancel"), onclick: closeModal }),
      ce("button", { class: "btn", text: t("note.save"), onclick: function () { closeModal(); action(apiJson("/note", { slug: b.slug, note: ta.value }), t("toast.note_saved")); } })
    ];
    openModal(modal(t("common.note"), "note", [ce("div", { class: "field" }, [ta])], foot));
  }

  // ---- Details ----
  function openDetails(b) {
    var date = I18n.dateTime(b.timestamp) || b.date;
    var ago = I18n.relTime(b.timestamp) || b.createdAt;
    var rows = [
      [t("common.name"), b.name], [t("details.created"), t("details.created_value", { date: date, ago: ago })], [t("details.size"), b.size],
      [t("details.type"), typeText(b.type)], [t("details.ha_version"), b.haVersion || "—"],
      [t("details.encrypted"), b.protected ? t("common.yes") : t("common.no")], [t("details.slug"), b.slug], [t("details.status"), statusText(b.status) || "—"]
    ];
    var dl = ce("div", { class: "grid", style: "gap:10px" });
    rows.forEach(function (r) {
      dl.appendChild(ce("div", { class: "between", style: "border-bottom:1px solid var(--stroke);padding-bottom:8px" }, [
        ce("span", { class: "muted", text: r[0] }), ce("span", { style: "text-align:right;word-break:break-word", text: String(r[1]) })
      ]));
    });
    var locs = ce("div", { class: "backup-badges", style: "margin-top:14px" });
    (b.sources || []).forEach(function (src) {
      var isHa = src.key === "HomeAssistant";
      locs.appendChild(ce("span", { class: "loc " + (isHa ? "ha" : "proton") }, [iconNode(isHa ? "home" : "cloud"), ce("span", { text: (isHa ? "Home Assistant" : "Proton Drive") + (src.size ? " · " + fmtBytes(src.size) : "") })]));
    });
    var body = [dl, ce("div", { style: "margin-top:6px" }, [ce("div", { class: "muted", style: "font-size:.8rem;margin-bottom:6px", text: t("details.stored_in") }), locs])];
    if ((b.folders || []).length) body.push(ce("div", { class: "mt" }, [ce("div", { class: "muted", style: "font-size:.8rem", text: t("details.folders") }), ce("div", { text: b.folders.join(", ") })]));
    if ((b.addons || []).length) body.push(ce("div", { class: "mt" }, [ce("div", { class: "muted", style: "font-size:.8rem", text: t("details.addons") }), ce("div", { text: b.addons.map(function (a) { return a.name; }).join(", ") })]));
    openModal(modal(t("details.title"), "info", body, [ce("button", { class: "btn ghost", text: t("common.close"), onclick: closeModal })], true));
  }

  // ---- Error details ----
  function openErrorDetails(e) {
    var text = errText(e, "error.generic.message");
    var body = [
      ce("p", { text: text }),
      // The backend's own wording too, when it was translated away: it's what
      // the log and a bug report will show.
      e.message && e.message !== text ? ce("p", { class: "muted", text: e.message }) : null,
      e.details ? ce("pre", { class: "log-view", text: e.details }) : null
    ];
    var foot = [
      ce("button", { class: "btn ghost", text: t("common.close"), onclick: closeModal }),
      ce("button", { class: "btn", onclick: function () { closeModal(); openBugReport(); } }, [iconNode("bug"), ce("span", { text: t("common.report_bug") })])
    ];
    openModal(modal(t("error.details_title"), "alert", body, foot, true));
  }

  // ---- Bug report ----
  function openBugReport() {
    var pre = ce("pre", { class: "log-view", text: t("bug.gathering") });
    var copyBtn = ce("button", { class: "btn", onclick: function () {
      navigator.clipboard ? navigator.clipboard.writeText(pre.textContent).then(function () { toast(t("toast.copied"), "ok"); }, function () { toast(t("toast.copy_failed"), "bad"); })
        : toast(t("toast.clipboard_unavailable"), "bad");
    } }, [iconNode("copy"), ce("span", { text: t("bug.copy") })]);
    openModal(modal(t("bug.title"), "bug", [
      ce("p", { class: "dim", text: t("bug.help") }),
      pre
    ], [ce("button", { class: "btn ghost", text: t("common.close"), onclick: closeModal }), copyBtn], true));
    api("/makeanissue").then(function (d) { pre.textContent = (d && d.markdown) || t("bug.none"); })
      .catch(function (e) { pre.textContent = errText(e, "bug.failed"); });
  }

  // ---- Proton login ----
  function loginModalOpen() { return !!(modalHost && modalHost.querySelector("#login-modal")); }
  function openLogin() {
    state.pendingLogin = false;
    var body = ce("div", { id: "login-modal" });
    var foot = ce("div", { class: "row", style: "width:100%;justify-content:flex-end" });
    var node = modal(t("login.title"), "cloud", [body], null);
    // Closing the dialog any way (Escape, backdrop, X, Cancel) must abandon an
    // in-progress login so we don't leave a dangling CLI session + 2s polling.
    openModal(node, { onClose: cancelPendingLogin });
    renderLoginStart(body, foot, node);
    scheduleRefresh(400);
  }
  function renderLoginStart(body, foot, node) {
    body.innerHTML = "";
    body.appendChild(ce("p", { class: "dim", text: t("login.intro") }));
    body.appendChild(ce("p", { class: "dim", text: t("common.third_party") }));
    function failed(msg) {
      toast(msg, "bad");
      startBtn.removeAttribute("disabled"); startBtn.querySelector("span").textContent = t("login.start");
    }
    var startBtn = ce("button", { class: "btn", onclick: function () {
      startBtn.setAttribute("disabled", ""); startBtn.querySelector("span").textContent = t("login.starting");
      api("/protonlogin", { method: "POST" }).then(function (d) {
        if (d && d.ok && d.url) { state.pendingLogin = true; renderLoginPending(body, d.url); scheduleRefresh(400); }
        // Not error.proton_cant_connect.message: it ends "the add-on will keep
        // retrying automatically", and nothing retries a sign-in.
        else failed(d && d.error_type === "proton_cant_connect" ? t("login.unreachable") : errText(d, "login.start_failed"));
      }).catch(function (e) { failed(errText(e, "login.start_failed")); });
    } }, [iconNode("link"), ce("span", { text: t("login.start") })]);
    body.appendChild(ce("div", { class: "btn-row" }, [startBtn]));
  }
  function renderLoginPending(body, url) {
    body.innerHTML = "";
    body.appendChild(ce("p", { text: t("login.pending") }));
    // SECURITY: the URL carries a secret #payload fragment. Only ever place it
    // in href/textContent, never innerHTML, never log it. rel=noopener.
    var link = ce("a", { href: url, target: "_blank", rel: "noopener noreferrer" });
    link.textContent = url;
    var copyBtn = ce("button", { class: "btn subtle icon", "aria-label": t("login.copy_link"), html: icon("copy"), onclick: function () {
      navigator.clipboard ? navigator.clipboard.writeText(url).then(function () { toast(t("toast.link_copied"), "ok"); }) : toast(t("toast.clipboard_unavailable"), "bad");
    } });
    body.appendChild(ce("div", { class: "login-link" }, [iconNode("link"), link, copyBtn]));
    body.appendChild(ce("div", { class: "btn-row mt", style: "align-items:center" }, [
      ce("a", { class: "btn", href: url, target: "_blank", rel: "noopener noreferrer", text: t("login.open") }),
      ce("span", { class: "row", style: "color:var(--text-dim);font-size:.85rem;gap:8px" }, [ce("span", { class: "spinner-inline" }), ce("span", { text: t("login.waiting") })])
    ]));
    body.appendChild(ce("div", { class: "btn-row mt" }, [
      ce("button", { class: "btn ghost", text: t("common.cancel"), onclick: closeModal })
    ]));
  }
  function updateLoginModal(url) {
    var body = el("#login-modal"); if (!body) return;
    var existing = body.querySelector(".login-link a");
    if (!existing || existing.textContent !== url) renderLoginPending(body, url);
  }
  // Invoked from the login modal's onClose. Only tells the backend to cancel
  // when a login was actually pending — the success path clears the flag first,
  // so a completed sign-in won't fire a spurious cancel.
  function cancelPendingLogin() {
    if (!state.pendingLogin) return;
    state.pendingLogin = false;
    api("/protonlogincancel", { method: "POST" }).catch(function () {});
  }

  function openProtonLogout() {
    var foot = [
      ce("button", { class: "btn ghost", text: t("common.cancel"), onclick: closeModal }),
      ce("button", { class: "btn danger", onclick: function () {
        closeModal();
        action(api("/protonlogout", { method: "POST" }), false).then(function (d) {
          if (d && d.ok) toast(t("toast.signed_out"), "ok");
          else toast(d && d.error_type === "proton_cant_connect" ? t("logout.unreachable")
            : errText(d, "toast.sign_out_failed"), "bad");
        }).catch(function () {});
      } }, [iconNode("x"), ce("span", { text: t("common.sign_out") })])
    ];
    var uploadOn = !state.status || state.status.enable_proton_upload;
    openModal(modal(t("logout.title"), "cloud", [
      ce("p", { text: t(uploadOn ? "logout.message" : "logout.message_upload_off") })
    ], foot));
  }

  // ------------------------------------------------------------------------
  // Mock dev panel
  // ------------------------------------------------------------------------
  function renderMockBar() {
    if (!MOCK) return;
    var bar = ce("div", { class: "mock-bar" });
    bar.appendChild(ce("div", { class: "mock-title", text: "Mock states" }));
    window.MockServer.scenarios().forEach(function (sc) {
      var btn = ce("button", { class: window.MockServer.current() === sc ? "active" : "", text: sc, onclick: function () {
        window.MockServer.setScenario(sc); state.pendingLogin = false; closeModal();
        bar.querySelectorAll("button").forEach(function (x) { x.classList.remove("active"); });
        btn.classList.add("active"); refresh();
      } });
      bar.appendChild(btn);
    });
    document.body.appendChild(bar);
  }

  // ------------------------------------------------------------------------
  // Init
  // ------------------------------------------------------------------------
  ensureToastHost();   // live region must exist before the first toast
  renderMockBar();
  // Strings first: everything rendered from here on goes through t().
  function boot() {
    I18n.load(function (code) { return u("/static/" + VERSION + "/app/locales/" + code + ".json"); }).then(function () {
      var boot = el(".boot p"); if (boot) boot.textContent = t("boot.loading");
      if (returningToSettings()) { state.tab = "settings"; loadConfig(); }
      refresh();
    }, function () {
      // Not even English loaded, so there's nothing to translate with. Keep
      // trying, as refresh() does while the add-on isn't answering.
      if (!el("#boot-failed")) renderBootFailed();
      setTimeout(boot, 8000);
    });
  }

  function renderBootFailed() {
    var app = el("#app");
    app.removeAttribute("aria-busy");
    app.innerHTML = "";
    app.appendChild(ce("div", { class: "shell", id: "boot-failed" }, [
      ce("div", { class: "banner bad", style: "margin-top:40px" }, [
        iconNode("alert", "b-ico"),
        ce("div", { class: "b-body" }, [
          ce("div", { class: "b-title", text: "Couldn't load the add-on's interface" }),
          ce("div", { class: "b-msg", text: "Some of its files didn't load. Trying again every few seconds." }),
          ce("div", { class: "b-actions" }, [ce("button", { class: "btn", text: "Reload", onclick: function () { location.reload(); } })])
        ])
      ])
    ]));
  }

  // i18n.js didn't load or didn't run: load it again in place every 8 s, as
  // boot() does for the catalogs. Reloading the page instead could land on
  // Home Assistant's bare "502: Bad Gateway" page while the add-on restarts,
  // and nothing on that page tries again.
  //
  // The address is the one index.jinja2 wrote into the page's own <script>
  // tag. Don't build it from VERSION: that comes out of the bootstrap JSON,
  // and page text must not end up in a script URL (CodeQL js/xss-through-dom).
  function retryI18n(attempt) {
    var first = document.querySelector('script[src$="/app/i18n.js"]');
    if (!first) return;  // index.jinja2 always has it; test_translations.py checks
    setTimeout(function () {
      var script = document.createElement("script");
      script.src = first.getAttribute("src") + "?retry=" + attempt;
      script.onload = function () {
        if (window.I18n) { I18n = window.I18n; t = I18n.t; boot(); return; }
        script.remove(); retryI18n(attempt + 1);  // it loaded but didn't run
      };
      script.onerror = function () { script.remove(); retryI18n(attempt + 1); };
      document.head.appendChild(script);
    }, 8000);
  }

  if (I18n) {
    boot();
  } else {
    renderBootFailed();
    retryI18n(1);
  }
})();
