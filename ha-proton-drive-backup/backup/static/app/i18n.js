/* =========================================================================
   Proton Drive Backup — translations for the web UI (vanilla JS, zero build)
   Loads locales/<lang>.json and exposes window.I18n. See README.md
   ("Translations") for how the language is chosen and how to add one.
   ========================================================================= */
(function () {
  "use strict";

  // Languages the UI ships, by Home Assistant language code. Adding one needs
  // locales/<code>.json (same keys as en.json) and translations/<code>.yaml
  // (the add-on's Configuration tab); tests/test_translations.py checks both.
  var SUPPORTED = {
    en: "English", cs: "Čeština", de: "Deutsch", es: "Español", fr: "Français", it: "Italiano", ml: "മലയാളം",
    nl: "Nederlands", pl: "Polski", "pt-BR": "Português (Brasil)", sv: "Svenska", uk: "Українська"
  };
  var FALLBACK = "en";

  var lang = FALLBACK;
  var base = {};      // English: fills keys a translation lacks
  var messages = {};  // the chosen language
  var timeZone = null;
  var plurals = null;

  // "fr-CA" -> "fr", "EN" -> "en", "pt" or "pt-PT" -> "pt-BR" (the only
  // Portuguese there is); null when unsupported.
  function match(code) {
    if (!code) return null;
    var lower = String(code).replace(/_/g, "-").toLowerCase();
    var primary = lower.split("-")[0];
    var exact = null, loose = null, sibling = null;
    Object.keys(SUPPORTED).forEach(function (k) {
      var key = k.toLowerCase();
      if (key === lower) exact = k;
      else if (key === primary) loose = k;
      else if (key.split("-")[0] === primary) sibling = k;
    });
    return exact || loose || sibling;
  }

  // ?lang= (previews) > Home Assistant's language > the browser's languages.
  // Ingress shows this page in a same-origin iframe inside Home Assistant, whose
  // <html lang> is the user's profile language; the extra server is a different
  // origin, so reading the parent throws and the browser's languages decide.
  function detect() {
    var candidates = [];
    var q = /[?&]lang=([A-Za-z0-9_-]+)/.exec(location.search);
    if (q) candidates.push(q[1]);
    try {
      if (window.parent && window.parent !== window) candidates.push(window.parent.document.documentElement.lang);
    } catch (e) { /* cross-origin */ }
    candidates = candidates.concat(navigator.languages || [navigator.language]);
    for (var i = 0; i < candidates.length; i++) {
      var hit = match(candidates[i]);
      if (hit) return hit;
    }
    return FALLBACK;
  }

  function fetchJson(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " for " + url);
      return r.json();
    });
  }

  function apply(code) {
    lang = code;
    document.documentElement.lang = code;
    try { plurals = new Intl.PluralRules(code); } catch (e) { plurals = null; }
  }

  // urlFor(code) -> URL of locales/<code>.json. Resolves once English (and the
  // chosen language, if any) is loaded; rejects only if English can't load.
  function load(urlFor) {
    var code = detect();
    var english = fetchJson(urlFor(FALLBACK));
    var chosen = code === FALLBACK ? english : fetchJson(urlFor(code)).catch(function () { code = FALLBACK; return null; });
    return Promise.all([english, chosen]).then(function (r) {
      base = r[0] || {};
      messages = r[1] || base;
      apply(code);
      return code;
    });
  }

  function has(key) { return messages[key] != null || base[key] != null; }

  function pick(forms, n) {
    var form = "other";
    var num = Number(n);
    if (!isNaN(num)) {
      if (plurals) { try { form = plurals.select(num); } catch (e) { /* keep "other" */ } }
      else if (num === 1) form = "one";
    }
    return forms[form] != null ? forms[form] : forms.other;
  }

  function fill(text, params, escape) {
    return String(text).replace(/\{(\w+)\}/g, function (whole, name) {
      if (!params || params[name] == null) return whole;
      var v = String(params[name]);
      return escape ? escape(v) : v;
    });
  }

  function raw(key, params) {
    var v = messages[key];
    if (v == null) v = base[key];
    if (v == null) return null;
    if (typeof v === "object") v = pick(v, params && params.n);
    return v;
  }

  // t("toast.ignored", { name: "Full Backup" }); plural messages ({one, other, …})
  // pick their form from params.n. Unknown keys render as the key itself.
  function t(key, params) {
    var v = raw(key, params);
    return v == null ? key : fill(v, params);
  }

  // For *_html messages only: the message's own markup (<b>) is kept, every
  // parameter is HTML-escaped.
  function tHtml(key, params) {
    var v = raw(key, params);
    if (v == null) return escapeHtml(key);
    return fill(v, params, escapeHtml);
  }
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ["a", "b", "c"] -> "a, b and c" in the current language.
  function list(items) {
    try { return new Intl.ListFormat(lang, { style: "long", type: "conjunction" }).format(items); }
    catch (e) { return items.join(", "); }
  }

  function number(n, opts) {
    try { return new Intl.NumberFormat(lang, opts).format(n); } catch (e) { return String(n); }
  }
  // 42 -> "42%" / "42 %" (fr)
  function percent(n) { return number(n / 100, { style: "percent", maximumFractionDigits: 0 }); }

  // Home Assistant's zone (status.time_zone), so dates match what the add-on
  // logs and the backup names say rather than the viewer's machine.
  function setTimeZone(tz) { timeZone = tz || null; }

  // Milliseconds to add to this device's clock to get the add-on's
  // (status.now_timestamp), so "5 minutes ago" doesn't depend on whether the
  // viewer's clock is right.
  var clockOffsetMs = 0;
  function setServerTime(epoch) {
    if (typeof epoch === "number" && isFinite(epoch)) clockOffsetMs = epoch * 1000 - Date.now();
  }

  function addMonths(d, n) {
    var r = new Date(d.getTime());
    var day = r.getDate();
    r.setDate(1);
    r.setMonth(r.getMonth() + n);
    var last = new Date(r.getFullYear(), r.getMonth() + 1, 0).getDate();
    r.setDate(Math.min(day, last));
    return r;
  }

  // Epoch seconds -> "3 days ago" / "in 2 hours", using the largest unit with
  // the same rounding as Time.formatDelta (backup/time.py), except minutes:
  // those round up from 30 seconds (formatDelta adds one from 30 minutes on,
  // so it says "31 minutes" for 30). null if no date.
  // "Now" is the add-on's clock (see setServerTime) unless nowMs is given.
  function relTime(epoch, nowMs) {
    if (epoch == null || epoch === "" || isNaN(Number(epoch))) return null;
    var now = nowMs != null ? nowMs : Date.now() + clockOffsetMs;
    var then = Number(epoch) * 1000;
    var past = then <= now;
    var a = new Date(past ? then : now), b = new Date(past ? now : then);
    var months = (b.getFullYear() - a.getFullYear()) * 12 + (b.getMonth() - a.getMonth());
    var anchor = addMonths(a, months);
    if (anchor > b) { months--; anchor = addMonths(a, months); }
    var rest = b - anchor;
    var days = Math.floor(rest / 864e5);
    var hours = Math.floor((rest % 864e5) / 36e5);
    var minutes = Math.floor((rest % 36e5) / 6e4);
    var seconds = Math.floor((rest % 6e4) / 1e3);
    var years = Math.floor(months / 12);
    months = months % 12;
    var unit, value;
    if (years > 0) { unit = "year"; value = years; }
    else if (months > 0) { unit = "month"; value = months + (days > 15 ? 1 : 0); }
    else if (days > 0) { unit = "day"; value = days + (hours >= 12 ? 1 : 0); }
    else if (hours > 0) { unit = "hour"; value = hours + (minutes >= 30 ? 1 : 0); }
    else if (minutes > 0) { unit = "minute"; value = minutes + (seconds >= 30 ? 1 : 0); }
    else { unit = "second"; value = seconds; }
    try {
      if (value === 0) return new Intl.RelativeTimeFormat(lang, { numeric: "auto" }).format(0, "second");
      return new Intl.RelativeTimeFormat(lang, { numeric: "always" }).format(past ? -value : value, unit);
    } catch (e) {
      return null;  // caller falls back to the server's English text
    }
  }

  // Epoch seconds -> e.g. "Nov 18, 2026, 10:30 AM" / "18 nov. 2026, 10:30".
  function dateTime(epoch) {
    if (epoch == null || epoch === "" || isNaN(Number(epoch))) return null;
    var d = new Date(Number(epoch) * 1000);
    var opts = { dateStyle: "medium", timeStyle: "short" };
    if (timeZone) {
      try { return new Intl.DateTimeFormat(lang, Object.assign({ timeZone: timeZone }, opts)).format(d); }
      catch (e) { /* unknown zone: use the browser's */ }
    }
    try { return new Intl.DateTimeFormat(lang, opts).format(d); } catch (e) { return d.toLocaleString(); }
  }

  // 0 = Monday … 6 = Sunday, e.g. "lundi".
  function weekday(i) {
    var d = new Date(Date.UTC(2024, 0, 1 + i));  // 2024-01-01 was a Monday
    try { return new Intl.DateTimeFormat(lang, { weekday: "long", timeZone: "UTC" }).format(d); }
    catch (e) { return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][i]; }
  }

  window.I18n = {
    SUPPORTED: SUPPORTED,
    load: load,
    lang: function () { return lang; },
    has: has,
    t: t,
    tHtml: tHtml,
    list: list,
    number: number,
    percent: percent,
    relTime: relTime,
    dateTime: dateTime,
    weekday: weekday,
    setTimeZone: setTimeZone,
    setServerTime: setServerTime
  };
})();
