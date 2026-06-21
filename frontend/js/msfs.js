/* msfs.js – shows YOUR own MSFS2024 aircraft (from the SimConnect bridge) as a
   distinct marker, and lets you replay logged flights. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});
  let marker = null, replayLine = null;

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
      const pos = [p.latitude, p.longitude];
      if (!marker) {
        marker = L.marker(pos, { icon: simIcon(p.heading), zIndexOffset: 2000 })
          .addTo(SW.map.leaflet);
        marker.on("click", () => marker.openPopup());
      } else {
        marker.setLatLng(pos);
        marker.setIcon(simIcon(p.heading));
      }
      const alt = p.altitude_ft != null ? `${Math.round(p.altitude_ft).toLocaleString()} ft` : "—";
      const spd = p.true_airspeed_kts != null ? `${Math.round(p.true_airspeed_kts)} kts` : "—";
      marker.bindTooltip(`🎮 ${p.aircraft || "My flight"} · ${alt} · ${spd}`,
        { direction: "top", offset: [0, -12] });
    } catch (e) { /* ignore */ }
  };

  // --- Flight replay (logged MSFS flights) ---
  SW.injectMsfsFlights = function () {
    const panel = document.getElementById("filter-panel");
    if (!panel || document.getElementById("msfs-flights")) return;
    const box = document.createElement("div");
    box.innerHTML = `<hr/><div class="muted">🎮 My MSFS flights</div>
      <div id="msfs-flights"><span class="muted">—</span></div>`;
    panel.appendChild(box);
    SW.loadMsfsFlights();
    document.getElementById("btn-filters")?.addEventListener("click", SW.loadMsfsFlights);
  };

  SW.loadMsfsFlights = async function () {
    const el = document.getElementById("msfs-flights");
    if (!el) return;
    try {
      const res = await fetch("/api/msfs/flights", SW.fetchOpts());
      const fl = (await res.json()).flights || [];
      if (!fl.length) { el.innerHTML = '<span class="muted">No flights logged yet.</span>'; return; }
      el.innerHTML = fl.slice(0, 15).map((f) => {
        const d = new Date(f.start_ts * 1000);
        const min = Math.round((f.duration_s || 0) / 60);
        return `<div class="flight-item" style="cursor:pointer" onclick="SkyWatch.replayMsfs(${f.id})">
          <span>${f.aircraft || "Flight"}</span>
          <span class="muted">${d.toLocaleDateString()} · ${min} min · ${Math.round(f.max_alt_ft || 0).toLocaleString()} ft</span>
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
