/* =========================================================================
   Dev mock server — only active with ?mock=1 on the URL.
   Lets every UI state be previewed without a running Home Assistant /
   Supervisor. Provides window.MockServer used by app.js's api() layer.

   Scenarios: normal, syncing, uploading, signed-out, auth-warning,
   login-pending, error-auth, error-offline, error-multiple-deletes,
   error-low-space, please-wait, cooldown, empty, many.
   ========================================================================= */
(function () {
  "use strict";
  if (!/[?&]mock=1/.test(location.search)) return;

  var scenario = "normal";

  function backup(over) {
    return Object.assign({
      name: "Full Backup 2026-06-28", slug: "b76660e7", size: "1.4 GB",
      date: "Sat Jun 28 02:51:38 2026", createdAt: "8 hours ago", timestamp: 1782010298,
      type: "full", haVersion: "2026.6.0", protected: true, isPending: false,
      uploadable: false, restorable: true, ignored: false, note: null,
      status: "Backed up", status_detail: null, upload_info: {}, folders: [], addons: [],
      sources: [
        // Per-source size is raw bytes from the backend (unlike the formatted
        // backup-level size string); the UI formats it with fmtBytes().
        { name: "HomeAssistant", key: "HomeAssistant", size: 1503238553, retained: false, ignored: false, delete_next: false, slug: "b76660e7" },
        { name: "ProtonDrive", key: "ProtonDrive", size: 1503238553, retained: true, ignored: false, delete_next: false, slug: "b76660e7" }
      ]
    }, over || {});
  }

  var baseBackups = [
    backup(),
    backup({
      name: "Full Backup 2026-06-25", slug: "a1234567", size: "1.3 GB",
      date: "Wed Jun 25 02:00:00 2026", createdAt: "3 days ago", timestamp: 1781748000,
      note: "before upgrade", protected: false,
      sources: [
        { name: "HomeAssistant", key: "HomeAssistant", size: "1.3 GB", retained: false, ignored: false, delete_next: true, slug: "a1234567" },
        { name: "ProtonDrive", key: "ProtonDrive", size: "1.3 GB", retained: false, ignored: false, delete_next: false, slug: "a1234567" }
      ]
    }),
    backup({
      name: "Partial Backup 2026-06-20", slug: "deadbeef", size: "220 MB",
      date: "Fri Jun 20 14:10:00 2026", createdAt: "8 days ago", timestamp: 1781316600,
      type: "partial", uploadable: true,
      sources: [
        { name: "HomeAssistant", key: "HomeAssistant", size: "220 MB", retained: false, ignored: false, delete_next: false, slug: "deadbeef" }
      ]
    })
  ];

  function sources(ha, proton) {
    return {
      HomeAssistant: { backups: ha, retained: 0, deletable: ha, name: "HomeAssistant", title: "Home Assistant", max: 4, size: "3.0 GB", icon: "home" },
      ProtonDrive: { backups: proton, retained: 1, deletable: proton - 1, name: "ProtonDrive", title: "Proton Drive", max: 4, size: "2.7 GB", icon: "cloud" }
    };
  }

  function base() {
    return {
      backups: baseBackups.map(function (b) { return JSON.parse(JSON.stringify(b)); }),
      ha_url_base: "http://homeassistant.local:8123", restore_backup_path: "hassio/backups",
      ask_error_reports: false,
      next_backup_text: "in 2 days", next_backup_machine: "2026-06-30T02:00:00", next_backup_detail: "Mon Jun 30 02:00:00 2026",
      last_backup_text: "8 hours ago", last_backup_machine: "2026-06-28T02:51:38", last_backup_detail: "Sat Jun 28 02:51:38 2026",
      last_error: null, last_error_count: 0, ignore_errors_for_now: false,
      syncing: false, ignore_sync_error: false, firstSync: false,
      backup_name_template: "Full Backup {year}-{month}-{day} {hr24}:{min}:{sec}",
      sources: sources(3, 2),
      enable_proton_upload: true, proton_authenticated: true, proton_auth_warning: null,
      proton_login_in_progress: false, proton_login_url: null, proton_login_error: null,
      proton_folder: "Home Assistant Backups", backup_cooldown_active: false,
      backup_name_keys: { year: "2026", month: "06", day: "28", hr24: "02", min: "51", sec: "38", version: "2026.6.0", date: "2026-06-28" }
    };
  }

  function status() {
    var s = base();
    switch (scenario) {
      case "empty":
        s.backups = []; s.sources = sources(0, 0); s.last_backup_text = "Never"; s.last_backup_detail = "Never";
        break;
      case "many":
        s.backups = [];
        for (var i = 0; i < 14; i++) {
          var both = i % 3 !== 0;
          s.backups.push(backup({
            name: "Full Backup 2026-06-" + String(28 - i).padStart(2, "0"), slug: "slug" + i,
            date: "Day " + i, createdAt: i + " days ago", timestamp: 1782010298 - i * 86400,
            type: i % 4 === 0 ? "partial" : "full", note: i === 2 ? "monthly keep" : null,
            uploadable: !both, protected: i % 2 === 0,
            sources: both ? backup().sources : [{ name: "HomeAssistant", key: "HomeAssistant", size: "1.1 GB", retained: false, ignored: false, delete_next: i > 8, slug: "slug" + i }]
          }));
        }
        s.sources = sources(14, 9);
        break;
      case "syncing":
        s.syncing = true;
        break;
      case "uploading":
        s.syncing = true;
        s.backups[2].uploadable = false;
        s.backups[2].status_detail = "Uploading to Proton Drive";
        // Real backend returns raw numbers: progress=float percent,
        // total=bytes transferred, speed=bytes/sec. The UI formats these.
        var pos = 30603026.479154732 + (Date.now() / 50 % 5000000);
        s.backups[2].status = "Uploading";
        s.backups[2].upload_info = { name: "Proton Drive", progress: 100 * pos / 587202560, speed: 3250000 + (Date.now() / 100 % 400000), total: pos, started: "2 minutes ago" };
        break;
      case "uploading-cli":
        // The opaque proton-drive CLI phase: progress pinned at 100, "speed"
        // = total/elapsed which decays. The UI should show an indeterminate
        // state, not a frozen 100% + bad speed.
        s.syncing = true;
        s.backups[2].uploadable = false;
        s.backups[2].status = "Uploading";
        s.backups[2].status_detail = "Uploading to Proton Drive";
        s.backups[2].upload_info = { name: "Proton Drive", progress: 100, speed: 587202560 / (((Date.now() / 1000) % 240) + 4), total: 587202560, started: "3 minutes ago" };
        break;
      case "pending":
        s.syncing = true;
        s.backups.unshift(backup({ name: "Full Backup (in progress)", slug: "pending1", size: "—", date: "just now", createdAt: "just now", isPending: true, restorable: false, status: "Creating", sources: [{ name: "HomeAssistant", key: "HomeAssistant", size: "—", retained: false, ignored: false, delete_next: false, slug: "pending1" }] }));
        break;
      case "signed-out":
        s.proton_authenticated = false;
        break;
      case "auth-warning":
        s.proton_auth_warning = "proton-drive exited 1: unexpected server error";
        break;
      case "login-pending":
        s.proton_authenticated = false; s.proton_login_in_progress = true;
        s.proton_login_url = "https://account.proton.me/authorize?client=web#payload=MOCK_SECRET_DO_NOT_LOG";
        break;
      case "error-auth":
        s.last_error = { error_type: "proton_not_authenticated", message: "The addon isn't signed in to Proton Drive. Open the addon's Web UI and click Sign in to authorize with Proton Drive.", details: "ProtonNotAuthenticated: session expired\n  at protoncli.py:120", data: {} };
        s.last_error_count = 3; s.proton_authenticated = false;
        break;
      case "error-offline":
        s.last_error = { error_type: "proton_cant_connect", message: "Couldn't reach Proton Drive (network problem).  The addon will keep retrying automatically.", details: "ProtonConnectionError: FailedToOpenSocket", data: {} };
        s.last_error_count = 2;
        break;
      case "error-multiple-deletes":
        s.last_error = { error_type: "multiple_deletes", message: "The add-on has been configured to delete more than one older backups. Please confirm this.", details: "DeleteMultipleBackups", data: { count: 3 } };
        s.last_error_count = 1;
        break;
      case "error-low-space":
        s.last_error = { error_type: "low_space", message: "Your backup folder is low on disk space. Backups can't be created until space is available.", details: "LowSpaceError", data: { free: "120 MB" } };
        s.last_error_count = 2;
        break;
      case "please-wait":
        s.syncing = true;
        s.last_error = { error_type: "please_wait", message: "A sync is already in progress, please wait.", details: "PleaseWait", data: {} };
        break;
      case "cooldown":
        s.backup_cooldown_active = true;
        break;
    }
    return s;
  }

  function ok(data) { return Promise.resolve(data || { message: "OK (mock)" }); }
  function reject(data) { return Promise.reject(data); }

  var SCENARIOS = ["normal", "many", "empty", "syncing", "uploading", "uploading-cli", "pending", "signed-out",
    "auth-warning", "login-pending", "cooldown", "error-auth", "error-offline", "error-multiple-deletes", "error-low-space", "please-wait"];

  window.MockServer = {
    scenarios: function () { return SCENARIOS; },
    current: function () { return scenario; },
    setScenario: function (s) { scenario = s; },
    log: function () {
      return Promise.resolve(
        "2026-06-28 02:50:01 INFO Starting backup sync\n" +
        "2026-06-28 02:51:38 INFO Created backup 'Full Backup 2026-06-28' (1.4 GB)\n" +
        "2026-06-28 02:52:10 INFO Uploading to Proton Drive...\n" +
        "2026-06-28 02:58:44 WARNING Upload slower than expected\n" +
        "2026-06-28 02:59:01 INFO Upload complete\n" +
        "2026-06-28 03:00:00 DEBUG Next backup scheduled for Mon Jun 30 02:00:00 2026\n"
      );
    },
    handle: function (path, opts) {
      var clean = path.split("?")[0];
      switch (clean) {
        case "/getstatus": return ok(status());
        case "/getconfig": return ok({
          config: {
            days_between_backups: 3, backup_time_of_day: "02:00", max_backups_in_ha: 4, max_backups_in_proton_drive: 4,
            backup_name: "Full Backup {year}-{month}-{day} {hr24}:{min}:{sec}", backup_password: "",
            delete_before_new_backup: false, call_backup_snapshot: false,
            enable_proton_upload: true, proton_folder_name: "Home Assistant Backups", delete_after_upload: false,
            upload_limit_bytes_per_second: "", proton_drive_timeout_seconds: 120, proton_transfer_timeout_seconds: 3600,
            exclude_folders: "", exclude_addons: "", exclude_ha_database: false,
            generational_days: 0, generational_weeks: 0, generational_months: 0, generational_years: 0,
            generational_day_of_week: "mon", generational_day_of_month: 1, generational_day_of_year: 1, generational_delete_early: false,
            stop_addons: "", disable_watchdog_when_stopping: false,
            notify_for_stale_backups: true, enable_backup_stale_sensor: true, enable_backup_state_sensor: true, send_error_reports: false,
            ignore_other_backups: false, ignore_upgrade_backups: false, delete_ignored_after_days: "",
            background_color: "", accent_color: "", expose_extra_server: false, require_login: false, use_ssl: false,
            certfile: "fullchain.pem", keyfile: "privkey.pem", port: 1627,
            confirm_multiple_deletes: true, warn_for_low_space: true, watch_backup_directory: true, verbose: false,
            log_level: "INFO", console_log_level: "INFO", proton_cli_path: "proton-drive", proton_data_path: "/data/proton",
            max_sync_interval_seconds: "1 hour", maximum_upload_chunk_bytes: "10 MB"
          },
          defaults: {
            days_between_backups: 3, max_backups_in_ha: 4, max_backups_in_proton_drive: 4, accent_color: "#1a5fb4",
            background_color: "#0b1020", backup_name: "Full Backup {year}-{month}-{day} {hr24}:{min}:{sec}", port: 1627,
            log_level: "INFO", console_log_level: "INFO", proton_folder_name: "Home Assistant Backups"
          },
          folders: [
            { slug: "homeassistant", name: "Home Assistant Configuration", description: "Your config directory, eg configuration.yaml" },
            { slug: "media", name: "Media", description: 'Your "/media" directory.' },
            { slug: "ssl", name: "SSL", description: 'Your "/ssl" directory.' },
            { slug: "share", name: "Share", description: 'Your "/share" directory.' },
            { slug: "addons/local", name: "Local Addons", description: "Your local add-ons directory." }
          ],
          addons: [
            { slug: "core_mosquitto", name: "Mosquitto broker", version: "6.4.0", description: "MQTT broker" },
            { slug: "a0d7b954_influxdb", name: "InfluxDB", version: "5.0.0", description: "Time series database" },
            { slug: "core_zwave_js", name: "Z-Wave JS", version: "0.7.0", description: "Z-Wave integration" }
          ]
        });
        case "/makeanissue": return ok({ markdown: "## Bug report (mock)\n\n- Version: dev\n- Scenario: " + scenario + "\n\nNo credentials are included.\n" });
        case "/protonlogin": return ok({ ok: true, url: "https://account.proton.me/authorize?client=web#payload=MOCK_SECRET_DO_NOT_LOG", message: "Open this link and sign in (mock)." });
        case "/protonlogincancel": scenario = "signed-out"; return ok({ ok: true });
        case "/protonauth": return ok({ authenticated: status().proton_authenticated, message: "Checked (mock)" });
        case "/protonlogout": scenario = "signed-out"; return ok({ ok: true, message: "Signed out (mock)" });
        case "/confirmdelete": scenario = "normal"; return ok({ message: "Confirmed (mock)" });
        case "/skipspacecheck": scenario = "normal"; return ok({ message: "Skipping space check (mock)" });
        case "/ignorestartupcooldown": scenario = "normal"; return ok({ message: "Cooldown skipped (mock)" });
        case "/startSync": case "/sync": scenario = "syncing"; return ok({ message: "Sync started (mock)" });
        case "/cancelSync": scenario = "normal"; return ok({ message: "Cancelled (mock)" });
        case "/backup": return ok({ message: "Requested backup (mock)" });
        case "/upload": return ok({ message: "Uploading in background (mock)" });
        case "/deleteSnapshot": return ok({ message: "Deleted (mock)" });
        case "/retain": return ok({ message: "Updated (mock)" });
        case "/note": return ok({ message: "Note saved (mock)" });
        case "/ignore": return ok({ message: "Updated (mock)" });
        case "/saveconfig": return ok({ message: "Settings saved (mock)", reload_page: false });
        default: return ok({ message: "OK (mock): " + clean });
      }
    }
  };

  // Allow choosing a scenario via ?mock=1&scenario=uploading
  var m = /[?&]scenario=([\w-]+)/.exec(location.search);
  if (m && SCENARIOS.indexOf(m[1]) >= 0) scenario = m[1];
})();
