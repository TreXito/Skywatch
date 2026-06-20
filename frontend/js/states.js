/* states.js – viewport-driven aircraft display (worldwide).

   When tracking_mode is "viewport" or "global", the map shows every aircraft in
   the current view (not just the home radius). It refetches on pan/zoom and on a
   timer. In "radius" mode this module is inactive and the WebSocket drives markers. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});
  let timer = null, debounce = null, inFlight = false;

  SW.initStates = function (config) {
    if (SW.trackingMode === "radius") return; // WebSocket handles markers
    const lf = SW.map.leaflet;
    const trigger = () => { clearTimeout(debounce); debounce = setTimeout(SW.fetchViewport, 450); };
    lf.on("moveend", trigger);
    SW.fetchViewport();
    const iv = Math.max(5, config.poll_interval || 10) * 1000;
    timer = setInterval(SW.fetchViewport, iv);
  };

  SW.fetchViewport = async function () {
    if (inFlight) return;
    inFlight = true;
    try {
      const lf = SW.map.leaflet;
      const b = lf.getBounds();
      const q = SW.trackingMode === "global" ? "" :
        `?lamin=${b.getSouth().toFixed(4)}&lamax=${b.getNorth().toFixed(4)}` +
        `&lomin=${Math.max(-180, b.getWest()).toFixed(4)}` +
        `&lomax=${Math.min(180, b.getEast()).toFixed(4)}`;
      const res = await fetch(`/api/states${q}`, SW.fetchOpts());
      const data = await res.json();
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
