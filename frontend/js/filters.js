/* filters.js – category toggles, search, panel show/hide, detail card. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  const state = {
    visibleCategories: new Set(Object.keys(SW.CATEGORY_LABELS)),
    search: "",
    airborneOnly: false,
  };
  SW.filters = state;

  SW.isCategoryVisible = (cat) => state.visibleCategories.has(cat || "normal");
  SW.passesGroundFilter = (ac) => !state.airborneOnly || !ac.on_ground;

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
    document.getElementById("toggle-airborne").addEventListener("change", (e) => {
      state.airborneOnly = e.target.checked;
      SW.rerender();
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
      ["Squawk", SW.squawkDisplay(ac.squawk)],
      ["Distance", ac.distance_km == null ? "—" : `${ac.distance_km.toFixed(1)} km`],
    ];

    card.innerHTML = `
      <h3><span class="cat-swatch" style="background:${color}"></span> ${cs}
        <span class="dc-close" onclick="SkyWatch.selectAircraft(null)">✕</span></h3>
      ${ac.watchlist_label ? `<div class="muted">⭐ ${ac.watchlist_label}</div>` : ""}
      <div class="dc-route" id="dc-route"></div>
      <div class="dc-photo" id="dc-photo"></div>
      <table>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>
      <div class="dc-links">
        ${cs !== "—" ? `<a href="https://www.flightradar24.com/${cs}" target="_blank">FR24 ↗</a>` : ""}
        <a href="https://globe.adsbexchange.com/?icao=${ac.icao24}" target="_blank">ADS-B ↗</a>
        <a href="#" id="dc-flights-toggle">Flight history</a>
      </div>
      <div class="dc-flights hidden" id="dc-flights"></div>`;
    card.classList.remove("hidden");
    // Fix the toggle label (avoid odd glyphs) and wire it.
    const ft = document.getElementById("dc-flights-toggle");
    if (ft) {
      ft.textContent = "🛫 Flight history";
      ft.addEventListener("click", (e) => {
        e.preventDefault();
        const box = document.getElementById("dc-flights");
        box.classList.toggle("hidden");
        if (!box.classList.contains("hidden")) SW.loadFlights(ac.icao24);
      });
    }
    SW.loadPhoto(ac.icao24);
    SW.loadRoute(ac);
  };

  // --- Squawk code explanation ---
  const SQUAWK_MEANINGS = {
    "7500": "⚠️ Hijack", "7600": "⚠️ Radio failure", "7700": "⚠️ Emergency",
    "7777": "Military interceptor / NORDO", "0000": "Non-discrete (military/error)",
    "1200": "VFR (US/Canada)", "7000": "VFR conspicuity (Europe)",
    "2000": "Default / uncontrolled entry", "1000": "IFR Mode-S (no discrete code)",
    "0030": "FIR conspicuity", "0033": "Parachute drop", "7004": "Aerobatics / display",
    "7010": "Aerodrome traffic", "5000": "NATO / military", "4000": "Military ops",
  };
  SW.squawkMeaning = function (sq) {
    if (!sq) return null;
    if (SQUAWK_MEANINGS[sq]) return SQUAWK_MEANINGS[sq];
    if (sq >= "7501" && sq <= "7577") return "Military / special use";
    if (sq >= "0301" && sq <= "0377") return "Domestic / FIR";
    return null;
  };
  SW.squawkDisplay = function (sq) {
    if (!sq) return "—";
    const m = SW.squawkMeaning(sq);
    return m ? `${sq} – ${m}` : sq;
  };

  // --- Flight history (FlightRadar24-like, observed by this instance) ---
  SW.loadFlights = async function (icao24) {
    const box = document.getElementById("dc-flights");
    if (!box) return;
    box.innerHTML = '<span class="muted">Loading…</span>';
    try {
      const res = await fetch(`/api/flights/${icao24}`, SW.fetchOpts());
      const d = await res.json();
      const fl = d.flights || [];
      if (!fl.length) { box.innerHTML = '<span class="muted">No recorded flights yet.</span>'; return; }
      box.innerHTML = fl.map((f) => {
        const start = new Date(f.start_ts * 1000);
        const dur = Math.max(0, Math.round((f.end_ts - f.start_ts) / 60));
        const route = (f.origin || f.destination)
          ? `<b>${f.origin || "?"}</b>→<b>${f.destination || "?"}</b> ` : "";
        const alt = f.max_alt_m ? ` · ${Math.round(f.max_alt_m).toLocaleString()} m` : "";
        return `<div class="flight-item">${route}
          <span>${f.callsign || "—"}</span>
          <span class="muted">${start.toLocaleDateString()} ${start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${dur} min${alt}</span></div>`;
      }).join("");
    } catch (e) { box.innerHTML = '<span class="muted">Failed to load.</span>'; }
  };

  // --- Flight route (origin → destination) + map line ---
  SW.loadRoute = async function (ac) {
    SW.clearRoute();
    if (!SW.features || !SW.features.routes) return;
    const cs = (ac.callsign || "").trim();
    if (!cs) return;
    try {
      const res = await fetch(
        `/api/route/${encodeURIComponent(cs)}?icao24=${ac.icao24}`, SW.fetchOpts());
      const d = await res.json();
      const r = d.route;
      if (!r || (!r.origin && !r.destination)) return;
      // Only render for the still-selected aircraft.
      if (SW.map.selected !== ac.icao24) return;

      const o = r.origin, dst = r.destination;
      const box = document.getElementById("dc-route");
      if (box) {
        const fmt = (a) => a ? `<b>${a.iata || a.icao || "?"}</b> <span class="muted">${a.city || a.name || ""}</span>` : "—";
        box.innerHTML = `<div class="route-line">
            <span>${fmt(o)}</span><span class="route-arrow">✈</span><span>${fmt(dst)}</span>
          </div>${r.airline ? `<div class="muted">${r.airline}</div>` : ""}`;
      }
      SW.drawRoute(ac, o, dst);
    } catch (e) { /* ignore */ }
  };

  SW.drawRoute = function (ac, o, dst) {
    const lf = SW.map.leaflet;
    if (!SW.map.routeLayer) SW.map.routeLayer = L.layerGroup().addTo(lf);
    const grp = SW.map.routeLayer;
    grp.clearLayers();
    const plane = (ac.latitude != null) ? [ac.latitude, ac.longitude] : null;

    function airportMarker(a, label) {
      const m = L.circleMarker([a.lat, a.lon], {
        radius: 6, color: "#fff", weight: 1.5, fillColor: "#2ecc71", fillOpacity: 1,
      }).bindTooltip(`${label}: ${a.name || a.iata}`, { direction: "top", permanent: false });
      grp.addLayer(m);
    }
    if (o && o.lat != null) airportMarker(o, "From");
    if (dst && dst.lat != null) airportMarker(dst, "To");

    // Route in orange so it stands apart from the blue aircraft. Flown segment
    // (origin → aircraft) solid; remaining (aircraft → destination) dashed.
    if (o && o.lat != null && plane)
      grp.addLayer(L.polyline(SW.greatCircle([o.lat, o.lon], plane),
        { color: "#ff9f1c", weight: 2.5, opacity: .9 }));
    if (dst && dst.lat != null && plane)
      grp.addLayer(L.polyline(SW.greatCircle(plane, [dst.lat, dst.lon]),
        { color: "#ff9f1c", weight: 2, opacity: .55, dashArray: "8 8" }));
  };

  SW.clearRoute = function () {
    if (SW.map.routeLayer) SW.map.routeLayer.clearLayers();
    const box = document.getElementById("dc-route");
    if (box) box.innerHTML = "";
  };

  // Great-circle interpolation between two [lat,lon] points.
  SW.greatCircle = function (a, b, n = 48) {
    const rad = Math.PI / 180, deg = 180 / Math.PI;
    const lat1 = a[0] * rad, lon1 = a[1] * rad, lat2 = b[0] * rad, lon2 = b[1] * rad;
    const d = 2 * Math.asin(Math.sqrt(
      Math.sin((lat2 - lat1) / 2) ** 2 +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2));
    if (!d) return [a, b];
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const f = i / n;
      const A = Math.sin((1 - f) * d) / Math.sin(d);
      const B = Math.sin(f * d) / Math.sin(d);
      const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
      const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
      const z = A * Math.sin(lat1) + B * Math.sin(lat2);
      pts.push([Math.atan2(z, Math.sqrt(x * x + y * y)) * deg, Math.atan2(y, x) * deg]);
    }
    return pts;
  };

  // Aircraft photo (Planespotters) – lazy, cached server-side.
  SW.loadPhoto = async function (icao24) {
    if (!SW.features || !SW.features.photos) return;
    try {
      const res = await fetch(`/api/photo/${icao24}`, SW.fetchOpts());
      const d = await res.json();
      const box = document.getElementById("dc-photo");
      if (box && d.photo && d.photo.thumbnail) {
        box.innerHTML = `<a href="${d.photo.link || "#"}" target="_blank">
          <img src="${d.photo.thumbnail}" alt="aircraft photo" /></a>
          <span class="muted">© ${d.photo.photographer || "Planespotters"}</span>`;
      }
    } catch (e) { /* ignore */ }
  };

  SW.isEmergencySquawk = (sq) => ["7500", "7600", "7700"].includes(sq);
})();
