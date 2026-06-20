/* app.js – bootstraps the application: load config, init map/UI, connect WS. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});
  SW.lastList = [];

  SW.setConnection = function (online) {
    const dot = document.getElementById("status-conn");
    dot.classList.toggle("online", online);
    dot.classList.toggle("offline", !online);
  };

  SW.updateStatus = function (status, count) {
    document.getElementById("status-count").textContent = `${count} aircraft`;
    document.getElementById("stat-count").textContent = count;
    if (!status) return;
    const text = document.getElementById("status-text");
    if (status.last_error) {
      text.textContent = status.rate_limited
        ? "OpenSky rate limited – backing off"
        : `API error: ${status.last_error}`;
    } else {
      text.textContent = `OpenSky (${status.auth_mode}) – live`;
    }
    if (status.last_update) {
      const dt = new Date(status.last_update * 1000);
      document.getElementById("status-update").textContent =
        `updated ${dt.toLocaleTimeString()}`;
    }
    document.getElementById("status-rate").textContent =
      status.rate_limited ? "⚠️ rate limited" : "";
  };

  async function refreshMeta() {
    try {
      const res = await fetch("/api/status", SW.fetchOpts());
      const s = await res.json();
      document.getElementById("stat-meta").textContent =
        (s.metadata_rows || 0).toLocaleString() + " rows";
    } catch (e) { /* ignore */ }
  }

  async function boot() {
    let config;
    try {
      const res = await fetch("/api/config", SW.fetchOpts());
      config = await res.json();
    } catch (e) {
      document.getElementById("status-text").textContent = "Failed to load config";
      return;
    }

    if (!config.configured) {
      document.getElementById("config-banner").classList.remove("hidden");
      config.latitude = config.latitude || 0;
      config.longitude = config.longitude || 0;
    }

    SW.features = config.features || {};
    SW.trackingMode = config.tracking_mode || "viewport";
    SW.initMap(config);
    SW.initFilters();
    SW.initAlerts();
    SW.initTools();
    SW.initStats();
    SW.initLayers(config);
    SW.initStates(config);

    // Theme.
    document.body.classList.toggle("dark", config.dark_mode);
    document.body.classList.toggle("light", !config.dark_mode);
    SW.darkMode = config.dark_mode;
    document.getElementById("btn-theme").addEventListener("click", () => {
      SW.darkMode = !SW.darkMode;
      document.body.classList.toggle("dark", SW.darkMode);
      document.body.classList.toggle("light", !SW.darkMode);
      // Map basemap is changed via the layers control (top-left); this toggles
      // the UI panels theme only.
    });

    // Ask for desktop notification permission (best effort).
    if (window.Notification && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }

    SW.connectWS();
    refreshMeta();
    setInterval(refreshMeta, 60000);

    // Focus an aircraft if ?focus=icao24 is in the URL (from Discord links).
    const focus = new URLSearchParams(location.search).get("focus");
    if (focus) {
      SW._pendingFocus = focus.toLowerCase();
      const tryFocus = setInterval(() => {
        if (SW.map.markers[SW._pendingFocus]) {
          SW.focusAircraft(SW._pendingFocus);
          clearInterval(tryFocus);
        }
      }, 1000);
      setTimeout(() => clearInterval(tryFocus), 30000);
    }
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
