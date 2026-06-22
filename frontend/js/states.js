/* states.js – viewport-driven aircraft display (worldwide).

   When tracking_mode is "viewport" or "global", the map shows every aircraft in
   the current view (not just the home radius). It refetches on pan/zoom and on a
   timer. In "radius" mode this module is inactive and the WebSocket drives markers. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});
  let timer = null, debounce = null, inFlight = false, lastBounds = null;

  SW.initStates = function (config) {
    if (SW.trackingMode === "radius") return; // WebSocket handles markers
    // Time-based refresh ONLY: the map refetches the current view on a fixed
    // timer, never on pan/zoom. Panning around therefore costs no extra OpenSky
    // credits; new areas fill in on the next tick.
    SW.fetchViewport();
    const iv = Math.max(15, config.poll_interval || 30) * 1000;
    timer = setInterval(SW.fetchViewport, iv);
  };

  SW.fetchViewport = async function () {
    if (inFlight) return;
    inFlight = true;
    try {
      const lf = SW.map.leaflet;
      const b = lf.getBounds();
      lastBounds = { b: b.pad(0.1), zoom: lf.getZoom() };
      const q = SW.trackingMode === "global" ? "" :
        `?lamin=${b.getSouth().toFixed(4)}&lamax=${b.getNorth().toFixed(4)}` +
        `&lomin=${Math.max(-180, b.getWest()).toFixed(4)}` +
        `&lomax=${Math.min(180, b.getEast()).toFixed(4)}`;
      const res = await fetch(`/api/states${q}`, SW.fetchOpts());
      const data = await res.json();
      // Sync the client clock to the server so we can age positions accurately.
      if (data.server_time) SW.clockOffset = data.server_time - Date.now() / 1000;
      SW.lastList = data.aircraft || [];
      SW.updateAircraft(SW.lastList);
      SW.updateStatus(data.status, SW.lastList.length);
      const total = data.count_total || SW.lastList.length;
      const el = document.getElementById("status-count");
      if (el) {
        el.textContent = total > SW.lastList.length
          ? `${SW.lastList.length} of ${total} shown`
          : `${SW.lastList.length} aircraft in view`;
      }
      const sc = document.getElementById("stat-count");
      if (sc) sc.textContent = SW.lastList.length;
    } catch (e) { /* ignore */ }
    finally { inFlight = false; }
  };
})();
