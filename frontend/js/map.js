/* map.js – Leaflet setup, basemaps, aircraft markers (size-scaled, predicted,
   highlight-on-focus), trails, radius. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  const CATEGORY_COLORS = {
    military: "#e74c3c",
    emergency: "#ff8c00",
    watchlist: "#f1c40f",
    helicopter: "#2ecc71",
    normal: "#4aa3ff",
    rare: "#c071f0",
    ground: "#1abc9c",
    balloon: "#ecf0f1",
  };
  SW.CATEGORY_COLORS = CATEGORY_COLORS;
  SW.CATEGORY_LABELS = {
    military: "Military",
    emergency: "Emergency squawk",
    watchlist: "Watchlist",
    helicopter: "Helicopter",
    normal: "Commercial / normal",
    rare: "Rare / interesting",
    ground: "Ground vehicle",
    balloon: "Balloon",
  };
  const SELECTED_COLOR = "#ffd54a";  // focused aircraft stands out (gold)
  const TRAIL_COLOR = "#ffd54a";

  const map = {
    leaflet: null,
    markers: {},        // icao24 -> { marker, lastSeen, data, anchorLat, ... }
    baseLayers: null,
    radiusCircle: null,
    trailLine: null,
    selected: null,
    config: null,
  };
  SW.map = map;

  // ---------------------------------------------------------------- basemaps
  function buildBasemaps() {
    const esri = "Tiles &copy; Esri";
    const darkEN = L.layerGroup([
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 16, attribution: esri }),
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 16 }),
    ]);
    const satellite = L.layerGroup([
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 18, attribution: esri }),
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 18 }),
    ]);
    return {
      byKey: {
        "dark-en": ["Dark · EN labels", darkEN],
        "dark": ["Dark (Carto)", L.tileLayer(
          "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
          { maxZoom: 19, attribution: "&copy; OSM &copy; CARTO" })],
        "german": ["Deutsch (OSM.de)", L.tileLayer(
          "https://tile.openstreetmap.de/{z}/{x}/{y}.png",
          { maxZoom: 18, attribution: "&copy; OpenStreetMap DE" })],
        "light": ["Light", L.tileLayer(
          "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
          { maxZoom: 19, attribution: "&copy; OSM &copy; CARTO" })],
        "satellite": ["Satellite", satellite],
      },
    };
  }

  SW.initMap = function (config) {
    map.config = config;
    map.leaflet = L.map("map", { zoomControl: true, attributionControl: true,
      worldCopyJump: true })
      .setView([config.latitude, config.longitude], config.zoom || 9);

    const bm = buildBasemaps();
    const styleKey = bm.byKey[config.map_style] ? config.map_style : "dark-en";
    map.baseLayers = {};
    Object.entries(bm.byKey).forEach(([key, [name, layer]]) => {
      map.baseLayers[name] = layer;
      if (key === styleKey) layer.addTo(map.leaflet);
    });

    map.overlays = {
      airports: L.layerGroup(),
      zones: L.layerGroup(),
      daynight: L.layerGroup(),
    };

    SW.drawRadius(true);
    map.leaflet.on("click", () => SW.selectAircraft(null));
    // Re-render on zoom so marker sizes + declutter update.
    let zt = null;
    map.leaflet.on("zoomend", () => {
      clearTimeout(zt);
      zt = setTimeout(() => { if (SW.lastList) SW.updateAircraft(SW.lastList); }, 60);
    });
    SW.startPrediction();
  };

  SW.drawRadius = function (show) {
    if (map.radiusCircle) { map.leaflet.removeLayer(map.radiusCircle); map.radiusCircle = null; }
    if (show && map.config && map.config.configured) {
      map.radiusCircle = L.circle([map.config.latitude, map.config.longitude], {
        radius: map.config.radius_km * 1000,
        color: "#4aa3ff", weight: 1, fillColor: "#4aa3ff", fillOpacity: 0.05,
      }).addTo(map.leaflet);
    }
  };

  // ---------------------------------------------------------------- icons
  // Scale factor by physical aircraft size (OpenSky category, typecode fallback).
  function sizeScale(ac) {
    const c = ac.category || 0;
    if (c >= 6) return 1.5;          // heavy
    if (c === 5) return 1.35;        // high-vortex large
    if (c === 4) return 1.15;        // large
    if (c === 3) return 0.92;        // small
    if (c === 2) return 0.72;        // light
    const tc = (ac.typecode || "").toUpperCase();
    if (/^(A38|A35|A34|A33|B74|B77|B78|B76|IL76|A124|A225|MD11|DC10|B75)/.test(tc)) return 1.4;
    if (/^(A19|A20|A21|A22|A32|B73|B71|E19|E17|E29|CRJ|DH8|AT[0-9]|E75|MD8|MD9)/.test(tc)) return 1.0;
    if (/^(C1[0-9][0-9]|C2[0-9][0-9]|PA[0-9]|SR2|DA[0-9]|BE[0-9]|P28|DV20|GA8|R44|R22)/.test(tc)) return 0.68;
    return 1.0;
  }

  function planeSvg(color, heading, stroke) {
    return `<svg viewBox="0 0 24 24" style="transform:rotate(${heading || 0}deg);width:100%;height:100%">
      <path fill="${color}" stroke="${stroke}" stroke-width="0.6"
        d="M12 2 L14 11 L22 15 L22 17 L14 14.5 L13.5 20 L16 21.5 L16 23 L12 22 L8 23 L8 21.5 L10.5 20 L10 14.5 L2 17 L2 15 L10 11 Z"/>
    </svg>`;
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

  // Markers shrink as you zoom out so key map locations stay visible.
  function zoomFactor() {
    const z = map.leaflet ? map.leaflet.getZoom() : 9;
    if (z >= 10) return 1.0;
    if (z >= 8) return 0.82;
    if (z >= 6) return 0.66;
    if (z >= 4) return 0.52;
    return 0.42;
  }

  // Display priority – interesting traffic survives decluttering at low zoom.
  const PRIORITY = { emergency: 95, military: 85, watchlist: 75, rare: 65,
    helicopter: 45, balloon: 30, ground: 12, normal: 25 };
  function priority(ac) {
    if (map.selected === ac.icao24) return 1000;
    return (PRIORITY[ac.marker_category] || 25) + sizeScale(ac);
  }

  function iconFor(ac, selected) {
    let color = CATEGORY_COLORS[ac.marker_category] || CATEGORY_COLORS.normal;
    const stroke = selected ? "#000" : "#0008";
    let scale = sizeScale(ac);
    let base = 26;
    let svg;
    if (ac.marker_category === "helicopter") { svg = heliSvg(color, stroke); base = 22; }
    else if (ac.marker_category === "ground" || ac.marker_category === "balloon") {
      svg = dotSvg(color, stroke); base = 16;
    } else svg = planeSvg(selected ? SELECTED_COLOR : color, ac.true_track, stroke);

    let size = Math.max(9, Math.round(base * scale * zoomFactor() * (selected ? 1.5 : 1)));
    const cls = "ac-marker" + (selected ? " focused" : "");
    const html = `<div class="${cls}" style="width:${size}px;height:${size}px">${svg}</div>`;
    return L.divIcon({ className: "", html, iconSize: [size, size],
      iconAnchor: [size / 2, size / 2] });
  }

  // ---------------------------------------------------------------- update
  // Max markers to draw at the current zoom (declutter when zoomed out).
  function displayCap() {
    const z = map.leaflet.getZoom();
    if (z >= 9) return Infinity;
    if (z >= 7) return 350;
    if (z >= 5) return 160;
    return 80;
  }

  SW.updateAircraft = function (list) {
    const now = Date.now();
    const present = new Set();          // icao seen in this payload (any filter)

    // Pre-filter, then declutter by priority so key locations stay readable.
    let candidates = list.filter((ac) =>
      ac.latitude != null && ac.longitude != null &&
      SW.isCategoryVisible(ac.marker_category) &&
      SW.matchesSearch(ac) &&
      (!SW.passesAltFilter || SW.passesAltFilter(ac)) &&
      (!SW.passesGroundFilter || SW.passesGroundFilter(ac)));
    list.forEach((ac) => { if (ac.latitude != null) present.add(ac.icao24); });

    const cap = displayCap();
    let showSet = null;
    if (candidates.length > cap) {
      showSet = new Set(
        candidates.slice().sort((a, b) => priority(b) - priority(a))
          .slice(0, cap).map((a) => a.icao24));
    }

    candidates.forEach((ac) => {
      const show = !showSet || showSet.has(ac.icao24);
      let entry = map.markers[ac.icao24];
      if (!show) {
        // Decluttered out → remove its marker if present.
        if (entry) { map.leaflet.removeLayer(entry.marker); delete map.markers[ac.icao24]; }
        return;
      }
      const pos = [ac.latitude, ac.longitude];
      const selected = map.selected === ac.icao24;
      if (entry) {
        entry.marker.setLatLng(pos);
        entry.marker.setIcon(iconFor(ac, selected));
        entry.data = ac;
        entry.lastSeen = now;
        entry.marker.getElement()?.classList.remove("stale");
      } else {
        const marker = L.marker(pos, { icon: iconFor(ac, selected) }).addTo(map.leaflet);
        marker.on("click", (e) => { L.DomEvent.stop(e); SW.selectAircraft(ac.icao24); });
        marker.bindTooltip(() => SW.markerTooltip(map.markers[ac.icao24]?.data || ac),
          { direction: "top", offset: [0, -10] });
        entry = map.markers[ac.icao24] = { marker, data: ac, lastSeen: now };
      }
      // Re-anchor prediction to the real reported position.
      entry.anchorLat = ac.latitude;
      entry.anchorLon = ac.longitude;
      entry.anchorTime = now;
      if (selected) entry.marker.setZIndexOffset(1000);
    });

    // Markers present in the feed but filtered out by category/search → remove
    // immediately (this is the filter fix). Ones no longer in the feed fade by age.
    const filteredOut = new Set();
    list.forEach((ac) => {
      if (!present.has(ac.icao24)) return;
      const passes =
        SW.isCategoryVisible(ac.marker_category) &&
        SW.matchesSearch(ac) &&
        (!SW.passesAltFilter || SW.passesAltFilter(ac)) &&
        (!SW.passesGroundFilter || SW.passesGroundFilter(ac));
      if (!passes) filteredOut.add(ac.icao24);
    });
    Object.keys(map.markers).forEach((icao) => {
      const entry = map.markers[icao];
      if (filteredOut.has(icao)) {
        map.leaflet.removeLayer(entry.marker);
        delete map.markers[icao];
        return;
      }
      if (present.has(icao)) return;  // updated above (or decluttered/removed)
      const age = now - entry.lastSeen;
      if (age > 5 * 60 * 1000) {
        map.leaflet.removeLayer(entry.marker);
        delete map.markers[icao];
      } else if (age > 60 * 1000) {
        entry.marker.getElement()?.querySelector(".ac-marker")?.classList.add("stale");
      }
    });

    if (map.selected && map.markers[map.selected]) {
      SW.renderDetail(map.markers[map.selected].data);
    }
  };

  // ---------------------------------------------------------------- prediction
  function destPoint(lat, lon, dist, bearing) {
    const R = 6378137, rad = Math.PI / 180, deg = 180 / Math.PI;
    const br = bearing * rad, lat1 = lat * rad, lon1 = lon * rad, dr = dist / R;
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(dr) +
      Math.cos(lat1) * Math.sin(dr) * Math.cos(br));
    const lon2 = lon1 + Math.atan2(Math.sin(br) * Math.sin(dr) * Math.cos(lat1),
      Math.cos(dr) - Math.sin(lat1) * Math.sin(lat2));
    return [lat2 * deg, lon2 * deg];
  }

  // Dead-reckoning: glide each marker along its heading between server updates,
  // so movement is smooth and we only "snap" when a real new position arrives.
  SW.startPrediction = function () {
    setInterval(() => {
      const now = Date.now();
      Object.values(map.markers).forEach((e) => {
        const a = e.data;
        if (!a || a.on_ground || !a.velocity || a.true_track == null) return;
        if (e.anchorLat == null) return;
        const dt = (now - e.anchorTime) / 1000;
        if (dt <= 0 || dt > 120) return;  // don't extrapolate stale data forever
        const [plat, plon] = destPoint(e.anchorLat, e.anchorLon, a.velocity * dt, a.true_track);
        e.marker.setLatLng([plat, plon]);
      });
    }, 1000);
  };

  SW.markerTooltip = function (ac) {
    const cs = (ac.callsign || ac.icao24).trim();
    const t = ac.typecode ? ` · ${ac.typecode}` : "";
    return `<span class="ac-label">${cs}${t}</span>`;
  };

  // ---------------------------------------------------------------- selection
  SW.selectAircraft = function (icao24) {
    const prev = map.selected;
    map.selected = icao24;
    if (prev && map.markers[prev]) {
      map.markers[prev].marker.setIcon(iconFor(map.markers[prev].data, false));
      map.markers[prev].marker.setZIndexOffset(0);
    }
    document.body.classList.toggle("has-selection", !!icao24);

    if (!icao24) {
      SW.clearTrail();
      if (SW.clearRoute) SW.clearRoute();
      document.getElementById("detail-card").classList.add("hidden");
      return;
    }
    const entry = map.markers[icao24];
    if (entry) {
      entry.marker.setIcon(iconFor(entry.data, true));
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

  // ---------------------------------------------------------------- trail
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
      if (pts.length > 1) {
        map.trailLine = L.polyline(pts, { color: TRAIL_COLOR, weight: 2.5, opacity: .9 })
          .addTo(map.leaflet);
      }
    } catch (e) { /* ignore */ }
  };

  SW.clearTrail = function () {
    if (map.trailLine) { map.leaflet.removeLayer(map.trailLine); map.trailLine = null; }
  };

  SW.recolorMarkers = function () {
    Object.values(map.markers).forEach((e) =>
      e.marker.setIcon(iconFor(e.data, map.selected === e.data.icao24)));
  };
})();
