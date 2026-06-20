/* tools.js – map tools: find-me, measure, fullscreen, sound alerts, altitude
   filter, CSV export. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  const sound = { enabled: false, ctx: null };
  SW.altFilter = { min: 0, max: 100000, enabled: false };

  SW.initTools = function () {
    const lf = SW.map.leaflet;

    // Find me (geolocation).
    document.getElementById("btn-locate")?.addEventListener("click", () => {
      if (!navigator.geolocation) return;
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const ll = [pos.coords.latitude, pos.coords.longitude];
          L.circleMarker(ll, { radius: 7, color: "#fff", fillColor: "#3498db",
            fillOpacity: 1 }).addTo(lf).bindPopup("You are here").openPopup();
          lf.setView(ll, 11);
        },
        () => alert("Could not get your location."));
    });

    // Fullscreen.
    document.getElementById("btn-fullscreen")?.addEventListener("click", () => {
      if (!document.fullscreenElement) document.documentElement.requestFullscreen?.();
      else document.exitFullscreen?.();
    });

    // Sound toggle.
    document.getElementById("btn-sound")?.addEventListener("click", (e) => {
      sound.enabled = !sound.enabled;
      e.currentTarget.classList.toggle("active", sound.enabled);
      e.currentTarget.textContent = sound.enabled ? "🔊" : "🔇";
      if (sound.enabled && !sound.ctx) {
        sound.ctx = new (window.AudioContext || window.webkitAudioContext)();
      }
    });

    // Measure tool.
    SW.initMeasure();

    // Altitude filter slider.
    const slider = document.getElementById("alt-slider");
    if (slider) {
      slider.addEventListener("input", (e) => {
        SW.altFilter.max = parseInt(e.target.value, 10);
        SW.altFilter.enabled = SW.altFilter.max < 100000;
        document.getElementById("alt-value").textContent =
          SW.altFilter.enabled ? `≤ ${SW.altFilter.max.toLocaleString()} m` : "all";
        SW.rerender();
      });
    }

    // CSV export.
    document.getElementById("export-history")?.addEventListener("click", () =>
      SW.download("/api/export/history.csv"));
    document.getElementById("export-alerts")?.addEventListener("click", () =>
      SW.download("/api/export/alerts.csv"));
  };

  SW.passesAltFilter = function (ac) {
    if (!SW.altFilter.enabled) return true;
    const alt = ac.baro_altitude ?? ac.geo_altitude;
    if (alt == null) return true;
    return alt <= SW.altFilter.max;
  };

  SW.playAlertSound = function () {
    if (!sound.enabled || !sound.ctx) return;
    const o = sound.ctx.createOscillator(), g = sound.ctx.createGain();
    o.connect(g); g.connect(sound.ctx.destination);
    o.type = "sine"; o.frequency.value = 880;
    g.gain.setValueAtTime(0.001, sound.ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.3, sound.ctx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.001, sound.ctx.currentTime + 0.5);
    o.start(); o.stop(sound.ctx.currentTime + 0.5);
  };

  SW.download = function (url) {
    const a = document.createElement("a");
    a.href = url; a.download = "";
    document.body.appendChild(a); a.click(); a.remove();
  };

  // --- simple two-click distance measure ---
  SW.initMeasure = function () {
    let active = false, p1 = null, line = null, marker = null;
    const btn = document.getElementById("btn-measure");
    if (!btn) return;
    btn.addEventListener("click", () => {
      active = !active;
      btn.classList.toggle("active", active);
      SW.map.leaflet.getContainer().style.cursor = active ? "crosshair" : "";
      if (!active) cleanup();
    });
    SW.map.leaflet.on("click", (e) => {
      if (!active) return;
      if (!p1) {
        p1 = e.latlng;
        marker = L.circleMarker(p1, { radius: 5, color: "#f1c40f" }).addTo(SW.map.leaflet);
      } else {
        const km = SW.map.leaflet.distance(p1, e.latlng) / 1000;
        if (line) SW.map.leaflet.removeLayer(line);
        line = L.polyline([p1, e.latlng], { color: "#f1c40f", dashArray: "5 5" })
          .addTo(SW.map.leaflet)
          .bindTooltip(`${km.toFixed(1)} km`, { permanent: true }).openTooltip();
        p1 = null;
      }
    });
    function cleanup() {
      [line, marker].forEach((l) => l && SW.map.leaflet.removeLayer(l));
      line = marker = p1 = null;
    }
  };
})();
