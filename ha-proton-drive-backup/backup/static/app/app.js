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
  // Render 'quoted' fragments as inline <code>. We walk the *raw* string and
  // esc() each piece individually — escaping the whole thing first would turn
  // the quotes into &#39; so the match could never fire. Input may contain
  // CLI/remote text, so every emitted piece is escaped (never raw HTML).
  function escWithCode(s) {
    s = String(s == null ? "" : s);
    var out = "", last = 0, re = /'([^']+?)'/g, m;
    while ((m = re.exec(s))) {
      out += esc(s.slice(last, m.index)) + "<code>" + esc(m[1]) + "</code>";
      last = m.index + m[0].length;
    }
    return out + esc(s.slice(last));
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
        var data = {};
        try { data = txt ? JSON.parse(txt) : {}; } catch (e) { data = { message: txt }; }
        if (!r.ok) { data.http_status = data.http_status || r.status; return Promise.reject(data); }
        return data;
      });
    });
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
  function toast(msg, kind) {
    ensureToastHost();
    kind = kind || "info";
    var ic = kind === "ok" ? "check" : kind === "bad" ? "alert" : "info";
    var node = ce("div", { class: "toast " + kind, role: "status" }, [iconNode(ic, "t-ico"), ce("div", { text: msg })]);
    toastHost.appendChild(node);
    setTimeout(function () {
      node.classList.add("out");
      setTimeout(function () { if (node.parentNode) node.parentNode.removeChild(node); }, 260);
    }, 4200);
  }
  // Friendly wrapper: run an API call, show the global activity bar while it is
  // in flight, then toast its message / error. The bar gives immediate feedback
  // so actions never look like nothing is happening.
  function action(promise, okMsg) {
    setBusy(true);
    return promise.then(function (d) {
      setBusy(false);
      if (okMsg !== false) toast(okMsg || (d && d.message) || "Done", "ok");
      scheduleRefresh(400);
      return d;
    }, function (e) {
      setBusy(false);
      if (e && e.error_type === "please_wait") {
        toast("A sync is in progress — try again in a moment.", "info");
      } else {
        toast((e && e.message) || "Something went wrong", "bad");
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
      offlineBar.appendChild(ce("span", { text: msg || "Can't reach the add-on — reconnecting…" }));
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
    if (up.started) parts.push("started " + up.started);
    return parts.join(" · ");
  }

  // ------------------------------------------------------------------------
  // App state
  // ------------------------------------------------------------------------
  var state = {
    status: null,
    config: null,        // { config, defaults, addons, folders }
    configDraft: {},     // unsaved settings edits, keyed by setting; survives
                         //   tab switches / advanced toggle until save or reset
    tab: "dashboard",
    pendingLogin: false,
    lastUploads: {},     // slug -> true (to detect upload completion)
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
      // Detect login completion.
      if (state.pendingLogin && s.proton_authenticated) {
        state.pendingLogin = false;
        toast("Signed in to Proton Drive", "ok");
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
      else { setOffline(true, (e && e.message) || "Can't reach the add-on — reconnecting…"); }
      scheduleRefresh(8000);
    });
  }

  function detectUploadCompletion(prev, s) {
    var nowUploading = {};
    (s.backups || []).forEach(function (b) {
      if (b.upload_info && typeof b.upload_info.progress === "number") nowUploading[b.slug] = true;
    });
    Object.keys(state.lastUploads).forEach(function (slug) {
      if (!nowUploading[slug]) {
        var b = (s.backups || []).filter(function (x) { return x.slug === slug; })[0];
        if (b && b.sources && b.sources.some(function (x) { return x.key === "ProtonDrive"; })) {
          toast("Upload to Proton Drive complete", "ok");
        }
      }
    });
    state.lastUploads = nowUploading;
  }

  // ------------------------------------------------------------------------
  // Render — shell
  // ------------------------------------------------------------------------
  var TABS = [
    { id: "dashboard", label: "Dashboard", icon: "shield" },
    { id: "backups", label: "Backups", icon: "archive" },
    { id: "settings", label: "Settings", icon: "settings" },
    { id: "logs", label: "Logs", icon: "doc" },
    { id: "about", label: "About", icon: "info" }
  ];

  // Tracks what is currently rendered so polling doesn't needlessly rebuild the
  // DOM (which would restart animations and wipe in-progress form edits).
  var renderedTab = null, lastSig = null, lastChipKey = null;

  function render() {
    state.booted = true;
    var app = el("#app");
    app.removeAttribute("aria-busy");

    if (!el(".shell")) {
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
      s.backup_cooldown_active ? 1 : 0, s.proton_login_in_progress ? 1 : 0, s.proton_auth_warning ? 1 : 0,
      s.last_error ? s.last_error.error_type : "", s.last_error_count || 0,
      s.next_backup_text || "", s.last_backup_text || "", s.proton_folder || ""
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
      var p = box.querySelector(".u-pct"); if (p) p.textContent = pct + "%";
      var t = box.querySelector(".u-total"); if (t) t.textContent = fmtBytes(up.total);
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
    if (s.syncing) { label = "Syncing…"; live = true; }
    else if (uploading.length) { label = "Working…"; live = true; }
    else { label = "Idle"; idle = true; }
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
    var nav = ce("nav", { class: "tabs", role: "tablist", "aria-label": "Sections" });
    TABS.forEach(function (t, idx) {
      var selected = state.tab === t.id;
      var btn = ce("button", {
        // Roving tabindex: only the selected tab is in the tab order; arrow keys
        // move between the rest (ARIA tablist pattern).
        class: "tab", role: "tab", id: "tab-" + t.id, "data-tab": t.id,
        "aria-controls": "view", tabindex: selected ? "0" : "-1",
        "aria-selected": selected ? "true" : "false",
        onclick: function () { selectTab(t.id); },
        onkeydown: function (e) {
          var next = null;
          if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (idx + 1) % TABS.length;
          else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (idx - 1 + TABS.length) % TABS.length;
          else if (e.key === "Home") next = 0;
          else if (e.key === "End") next = TABS.length - 1;
          if (next != null) { e.preventDefault(); selectTab(TABS[next].id, true); }
        }
      }, [iconNode(t.icon), ce("span", { text: t.label }), ce("span", { class: "badge hidden", id: "tabbadge-" + t.id })]);
      nav.appendChild(btn);
    });
    return nav;
  }
  function updateTabs() {
    TABS.forEach(function (t) {
      var btn = el("#tab-" + t.id); if (!btn) return;
      var selected = state.tab === t.id;
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
          ce("div", { class: "b-title", text: "Couldn't reach the add-on" }),
          ce("div", { class: "b-msg", text: (e && e.message) || "The backend isn't responding. It may still be starting up." }),
          ce("div", { class: "b-actions" }, [ce("button", { class: "btn", text: "Retry", onclick: refresh })])
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
        ce("h2", { text: "Overview" }), ce("div", { class: "spacer" }),
        ce("button", { class: "btn", onclick: openCreateBackup }, [iconNode("plus"), ce("span", { text: "Back up now" })]),
        ce("button", { class: "btn ghost", onclick: doSync }, [iconNode("sync"), ce("span", { text: s.syncing ? "Syncing…" : "Sync now" })])
      ]),
      ce("div", { class: "grid cols-3" }, [
        statTile("Next backup", s.next_backup_text, s.next_backup_detail, "clock"),
        statTile("Last backup", s.last_backup_text, s.last_backup_detail, "check"),
        statTile("Proton Drive",
          !s.proton_authenticated ? "Signed out" : s.proton_auth_warning ? "Connected (unverified)" : "Connected",
          !s.proton_authenticated ? "Sign in required" : s.proton_auth_warning ? "Session couldn't be verified" : ("Folder: " + (s.proton_folder || "—")), "cloud")
      ])
    ]);
    // disable backup button if can't
    var bbtn = actions.querySelector(".btn");
    if (!canBackup) { bbtn.setAttribute("disabled", ""); bbtn.title = "Sign in to Proton Drive first"; }
    host.appendChild(actions);

    // ---- Destinations ----
    var src = s.sources || {};
    var dests = ce("div", { class: "card" }, [
      ce("h2", { text: "Where your backups live" }),
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
        ce("h2", { text: "Recent backups" }), ce("div", { class: "spacer" }),
        ce("button", { class: "btn subtle sm", text: "View all", onclick: function () { state.tab = "backups"; render(); } })
      ])
    ]);
    if (!recent.length) peek.appendChild(emptyState("archive", "No backups yet", "Create your first backup to get started."));
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
    if (info.max) sub.push("max " + info.max);
    if (retained) sub.push(retained + " kept");
    var badge = ce("div", { class: "badge-ico " + cls }); badge.innerHTML = icon(ic);
    return ce("div", { class: "dest" }, [
      badge,
      ce("div", {}, [ce("div", { class: "name", text: name }), ce("div", { class: "meta", text: sub.join(" · ") || "—" })]),
      ce("div", { class: "count" }, [ce("b", { text: String(count) }), ce("span", { text: count === 1 ? "backup" : "backups" })])
    ]);
  }

  // ---- Banners ----
  function activityTitle(s) {
    if ((s.backups || []).some(function (b) { return b.isPending; })) return "Creating a backup…";
    if ((s.backups || []).some(isActive)) return "Uploading to Proton Drive";
    return "Syncing with Proton Drive…";
  }
  function activityMessage(s) {
    var pending = (s.backups || []).filter(function (b) { return b.isPending; });
    if (pending.length) return "Home Assistant is building the backup archive. This can take a while for large installs.";
    var uploading = (s.backups || []).filter(isActive);
    if (uploading.length) {
      var b = uploading[0], up = b.upload_info, pct = clampPct(up.progress);
      if (pct >= 100) return b.name + " — uploading to Proton Drive (large backups can take several minutes).";
      var sp = fmtSpeed(up.speed);
      return b.name + " — preparing " + pct + "%" + (sp ? " · " + sp : "");
    }
    return "Checking backups and applying your retention rules.";
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
    host.appendChild(banner("warn", "clock", "Startup cooldown active",
      "New backups are paused briefly after start-up to let Home Assistant settle.",
      [{ label: "Back up now anyway", cls: "btn", fn: function () { action(api("/ignorestartupcooldown"), "Skipping cooldown — starting now"); } }]));
  }

  function renderAuthBanner(host, s) {
    if (!s.enable_proton_upload) return;
    if (s.proton_authenticated && s.proton_auth_warning) {
      host.appendChild(banner("warn", "cloud", "Proton Drive session couldn't be verified",
        "The last check failed unexpectedly. Backups will still be attempted; if they keep failing, sign in again.",
        [{ label: "Sign in again", cls: "btn", fn: openLogin },
         { label: "Sign out", cls: "btn ghost", fn: openProtonLogout }]));
      return;
    }
    if (s.proton_authenticated) return;
    host.appendChild(banner("warn", "cloud", "Not signed in to Proton Drive",
      "Backups can be created in Home Assistant, but they won't be uploaded until you sign in to Proton Drive.",
      [{ label: "Sign in to Proton", cls: "btn", fn: openLogin }]));
  }

  function renderErrorBanner(host, s) {
    var e = s.last_error;
    if (!e) return;
    if (e.error_type === "please_wait") {
      host.appendChild(banner("info", "clock", "Waiting for the current sync to finish",
        "Your last action is queued and will run as soon as the in-progress sync completes.", []));
      return;
    }
    var actions = resolutionsFor(e);
    var b = ce("div", { class: "banner bad" }, [
      iconNode("alert", "b-ico"),
      ce("div", { class: "b-body" }, [
        ce("div", { class: "b-title", text: errorTitle(e) }),
        (function () { var m = ce("div", { class: "b-msg" }); m.innerHTML = escWithCode(e.message || "An error occurred."); return m; })(),
        s.last_error_count > 1 ? ce("div", { class: "muted", style: "font-size:.8rem;margin-top:6px", text: "Happened " + s.last_error_count + " times in a row." }) : null,
        ce("div", { class: "b-actions" }, actions.map(function (a) {
          return ce("button", { class: a.cls || "btn ghost", text: a.label, onclick: a.fn });
        }).concat([
          ce("button", { class: "btn subtle", text: "Details", onclick: function () { openErrorDetails(e); } })
        ]))
      ])
    ]);
    host.appendChild(b);
  }

  function errorTitle(e) {
    switch (e.error_type) {
      case "proton_not_authenticated": return "Proton Drive sign-in needed";
      case "proton_cant_connect": case "proton_timeout": return "Can't reach Proton Drive";
      case "multiple_deletes": return "Confirm deleting multiple backups";
      case "low_space": case "drive_full": return "Low on space";
      default: return "Something needs your attention";
    }
  }
  function resolutionsFor(e) {
    var out = [];
    switch (e.error_type) {
      case "proton_not_authenticated":
        out.push({ label: "Sign in to Proton", cls: "btn", fn: openLogin }); break;
      case "proton_cant_connect": case "proton_timeout":
        out.push({ label: "Retry now", cls: "btn", fn: doSync }); break;
      case "multiple_deletes":
        out.push({ label: "Delete them, just this once", cls: "btn", fn: function () { action(api("/confirmdelete"), "Confirmed — cleaning up"); } });
        out.push({ label: "Always allow", cls: "btn ghost", fn: function () { action(api("/confirmdelete?always=true"), "Saved — I won't ask again"); } });
        break;
      case "low_space": case "drive_full":
        out.push({ label: "Skip the space check", cls: "btn", fn: function () { action(api("/skipspacecheck"), "Skipping space check"); } });
        break;
      default:
        out.push({ label: "Retry now", cls: "btn", fn: doSync });
        out.push({ label: "Report a bug", cls: "btn ghost", fn: openBugReport });
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
        ce("h2", { text: "Backups (" + (s.backups || []).length + ")" }),
        ce("div", { class: "spacer" }),
        ce("button", { class: "btn", onclick: openCreateBackup }, [iconNode("plus"), ce("span", { text: "Back up now" })])
      ])
    ]);
    var list = (s.backups || []).slice().reverse();
    if (!list.length) card.appendChild(emptyState("archive", "No backups yet", "Create a backup now or wait for the next scheduled run."));
    else list.forEach(function (b) { card.appendChild(backupCard(b, false)); });
    host.appendChild(card);
  }

  function backupCard(b, compact) {
    var cls = "backup";
    if (b.isPending) cls += " pending";
    if (b.ignored) cls += " ignored";
    if (b.upload_info && typeof b.upload_info.progress === "number") cls += " uploading";

    var sub = [];
    sub.push(b.date);
    if (b.size) sub.push(b.size);
    if (b.haVersion) sub.push("HA " + b.haVersion);
    var subRow = ce("div", { class: "backup-sub" }, sub.map(function (x) { return ce("span", { text: x }); }));

    // Badges: type, locations, retained, status, delete-next
    var badges = ce("div", { class: "backup-badges" });
    badges.appendChild(pill(b.type === "full" ? "accent" : "neutral", null, (b.type || "backup")));
    (b.sources || []).forEach(function (src) {
      var isHa = src.key === "HomeAssistant";
      var loc = ce("span", { class: "loc " + (isHa ? "ha" : "proton") }, [
        iconNode(isHa ? "home" : "cloud"),
        ce("span", { text: isHa ? "Home Assistant" : "Proton Drive" })
      ]);
      if (src.retained) loc.appendChild(ce("span", { class: "tag", text: "kept" }));
      if (src.delete_next) loc.appendChild(ce("span", { class: "tag", text: "next to delete" }));
      badges.appendChild(loc);
    });
    if (b.protected) badges.appendChild(pill("neutral", "shield", "encrypted"));
    if (b.ignored) badges.appendChild(pill("neutral", "ignore", "ignored"));
    if (b.isPending) badges.appendChild(pill("info", "clock", "creating…"));
    else if (b.status && !(b.upload_info && b.upload_info.progress != null)) badges.appendChild(pill("info", null, b.status));

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
    else if (b.isPending) card.appendChild(uploadIndeterminate("Creating backup…"));

    // Primary action row (only on full list, not compact peek)
    if (!compact) card.appendChild(backupActions(b));
    return card;
  }

  function uploadProgress(slug, up) {
    var pct = clampPct(up.progress);
    var dest = up.name || "Proton Drive";
    // The backend can track the Home-Assistant -> local staging read (real
    // progress + speed), but the proton-drive CLI reports nothing while it
    // uploads the staged file. Once staging hits 100% we therefore show an
    // honest indeterminate state instead of a frozen 100% and a decaying
    // (total ÷ elapsed) "speed".
    if (pct >= 100) {
      return ce("div", { class: "upload", "data-upload-slug": slug }, [
        ce("div", { class: "u-head" }, [ce("span", { text: "Uploading to " + dest + "…" }), ce("b", { html: '<span class="spinner-inline"></span>' })]),
        ce("div", { class: "bar indeterminate" }, [ce("i")]),
        ce("div", { class: "u-foot" }, [
          ce("span", { class: "u-total", text: fmtBytes(up.total) }),
          ce("span", { text: "Large backups can take several minutes" })
        ])
      ]);
    }
    return ce("div", { class: "upload", "data-upload-slug": slug }, [
      ce("div", { class: "u-head" }, [ce("span", { text: "Preparing for " + dest + "…" }), ce("b", { class: "u-pct", text: pct + "%" })]),
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
      row.appendChild(ce("button", { class: "btn sm", onclick: function () { downloadBackup(b); } }, [iconNode("download"), ce("span", { text: "Download" })]));
      row.appendChild(ce("button", { class: "btn ghost sm", onclick: function () { openRestore(b); } }, [iconNode("restore"), ce("span", { text: "Restore" })]));
    }
    if (b.uploadable) {
      var ub = ce("button", { class: "btn ghost sm", onclick: function () { uploadBackup(b); } }, [iconNode("upload"), ce("span", { text: "Upload to Proton" })]);
      if (!state.status.proton_authenticated) { ub.setAttribute("disabled", ""); ub.title = "Sign in to Proton Drive first"; }
      row.appendChild(ub);
    }
    return row;
  }

  function backupMenu(b) {
    var wrap = ce("div", { class: "backup-menu" });
    var btn = ce("button", { class: "btn subtle icon", "aria-label": "More actions", "aria-haspopup": "menu", "aria-expanded": "false", html: icon("dots") });
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
      addItem(menu, "note", b.note ? "Edit note" : "Add note", function () { openNote(b); });
      // Retain toggles per source
      (b.sources || []).forEach(function (src) {
        var label = (src.retained ? "Stop keeping in " : "Keep in ") + (src.key === "HomeAssistant" ? "Home Assistant" : "Proton Drive");
        addItem(menu, "pin", label, function () { toggleRetain(b, src.key, !src.retained); });
      });
      addItem(menu, b.ignored ? "eye" : "ignore", b.ignored ? "Un-ignore" : "Ignore", function () { toggleIgnore(b, !b.ignored); });
      addItem(menu, "info", "Details", function () { openDetails(b); });
      menu.appendChild(ce("hr"));
      addItem(menu, "trash", "Delete…", function () { openDelete(b); }, true);
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
  function uploadBackup(b) { action(api("/upload?slug=" + encodeURIComponent(b.slug)), "Uploading to Proton Drive in the background"); }
  function toggleRetain(b, sourceKey, value) {
    var sources = {}; (b.sources || []).forEach(function (s) { sources[s.key] = !!s.retained; });
    sources[sourceKey] = value;
    action(apiJson("/retain", { slug: b.slug, sources: sources }), value ? "This backup will be kept" : "This backup is no longer pinned");
  }
  function toggleIgnore(b, value) { action(apiJson("/ignore", { slug: b.slug, ignore: value })); }
  function doSync() {
    if (state.status && state.status.syncing) { toast("A sync is already running", "info"); return; }
    action(api("/startSync"), "Sync started").catch(function () {});
  }

  // ------------------------------------------------------------------------
  // View: Settings
  // ------------------------------------------------------------------------
  var SETTINGS_GROUPS = [
    {
      title: "Backup schedule", icon: "clock",
      desc: "How often backups are made and how many are kept.",
      fields: [
        { key: "days_between_backups", label: "Days between backups", type: "number", step: "0.1", min: 0, help: "How frequently a new backup is created. 0 disables scheduled backups." },
        { key: "backup_time_of_day", label: "Time of day", type: "time", help: "Local time to create scheduled backups. Leave blank for any time." },
        { key: "max_backups_in_ha", label: "Keep in Home Assistant", type: "number", min: 0, help: "Most recent backups to keep on this Home Assistant machine. 0 keeps none locally." },
        { key: "max_backups_in_proton_drive", label: "Keep in Proton Drive", type: "number", min: 0, help: "Most recent backups to keep in Proton Drive." },
        { key: "backup_name", label: "Naming template", type: "text", help: "Template for backup names. Placeholders are shown below.", template: true },
        { key: "backup_password", label: "Backup password", type: "password", help: "Optionally encrypt backups with a password. Leave blank for none." },
        { key: "delete_before_new_backup", label: "Delete old backup before making a new one", type: "bool", help: "Useful when disk space is tight — removes the oldest backup first." },
        { key: "call_backup_snapshot", label: 'Call backups "snapshots"', type: "bool", help: "Use the older term \"snapshot\" in notifications and sensors." }
      ]
    },
    {
      title: "Proton Drive", icon: "cloud",
      desc: "Where and how backups are uploaded to Proton Drive.",
      fields: [
        { key: "enable_proton_upload", label: "Upload backups to Proton Drive", type: "bool", help: "When off, backups are only kept in Home Assistant." },
        { key: "proton_folder_name", label: "Proton folder name", type: "text", help: "Folder in your Proton Drive where backups are stored." },
        { key: "delete_after_upload", label: "Delete from Home Assistant after upload", type: "bool", help: "Keep backups only in Proton Drive once uploaded." },
        { key: "upload_limit_bytes_per_second", label: "Upload speed limit", type: "text", advanced: true, placeholder: "e.g. 5 MB (empty = unlimited)", help: "Throttle uploads to Proton Drive, e.g. \"5 MB\" or \"500 KB\". Leave blank for unlimited." },
        { key: "proton_drive_timeout_seconds", label: "CLI timeout (seconds)", type: "number", min: 1, advanced: true, help: "How long to wait for proton-drive commands." },
        { key: "proton_transfer_timeout_seconds", label: "Transfer timeout (seconds)", type: "number", min: 1, advanced: true, help: "How long to wait for a single upload/download transfer." }
      ]
    },
    {
      title: "What to back up", icon: "folder",
      desc: "Choose which folders and add-ons are included.",
      fields: [
        { key: "exclude_folders", label: "Exclude folders", type: "folders", help: "Folders to leave out of backups." },
        { key: "exclude_addons", label: "Exclude add-ons", type: "addons", help: "Add-ons to leave out of backups." },
        { key: "exclude_ha_database", label: "Exclude the Home Assistant database", type: "bool", help: "Skip home-assistant_v2.db to make backups smaller." }
      ]
    },
    {
      title: "Generational backups", icon: "archive",
      desc: "Keep a spread of older backups (daily, weekly, monthly, yearly).",
      advanced: true,
      fields: [
        { key: "generational_days", label: "Daily backups to keep", type: "number", min: 0 },
        { key: "generational_weeks", label: "Weekly backups to keep", type: "number", min: 0 },
        { key: "generational_months", label: "Monthly backups to keep", type: "number", min: 0 },
        { key: "generational_years", label: "Yearly backups to keep", type: "number", min: 0 },
        { key: "generational_day_of_week", label: "Weekly backup day", type: "select", options: [["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"], ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"]] },
        { key: "generational_day_of_month", label: "Monthly backup day (1–31)", type: "number", min: 1, max: 31 },
        { key: "generational_day_of_year", label: "Yearly backup day (1–365)", type: "number", min: 1, max: 365 },
        { key: "generational_delete_early", label: "Delete extra backups early", type: "bool", help: "Remove redundant backups before the count limit is hit." }
      ]
    },
    {
      title: "Stop add-ons during backup", icon: "bolt",
      desc: "Optionally stop add-ons while a backup runs (useful for databases).",
      advanced: true,
      fields: [
        { key: "stop_addons", label: "Stop these add-ons", type: "addons", help: "These add-ons are stopped before the backup and restarted afterwards." },
        { key: "disable_watchdog_when_stopping", label: "Disable watchdog while stopped", type: "bool", help: "Prevents the supervisor from restarting add-ons mid-backup." }
      ]
    },
    {
      title: "Notifications & sensors", icon: "info",
      fields: [
        { key: "notify_for_stale_backups", label: "Notify when backups are stale", type: "bool", help: "Send a persistent notification if backups stop happening." },
        { key: "enable_backup_stale_sensor", label: "Expose a \"stale\" binary sensor", type: "bool" },
        { key: "enable_backup_state_sensor", label: "Expose a backup state sensor", type: "bool" }
      ]
    },
    {
      title: "Other backups & retention", icon: "list", advanced: true,
      fields: [
        { key: "ignore_other_backups", label: "Ignore backups made elsewhere", type: "bool", help: "Don't manage or delete backups this add-on didn't create." },
        { key: "ignore_upgrade_backups", label: "Ignore upgrade backups", type: "bool", help: "Don't count automatic backups Home Assistant makes during upgrades." },
        { key: "delete_ignored_after_days", label: "Delete ignored backups after", type: "text", placeholder: "e.g. 30 days (empty = never)", help: "Automatically delete ignored backups after this long, e.g. \"30 days\". Leave blank to keep them forever." }
      ]
    },
    {
      title: "Appearance", icon: "eye",
      desc: "Personalise the look of this UI. Changes apply after saving.",
      fields: [
        { key: "background_color", label: "Background color", type: "color" },
        { key: "accent_color", label: "Accent color", type: "color" }
      ]
    },
    {
      title: "Server & networking", icon: "settings", advanced: true,
      desc: "Expose an extra web server outside of Home Assistant ingress.",
      fields: [
        { key: "expose_extra_server", label: "Expose extra web server", type: "bool" },
        { key: "require_login", label: "Require Home Assistant login", type: "bool" },
        { key: "use_ssl", label: "Use SSL", type: "bool" },
        { key: "certfile", label: "Certificate file", type: "text" },
        { key: "keyfile", label: "Key file", type: "text" },
        { key: "port", label: "Port", type: "number", min: 0 }
      ]
    },
    {
      title: "Advanced & diagnostics", icon: "bug", advanced: true,
      fields: [
        { key: "confirm_multiple_deletes", label: "Ask before deleting multiple backups", type: "bool" },
        { key: "warn_for_low_space", label: "Warn when low on space", type: "bool" },
        { key: "watch_backup_directory", label: "Watch the backup directory for changes", type: "bool" },
        { key: "verbose", label: "Verbose logging", type: "bool" },
        { key: "log_level", label: "Log level (file)", type: "select", options: enumOpts(["DEBUG", "TRACE", "INFO", "WARN", "WARNING", "CRITICAL"]) },
        { key: "console_log_level", label: "Log level (console)", type: "select", options: enumOpts(["DEBUG", "TRACE", "INFO", "WARN", "WARNING", "CRITICAL"]) },
        { key: "proton_cli_path", label: "proton-drive CLI path", type: "text" },
        { key: "proton_data_path", label: "Proton data path", type: "text" },
        { key: "max_sync_interval_seconds", label: "Max sync interval", type: "text", placeholder: "e.g. 3 hours", help: "Longest the add-on waits between syncs, e.g. \"3 hours\", \"90 minutes\" or \"1:30:00\"." },
        { key: "maximum_upload_chunk_bytes", label: "Max upload chunk", type: "text", placeholder: "e.g. 10 MB", help: "Upload chunk size, e.g. \"10 MB\". Minimum 256 KB." }
      ]
    }
  ];
  function enumOpts(arr) { return arr.map(function (x) { return [x, x]; }); }

  var showAdvanced = false;

  function viewSettings(host) {
    if (!state.config) {
      host.appendChild(ce("div", { class: "card" }, [centerSpinner("Loading settings…")]));
      return;
    }
    var cfg = state.config.config || {};
    var card = ce("div", { class: "card" });
    card.appendChild(ce("div", { class: "card-head" }, [
      ce("h2", { text: "Settings" }), ce("div", { class: "spacer" }),
      switchControl("Show advanced", showAdvanced, function (v) { showAdvanced = v; renderView(); })
    ]));

    var form = ce("form", { id: "settings-form", onsubmit: function (e) { e.preventDefault(); saveConfig(); } });

    SETTINGS_GROUPS.forEach(function (g) {
      var fields = g.fields.filter(function (f) { return showAdvanced || !f.advanced; });
      if (!showAdvanced && g.advanced) return;
      if (!fields.length) return;
      var body = ce("div", { class: "group-body" });
      if (g.desc) body.appendChild(ce("div", { class: "group-desc", text: g.desc }));
      fields.forEach(function (f) { body.appendChild(renderField(f, cfg)); });
      var grp = ce("details", { class: "settings-group", open: true }, [
        ce("summary", {}, [iconNode(g.icon), ce("span", { text: g.title }), ce("span", { class: "chev", html: icon("chev") })]),
        body
      ]);
      form.appendChild(grp);
    });

    form.appendChild(ce("div", { class: "settings-actions" }, [
      ce("button", { class: "btn", type: "submit" }, [iconNode("check"), ce("span", { text: "Save settings" })]),
      ce("button", { class: "btn ghost", type: "button", text: "Reset", onclick: function () { state.configDraft = {}; renderView(); } })
    ]));
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

    if (f.type === "bool") {
      wrap.appendChild(ce("div", {}, [switchControl(f.label, !!val, function (v) { draft[f.key] = v; }, id, f.key)]));
      if (f.help) wrap.appendChild(ce("div", { class: "help", text: f.help }));
      return wrap;
    }

    wrap.appendChild(ce("label", { for: id, text: f.label }));
    if (f.help) wrap.appendChild(ce("div", { class: "help", text: f.help }));

    if (f.type === "select") {
      var sel = ce("select", { id: id, "data-key": f.key });
      sel.appendChild(ce("option", { value: "", text: "— default —" }));
      f.options.forEach(function (o) { sel.appendChild(ce("option", { value: o[0], text: o[1] })); });
      sel.value = val != null ? String(val) : "";
      sel.addEventListener("change", function () { if (sel.value !== "") draft[f.key] = sel.value; else delete draft[f.key]; });
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
      if (f.placeholder) attrs.placeholder = f.placeholder;
      else if (defs[f.key] != null && defs[f.key] !== "") attrs.placeholder = "default: " + defs[f.key];
      var input = ce("input", attrs);
      // Empty = "use the default"; drop it from the draft so we never submit an
      // out-of-range 0 for fields that have a minimum.
      input.addEventListener("input", function () {
        if (input.value === "") delete draft[f.key];
        else draft[f.key] = f.type === "number" ? Number(input.value) : input.value;
      });
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

  function multiCheck(f, val) {
    var items = f.type === "folders" ? (state.config.folders || []) : (state.config.addons || []);
    var selected = parseCsv(val);
    var box = ce("div", { class: "checks", "data-multi": f.key, "data-kind": f.type });
    if (!items.length) { box.appendChild(ce("div", { class: "help", text: f.type === "addons" ? "No add-ons detected." : "No folders available." })); return box; }
    items.forEach(function (it) {
      var slug = it.slug;
      var name = it.name || it.slug;
      var lbl = ce("label", {}, [
        ce("input", { type: "checkbox", value: slug, checked: selected.indexOf(slug) >= 0 }),
        ce("div", {}, [ce("div", { class: "cx-name", text: name }), it.description ? ce("div", { class: "cx-desc", text: it.description }) : (it.version ? ce("div", { class: "cx-desc", text: "v" + it.version }) : null)])
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
      .catch(function (e) { toast((e && e.message) || "Couldn't load settings", "bad"); });
  }

  function collectConfig() {
    var out = {};
    // Seed with drafted edits first so fields hidden by the advanced toggle are
    // still saved; visible fields are then overridden from the live DOM below.
    var draft = state.configDraft || {};
    Object.keys(draft).forEach(function (k) { out[k] = draft[k]; });
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
    var cfg = collectConfig();
    var btn = el('#settings-form button[type="submit"]');
    if (btn) { btn.setAttribute("disabled", ""); btn.querySelector("span").textContent = "Saving…"; }
    setBusy(true);
    apiJson("/saveconfig", { config: cfg }).then(function (d) {
      toast((d && d.message) || "Settings saved", "ok");
      state.configDraft = {};   // edits are now persisted server-side
      if (d && d.reload_page) { setTimeout(function () { location.reload(); }, 600); return; }
      loadConfig();
      scheduleRefresh(400);
    }).catch(function (e) {
      toast((e && e.message) || "Couldn't save settings", "bad");
    }).then(function () {
      setBusy(false);
      if (btn) { btn.removeAttribute("disabled"); btn.querySelector("span").textContent = "Save settings"; }
    });
  }

  // ------------------------------------------------------------------------
  // View: Logs
  // ------------------------------------------------------------------------
  var logState = { text: "", loading: false };
  function viewLogs(host) {
    var card = ce("div", { class: "card" });
    card.appendChild(ce("div", { class: "card-head" }, [
      ce("h2", { text: "Add-on log" }), ce("div", { class: "spacer" }),
      ce("button", { class: "btn ghost sm", onclick: loadLogs }, [iconNode("refresh"), ce("span", { text: "Refresh" })]),
      ce("button", { class: "btn subtle sm", onclick: function () {
        if (MOCK) { toast("Download (mock)", "info"); return; }
        var a = ce("a", { href: u("/log?format=download") }); document.body.appendChild(a); a.click(); a.remove();
      } }, [iconNode("download"), ce("span", { text: "Download" })])
    ]));
    var view = ce("pre", { class: "log-view", id: "log-view" });
    if (logState.loading) view.appendChild(centerSpinner("Loading log…"));
    else view.innerHTML = colorizeLog(logState.text || "No log output yet.");
    card.appendChild(view);
    host.appendChild(card);
  }
  function loadLogs() {
    logState.loading = true; if (state.tab === "logs") renderView();
    var p = MOCK ? window.MockServer.log() : fetch(u("/log?format=view")).then(function (r) { return r.text(); });
    Promise.resolve(p).then(function (txt) {
      logState.text = txt; logState.loading = false;
      if (state.tab === "logs") { renderView(); var v = el("#log-view"); if (v) v.scrollTop = v.scrollHeight; }
    }).catch(function () { logState.loading = false; logState.text = "Couldn't load the log."; if (state.tab === "logs") renderView(); });
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
      ce("h2", { text: "About" }),
      ce("p", { class: "dim", text: "Proton Drive Backup automatically creates Home Assistant backups and mirrors them to your end-to-end encrypted Proton Drive." }),
      ce("div", { class: "grid cols-2 mt" }, [
        statTile("Version", "v" + VERSION, null, "info"),
        statTile("Proton Drive", s.proton_authenticated ? "Signed in" : "Signed out", s.proton_folder ? "Folder: " + s.proton_folder : null, "cloud")
      ]),
      ce("div", { class: "btn-row mt" }, [
        ce("button", { class: "btn ghost", onclick: openBugReport }, [iconNode("bug"), ce("span", { text: "Create a bug report" })]),
        ce("button", { class: "btn subtle", onclick: function () { state.tab = "logs"; render(); loadLogs(); } }, [iconNode("doc"), ce("span", { text: "View logs" })])
      ])
    ]));
    if (!s.proton_authenticated) {
      host.appendChild(ce("div", { class: "card" }, [
        ce("h2", { text: "Proton Drive sign-in" }),
        ce("p", { class: "dim", text: "Proton Drive uses an interactive sign-in (not OAuth). Click below to start; you'll open a Proton link and complete sign-in, including 2-factor, in your browser." }),
        ce("p", { class: "dim", text: "This is a third-party application not officially supported by Proton." }),
        ce("button", { class: "btn", onclick: openLogin }, [iconNode("link"), ce("span", { text: "Sign in to Proton" })])
      ]));
    } else {
      host.appendChild(ce("div", { class: "card" }, [
        ce("h2", { text: "Proton Drive account" }),
        ce("p", { class: "dim", text: s.proton_auth_warning
          ? "Signed in, but the session couldn't be verified on the last check. If backups keep failing, sign in again."
          : "Signed in. Signing out keeps your backups in Proton Drive but pauses uploads until you sign in again." }),
        ce("div", { class: "btn-row" }, [
          s.proton_auth_warning ? ce("button", { class: "btn", onclick: openLogin }, [iconNode("link"), ce("span", { text: "Sign in again" })]) : null,
          ce("button", { class: "btn ghost", onclick: openProtonLogout }, [iconNode("x"), ce("span", { text: "Sign out" })])
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
      ce("span", { class: "spinner-inline" }), ce("span", { text: label || "Loading…" })
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
      ce("div", { class: "modal-head" }, [iconNode(ic), ce("h3", { text: title }), ce("button", { class: "btn subtle icon x", "aria-label": "Close", html: icon("x"), onclick: closeModal })]),
      ce("div", { class: "modal-body" }, bodyChildren),
      footChildren ? ce("div", { class: "modal-foot" }, footChildren) : null
    ]);
  }

  // ---- Create backup ----
  function openCreateBackup() {
    var s = state.status || {};
    var nameInput = ce("input", { type: "text", placeholder: s.backup_name_template || "Custom name (optional)" });
    var noteInput = ce("textarea", { placeholder: "Optional note (e.g. before upgrade)" });
    var retainHa = ce("input", { type: "checkbox" });
    var retainProton = ce("input", { type: "checkbox" });
    var body = [
      ce("div", { class: "field" }, [ce("label", { text: "Name" }), ce("div", { class: "help", text: "Leave blank to use your naming template." }), nameInput]),
      ce("div", { class: "field" }, [ce("label", { text: "Note" }), noteInput]),
      ce("div", { class: "field" }, [
        ce("label", { text: "Keep this backup (exempt from deletion)" }),
        ce("div", { class: "checks" }, [
          ce("label", {}, [retainHa, ce("div", {}, [ce("div", { class: "cx-name", text: "Keep in Home Assistant" })])]),
          ce("label", {}, [retainProton, ce("div", {}, [ce("div", { class: "cx-name", text: "Keep in Proton Drive" })])])
        ])
      ])
    ];
    var foot = [
      ce("button", { class: "btn ghost", text: "Cancel", onclick: closeModal }),
      ce("button", { class: "btn", onclick: function () {
        var query = qs({ custom_name: nameInput.value, note: noteInput.value, retain_ha: retainHa.checked, retain_proton: retainProton.checked });
        closeModal();
        action(api("/backup" + (query ? "?" + query : "")), "Backup requested");
      } }, [iconNode("plus"), ce("span", { text: "Create backup" })])
    ];
    openModal(modal("Create a backup now", "plus", body, foot));
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
      ce("div", { class: "b-body" }, [ce("div", { class: "b-msg", text: "Deleting a backup can't be undone." })])
    ]);
    var body = [warn, ce("div", { class: "field" }, [ce("label", { text: "Delete from:" }), ce("div", { class: "checks" }, rows)])];
    var delBtn = ce("button", { class: "btn danger", onclick: function () {
      var chosen = Object.keys(picks).filter(function (k) { return picks[k]; });
      if (!chosen.length) return;
      closeModal();
      action(apiJson("/deleteSnapshot", { slug: b.slug, sources: chosen }), "Backup deleted");
    } }, [iconNode("trash"), ce("span", { text: "Delete" })]);
    function updateBtn() {
      var n = Object.keys(picks).filter(function (k) { return picks[k]; }).length;
      delBtn.querySelector("span").textContent = n ? "Delete from " + n + " place" + (n > 1 ? "s" : "") : "Delete";
      delBtn.toggleAttribute("disabled", n === 0);
    }
    updateBtn();
    openModal(modal('Delete "' + b.name + '"', "trash", body, [ce("button", { class: "btn ghost", text: "Cancel", onclick: closeModal }), delBtn]));
  }

  // ---- Restore ----
  function openRestore(b) {
    var s = state.status || {};
    var path = (s.ha_url_base || "") ;
    var body = [
      ce("p", { class: "dim", text: "Home Assistant restores backups from its own Settings screen. This backup is available in Home Assistant and ready to restore." }),
      ce("div", { class: "banner info", style: "margin:0" }, [
        iconNode("info", "b-ico"),
        ce("div", { class: "b-body" }, [
          ce("div", { class: "b-title", text: "How to restore" }),
          ce("div", { class: "b-msg", html: "Open <b>Settings → System → Backups</b> in Home Assistant, choose <b>" + esc(b.name) + "</b>, and select Restore. You can also download the backup here and upload it manually." })
        ])
      ])
    ];
    var foot = [
      ce("button", { class: "btn ghost", text: "Close", onclick: closeModal }),
      ce("button", { class: "btn", onclick: function () { downloadBackup(b); } }, [iconNode("download"), ce("span", { text: "Download backup" })])
    ];
    if (s.ha_url_base) foot.unshift(ce("a", { class: "btn subtle", href: s.ha_url_base + "/config/backup/list", target: "_blank", rel: "noopener", text: "Open HA backups" }));
    openModal(modal("Restore backup", "restore", body, foot));
  }

  // ---- Note ----
  function openNote(b) {
    var ta = ce("textarea", { placeholder: "Write a note for this backup…" }); ta.value = b.note || "";
    var foot = [
      ce("button", { class: "btn ghost", text: "Cancel", onclick: closeModal }),
      ce("button", { class: "btn", text: "Save note", onclick: function () { closeModal(); action(apiJson("/note", { slug: b.slug, note: ta.value }), "Note saved"); } })
    ];
    openModal(modal("Note", "note", [ce("div", { class: "field" }, [ta])], foot));
  }

  // ---- Details ----
  function openDetails(b) {
    var rows = [
      ["Name", b.name], ["Created", b.date + " (" + b.createdAt + ")"], ["Size", b.size],
      ["Type", b.type], ["Home Assistant version", b.haVersion || "—"],
      ["Encrypted", b.protected ? "Yes" : "No"], ["Slug", b.slug], ["Status", b.status || "—"]
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
    var body = [dl, ce("div", { style: "margin-top:6px" }, [ce("div", { class: "muted", style: "font-size:.8rem;margin-bottom:6px", text: "Stored in" }), locs])];
    if ((b.folders || []).length) body.push(ce("div", { class: "mt" }, [ce("div", { class: "muted", style: "font-size:.8rem", text: "Folders" }), ce("div", { text: b.folders.join(", ") })]));
    if ((b.addons || []).length) body.push(ce("div", { class: "mt" }, [ce("div", { class: "muted", style: "font-size:.8rem", text: "Add-ons" }), ce("div", { text: b.addons.map(function (a) { return a.name; }).join(", ") })]));
    openModal(modal("Backup details", "info", body, [ce("button", { class: "btn ghost", text: "Close", onclick: closeModal })], true));
  }

  // ---- Error details ----
  function openErrorDetails(e) {
    var body = [
      (function () { var m = ce("p", {}); m.innerHTML = escWithCode(e.message || ""); return m; })(),
      e.details ? ce("pre", { class: "log-view", text: e.details }) : null
    ];
    var foot = [
      ce("button", { class: "btn ghost", text: "Close", onclick: closeModal }),
      ce("button", { class: "btn", onclick: function () { closeModal(); openBugReport(); } }, [iconNode("bug"), ce("span", { text: "Report a bug" })])
    ];
    openModal(modal("Error details", "alert", body, foot, true));
  }

  // ---- Bug report ----
  function openBugReport() {
    var pre = ce("pre", { class: "log-view", text: "Gathering report…" });
    var copyBtn = ce("button", { class: "btn", onclick: function () {
      navigator.clipboard ? navigator.clipboard.writeText(pre.textContent).then(function () { toast("Copied to clipboard", "ok"); }, function () { toast("Couldn't copy", "bad"); })
        : toast("Clipboard unavailable", "bad");
    } }, [iconNode("copy"), ce("span", { text: "Copy report" })]);
    openModal(modal("Bug report", "bug", [
      ce("p", { class: "dim", text: "Copy the report below into a new GitHub issue. It includes diagnostics but no Proton credentials." }),
      pre
    ], [ce("button", { class: "btn ghost", text: "Close", onclick: closeModal }), copyBtn], true));
    api("/makeanissue").then(function (d) { pre.textContent = (d && d.markdown) || "No report available."; })
      .catch(function (e) { pre.textContent = (e && e.message) || "Couldn't build the report."; });
  }

  // ---- Proton login ----
  function loginModalOpen() { return !!(modalHost && modalHost.querySelector("#login-modal")); }
  function openLogin() {
    state.pendingLogin = false;
    var body = ce("div", { id: "login-modal" });
    var foot = ce("div", { class: "row", style: "width:100%;justify-content:flex-end" });
    var node = modal("Sign in to Proton Drive", "cloud", [body], null);
    // Closing the dialog any way (Escape, backdrop, X, Cancel) must abandon an
    // in-progress login so we don't leave a dangling CLI session + 2s polling.
    openModal(node, { onClose: cancelPendingLogin });
    renderLoginStart(body, foot, node);
    scheduleRefresh(400);
  }
  function renderLoginStart(body, foot, node) {
    body.innerHTML = "";
    body.appendChild(ce("p", { class: "dim", text: "Proton uses an interactive sign-in. Start the flow, open the link in your browser, and complete sign-in (including 2-factor). This page updates automatically." }));
    body.appendChild(ce("p", { class: "dim", text: "This is a third-party application not officially supported by Proton." }));
    var startBtn = ce("button", { class: "btn", onclick: function () {
      startBtn.setAttribute("disabled", ""); startBtn.querySelector("span").textContent = "Starting…";
      api("/protonlogin", { method: "POST" }).then(function (d) {
        if (d && d.ok && d.url) { state.pendingLogin = true; renderLoginPending(body, d.url, d.message); scheduleRefresh(400); }
        else { toast((d && d.message) || "Couldn't start sign-in", "bad"); startBtn.removeAttribute("disabled"); startBtn.querySelector("span").textContent = "Start sign-in"; }
      }).catch(function (e) { toast((e && e.message) || "Couldn't start sign-in", "bad"); startBtn.removeAttribute("disabled"); startBtn.querySelector("span").textContent = "Start sign-in"; });
    } }, [iconNode("link"), ce("span", { text: "Start sign-in" })]);
    body.appendChild(ce("div", { class: "btn-row" }, [startBtn]));
  }
  function renderLoginPending(body, url, message) {
    body.innerHTML = "";
    body.appendChild(ce("p", { text: message || "Open this link, sign in to Proton (including 2-factor), then keep this page open." }));
    // SECURITY: the URL carries a secret #payload fragment. Only ever place it
    // in href/textContent, never innerHTML, never log it. rel=noopener.
    var link = ce("a", { href: url, target: "_blank", rel: "noopener noreferrer" });
    link.textContent = url;
    var copyBtn = ce("button", { class: "btn subtle icon", "aria-label": "Copy link", html: icon("copy"), onclick: function () {
      navigator.clipboard ? navigator.clipboard.writeText(url).then(function () { toast("Link copied", "ok"); }) : toast("Clipboard unavailable", "bad");
    } });
    body.appendChild(ce("div", { class: "login-link" }, [iconNode("link"), link, copyBtn]));
    body.appendChild(ce("div", { class: "btn-row mt", style: "align-items:center" }, [
      ce("a", { class: "btn", href: url, target: "_blank", rel: "noopener noreferrer", text: "Open Proton sign-in" }),
      ce("span", { class: "row", style: "color:var(--text-dim);font-size:.85rem;gap:8px" }, [ce("span", { class: "spinner-inline" }), ce("span", { text: "Waiting for you to finish…" })])
    ]));
    body.appendChild(ce("div", { class: "btn-row mt" }, [
      ce("button", { class: "btn ghost", text: "Cancel", onclick: closeModal })
    ]));
  }
  function updateLoginModal(url) {
    var body = el("#login-modal"); if (!body) return;
    var existing = body.querySelector(".login-link a");
    if (!existing || existing.textContent !== url) renderLoginPending(body, url, null);
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
      ce("button", { class: "btn ghost", text: "Cancel", onclick: closeModal }),
      ce("button", { class: "btn danger", onclick: function () {
        closeModal();
        action(api("/protonlogout", { method: "POST" }), false).then(function (d) {
          if (d && d.ok) toast(d.message || "Signed out of Proton Drive", "ok");
          else toast((d && d.message) || "Couldn't sign out", "bad");
        }).catch(function () {});
      } }, [iconNode("x"), ce("span", { text: "Sign out" })])
    ];
    openModal(modal("Sign out of Proton Drive?", "cloud", [
      ce("p", { text: "Your backups stay in Proton Drive, but uploads pause until you sign in again." })
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
  refresh();
})();
