/* filters.js – category toggles, search, panel show/hide, detail card. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  const state = {
    visibleCategories: new Set(Object.keys(SW.CATEGORY_LABELS)),
    search: "",
  };
  SW.filters = state;

  SW.isCategoryVisible = (cat) => state.visibleCategories.has(cat || "normal");

  SW.matchesSearch = function (ac) {
    if (!state.search) return true;
    const q = state.search.toLowerCase();
    return (
      (ac.callsign || "").toLowerCase().includes(q) ||
      (ac.typecode || "").toLowerCase().includes(q) ||
      (ac.icao24 || "").toLowerCase().includes(q) ||
      (ac.registration || "").toLowerCase().includes(q) ||
      (ac.operator || "").toLowerCase().includes(q)
    );
  };

  SW.initFilters = function () {
    const container = document.getElementById("category-toggles");
    Object.entries(SW.CATEGORY_LABELS).forEach(([cat, label]) => {
      const row = document.createElement("label");
      row.className = "cat-toggle";
      row.innerHTML = `
        <input type="checkbox" data-cat="${cat}" checked />
        <span class="cat-swatch" style="background:${SW.CATEGORY_COLORS[cat]}"></span>
        <span>${label}</span>`;
      row.querySelector("input").addEventListener("change", (e) => {
        if (e.target.checked) state.visibleCategories.add(cat);
        else state.visibleCategories.delete(cat);
        SW.rerender();
      });
      container.appendChild(row);
    });

    document.getElementById("search-input").addEventListener("input", (e) => {
      state.search = e.target.value.trim();
      SW.rerender();
    });

    // Panel toggles.
    const toggle = (id, panelId) =>
      document.getElementById(id).addEventListener("click", () => {
        document.querySelectorAll(".panel").forEach((p) => {
          if (p.id !== panelId) p.classList.add("hidden");
        });
        document.getElementById(panelId).classList.toggle("hidden");
      });
    toggle("btn-filters", "filter-panel");
    toggle("btn-alerts", "alerts-panel");

    document.getElementById("toggle-trails").addEventListener("change", () => {
      SW.refreshTrail();
    });
    document.getElementById("toggle-radius").addEventListener("change", (e) => {
      SW.drawRadius(e.target.checked);
    });
  };

  SW.rerender = function () {
    if (SW.lastList) SW.updateAircraft(SW.lastList);
  };

  // --- Detail card rendering ---
  SW.renderDetail = function (ac) {
    const card = document.getElementById("detail-card");
    const cs = (ac.callsign || "—").trim();
    const fmtAlt = (m) => (m == null ? "—" : `${Math.round(m).toLocaleString()} m`);
    const fmtSpd = (v) => (v == null ? "—" : `${Math.round(v * 3.6).toLocaleString()} km/h`);
    const color = SW.CATEGORY_COLORS[ac.marker_category] || SW.CATEGORY_COLORS.normal;

    const rows = [
      ["Type", ac.model || ac.typecode || "Unknown"],
      ["Registration", ac.registration || "—"],
      ["Operator", ac.operator || ac.owner || "—"],
      ["Origin", ac.origin_country || "—"],
      ["Altitude", fmtAlt(ac.baro_altitude ?? ac.geo_altitude)],
      ["Speed", fmtSpd(ac.velocity)],
      ["Heading", ac.true_track == null ? "—" : `${Math.round(ac.true_track)}°`],
      ["Squawk", ac.squawk ? `${ac.squawk}${SW.isEmergencySquawk(ac.squawk) ? " ⚠️" : ""}` : "—"],
      ["Distance", ac.distance_km == null ? "—" : `${ac.distance_km.toFixed(1)} km`],
    ];

    card.innerHTML = `
      <h3><span class="cat-swatch" style="background:${color}"></span> ${cs}
        <span class="dc-close" onclick="SkyWatch.selectAircraft(null)">✕</span></h3>
      ${ac.watchlist_label ? `<div class="muted">⭐ ${ac.watchlist_label}</div>` : ""}
      <table>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>
      <div class="dc-links">
        ${cs !== "—" ? `<a href="https://www.flightradar24.com/${cs}" target="_blank">FR24 ↗</a>` : ""}
        <a href="https://globe.adsbexchange.com/?icao=${ac.icao24}" target="_blank">ADS-B ↗</a>
      </div>`;
    card.classList.remove("hidden");
  };

  SW.isEmergencySquawk = (sq) => ["7500", "7600", "7700"].includes(sq);
})();
