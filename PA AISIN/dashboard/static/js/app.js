/* ────────────────────────────────────────────────────────────────
   Urban Route Intelligence Dashboard  ·  app.js
──────────────────────────────────────────────────────────────── */

"use strict";

let map, dashData = {}, chart = null;
let routeLayers = {}, markerLayers = {};   // key → array of Leaflet layers
let activeSession = "all";
let showPhotos = true;

/* ── MAP INIT ──────────────────────────────────────────────── */
function initMap() {
  map = L.map("map", {
    center: [33.576, -7.608],
    zoom: 14,
    zoomControl: false,
    renderer: L.canvas({ padding: 0.5 }),
  });

  L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    { attribution: "© OpenStreetMap · © CartoDB", subdomains: "abcd", maxZoom: 21 }
  ).addTo(map);

  L.control.zoom({ position: "topright" }).addTo(map);
}

/* ── COLOR HELPERS ─────────────────────────────────────────── */
function speedColor(kmh) {
  if (kmh < 5)  return "#00d4aa";
  if (kmh < 15) return "#4ade80";
  if (kmh < 30) return "#facc15";
  if (kmh < 50) return "#f97316";
  return "#ef4444";
}

/* ── TIMESTAMP FORMATTER ───────────────────────────────────── */
function fmtTs(ms) {
  return new Date(ms).toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

/* ── DRAW ROUTE ────────────────────────────────────────────── */
function drawRoute(key, data) {
  const pts = data.route;
  if (!pts.length) return;

  removeLayers(routeLayers, key);
  routeLayers[key] = [];

  // Speed-colored segments
  for (let i = 1; i < pts.length; i++) {
    const [lat1, lon1, spd1] = pts[i - 1];
    const [lat2, lon2, spd2] = pts[i];
    const line = L.polyline(
      [[lat1, lon1], [lat2, lon2]],
      { color: speedColor((spd1 + spd2) / 2), weight: 4, opacity: 0.82 }
    ).addTo(map);
    routeLayers[key].push(line);
  }

}

function makeDot(lat, lon, color, tip) {
  return L.marker([lat, lon], {
    icon: L.divIcon({
      html: `<div style="width:11px;height:11px;background:${color};border:2px solid #fff;border-radius:50%;box-shadow:0 0 10px ${color}88"></div>`,
      iconSize: [11, 11], iconAnchor: [5.5, 5.5], className: "",
    }),
  }).bindTooltip(tip, { className: "", direction: "top" });
}

/* ── DRAW IMAGE MARKERS ────────────────────────────────────── */
function drawMarkers(key, data) {
  removeLayers(markerLayers, key);
  markerLayers[key] = [];

  if (!showPhotos || !data.images.length) return;

  const colorMap = { a: "#00d4aa", b: "#a78bfa", c: "#fbbf24", d: "#f472b6", e: "#38bdf8" };
  const mColor = colorMap[key] || data.color;
  const borderStyle = `border-color:${mColor};box-shadow:0 0 0 3px ${mColor}22`;

  data.images.forEach((img) => {
    const hasDet = img.detections && img.detections.detections && img.detections.detections.length > 0;
    const classes = hasDet ? img.detections.detections.map(d => d.class) : [];
    const hasBin     = classes.includes("bin");
    const hasGarbage = classes.includes("garbage");

    let icon;
    if (hasBin) {
      icon = L.divIcon({
        html: `<div class="bin-marker" title="Bin detected">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="5" y="8" width="14" height="13" rx="2" fill="#00b896" stroke="#fff" stroke-width="1.2"/>
            <path d="M3 8h18M10 8V5h4v3" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>
            <line x1="10" y1="11" x2="10" y2="18" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="14" y1="11" x2="14" y2="18" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/>
          </svg>
        </div>`,
        iconSize: [28, 28], iconAnchor: [14, 14], className: "",
      });
    } else {
      let emoji = "📷";
      let style = borderStyle;
      if (hasGarbage) {
        emoji = "🗑️";
        style = `border-color:#f59e0b;box-shadow:0 0 0 3px #f59e0b44`;
      }
      icon = L.divIcon({
        html: `<div class="img-marker" style="${style}" title="${img.spd_kmh} km/h">${emoji}</div>`,
        iconSize: [30, 30], iconAnchor: [15, 15], className: "",
      });
    }

    const m = L.marker([img.lat, img.lon], { icon })
      .on("click", () => showDetail(img, data));
    m.addTo(map);
    markerLayers[key].push(m);
  });
}

/* ── DETAIL PANEL ──────────────────────────────────────────── */
function showDetail(img, data) {
  const panel = document.getElementById("detail-panel");
  panel.classList.remove("hidden");

  // Image — use annotated version (with boxes) when available
  const imgEl = document.getElementById("dp-img");
  imgEl.style.opacity = "0";
  imgEl.src = img.annotated
    ? `/image/${img.folder}/annotated/${img.filename}`
    : `/image/${img.folder}/${img.filename}`;
  imgEl.onload = () => { imgEl.style.opacity = "1"; };

  // Badge
  const badge = document.getElementById("dp-route-badge");
  badge.textContent = data.name;
  badge.style.cssText = `background:${data.color}28;color:${data.color};border:1px solid ${data.color}55;`;

  // Meta
  document.getElementById("dp-lat").textContent  = img.lat.toFixed(6);
  document.getElementById("dp-lon").textContent  = img.lon.toFixed(6);
  document.getElementById("dp-spd").textContent  = `${img.spd_kmh} km/h`;
  document.getElementById("dp-dist").textContent = img.cum_dist_km != null
    ? `${img.cum_dist_km.toFixed(2)} km` : "—";
  document.getElementById("dp-ts").textContent   = fmtTs(img.ts);

  // Detections / description
  const detSec  = document.getElementById("dp-det-section");
  const descSec = document.getElementById("dp-desc-section");
  const noDet   = document.getElementById("dp-no-det");
  const detList = document.getElementById("dp-det-list");

  if (img.detections) {
    noDet.classList.add("hidden");
    const dets = img.detections.detections || [];
    if (dets.length) {
      detSec.classList.remove("hidden");
      detList.innerHTML = dets.map((d) => `
        <div class="det-item">
          <span class="det-class ${d.class.toLowerCase()}">${d.class}</span>
          <span class="det-conf">${(d.confidence * 100).toFixed(1)}%</span>
        </div>`).join("");
    } else {
      detSec.classList.add("hidden");
    }
    if (img.detections.description) {
      descSec.classList.remove("hidden");
      document.getElementById("dp-desc-text").textContent = img.detections.description;
    } else {
      descSec.classList.add("hidden");
    }
  } else {
    detSec.classList.add("hidden");
    descSec.classList.add("hidden");
    noDet.classList.remove("hidden");
  }

  // Fly map to marker
  map.panTo([img.lat, img.lon], { animate: true, duration: 0.5 });
}

/* ── SESSION CARDS ─────────────────────────────────────────── */
function buildCards(data) {
  const c = document.getElementById("session-cards");
  c.innerHTML = "";

  Object.entries(data).forEach(([key, sess]) => {
    const s = sess.stats;
    const card = document.createElement("div");
    card.className = "s-card";
    card.style.setProperty("--c-color", sess.color);
    card.innerHTML = `
      <div class="s-card-head">
        <div class="s-card-name">
          <span class="s-card-dot" style="background:${sess.color}"></span>
          ${sess.name}
        </div>
        <span class="s-card-imgs">${s.image_count} imgs</span>
      </div>
      <div class="s-stats-grid">
        <div class="s-stat">
          <span class="s-stat-val" style="color:${sess.color}">${s.distance_km}</span>
          <span class="s-stat-lbl">km</span>
        </div>
        <div class="s-stat">
          <span class="s-stat-val">${s.duration_min}′</span>
          <span class="s-stat-lbl">duration</span>
        </div>
        <div class="s-stat">
          <span class="s-stat-val">${s.avg_speed_kmh}</span>
          <span class="s-stat-lbl">avg km/h</span>
        </div>
        <div class="s-stat">
          <span class="s-stat-val">${s.max_speed_kmh}</span>
          <span class="s-stat-lbl">max km/h</span>
        </div>
      </div>`;

    card.addEventListener("click", () => {
      setSession(key);
      const pts = sess.route.map((p) => [p[0], p[1]]);
      if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.08));
    });
    c.appendChild(card);
  });
}

/* ── HEADER STATS ──────────────────────────────────────────── */
function updateHeaderStats(data) {
  let dist = 0, imgs = 0, mins = 0;
  Object.values(data).forEach((s) => {
    dist += s.stats.distance_km;
    imgs += s.stats.image_count;
    mins += s.stats.duration_min;
  });
  document.getElementById("total-dist").textContent   = dist.toFixed(1);
  document.getElementById("total-images").textContent = imgs;
  document.getElementById("total-time").textContent   = Math.round(mins);
}

/* ── SESSION SWITCHING ─────────────────────────────────────── */
function setSession(session) {
  activeSession = session;

  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.session === session)
  );
  document.querySelectorAll(".s-card").forEach((card, i) => {
    const k = Object.keys(dashData)[i];
    card.classList.toggle("active", session === "all" || session === k);
  });

  Object.keys(dashData).forEach((k) => {
    const show = session === "all" || session === k;
    toggleLayerSet(routeLayers[k], show);
    toggleLayerSet(markerLayers[k], show);
  });

  updateChart(session);
}

/* ── SPEED CHART ───────────────────────────────────────────── */
function updateChart(session) {
  const keys = session === "all" ? Object.keys(dashData) : [session];

  const datasets = keys
    .filter((k) => dashData[k])
    .map((k) => {
      const d = dashData[k];
      return {
        label: d.name,
        data: d.chart.dist.map((x, i) => ({ x, y: d.chart.spd[i] })),
        borderColor: d.color,
        backgroundColor: d.color + "18",
        fill: true, borderWidth: 2, pointRadius: 0, tension: 0.35,
      };
    });

  const sub = document.getElementById("chart-subtitle");
  sub.textContent = session === "all" ? "— All Routes" : `— ${dashData[session]?.name || ""}`;

  if (chart) {
    chart.data.datasets = datasets;
    chart.update("none");
    return;
  }

  chart = new Chart(document.getElementById("speed-chart"), {
    type: "line",
    data: { datasets },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          type: "linear",
          title: { display: true, text: "Distance (km)", color: "#64748b", font: { size: 10 } },
          grid: { color: "rgba(0,0,0,.07)" },
          ticks: { color: "#64748b", font: { size: 10 }, maxTicksLimit: 10 },
        },
        y: {
          title: { display: true, text: "Speed (km/h)", color: "#64748b", font: { size: 10 } },
          grid: { color: "rgba(0,0,0,.07)" },
          ticks: { color: "#64748b", font: { size: 10 } },
          min: 0,
        },
      },
      plugins: {
        legend: { labels: { color: "#475569", boxWidth: 10, font: { size: 11 } } },
        tooltip: { callbacks: { label: (c) => ` ${c.parsed.y.toFixed(1)} km/h` } },
      },
    },
  });
}

/* ── LAYER HELPERS ─────────────────────────────────────────── */
function removeLayers(store, key) {
  (store[key] || []).forEach((l) => map.removeLayer(l));
  store[key] = [];
}

function toggleLayerSet(layers, show) {
  (layers || []).forEach((l) => {
    if (show) { if (!map.hasLayer(l)) map.addLayer(l); }
    else       { if (map.hasLayer(l))  map.removeLayer(l); }
  });
}

/* ── LOAD DATA (retry until ready) ────────────────────────── */
function loadData() {
  fetch("/api/data")
    .then((r) => r.json())
    .then((data) => {
      dashData = data;

      const allPts = [];
      Object.entries(data).forEach(([key, sess]) => {
        drawRoute(key, sess);
        sess.route.forEach((p) => allPts.push([p[0], p[1]]));
      });

      buildCards(data);
      updateHeaderStats(data);
      updateChart("all");

      if (allPts.length) map.fitBounds(L.latLngBounds(allPts).pad(0.06));

      document.getElementById("chart-panel").classList.remove("hidden");
      document.getElementById("btn-chart").classList.add("active");
    })
    .catch(() => setTimeout(loadData, 3000));
}

/* ── BOOTSTRAP ─────────────────────────────────────────────── */
function init() {
  initMap();

  document.getElementById("sidebar-toggle").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("collapsed");
  });

  document.getElementById("close-detail").addEventListener("click", () => {
    document.getElementById("detail-panel").classList.add("hidden");
  });

  document.getElementById("close-chart").addEventListener("click", () => {
    document.getElementById("chart-panel").classList.add("hidden");
    document.getElementById("btn-chart").classList.remove("active");
  });

  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => setSession(t.dataset.session))
  );

  document.getElementById("btn-fit").addEventListener("click", () => {
    const all = [];
    Object.values(dashData).forEach((d) => d.route.forEach((p) => all.push([p[0], p[1]])));
    if (all.length) map.fitBounds(L.latLngBounds(all).pad(0.05));
  });

  document.getElementById("btn-chart").addEventListener("click", (e) => {
    const p = document.getElementById("chart-panel");
    p.classList.toggle("hidden");
    e.currentTarget.classList.toggle("active", !p.classList.contains("hidden"));
  });

  loadData();
}

document.addEventListener("DOMContentLoaded", init);

/* ── keep Leaflet map pixel-accurate on any resize ── */
window.addEventListener("resize", () => {
  if (map) map.invalidateSize();
  if (chart) chart.resize();
});
