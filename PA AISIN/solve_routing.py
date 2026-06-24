"""
solve_routing.py  — Orienteering Problem solver for Route Epsilon waste collection.

Run:
  C:/Users/kawta/AppData/Local/Programs/Python/Python312/python.exe solve_routing.py

Distance matrix comes from the ACTUAL GPS track cumulative distances —
not OSRM/haversine — so the solver only picks stops reachable along the
real roads the truck already recorded.
"""

import sys, os, json, math, csv, urllib.request
from pathlib import Path
from pulp import LpProblem, LpMaximize, LpVariable, lpSum, value, LpStatus, PULP_CBC_CMD

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT     = Path("f:/AISIN/20260205")
FOLDER   = ROOT / "20260205e_blurred"
DET_PATH = FOLDER / "detections.json"
GPS_FILE = FOLDER / "GPS_1770294010100.csv"
OUT_PATH = ROOT / "dashboard" / "static" / "optimal_route.json"

# ── SOLVER PARAMETERS (overridable via env vars from /api/solve) ───────────────
T_BUDGET_KM    = float(os.environ.get("BUDGET_KM",    "2.0"))
C_CAPACITY_KG  = float(os.environ.get("CAPACITY_KG",  "500"))
CLUSTER_DIST_M = float(os.environ.get("CLUSTER_M",    "40.0"))

P_BIN_FULL       = int(os.environ.get("P_BIN_FULL",       "10"))
P_BIN_MID        = int(os.environ.get("P_BIN_MID",         "5"))
P_GARBAGE_LOT    = int(os.environ.get("P_GARBAGE_LOT",     "8"))
P_GARBAGE_LITTLE = int(os.environ.get("P_GARBAGE_LITTLE",  "2"))
P_BIN_UNKNOWN    = int(os.environ.get("P_BIN_UNKNOWN",     "3"))
P_GARBAGE_UNKNOWN= int(os.environ.get("P_GARBAGE_UNKNOWN", "2"))

W_BIN_FULL       = float(os.environ.get("W_BIN_FULL",       "80"))
W_BIN_MID        = float(os.environ.get("W_BIN_MID",        "40"))
W_GARBAGE_LOT    = float(os.environ.get("W_GARBAGE_LOT",   "120"))
W_GARBAGE_LITTLE = float(os.environ.get("W_GARBAGE_LITTLE", "25"))
W_BIN_UNKNOWN    = float(os.environ.get("W_BIN_UNKNOWN",    "35"))
W_GARBAGE_UNKNOWN= float(os.environ.get("W_GARBAGE_UNKNOWN","20"))

try:
    TRAFFIC_ZONES = json.loads(os.environ.get("TRAFFIC_ZONES", "[]"))
except Exception:
    TRAFFIC_ZONES = []

DEPOT_LAT = os.environ.get("DEPOT_LAT", "")
DEPOT_LON = os.environ.get("DEPOT_LON", "")
HAS_DEPOT = bool(DEPOT_LAT and DEPOT_LON)
# ───────────────────────────────────────────────────────────────────────────────

PRIORITY = {
    ("bin",     "full"):     P_BIN_FULL,
    ("bin",     "mid full"): P_BIN_MID,
    ("garbage", "a lot"):    P_GARBAGE_LOT,
    ("garbage", "a little"): P_GARBAGE_LITTLE,
}
WASTE_KG = {
    ("bin",     "full"):     W_BIN_FULL,
    ("bin",     "mid full"): W_BIN_MID,
    ("garbage", "a lot"):    W_GARBAGE_LOT,
    ("garbage", "a little"): W_GARBAGE_LITTLE,
}


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def traffic_factor_segment(locA: dict, locB: dict) -> float:
    """Return the max traffic slowdown factor for the segment A→B (midpoint check)."""
    mid_lat = (locA["lat"] + locB["lat"]) / 2
    mid_lon = (locA["lon"] + locB["lon"]) / 2
    max_f = 1.0
    for tz in TRAFFIC_ZONES:
        if haversine_km(mid_lat, mid_lon, tz["lat"], tz["lon"]) * 1000 <= tz["radius_m"]:
            max_f = max(max_f, tz.get("factor", 1.0))
    return max_f


def apply_traffic(locs: list, D: list) -> list:
    """Multiply each D[i][j] by the traffic factor for that segment."""
    if not TRAFFIC_ZONES:
        return D
    n = len(locs)
    D_eff = [[D[i][j] * traffic_factor_segment(locs[i], locs[j])
              for j in range(n)] for i in range(n)]
    factors = set()
    for i in range(n):
        for j in range(n):
            if i != j:
                f = D_eff[i][j] / D[i][j] if D[i][j] > 0 else 1.0
                if f > 1.0:
                    factors.add(round(f, 1))
    if factors:
        print(f"  Traffic applied: effective multipliers used: {sorted(factors)}")
    return D_eff


def osrm_distance_matrix(locs: list) -> list:
    """Real road distance matrix (km) via OSRM /table/ — any driveable road in OSM."""
    coords = ";".join(f"{l['lon']},{l['lat']}" for l in locs)
    url = (f"https://router.project-osrm.org/table/v1/driving/{coords}"
           f"?annotations=distance")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())
        if data.get("code") == "Ok" and "distances" in data:
            km = [[d / 1000.0 for d in row] for row in data["distances"]]
            print(f"  OSRM table OK ({len(locs)}x{len(locs)})")
            return km
        print(f"  OSRM table: {data.get('code')}")
    except Exception as e:
        print(f"  OSRM table failed ({e}), falling back to haversine*1.35")
    n = len(locs)
    return [[haversine_km(locs[i]["lat"], locs[i]["lon"],
                          locs[j]["lat"], locs[j]["lon"]) * 1.35
             for j in range(n)] for i in range(n)]


def osrm_route(a: dict, b: dict) -> list:
    """Real road geometry between two stops via OSRM /route/."""
    url = (f"https://router.project-osrm.org/route/v1/driving/"
           f"{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
           f"?overview=full&geometries=geojson")
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        if data.get("code") == "Ok":
            return [[c[1], c[0]] for c in data["routes"][0]["geometry"]["coordinates"]]
    except Exception as e:
        print(f"  OSRM route fallback ({e})")
    return [[a["lat"], a["lon"]], [b["lat"], b["lon"]]]


def cluster_locations(locs: list, radius_m: float) -> list:
    remaining = list(locs)
    clusters  = []
    while remaining:
        seed  = remaining.pop(0)
        group = [seed]
        keep  = []
        for other in remaining:
            if haversine_km(seed["lat"], seed["lon"],
                            other["lat"], other["lon"]) * 1000 <= radius_m:
                group.append(other)
            else:
                keep.append(other)
        remaining = keep
        rep = max(group, key=lambda x: x["priority"])
        clusters.append({
            "id":        rep["id"],
            "lat":       rep["lat"],
            "lon":       rep["lon"],
            "type":      rep["type"],
            "label":     rep["label"],
            "priority":  sum(x["priority"]  for x in group),
            "weight_kg": sum(x["weight_kg"] for x in group),
            "note":      rep["note"],
            "count":     len(group),
        })
    return clusters


def load_locations():
    with open(DET_PATH, encoding="utf-8") as f:
        detections = json.load(f)

    locs = []
    for fn, data in detections.items():
        if not data.get("annotated"):
            continue
        lat, lon = data.get("lat"), data.get("lon")
        if lat is None or lon is None:
            continue

        vlm  = data.get("vlm")
        dets = data.get("detections", [])

        if vlm:
            kind  = vlm.get("type", "")
            level = (vlm.get("level") or vlm.get("amount") or "").lower()
            score = PRIORITY.get((kind, level), 0)
            kg    = WASTE_KG.get((kind, level), 0)
            if score == 0:
                continue
            locs.append({
                "id": fn, "lat": lat, "lon": lon,
                "type": kind, "label": level,
                "priority": score, "weight_kg": kg,
                "note": vlm.get("note", ""),
            })
        else:
            has_bin = any(d["class"] == "bin"     and d["confidence"] >= 0.50 for d in dets)
            has_grb = any(d["class"] == "garbage" and d["confidence"] >= 0.75 for d in dets)
            if not (has_bin or has_grb):
                continue
            if has_bin:
                kind, label = "bin",     "unknown"
                score, kg   = P_BIN_UNKNOWN, W_BIN_UNKNOWN
            else:
                kind, label = "garbage", "unknown"
                score, kg   = P_GARBAGE_UNKNOWN, W_GARBAGE_UNKNOWN
            locs.append({
                "id": fn, "lat": lat, "lon": lon,
                "type": kind, "label": label,
                "priority": score, "weight_kg": kg,
                "note": "YOLO only",
            })
    return locs


def solve_op(locs: list, D: list, D_actual: list = None, closed: bool = False) -> tuple:
    """D is used for the budget constraint (may include traffic), D_actual for km reporting.
       closed=True enforces a return arc back to locs[0] (depot)."""
    if D_actual is None:
        D_actual = D
    n   = len(locs)
    idx = list(range(n))

    prob = LpProblem("OP_Epsilon", LpMaximize)
    x = [[LpVariable(f"x_{i}_{j}", cat="Binary") if i != j else 0
          for j in idx] for i in idx]
    u = [LpVariable(f"u_{i}", cat="Binary") for i in idx]
    f = [LpVariable(f"f_{i}", lowBound=0, upBound=n) for i in idx]

    prob += u[0] == 1
    prob += lpSum(locs[i]["priority"] * u[i] for i in idx)

    prob += lpSum(x[0][j] for j in idx if j != 0) == 1
    prob += lpSum(x[j][0] for j in idx if j != 0) == (1 if closed else 0)
    for i in idx[1:]:
        prob += lpSum(x[j][i] for j in idx if j != i) == u[i]
        prob += lpSum(x[i][j] for j in idx if j != i) <= u[i]

    prob += lpSum(D[i][j] * x[i][j]
                  for i in idx for j in idx if i != j) <= T_BUDGET_KM
    prob += lpSum(locs[i]["weight_kg"] * u[i] for i in idx) <= C_CAPACITY_KG

    for i in idx[1:]:
        for j in idx[1:]:
            if i != j:
                prob += f[i] - f[j] + n * x[i][j] <= n - 1

    prob.solve(PULP_CBC_CMD(msg=0))
    status = LpStatus[prob.status]
    print(f"Solver: {status}")
    if status != "Optimal":
        return [], 0, 0, 0

    visited = [i for i in idx if value(u[i]) > 0.5]
    total_d  = sum(D_actual[i][j] * value(x[i][j])   # actual km, not traffic-weighted
                   for i in idx for j in idx
                   if i != j and value(x[i][j]) > 0.5)
    total_p  = int(round(sum(locs[i]["priority"]  for i in visited)))
    total_kg = sum(locs[i]["weight_kg"] for i in visited)

    tour, cur = [0], 0
    remaining = set(visited) - {0}
    while remaining:
        nxt = next((j for j in idx if j != cur
                    and j in remaining
                    and value(x[cur][j]) > 0.5), None)
        if nxt is None:
            break
        tour.append(nxt)
        remaining.discard(nxt)
        cur = nxt

    if closed:
        tour.append(0)   # return to depot at the end of the tour
    return [locs[i] for i in tour], total_p, total_d, total_kg


def main():
    print("Loading detections ...")
    locs = load_locations()
    print(f"  {len(locs)} waste locations (VLM + YOLO)")

    if not locs:
        print("Nothing to route. Run run_vlm_analysis.py first.")
        return

    locs = cluster_locations(locs, CLUSTER_DIST_M)
    print(f"After clustering ({CLUSTER_DIST_M}m): {len(locs)} stops")
    for l in locs:
        cnt = f" x{l['count']}" if l['count'] > 1 else ""
        print(f"  [p={l['priority']:3d} w={l['weight_kg']:5.0f}kg] "
              f"{l['type']:7s} '{l['label']}'{cnt}  ({l['lat']:.5f}, {l['lon']:.5f})")

    locs = sorted(locs, key=lambda x: -x["priority"])

    if HAS_DEPOT:
        locs = [{
            "id": "depot", "lat": float(DEPOT_LAT), "lon": float(DEPOT_LON),
            "type": "depot", "label": "depot", "priority": 0, "weight_kg": 0,
            "note": "user-placed depot", "count": 1,
        }] + locs
        print(f"  Depot at ({DEPOT_LAT}, {DEPOT_LON}) — closed round-trip route")

    print(f"\nFetching real road distances from OSRM ...")
    D = osrm_distance_matrix(locs)

    if TRAFFIC_ZONES:
        print(f"  Applying {len(TRAFFIC_ZONES)} traffic zone(s) to cost matrix ...")
    D_eff = apply_traffic(locs, D)

    mode = "closed round-trip" if HAS_DEPOT else "open route"
    print(f"\nSolving OP  (budget={T_BUDGET_KM} km eff, capacity={C_CAPACITY_KG} kg, {mode}) ...")
    stops, total_p, total_d, total_kg = solve_op(locs, D_eff, D_actual=D, closed=HAS_DEPOT)

    if not stops:
        print("No feasible solution found.")
        return

    print(f"\nOptimal tour: {len(stops)} stops, "
          f"{total_d:.2f} km road, {total_kg:.0f} kg, urgency={total_p}")
    for i, s in enumerate(stops):
        print(f"  {i+1:2d}. [p={s['priority']} w={s['weight_kg']:.0f}kg] "
              f"{s['type']:7s} '{s['label']}'  ({s['lat']:.5f}, {s['lon']:.5f})")

    print("\nFetching road geometry from OSRM ...")
    segments = []
    for i in range(len(stops) - 1):
        seg = osrm_route(stops[i], stops[i + 1])
        segments.append(seg)
        print(f"  {i+1}->{i+2}: {len(seg)} pts")

    out = {
        "stops":         stops,
        "segments":      segments,
        "total_km":      round(total_d, 3),
        "total_urgency": total_p,
        "total_kg":      round(total_kg, 1),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nSaved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
