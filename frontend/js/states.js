/* states.js – viewport-driven aircraft display (worldwide).

   When tracking_mode is "viewport" or "global", the map shows every aircraft in
   the current view (not just the home radius). It refetches on pan/zoom and on a
   timer. In "radius" mode this module is inactive and the WebSocket drives markers. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});
  let timer = null, debounce = null, inFlight = false, lastBounds = null;

  SW.initStates = function (config) {
    if (SW.trackingMode === "radius") return; // WebSocket handles markers
    const lf = SW.map.leaflet;
    // Longer debounce + significant-move gate so casually panning around doesn't
    // fire a fetch (and burn OpenSky credits) on every little move.
    const trigger = () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { if (movedEnough()) SW.fetchViewport(); }, 1200);
    };
    lf.on("moveend", trigger);
    SW.fetchViewport();
    const iv = Math.max(15, config.poll_interval || 30) * 1000;
    timer = setInterval(SW.fetchViewport, iv);
  };

  // Only refetch if the view changed meaningfully (new area or zoom), not for
  // small pans within the area we already loaded.
  function movedEnough() {
    const lf = SW.map.leaflet;
    const b = lf.getBounds();
    if (!lastBounds) return true;
    if (lf.getZoom() !== lastBounds.zoom) return true;
    // If the new center is still well inside the previously fetched bounds, skip.
    const c = b.getCenter();
    const lb = lastBounds.b;
    const inside = lb.contains(c);
    const grew = !lb.contains(b.getNorthEast()) || !lb.contains(b.getSouthWest());
    return !inside || grew;
  }

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
