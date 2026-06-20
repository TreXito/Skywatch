/* alerts.js – alert history panel + live alert toasts/badge. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  const COLORS = {
    emergency: "#e74c3c", military: "#f1c40f", watchlist: "#f39c12",
    rare: "#3498db", holding: "#9b59b6",
  };
  let unseen = 0;

  SW.initAlerts = async function () {
    await SW.loadAlertHistory();
  };

  SW.loadAlertHistory = async function () {
    try {
      const res = await fetch("/api/alerts?limit=100", SW.fetchOpts());
      const data = await res.json();
      SW.renderAlerts(data.alerts || []);
    } catch (e) { /* ignore */ }
  };

  SW.renderAlerts = function (alerts) {
    const list = document.getElementById("alerts-list");
    if (!alerts.length) {
      list.innerHTML = '<p class="muted">No alerts yet.</p>';
      return;
    }
    list.innerHTML = alerts.map((a) => {
      const color = COLORS[a.alert_type] || "#95a5a6";
      const when = new Date((a.ts || a.timestamp) * 1000).toLocaleString();
      const cs = (a.callsign || a.icao24 || "").trim();
      return `<div class="alert-item" style="border-left-color:${color}"
                   onclick="SkyWatch.focusAircraft('${a.icao24}')">
        <div class="a-title">${a.title || a.alert_type}</div>
        <div class="a-meta">${cs}${a.typecode ? " · " + a.typecode : ""} · ${when}</div>
      </div>`;
    }).join("");
  };

  // Called when a poll delivers new alerts.
  SW.onNewAlerts = function (alerts) {
    if (!alerts || !alerts.length) return;
    const panel = document.getElementById("alerts-panel");
    if (panel.classList.contains("hidden")) {
      unseen += alerts.length;
      const badge = document.getElementById("alert-badge");
      badge.textContent = unseen;
      badge.classList.remove("hidden");
    }
    SW.loadAlertHistory();
    if (Notification && Notification.permission === "granted") {
      alerts.forEach((a) =>
        new Notification("Sky Watch", { body: a.title + " – " + (a.callsign || a.icao24) }));
    }
  };

  // Clear badge when the panel is opened.
  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-alerts").addEventListener("click", () => {
      unseen = 0;
      document.getElementById("alert-badge").classList.add("hidden");
    });
  });
})();
