/* websocket.js – live update channel with auto-reconnect + REST fallback. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  let ws = null;
  let reconnectDelay = 1000;
  let fallbackTimer = null;

  // Optional bearer token (token auth mode): read from cookie if present.
  function token() {
    const m = document.cookie.match(/skywatch_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  SW.fetchOpts = function () {
    const t = token();
    return t ? { headers: { Authorization: "Bearer " + t } } : {};
  };

  SW.connectWS = function () {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const t = token();
    const url = `${proto}://${location.host}/ws${t ? "?token=" + encodeURIComponent(t) : ""}`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      reconnectDelay = 1000;
      SW.setConnection(true);
      if (fallbackTimer) { clearInterval(fallbackTimer); fallbackTimer = null; }
    };
    ws.onmessage = (ev) => {
      try { SW.handlePayload(JSON.parse(ev.data)); } catch (e) { /* ignore */ }
    };
    ws.onclose = () => {
      SW.setConnection(false);
      startFallback();
      setTimeout(SW.connectWS, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.6, 15000);
    };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  };

  // If WS is down, poll the REST endpoint so the map still updates.
  function startFallback() {
    if (fallbackTimer) return;
    fallbackTimer = setInterval(async () => {
      try {
        const res = await fetch("/api/aircraft", SW.fetchOpts());
        const data = await res.json();
        SW.handlePayload({ type: "update", aircraft: data.aircraft,
          status: data.status, new_alerts: [] });
      } catch (e) { /* ignore */ }
    }, 8000);
  }

  SW.handlePayload = function (payload) {
    if (payload.type !== "update") return;
    SW.lastList = payload.aircraft || [];
    SW.updateAircraft(SW.lastList);
    SW.updateStatus(payload.status, SW.lastList.length);
    if (payload.new_alerts && payload.new_alerts.length) SW.onNewAlerts(payload.new_alerts);
  };
})();
