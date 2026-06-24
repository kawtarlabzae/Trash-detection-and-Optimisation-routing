import json, threading, sys, os, subprocess
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
from pathlib import Path
from math import radians, sin, cos, sqrt, atan2
import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, send_file, abort, request

app = Flask(__name__)

ROOT = Path("f:/AISIN/20260205")

ROUTES = {
    "a": {"name": "Route Alpha",   "color": "#00d4aa", "folder": "20260205a_blurred", "gps": "GPS_1770276300096.csv"},
    "b": {"name": "Route Beta",    "color": "#a78bfa", "folder": "20260205b_blurred", "gps": "GPS_1770279422095.csv"},
    "c": {"name": "Route Gamma",   "color": "#fbbf24", "folder": "20260205c_blurred", "gps": "GPS_1770283224395.csv"},
    "d": {"name": "Route Delta",   "color": "#f472b6", "folder": "20260205d_blurred", "gps": "GPS_1770288210103.csv"},
    "e": {"name": "Route Epsilon", "color": "#38bdf8", "folder": "20260205e_blurred", "gps": "GPS_1770294010100.csv"},
}

# Only images starting with 177... (correct clock, Feb 2026)
MIN_IMG_TS    = 1_770_000_000_000
MAX_GPS_GAP   = 1_000   # ms
SAMPLE_DIST_M = 10.0    # min metres between consecutive image markers

DASHBOARD_DATA = {}
DATA_READY = threading.Event()


def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    f1, f2 = radians(lat1), radians(lat2)
    df, dl = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(df / 2) ** 2 + cos(f1) * cos(f2) * sin(dl / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def load_gps(gps_path: Path) -> pd.DataFrame:
    gdf = pd.read_csv(gps_path).sort_values("unixtime_ms").reset_index(drop=True)
    gdf["spd_kmh"] = gdf["spd"]
    return gdf


def match_images(folder: Path, m_ts, m_lat, m_lon, m_spd) -> list[dict]:
    """
    Match every 177... image in this folder to the MERGED GPS pool.
    Each camera records at different times of the day - the matching GPS
    point may come from a different folder's GPS file.
    """
    images = sorted(
        (img for img in folder.glob("*.jpg") if int(img.stem) >= MIN_IMG_TS),
        key=lambda p: int(p.stem),
    )
    pts = []
    for img in images:
        ts  = int(img.stem)
        idx = int(np.searchsorted(m_ts, ts))
        if idx >= len(m_ts):
            idx = len(m_ts) - 1
        elif idx > 0 and abs(int(m_ts[idx-1]) - ts) < abs(int(m_ts[idx]) - ts):
            idx -= 1

        if abs(int(m_ts[idx]) - ts) > MAX_GPS_GAP:
            continue

        pts.append({
            "filename": img.name,
            "ts":       ts,
            "lat":      float(m_lat[idx]),
            "lon":      float(m_lon[idx]),
            "spd_kmh":  float(m_spd[idx]),
        })
    return pts


def add_cum_dist(pts: list[dict]) -> None:
    cum = 0.0
    for i, p in enumerate(pts):
        if i > 0:
            cum += haversine(pts[i-1]["lat"], pts[i-1]["lon"], p["lat"], p["lon"])
        p["cum_dist_m"] = cum


def sample_markers(pts: list[dict], min_m: float) -> list[dict]:
    kept = []
    last_lat = last_lon = None
    for p in pts:
        if last_lat is None or haversine(last_lat, last_lon, p["lat"], p["lon"]) >= min_m:
            kept.append(p)
            last_lat, last_lon = p["lat"], p["lon"]
    return kept


def precompute():
    # -- Build merged GPS pool from ALL folders -----------------------------------
    print("[Dashboard] Loading all GPS files into merged pool ...")
    chunks = []
    for key, meta in ROUTES.items():
        gps_path = ROOT / meta["folder"] / meta["gps"]
        if not gps_path.exists():
            print(f"[Dashboard]  MISS Route {key}: GPS file not found")
            continue
        gdf = load_gps(gps_path)
        chunks.append(gdf[["unixtime_ms", "lat", "lon", "spd_kmh"]])
        print(f"[Dashboard]  OK Route {key}: {len(gdf)} pts  "
              f"ts {gdf['unixtime_ms'].iloc[0]} ... {gdf['unixtime_ms'].iloc[-1]}")

    if not chunks:
        DATA_READY.set()
        return

    merged = pd.concat(chunks).sort_values("unixtime_ms").reset_index(drop=True)
    m_ts   = merged["unixtime_ms"].to_numpy(dtype=np.int64)
    m_lat  = merged["lat"].to_numpy()
    m_lon  = merged["lon"].to_numpy()
    m_spd  = merged["spd_kmh"].to_numpy()
    print(f"[Dashboard] Merged GPS: {len(merged)} pts  "
          f"ts {m_ts[0]} ... {m_ts[-1]}\n")

    # -- Match each folder's images against the FULL merged pool -----------------
    for key, meta in ROUTES.items():
        folder = ROOT / meta["folder"]
        if not folder.exists():
            continue

        all_pts = match_images(folder, m_ts, m_lat, m_lon, m_spd)

        if not all_pts:
            print(f"[Dashboard] Route {key}: no 177... images matched any GPS - skipped.")
            imgs_177 = [int(i.stem) for i in folder.glob("*.jpg") if int(i.stem) >= MIN_IMG_TS]
            print(f"            (images span {min(imgs_177, default=0)} ... {max(imgs_177, default=0)}, "
                  f"GPS pool {m_ts[0]} ... {m_ts[-1]})")
            continue

        # Sample first (removes GPS noise from stationary periods),
        # then compute cumulative distance on the clean deduplicated points.
        route_imgs = sample_markers(all_pts, SAMPLE_DIST_M)
        add_cum_dist(route_imgs)

        # Detections
        det_path   = folder / "detections.json"
        detections = {}
        if det_path.exists():
            with open(det_path) as f:
                detections = json.load(f)

        for img in route_imgs:
            img["folder"]      = meta["folder"]
            img["lat"]         = round(img["lat"], 6)
            img["lon"]         = round(img["lon"], 6)
            img["spd_kmh"]    = round(img["spd_kmh"], 1)
            img["cum_dist_km"] = round(img["cum_dist_m"] / 1000, 3)
            if img["filename"] in detections:
                det_data = detections[img["filename"]]
                img["detections"] = det_data
                if det_data.get("annotated"):
                    if (folder / "annotated" / img["filename"]).exists():
                        img["annotated"] = True

        # Route polyline from spatially sampled points (no zigzag from stationary noise)
        step  = max(1, len(route_imgs) // 3000)
        route = [
            [round(p["lat"], 6), round(p["lon"], 6), round(p["spd_kmh"], 1)]
            for p in route_imgs[::step]
        ]

        # Speed chart (max 600 pts)
        cs    = max(1, len(route_imgs) // 600)
        chart = {
            "dist": [round(p["cum_dist_m"] / 1000, 3) for p in route_imgs[::cs]],
            "spd":  [round(p["spd_kmh"], 1)           for p in route_imgs[::cs]],
        }

        dist_km    = route_imgs[-1]["cum_dist_m"] / 1000
        duration_s = (route_imgs[-1]["ts"] - route_imgs[0]["ts"]) / 1000
        speeds     = [p["spd_kmh"] for p in route_imgs]
        lats       = [p["lat"] for p in route_imgs]
        lons       = [p["lon"] for p in route_imgs]

        DASHBOARD_DATA[key] = {
            "name":   meta["name"],
            "color":  meta["color"],
            "route":  route,
            "chart":  chart,
            "images": route_imgs,
            "stats": {
                "distance_km":   round(dist_km, 2),
                "duration_min":  round(duration_s / 60, 1),
                "avg_speed_kmh": round(float(np.mean(speeds)), 1),
                "max_speed_kmh": round(float(np.max(speeds)), 1),
                "gps_points":    len(all_pts),
                "image_count":   len(route_imgs),
                "start": [round(lats[0],  5), round(lons[0],  5)],
                "end":   [round(lats[-1], 5), round(lons[-1], 5)],
            },
        }
        print(f"[Dashboard] Route {key}: {dist_km:.2f} km  "
              f"{len(all_pts)} matched -> {len(route_imgs)} markers")

    DATA_READY.set()
    print("\n[Dashboard] All routes ready.")


threading.Thread(target=precompute, daemon=True).start()


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/epsilon")
def epsilon():
    return render_template("epsilon.html")

@app.route("/api/ready")
def api_ready():
    return jsonify({"ready": DATA_READY.is_set()})

@app.route("/api/data")
def api_data():
    DATA_READY.wait()
    return jsonify(DASHBOARD_DATA)

@app.route("/api/optimal_route")
def api_optimal_route():
    p = ROOT / "dashboard" / "static" / "optimal_route.json"
    if p.exists():
        return send_file(str(p), mimetype="application/json")
    return jsonify({"stops": [], "segments": [], "total_km": 0, "total_urgency": 0})


PYTHON_EXE = "C:/Users/kawta/AppData/Local/Programs/Python/Python312/python.exe"
SOLVER_SCRIPT = str(ROOT / "solve_routing.py")

@app.route("/api/solve", methods=["POST"])
def api_solve():
    """Run the routing solver with custom parameters, return the optimal route."""
    p = request.get_json() or {}
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # Pass every recognised parameter from the JSON body as an env var
    mapping = {
        "budget_km":        "BUDGET_KM",
        "cluster_m":        "CLUSTER_M",
        "capacity_kg":      "CAPACITY_KG",
        "p_bin_full":       "P_BIN_FULL",
        "p_bin_mid":        "P_BIN_MID",
        "p_garbage_lot":    "P_GARBAGE_LOT",
        "p_garbage_little": "P_GARBAGE_LITTLE",
        "w_bin_full":       "W_BIN_FULL",
        "w_bin_mid":        "W_BIN_MID",
        "w_garbage_lot":    "W_GARBAGE_LOT",
        "w_garbage_little": "W_GARBAGE_LITTLE",
    }
    for key, envvar in mapping.items():
        if key in p:
            env[envvar] = str(p[key])
    if "traffic_zones" in p:
        env["TRAFFIC_ZONES"] = json.dumps(p["traffic_zones"])
    if "depot_lat" in p:
        env["DEPOT_LAT"] = str(p["depot_lat"])
    if "depot_lon" in p:
        env["DEPOT_LON"] = str(p["depot_lon"])

    try:
        proc = subprocess.run(
            [PYTHON_EXE, SOLVER_SCRIPT],
            env=env, capture_output=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
        print("[Solver]", proc.stdout[-800:] if proc.stdout else "")
        if proc.returncode != 0:
            return jsonify({"error": "solver failed", "detail": proc.stderr[-400:]}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "solver timed out (> 120 s)"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    p = ROOT / "dashboard" / "static" / "optimal_route.json"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "output file not found"}), 500

@app.route("/image/<path:rel_path>")
def serve_image(rel_path):
    full = ROOT / rel_path
    if full.exists():
        return send_file(str(full))
    abort(404)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
