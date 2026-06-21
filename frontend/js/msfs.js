/* msfs.js – shows YOUR own MSFS2024 aircraft (from the SimConnect bridge) as a
   distinct marker, and lets you replay logged flights. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});
  let marker = null, replayLine = null, last = null;

  SW.initMsfs = function () {
    if (!SW.features || !SW.features.msfs) return;
    SW.pollMsfs();
    setInterval(SW.pollMsfs, 3000);
    SW.injectMsfsFlights();
  };

  function simIcon(heading) {
    const html = `<div class="sim-marker">
      <svg viewBox="0 0 24 24" width="30" height="30" style="transform:rotate(${heading || 0}deg)">
        <path fill="#00e5ff" stroke="#003" stroke-width="0.8"
          d="M12 2 L14 11 L22 15 L22 17 L14 14.5 L13.5 20 L16 21.5 L16 23 L12 22 L8 23 L8 21.5 L10.5 20 L10 14.5 L2 17 L2 15 L10 11 Z"/>
      </svg><span class="sim-badge">SIM</span></div>`;
    return L.divIcon({ className: "", html, iconSize: [30, 30], iconAnchor: [15, 15] });
  }

  SW.pollMsfs = async function () {
    try {
      const res = await fetch("/api/msfs_position", SW.fetchOpts());
      const d = await res.json();
      if (!d.active || !d.position) {            // sim not running → hide marker
        if (marker) { SW.map.leaflet.removeLayer(marker); marker = null; }
        return;
      }
      const p = d.position;
      last = p;
      const pos = [p.latitude, p.longitude];
      if (!marker) {
        marker = L.marker(pos, { icon: simIcon(p.heading), zIndexOffset: 2000 })
          .addTo(SW.map.leaflet);
        marker.on("click", (e) => { L.DomEvent.stop(e); SW.selectSim(); });
      } else {
        marker.setLatLng(pos);
        marker.setIcon(simIcon(p.heading));
      }
      const alt = p.altitude_ft != null ? `${Math.round(p.altitude_ft).toLocaleString()} ft` : "—";
      const spd = p.true_airspeed_kts != null ? `${Math.round(p.true_airspeed_kts)} kts` : "—";
      marker.bindTooltip(`🎮 ${p.aircraft || "My flight"} · ${alt} · ${spd}`,
        { direction: "top", offset: [0, -12] });
      if (SW.simSelected) SW.renderSimDetail(p);   // keep the open card fresh
    } catch (e) { /* ignore */ }
  };

  // Click the SIM marker → same kind of detail overlay as the real aircraft.
  SW.selectSim = function () {
    if (!last) return;
    SW.selectAircraft(null);          // clear any real selection
    SW.simSelected = true;
    SW.map.leaflet.panTo([last.latitude, last.longitude]);
    SW.renderSimDetail(last);
  };

  SW.renderSimDetail = function (p) {
    const card = document.getElementById("detail-card");
    if (!card) return;
    const model = p.aircraft || "My aircraft";
    const altFt = p.altitude_ft != null ? Math.round(p.altitude_ft).toLocaleString() + " ft" : "—";
    const altM = p.altitude_ft != null ? ` (${Math.round(p.altitude_ft * 0.3048).toLocaleString()} m)` : "";
    const kts = p.true_airspeed_kts != null ? Math.round(p.true_airspeed_kts) : null;
    const spd = kts != null ? `${kts} kts (${Math.round(kts * 1.852)} km/h)` : "—";
    const vs = p.vertical_speed_fpm != null ? `${Math.round(p.vertical_speed_fpm)} fpm` : "—";
    const rows = [
      ["Aircraft", model],
      ["Altitude", altFt + altM],
      ["Speed", spd],
      ["Vertical speed", vs],
      ["Heading", p.heading != null ? `${Math.round(p.heading)}°` : "—"],
      ["Squawk", p.squawk || "—"],
      ["Status", p.on_ground ? "On ground" : "Airborne"],
      ["Position", `${p.latitude.toFixed(4)}, ${p.longitude.toFixed(4)}`],
    ];
    card.innerHTML = `
      <h3><span class="cat-swatch" style="background:#00e5ff"></span> 🎮 SIM
        <span class="dc-close" onclick="SkyWatch.closeSim()">✕</span></h3>
      <div class="muted">${model} · live from MSFS2024</div>
      <div class="dc-photo" id="dc-photo"></div>
      <table>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>`;
    card.classList.remove("hidden");
    SW.loadSimPhoto(model);
  };

  SW.closeSim = function () {
    SW.simSelected = false;
    document.getElementById("detail-card").classList.add("hidden");
  };

  let lastPhotoModel = null;
  SW.loadSimPhoto = async function (model) {
    const box = document.getElementById("dc-photo");
    if (!box) return;
    if (model === lastPhotoModel && SW._simPhotoUrl) {     // avoid refetching each poll
      box.innerHTML = `<img src="${SW._simPhotoUrl}" alt="${model}"/>`;
      return;
    }
    lastPhotoModel = model;
    try {
      const res = await fetch(`/api/image?q=${encodeURIComponent(model + " aircraft")}`, SW.fetchOpts());
      const d = await res.json();
      if (d.url && document.getElementById("dc-photo")) {
        SW._simPhotoUrl = d.url;
        document.getElementById("dc-photo").innerHTML = `<img src="${d.url}" alt="${model}"/>`;
      }
    } catch (e) { /* ignore */ }
  };

  // --- MSFS flights browser (dedicated panel) ---
  SW.injectMsfsFlights = function () {
    const btn = document.getElementById("btn-msfs");
    if (!btn) return;
    btn.addEventListener("click", () => {
      document.querySelectorAll(".panel").forEach((p) => {
        if (p.id !== "msfs-panel") p.classList.add("hidden");
      });
      const show = document.getElementById("msfs-panel").classList.toggle("hidden") === false;
      if (show) SW.loadMsfsFlights();
    });
  };

  SW.loadMsfsFlights = async function () {
    const el = document.getElementById("msfs-body");
    if (!el) return;
    try {
      const res = await fetch("/api/msfs/flights", SW.fetchOpts());
      const fl = (await res.json()).flights || [];
      if (!fl.length) { el.innerHTML = '<p class="muted">No flights logged yet. Fly in MSFS and they\'ll appear here.</p>'; return; }
      el.innerHTML = fl.map((f) => {
        const d = new Date(f.start_ts * 1000);
        const min = Math.round((f.duration_s || 0) / 60);
        const route = (f.dep_airport || f.arr_airport)
          ? `<div class="ai-reason">🛫 ${f.dep_airport || "?"} → 🛬 ${f.arr_airport || "?"}</div>` : "";
        const stats = [
          `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
          `${min} min`,
          f.distance_km ? `${Math.round(f.distance_km)} km` : null,
          f.max_alt_ft ? `${Math.round(f.max_alt_ft).toLocaleString()} ft` : null,
          f.max_speed_kts ? `${Math.round(f.max_speed_kts)} kts` : null,
        ].filter(Boolean).join(" · ");
        return `<div class="ai-item" onclick="SkyWatch.replayMsfs(${f.id})">
          <div class="ai-head"><span class="cat-swatch" style="background:#00e5ff"></span>
            <b>${f.aircraft || "Flight"}</b></div>
          ${route}
          <div class="muted" style="font-size:.72rem">${stats}</div>
        </div>`;
      }).join("");
    } catch (e) { /* ignore */ }
  };

  SW.replayMsfs = async function (id) {
    try {
      const res = await fetch(`/api/msfs/flights/${id}`, SW.fetchOpts());
      const gj = await res.json();
      const coords = (gj.geometry && gj.geometry.coordinates) || [];
      if (!coords.length) return;
      if (replayLine) SW.map.leaflet.removeLayer(replayLine);
      const latlngs = coords.map((c) => [c[1], c[0]]);
      replayLine = L.polyline(latlngs, { color: "#00e5ff", weight: 3, opacity: 0.9 })
        .addTo(SW.map.leaflet);
      SW.map.leaflet.fitBounds(replayLine.getBounds(), { padding: [40, 40] });
    } catch (e) { /* ignore */ }
  };
})();
