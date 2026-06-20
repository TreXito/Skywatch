/* layers.js – overlay layers: weather radar (RainViewer, animated), day/night
   terminator, airports (with METAR popups), and conflict/hazard zones. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  const radar = {
    frames: [], host: "", layers: {}, idx: 0, playing: false, timer: null,
    layerGroup: null, control: null, active: false,
  };

  SW.initLayers = async function (config) {
    const lf = SW.map.leaflet;
    const ov = SW.map.overlays;
    const features = config.features || {};
    const overlaysForControl = {};

    // --- Airports ---
    if (features.airports) {
      await SW.loadAirports();
      overlaysForControl["🛬 Airports"] = ov.airports;
    }
    // --- Conflict / hazard zones ---
    if (features.zones) {
      await SW.loadZones();
      overlaysForControl["⚠️ Conflict zones"] = ov.zones;
      ov.zones.addTo(lf); // on by default
    }
    // --- Day / night terminator ---
    if (features.daynight) {
      SW.drawTerminator();
      overlaysForControl["🌓 Day / night"] = ov.daynight;
      setInterval(SW.drawTerminator, 5 * 60 * 1000);
    }
    // --- Weather radar (RainViewer) ---
    if (features.weather) {
      radar.layerGroup = L.layerGroup();
      overlaysForControl["🌧️ Weather radar"] = radar.layerGroup;
      await SW.initRadar();
      lf.on("overlayadd", (e) => { if (e.layer === radar.layerGroup) SW.radarOn(); });
      lf.on("overlayremove", (e) => { if (e.layer === radar.layerGroup) SW.radarOff(); });
      if (SW.satelliteAvailable()) {
        const satGroup = L.layerGroup();
        overlaysForControl["🛰️ Clouds (satellite)"] = satGroup;
        lf.on("overlayadd", (e) => { if (e.layer === satGroup) SW.satelliteOn(); });
        lf.on("overlayremove", (e) => { if (e.layer === satGroup) SW.satelliteOff(); });
      }
    }

    if (Object.keys(overlaysForControl).length) {
      L.control.layers(null, overlaysForControl, { collapsed: true, position: "topleft" })
        .addTo(lf);
    }

    // Refresh airports/zones periodically.
    setInterval(() => { if (features.airports) SW.loadAirports(); }, 10 * 60 * 1000);
    setInterval(() => { if (features.zones) SW.loadZones(); }, 5 * 60 * 1000);
  };

  // ---------------------------------------------------------------- Airports
  SW.loadAirports = async function () {
    try {
      const res = await fetch("/api/airports", SW.fetchOpts());
      const data = await res.json();
      const group = SW.map.overlays.airports;
      group.clearLayers();
      (data.airports || []).forEach((ap) => {
        const big = ap.type === "large_airport";
        const m = L.circleMarker([ap.latitude, ap.longitude], {
          radius: big ? 6 : 4, color: "#1abc9c", weight: 1,
          fillColor: "#1abc9c", fillOpacity: 0.6,
        });
        m.bindPopup(() => SW.airportPopup(ap, m));
        group.addLayer(m);
      });
    } catch (e) { /* ignore */ }
  };

  SW.airportPopup = function (ap, marker) {
    const id = ap.icao || ap.ident;
    const div = L.DomUtil.create("div");
    div.innerHTML = `<b>${ap.name}</b><br>
      <span class="muted">${id}${ap.iata ? " / " + ap.iata : ""} ·
      ${ap.distance_km} km · ${ap.iso_country || ""}</span>
      <div class="metar-box muted">Loading weather…</div>`;
    // Lazy-load METAR.
    fetch(`/api/weather/metar/${id}`, SW.fetchOpts())
      .then((r) => r.json()).then((d) => {
        const box = div.querySelector(".metar-box");
        const m = d.metar;
        if (!m) { box.textContent = "No METAR available."; return; }
        box.classList.remove("muted");
        box.innerHTML = `🌡️ ${m.temp_c ?? "—"}°C &nbsp; 💨 ${m.wind_dir ?? "—"}°/${m.wind_kt ?? "—"}kt
          ${m.flight_category ? ` &nbsp; <b>${m.flight_category}</b>` : ""}
          <br><code style="font-size:.72rem">${m.raw || ""}</code>`;
        marker.getPopup().update();
      }).catch(() => {});
    return div;
  };

  // ---------------------------------------------------------------- Zones
  const ZONE_COLORS = { high: "#e74c3c", medium: "#e67e22", low: "#f1c40f", static: "#9b59b6" };

  SW.loadZones = async function () {
    try {
      const res = await fetch("/api/zones", SW.fetchOpts());
      const data = await res.json();
      const group = SW.map.overlays.zones;
      group.clearLayers();
      (data.zones || []).forEach((z) => {
        const color = z.static ? ZONE_COLORS.static : (ZONE_COLORS[z.severity] || ZONE_COLORS.low);
        const circle = L.circle([z.lat, z.lon], {
          radius: z.radius_km * 1000, color, weight: 1.5,
          fillColor: color, fillOpacity: 0.12, dashArray: z.static ? null : "6 4",
        });
        circle.bindPopup(SW.zonePopup(z));
        group.addLayer(circle);
      });
      SW.zoneCount = (data.zones || []).length;
    } catch (e) { /* ignore */ }
  };

  SW.zonePopup = function (z) {
    const heads = (z.headlines || []).map((h) =>
      `<li><a href="${h.link}" target="_blank">${h.title}</a>
       <span class="muted">${h.source ? "– " + h.source : ""}</span></li>`).join("");
    return `<div class="zone-popup">
      <b>${z.static ? "📍" : "⚠️"} ${z.name}</b>
      <div class="muted">${z.static ? (z.note || "User zone")
        : `${z.mentions} recent mention(s) · severity: ${z.severity}`}</div>
      ${heads ? `<ul class="zone-news">${heads}</ul>` : ""}</div>`;
  };

  // ---------------------------------------------------------------- Weather radar
  SW.initRadar = async function () {
    try {
      const res = await fetch("https://api.rainviewer.com/public/weather-maps.json");
      const data = await res.json();
      radar.host = data.host;
      const past = (data.radar && data.radar.past) || [];
      const now = (data.radar && data.radar.nowcast) || [];
      radar.pastCount = past.length;
      radar.frames = past.concat(now); // live history + forecast (nowcast)
      radar.idx = Math.max(0, past.length - 1); // start at "now"
      radar.satFrames = (data.satellite && data.satellite.infrared) || [];
      SW.buildRadarControl();
    } catch (e) { /* ignore */ }
  };

  // Satellite (infrared cloud) layer – latest frame, static toggle.
  let satLayer = null;
  SW.satelliteAvailable = function () { return radar.satFrames && radar.satFrames.length; };
  SW.satelliteOn = function () {
    const f = radar.satFrames[radar.satFrames.length - 1];
    if (!f) return;
    satLayer = L.tileLayer(`${radar.host}${f.path}/256/{z}/{x}/{y}/0/0_0.png`,
      { opacity: 0.5, zIndex: 4, maxZoom: 19 }).addTo(SW.map.leaflet);
  };
  SW.satelliteOff = function () {
    if (satLayer) { SW.map.leaflet.removeLayer(satLayer); satLayer = null; }
  };

  function tileLayerForFrame(f) {
    if (radar.layers[f.path]) return radar.layers[f.path];
    const url = `${radar.host}${f.path}/256/{z}/{x}/{y}/4/1_1.png`;
    const layer = L.tileLayer(url, { opacity: 0, zIndex: 5, maxZoom: 19 });
    radar.layers[f.path] = layer;
    return layer;
  }

  SW.radarOn = function () {
    radar.active = true;
    if (!radar.frames.length) return;
    radar.frames.forEach((f) => tileLayerForFrame(f).addTo(SW.map.leaflet));
    SW.showRadarFrame(radar.idx);
    if (radar.control) radar.control.style.display = "flex";
    SW.playRadar();
  };

  SW.radarOff = function () {
    radar.active = false;
    SW.pauseRadar();
    Object.values(radar.layers).forEach((l) => SW.map.leaflet.removeLayer(l));
    if (radar.control) radar.control.style.display = "none";
  };

  SW.showRadarFrame = function (i) {
    if (!radar.frames.length) return;
    radar.idx = (i + radar.frames.length) % radar.frames.length;
    radar.frames.forEach((f, j) =>
      tileLayerForFrame(f).setOpacity(j === radar.idx ? 0.7 : 0));
    const f = radar.frames[radar.idx];
    const label = document.getElementById("radar-time");
    const tag = document.getElementById("radar-tag");
    if (label) {
      label.textContent = new Date(f.time * 1000)
        .toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    if (tag) {
      const isForecast = radar.idx >= radar.pastCount;
      const mins = Math.round((f.time * 1000 - Date.now()) / 60000);
      tag.textContent = isForecast ? `forecast +${Math.max(0, mins)}m`
        : (radar.idx === radar.pastCount - 1 ? "live" : `${mins}m`);
      tag.className = isForecast ? "radar-tag forecast" : "radar-tag live";
    }
    const slider = document.getElementById("radar-slider");
    if (slider) slider.value = radar.idx;
  };

  SW.playRadar = function () {
    radar.playing = true;
    document.getElementById("radar-play") && (document.getElementById("radar-play").textContent = "⏸");
    clearInterval(radar.timer);
    radar.timer = setInterval(() => SW.showRadarFrame(radar.idx + 1), 700);
  };
  SW.pauseRadar = function () {
    radar.playing = false;
    clearInterval(radar.timer);
    const b = document.getElementById("radar-play"); if (b) b.textContent = "▶";
  };

  SW.buildRadarControl = function () {
    const ctrl = document.createElement("div");
    ctrl.id = "radar-control";
    ctrl.style.display = "none";
    ctrl.innerHTML = `
      <button id="radar-play" class="icon-btn" title="Play/pause">▶</button>
      <input id="radar-slider" type="range" min="0" max="${Math.max(0, radar.frames.length - 1)}" value="${radar.idx}" />
      <span id="radar-time" class="muted">—</span>
      <span id="radar-tag" class="radar-tag live">live</span>`;
    document.body.appendChild(ctrl);
    radar.control = ctrl;
    ctrl.querySelector("#radar-play").addEventListener("click", () =>
      radar.playing ? SW.pauseRadar() : SW.playRadar());
    ctrl.querySelector("#radar-slider").addEventListener("input", (e) => {
      SW.pauseRadar(); SW.showRadarFrame(parseInt(e.target.value, 10));
    });
  };

  // ---------------------------------------------------------------- Day/night
  // Compact solar terminator (adapted from the MIT-licensed Leaflet.Terminator).
  SW.drawTerminator = function () {
    const group = SW.map.overlays.daynight;
    group.clearLayers();
    const rad = Math.PI / 180, deg = 180 / Math.PI;
    const now = new Date();
    const jd = now / 86400000 + 2440587.5;
    const n = jd - 2451545.0;
    const meanLon = (280.460 + 0.9856474 * n) % 360;
    const g = (357.528 + 0.9856003 * n) % 360;
    const lambda = meanLon + 1.915 * Math.sin(g * rad) + 0.020 * Math.sin(2 * g * rad);
    const obliq = 23.439 - 0.0000004 * n;
    let alpha = Math.atan(Math.cos(obliq * rad) * Math.tan(lambda * rad)) * deg;
    const delta = Math.asin(Math.sin(obliq * rad) * Math.sin(lambda * rad)) * deg;
    const lQuad = Math.floor(lambda / 90) * 90, aQuad = Math.floor(alpha / 90) * 90;
    alpha += lQuad - aQuad;
    const gst = (18.697374558 + 24.06570982441908 * n) % 24;

    const pts = [];
    for (let lng = -180; lng <= 180; lng += 2) {
      const lst = gst + lng / 15;
      const ha = lst * 15 - alpha;
      let lat = Math.atan(-Math.cos(ha * rad) / Math.tan(delta * rad)) * deg;
      pts.push([lat, lng]);
    }
    // Close the polygon over the night-side pole.
    const pole = delta < 0 ? 90 : -90;
    pts.unshift([pole, -180]);
    pts.push([pole, 180]);
    group.addLayer(L_polygon(pts));
  };

  function L_polygon(pts) {
    return L.polygon(pts, {
      stroke: false, color: "#000", fillColor: "#0b1622", fillOpacity: 0.28,
      interactive: false,
    });
  }
})();
