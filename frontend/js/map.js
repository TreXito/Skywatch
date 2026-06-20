/* map.js – Leaflet setup, aircraft markers (updated in place), trails, radius. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  const CATEGORY_COLORS = {
    military: "#e74c3c",
    emergency: "#ff8c00",
    watchlist: "#f1c40f",
    helicopter: "#2ecc71",
    normal: "#3498db",
    rare: "#9b59b6",
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

  const map = {
    leaflet: null,
    markers: {},        // icao24 -> { marker, lastSeen, data }
    tileLayer: null,
    radiusCircle: null,
    trailLine: null,
    selected: null,
    config: null,
  };
  SW.map = map;

  SW.initMap = function (config) {
    map.config = config;
    map.leaflet = L.map("map", { zoomControl: true, attributionControl: true })
      .setView([config.latitude, config.longitude], config.zoom || 9);

    map.tileLayer = L.tileLayer(config.tile_url, {
      attribution: config.tile_attribution,
      maxZoom: 19,
    }).addTo(map.leaflet);

    SW.drawRadius(true);

    map.leaflet.on("click", () => SW.selectAircraft(null));
  };

  SW.setTiles = function (url) {
    if (map.tileLayer) map.leaflet.removeLayer(map.tileLayer);
    map.tileLayer = L.tileLayer(url, {
      attribution: map.config.tile_attribution, maxZoom: 19,
    }).addTo(map.leaflet);
  };

  SW.drawRadius = function (show) {
    if (map.radiusCircle) { map.leaflet.removeLayer(map.radiusCircle); map.radiusCircle = null; }
    if (show && map.config) {
      map.radiusCircle = L.circle([map.config.latitude, map.config.longitude], {
        radius: map.config.radius_km * 1000,
        color: "#3498db", weight: 1, fillColor: "#3498db", fillOpacity: 0.05,
      }).addTo(map.leaflet);
    }
  };

  function planeSvg(color, heading) {
    const rot = heading || 0;
    return `<svg class="ac-marker" width="26" height="26" viewBox="0 0 24 24"
      style="transform:rotate(${rot}deg)">
      <path fill="${color}" stroke="#0008" stroke-width="0.5"
        d="M12 2 L14 11 L22 15 L22 17 L14 14.5 L13.5 20 L16 21.5 L16 23 L12 22 L8 23 L8 21.5 L10.5 20 L10 14.5 L2 17 L2 15 L10 11 Z"/>
    </svg>`;
  }

  function heliSvg(color) {
    return `<svg class="ac-marker" width="22" height="22" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="5" fill="${color}" stroke="#0008" stroke-width="0.5"/>
      <line x1="3" y1="3" x2="21" y2="21" stroke="${color}" stroke-width="2"/>
      <line x1="21" y1="3" x2="3" y2="21" stroke="${color}" stroke-width="2"/>
    </svg>`;
  }

  function dotSvg(color) {
    return `<svg class="ac-marker" width="16" height="16" viewBox="0 0 16 16">
      <rect x="3" y="3" width="10" height="10" rx="2" fill="${color}" stroke="#0008" stroke-width="0.5"/>
    </svg>`;
  }

  function iconFor(ac) {
    const color = CATEGORY_COLORS[ac.marker_category] || CATEGORY_COLORS.normal;
    let html;
    if (ac.marker_category === "helicopter") html = heliSvg(color);
    else if (ac.marker_category === "ground" || ac.marker_category === "balloon")
      html = dotSvg(color);
    else html = planeSvg(color, ac.true_track);
    return L.divIcon({ className: "", html, iconSize: [26, 26], iconAnchor: [13, 13] });
  }

  // Update markers in place to avoid flicker. `visibleSet` controls filtering.
  SW.updateAircraft = function (list) {
    const now = Date.now();
    const seen = new Set();

    list.forEach((ac) => {
      if (ac.latitude == null || ac.longitude == null) return;
      if (!SW.isCategoryVisible(ac.marker_category)) return;
      if (!SW.matchesSearch(ac)) return;
      seen.add(ac.icao24);
      const pos = [ac.latitude, ac.longitude];
      let entry = map.markers[ac.icao24];
      if (entry) {
        entry.marker.setLatLng(pos);
        entry.marker.setIcon(iconFor(ac));
        entry.data = ac;
        entry.lastSeen = now;
        entry.marker.getElement()?.classList.remove("stale");
      } else {
        const marker = L.marker(pos, { icon: iconFor(ac) }).addTo(map.leaflet);
        marker.on("click", (e) => { L.DomEvent.stop(e); SW.selectAircraft(ac.icao24); });
        marker.bindTooltip(() => SW.markerTooltip(map.markers[ac.icao24]?.data || ac),
          { direction: "top", offset: [0, -10] });
        map.markers[ac.icao24] = { marker, data: ac, lastSeen: now };
      }
    });

    // Fade / remove stale markers.
    Object.keys(map.markers).forEach((icao) => {
      const entry = map.markers[icao];
      const age = now - entry.lastSeen;
      if (!seen.has(icao)) {
        if (age > 5 * 60 * 1000) {
          map.leaflet.removeLayer(entry.marker);
          delete map.markers[icao];
        } else if (age > 60 * 1000) {
          entry.marker.getElement()?.classList.add("stale");
        }
      }
    });

    if (map.selected && map.markers[map.selected]) {
      SW.renderDetail(map.markers[map.selected].data);
      SW.refreshTrail();
    }
  };

  SW.markerTooltip = function (ac) {
    const cs = (ac.callsign || ac.icao24).trim();
    const t = ac.typecode ? ` · ${ac.typecode}` : "";
    return `<span class="ac-label">${cs}${t}</span>`;
  };

  SW.selectAircraft = function (icao24) {
    map.selected = icao24;
    if (!icao24) {
      SW.clearTrail();
      document.getElementById("detail-card").classList.add("hidden");
      return;
    }
    const entry = map.markers[icao24];
    if (entry) {
      SW.renderDetail(entry.data);
      map.leaflet.panTo(entry.marker.getLatLng());
      SW.refreshTrail();
    }
  };

  SW.focusAircraft = function (icao24) {
    const entry = map.markers[icao24];
    if (entry) { map.leaflet.setView(entry.marker.getLatLng(), 11); SW.selectAircraft(icao24); }
  };

  // --- Trails ---
  SW.refreshTrail = async function () {
    if (!map.selected) return;
    if (!document.getElementById("toggle-trails").checked) { SW.clearTrail(); return; }
    try {
      const res = await fetch(`/api/track/${map.selected}`, SW.fetchOpts());
      const data = await res.json();
      const pts = (data.track || []).map((p) => [p.latitude, p.longitude]);
      const cur = map.markers[map.selected];
      if (cur) pts.push(cur.marker.getLatLng());
      SW.clearTrail();
      if (pts.length > 1) {
        map.trailLine = L.polyline(pts, { color: "#3498db", weight: 2, opacity: .8 })
          .addTo(map.leaflet);
      }
    } catch (e) { /* ignore */ }
  };

  SW.clearTrail = function () {
    if (map.trailLine) { map.leaflet.removeLayer(map.trailLine); map.trailLine = null; }
  };

  SW.recolorMarkers = function () {
    Object.values(map.markers).forEach((e) => e.marker.setIcon(iconFor(e.data)));
  };
})();
