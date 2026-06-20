/* map.js – Leaflet setup, basemaps + theme, size-scaled icons, per-aircraft
   trails, smooth eased prediction, focus highlight. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  const CATEGORY_COLORS = {
    military: "#e74c3c", emergency: "#ff8c00", watchlist: "#f1c40f",
    helicopter: "#2ecc71", normal: "#4aa3ff", rare: "#c071f0",
    ground: "#1abc9c", balloon: "#ecf0f1",
  };
  SW.CATEGORY_COLORS = CATEGORY_COLORS;
  SW.CATEGORY_LABELS = {
    military: "Military", emergency: "Emergency squawk", watchlist: "Watchlist",
    helicopter: "Helicopter", normal: "Commercial / normal", rare: "Rare / interesting",
    ground: "Ground vehicle", balloon: "Balloon",
  };
  const SELECTED_COLOR = "#ffd54a";

  const map = {
    leaflet: null, markers: {}, baseLayers: {}, activeBaseName: null,
    radiusCircle: null, trailLine: null, trailRenderer: null,
    selected: null, config: null,
  };
  SW.map = map;
  SW.showAllTrails = true;

  // ---------------------------------------------------------------- basemaps
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
  function esriCanvas(shade) {
    return L.layerGroup([
      L.tileLayer(`${ESRI}/Canvas/World_${shade}_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
        { maxZoom: 16, attribution: "Tiles &copy; Esri" }),
      L.tileLayer(`${ESRI}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}`,
        { maxZoom: 16 }),
      L.tileLayer(`${ESRI}/Canvas/World_${shade}_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
        { maxZoom: 16 }),
    ]);
  }
  function buildBasemaps() {
    return {
      "Dark · EN labels": esriCanvas("Dark"),
      "Light · EN labels": esriCanvas("Light"),
      "Dark (Carto)": L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        { maxZoom: 19, attribution: "&copy; OSM &copy; CARTO" }),
      "Deutsch (OSM.de)": L.tileLayer("https://tile.openstreetmap.de/{z}/{x}/{y}.png",
        { maxZoom: 18, attribution: "&copy; OpenStreetMap DE" }),
      "Satellite": L.layerGroup([
        L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
          { maxZoom: 18, attribution: "Tiles &copy; Esri" }),
        L.tileLayer(`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`,
          { maxZoom: 18 }),
      ]),
    };
  }
  const STYLE_TO_NAME = {
    "dark-en": "Dark · EN labels", "dark": "Dark (Carto)",
    "german": "Deutsch (OSM.de)", "light": "Light · EN labels",
    "satellite": "Satellite",
  };

  SW.initMap = function (config) {
    map.config = config;
    map.leaflet = L.map("map", { zoomControl: true, attributionControl: true,
      worldCopyJump: true, preferCanvas: true })
      .setView([config.latitude, config.longitude], config.zoom || 9);

    map.baseLayers = buildBasemaps();
    const name = STYLE_TO_NAME[config.map_style] || "Dark · EN labels";
    SW.setBasemap(name);

    map.trailRenderer = L.canvas({ padding: 0.5 });
    map.overlays = { airports: L.layerGroup(), zones: L.layerGroup(), daynight: L.layerGroup() };

    SW.drawRadius(true);
    map.leaflet.on("click", () => SW.selectAircraft(null));
    let zt = null;
    map.leaflet.on("zoomend", () => {
      clearTimeout(zt);
      zt = setTimeout(() => { if (SW.lastList) SW.updateAircraft(SW.lastList); }, 60);
    });
    requestAnimationFrame(animate);
  };

  SW.setBasemap = function (name) {
    if (!map.baseLayers[name]) return;
    if (map.activeBaseName && map.baseLayers[map.activeBaseName])
      map.leaflet.removeLayer(map.baseLayers[map.activeBaseName]);
    map.baseLayers[name].addTo(map.leaflet);
    if (map.baseLayers[name].bringToBack) map.baseLayers[name].bringToBack();
    map.activeBaseName = name;
  };
  SW.setTheme = function (dark) {
    SW.setBasemap(dark ? "Dark · EN labels" : "Light · EN labels");
  };

  SW.drawRadius = function (show) {
    if (map.radiusCircle) { map.leaflet.removeLayer(map.radiusCircle); map.radiusCircle = null; }
    if (show && map.config && map.config.configured) {
      map.radiusCircle = L.circle([map.config.latitude, map.config.longitude], {
        radius: map.config.radius_km * 1000, color: "#4aa3ff", weight: 1,
        fillColor: "#4aa3ff", fillOpacity: 0.05,
      }).addTo(map.leaflet);
    }
  };

  // ---------------------------------------------------------------- icons
  function sizeScale(ac) {
    const c = ac.category || 0;
    if (c >= 6) return 1.5;
    if (c === 5) return 1.35;
    if (c === 4) return 1.15;
    if (c === 3) return 0.92;
    if (c === 2) return 0.72;
    const tc = (ac.typecode || "").toUpperCase();
    if (/^(A38|A35|A34|A33|B74|B77|B78|B76|IL76|A124|A225|MD11|DC10|B75)/.test(tc)) return 1.4;
    if (/^(A19|A20|A21|A22|A32|B73|B71|E19|E17|E29|CRJ|DH8|AT[0-9]|E75|MD8|MD9)/.test(tc)) return 1.0;
    if (/^(C1[0-9][0-9]|C2[0-9][0-9]|PA[0-9]|SR2|DA[0-9]|BE[0-9]|P28|DV20|GA8|R44|R22)/.test(tc)) return 0.68;
    return 1.0;
  }
  function zoomFactor() {
    const z = map.leaflet ? map.leaflet.getZoom() : 9;
    if (z >= 10) return 1.0; if (z >= 8) return 0.82; if (z >= 6) return 0.66;
    if (z >= 4) return 0.52; return 0.42;
  }
  const PRIORITY = { emergency: 95, military: 85, watchlist: 75, rare: 65,
    helicopter: 45, balloon: 30, ground: 12, normal: 25 };
  function priority(ac) {
    if (map.selected === ac.icao24) return 1000;
    return (PRIORITY[ac.marker_category] || 25) + sizeScale(ac);
  }

  function planeSvg(color, heading, stroke) {
    return `<svg viewBox="0 0 24 24" style="transform:rotate(${heading || 0}deg);width:100%;height:100%">
      <path fill="${color}" stroke="${stroke}" stroke-width="0.6"
        d="M12 2 L14 11 L22 15 L22 17 L14 14.5 L13.5 20 L16 21.5 L16 23 L12 22 L8 23 L8 21.5 L10.5 20 L10 14.5 L2 17 L2 15 L10 11 Z"/></svg>`;
  }
  function heliSvg(color, stroke) {
    return `<svg viewBox="0 0 24 24" style="width:100%;height:100%">
      <circle cx="12" cy="12" r="5" fill="${color}" stroke="${stroke}" stroke-width="0.6"/>
      <line x1="3" y1="3" x2="21" y2="21" stroke="${color}" stroke-width="2"/>
      <line x1="21" y1="3" x2="3" y2="21" stroke="${color}" stroke-width="2"/></svg>`;
  }
  function dotSvg(color, stroke) {
    return `<svg viewBox="0 0 16 16" style="width:100%;height:100%">
      <rect x="3" y="3" width="10" height="10" rx="2" fill="${color}" stroke="${stroke}" stroke-width="0.6"/></svg>`;
  }
  function iconSize(ac, selected) {
    let base = ac.marker_category === "helicopter" ? 22
      : (ac.marker_category === "ground" || ac.marker_category === "balloon") ? 16 : 26;
    return Math.max(9, Math.round(base * sizeScale(ac) * zoomFactor() * (selected ? 1.5 : 1)));
  }
  function iconFor(ac, selected) {
    const color = CATEGORY_COLORS[ac.marker_category] || CATEGORY_COLORS.normal;
    const stroke = selected ? "#000" : "#0008";
    let svg;
    if (ac.marker_category === "helicopter") svg = heliSvg(color, stroke);
    else if (ac.marker_category === "ground" || ac.marker_category === "balloon") svg = dotSvg(color, stroke);
    else svg = planeSvg(selected ? SELECTED_COLOR : color, ac.true_track, stroke);
    const size = iconSize(ac, selected);
    const html = `<div class="ac-marker${selected ? " focused" : ""}" style="width:${size}px;height:${size}px">${svg}</div>`;
    return L.divIcon({ className: "", html, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });
  }
  // Cheap signature so we only rebuild the icon DOM when something visual changes.
  function iconKey(ac, selected) {
    return `${ac.marker_category}|${selected ? 1 : 0}|${iconSize(ac, selected)}|${Math.round((ac.true_track || 0) / 6)}`;
  }

  // ---------------------------------------------------------------- update
  function displayCap() {
    const z = map.leaflet.getZoom();
    if (z >= 9) return Infinity; if (z >= 7) return 400; if (z >= 5) return 180; return 90;
  }

  SW.updateAircraft = function (list) {
    const now = Date.now();
    const present = new Set();
    let candidates = list.filter((ac) =>
      ac.latitude != null && ac.longitude != null &&
      SW.isCategoryVisible(ac.marker_category) && SW.matchesSearch(ac) &&
      (!SW.passesAltFilter || SW.passesAltFilter(ac)) &&
      (!SW.passesGroundFilter || SW.passesGroundFilter(ac)));
    list.forEach((ac) => { if (ac.latitude != null) present.add(ac.icao24); });

    const cap = displayCap();
    let showSet = null;
    if (candidates.length > cap)
      showSet = new Set(candidates.slice().sort((a, b) => priority(b) - priority(a))
        .slice(0, cap).map((a) => a.icao24));

    candidates.forEach((ac) => {
      const show = !showSet || showSet.has(ac.icao24);
      let entry = map.markers[ac.icao24];
      if (!show) { if (entry) removeMarker(ac.icao24); return; }

      const selected = map.selected === ac.icao24;
      const key = iconKey(ac, selected);
      if (entry) {
        if (entry.iconKey !== key) { entry.marker.setIcon(iconFor(ac, selected)); entry.iconKey = key; }
        entry.data = ac; entry.lastSeen = now;
      } else {
        const marker = L.marker([ac.latitude, ac.longitude], { icon: iconFor(ac, selected) }).addTo(map.leaflet);
        marker.on("click", (e) => { L.DomEvent.stop(e); SW.selectAircraft(ac.icao24); });
        marker.bindTooltip(() => SW.markerTooltip(map.markers[ac.icao24]?.data || ac),
          { direction: "top", offset: [0, -10] });
        entry = map.markers[ac.icao24] = {
          marker, data: ac, lastSeen: now, iconKey: key,
          dispLat: ac.latitude, dispLon: ac.longitude, trail: [],
        };
      }
      // Re-anchor prediction to the reported position.
      entry.anchorLat = ac.latitude; entry.anchorLon = ac.longitude; entry.anchorTime = now;
      const moving = !ac.on_ground && ac.velocity && ac.true_track != null;
      if (!moving) { entry.dispLat = ac.latitude; entry.dispLon = ac.longitude;
        entry.marker.setLatLng([ac.latitude, ac.longitude]); }
      if (selected) entry.marker.setZIndexOffset(1000);
      updateTrail(entry, ac);
    });

    // Remove markers filtered out (immediate) or long gone (by age).
    const filteredOut = new Set();
    list.forEach((ac) => {
      if (!present.has(ac.icao24)) return;
      const passes = SW.isCategoryVisible(ac.marker_category) && SW.matchesSearch(ac) &&
        (!SW.passesAltFilter || SW.passesAltFilter(ac)) &&
        (!SW.passesGroundFilter || SW.passesGroundFilter(ac));
      if (!passes) filteredOut.add(ac.icao24);
    });
    Object.keys(map.markers).forEach((icao) => {
      const entry = map.markers[icao];
      if (filteredOut.has(icao)) { removeMarker(icao); return; }
      if (present.has(icao)) return;
      const age = now - entry.lastSeen;
      if (age > 5 * 60 * 1000) removeMarker(icao);
      else if (age > 60 * 1000) entry.marker.getElement()?.querySelector(".ac-marker")?.classList.add("stale");
    });

    if (map.selected && map.markers[map.selected]) SW.renderDetail(map.markers[map.selected].data);
  };

  function removeMarker(icao) {
    const e = map.markers[icao];
    if (!e) return;
    map.leaflet.removeLayer(e.marker);
    if (e.trailLine) map.leaflet.removeLayer(e.trailLine);
    delete map.markers[icao];
  }

  // ---------------------------------------------------------------- trails (all)
  function updateTrail(entry, ac) {
    if (!SW.showAllTrails) {
      if (entry.trailLine) { map.leaflet.removeLayer(entry.trailLine); entry.trailLine = null; }
      return;
    }
    const last = entry.trail[entry.trail.length - 1];
    if (!last || last[0] !== ac.latitude || last[1] !== ac.longitude) {
      entry.trail.push([ac.latitude, ac.longitude]);
      if (entry.trail.length > 30) entry.trail.shift();
    }
    if (entry.trail.length > 1) {
      const color = CATEGORY_COLORS[ac.marker_category] || CATEGORY_COLORS.normal;
      if (!entry.trailLine) {
        entry.trailLine = L.polyline(entry.trail, { renderer: map.trailRenderer,
          color, weight: 1.4, opacity: 0.45 }).addTo(map.leaflet);
      } else {
        entry.trailLine.setLatLngs(entry.trail);
        entry.trailLine.setStyle({ color });
      }
    }
  }
  SW.setAllTrails = function (on) {
    SW.showAllTrails = on;
    if (!on) Object.values(map.markers).forEach((e) => {
      if (e.trailLine) { map.leaflet.removeLayer(e.trailLine); e.trailLine = null; }
    });
  };

  // ---------------------------------------------------------------- prediction
  function destPoint(lat, lon, dist, bearing) {
    const R = 6378137, rad = Math.PI / 180, deg = 180 / Math.PI;
    const br = bearing * rad, lat1 = lat * rad, lon1 = lon * rad, dr = dist / R;
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(dr) + Math.cos(lat1) * Math.sin(dr) * Math.cos(br));
    const lon2 = lon1 + Math.atan2(Math.sin(br) * Math.sin(dr) * Math.cos(lat1),
      Math.cos(dr) - Math.sin(lat1) * Math.sin(lat2));
    return [lat2 * deg, lon2 * deg];
  }

  // Continuous, eased dead-reckoning at ~25 fps so motion is smooth (no 1s jumps).
  let lastFrame = 0;
  function animate(ts) {
    requestAnimationFrame(animate);
    if (ts - lastFrame < 40) return;
    lastFrame = ts;
    const now = Date.now();
    const markers = map.markers;
    for (const icao in markers) {
      const e = markers[icao];
      const a = e.data;
      if (!a || a.on_ground || !a.velocity || a.true_track == null || e.anchorLat == null) continue;
      const age = (now - e.anchorTime) / 1000;
      if (age > 120) continue;
      const [tlat, tlon] = destPoint(e.anchorLat, e.anchorLon, a.velocity * age, a.true_track);
      // Ease toward the predicted target → smooth, absorbs re-anchor corrections.
      e.dispLat += (tlat - e.dispLat) * 0.18;
      e.dispLon += (tlon - e.dispLon) * 0.18;
      e.marker.setLatLng([e.dispLat, e.dispLon]);
    }
  }

  SW.markerTooltip = function (ac) {
    const cs = (ac.callsign || ac.icao24).trim();
    return `<span class="ac-label">${cs}${ac.typecode ? " · " + ac.typecode : ""}</span>`;
  };

  // ---------------------------------------------------------------- selection
  SW.selectAircraft = function (icao24) {
    const prev = map.selected;
    map.selected = icao24;
    if (prev && map.markers[prev]) {
      const e = map.markers[prev];
      e.marker.setIcon(iconFor(e.data, false));
      e.iconKey = iconKey(e.data, false);
      e.marker.setZIndexOffset(0);
    }
    document.body.classList.toggle("has-selection", !!icao24);
    if (!icao24) {
      SW.clearTrail(); if (SW.clearRoute) SW.clearRoute();
      document.getElementById("detail-card").classList.add("hidden");
      return;
    }
    const entry = map.markers[icao24];
    if (entry) {
      entry.marker.setIcon(iconFor(entry.data, true));
      entry.iconKey = iconKey(entry.data, true);
      entry.marker.setZIndexOffset(1000);
      SW.renderDetail(entry.data);
      map.leaflet.panTo(entry.marker.getLatLng());
      SW.refreshTrail();
    }
  };
  SW.focusAircraft = function (icao24) {
    const entry = map.markers[icao24];
    if (entry) { map.leaflet.setView(entry.marker.getLatLng(), 11); SW.selectAircraft(icao24); }
  };

  // Fly to a worldwide aircraft that may not be on the current view yet, then
  // select it once the viewport fetch has loaded markers there.
  SW.flyToAircraft = function (icao24, lat, lon) {
    if (map.markers[icao24]) { SW.focusAircraft(icao24); return; }
    if (lat == null || lon == null) return;
    map.leaflet.setView([lat, lon], 8);
    let tries = 0;
    const iv = setInterval(() => {
      if (map.markers[icao24]) { SW.selectAircraft(icao24); clearInterval(iv); }
      if (++tries > 12) clearInterval(iv);
    }, 1000);
  };

  // Full historical trail for the selected aircraft (from the server DB).
  SW.refreshTrail = async function () {
    if (!map.selected) return;
    const tt = document.getElementById("toggle-trails");
    if (tt && !tt.checked) { SW.clearTrail(); return; }
    try {
      const res = await fetch(`/api/track/${map.selected}`, SW.fetchOpts());
      const data = await res.json();
      const pts = (data.track || []).map((p) => [p.latitude, p.longitude]);
      const cur = map.markers[map.selected];
      if (cur) pts.push(cur.marker.getLatLng());
      SW.clearTrail();
      if (pts.length > 1)
        map.trailLine = L.polyline(pts, { color: SELECTED_COLOR, weight: 2.5, opacity: .9 }).addTo(map.leaflet);
    } catch (e) { /* ignore */ }
  };
  SW.clearTrail = function () {
    if (map.trailLine) { map.leaflet.removeLayer(map.trailLine); map.trailLine = null; }
  };
  SW.recolorMarkers = function () {
    Object.values(map.markers).forEach((e) => {
      const sel = map.selected === e.data.icao24;
      e.marker.setIcon(iconFor(e.data, sel)); e.iconKey = iconKey(e.data, sel);
    });
  };
})();
