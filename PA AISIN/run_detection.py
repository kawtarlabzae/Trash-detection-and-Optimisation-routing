"""
Run YOLO inference (best.pt) on all 5 route folders.

Key design points:
  - Image filenames and GPS timestamps are on DIFFERENT clocks (~345 days apart).
    The script auto-detects this offset and applies it before matching.
  - Each image is matched against the MERGED GPS pool from ALL folders.
  - Only frames >= MIN_DIST_M apart are processed (spatial sampling).
  - Model labels are swapped (bin→garbage, garbage→bin) and corrected here.

Output: detections.json in each folder, compatible with the dashboard.

Adjust MIN_DIST_M:  5 m = dense,  10 m = recommended,  30 m = fast pass.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from math import radians, sin, cos, sqrt, atan2
from ultralytics import YOLO

BASE_DIR       = Path("f:/AISIN/20260205")
MODEL_PATH     = BASE_DIR / "best.pt"
MIN_DIST_M     = 10.0
MAX_GPS_GAP_MS     = 1_000   # tolerance after offset correction
OLD_CLOCK_THRESHOLD = 1_760_000_000_000  # images below this are on the old clock (~1740...)

FOLDERS = [
    "20260205a_blurred",
    "20260205b_blurred",
    "20260205c_blurred",
    "20260205d_blurred",
    "20260205e_blurred",
]

GPS_CSV = {
    "20260205a_blurred": "GPS_1770276300096.csv",
    "20260205b_blurred": "GPS_1770279422095.csv",
    "20260205c_blurred": "GPS_1770283224395.csv",
    "20260205d_blurred": "GPS_1770288210103.csv",
    "20260205e_blurred": "GPS_1770294010100.csv",
}

LABEL_FIX = {
    "bin":     "garbage",
    "bins":    "garbage",
    "garbage": "bin",
}


def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    f1, f2 = radians(lat1), radians(lat2)
    df = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a  = sin(df / 2) ** 2 + cos(f1) * cos(f2) * sin(dl / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def load_gps(gps_path: Path) -> pd.DataFrame:
    gdf = pd.read_csv(gps_path).sort_values("unixtime_ms").reset_index(drop=True)
    lats = gdf["lat"].to_numpy()
    lons = gdf["lon"].to_numpy()
    cum  = [0.0]
    for i in range(1, len(lats)):
        cum.append(cum[-1] + haversine(lats[i-1], lons[i-1], lats[i], lons[i]))
    gdf["cum_dist_m"] = cum
    return gdf


def detect_offset(img_timestamps: np.ndarray, gps_timestamps: np.ndarray,
                  sample: int = 300) -> int:
    """Return median(gps_ts - img_ts) to ADD to image timestamps before GPS matching."""
    if len(img_timestamps) == 0 or len(gps_timestamps) == 0:
        return 0
    step = max(1, len(img_timestamps) // sample)
    diffs = []
    for img_ts in img_timestamps[::step]:
        idx = int(np.searchsorted(gps_timestamps, img_ts))
        if idx >= len(gps_timestamps):
            idx = len(gps_timestamps) - 1
        elif idx > 0 and abs(gps_timestamps[idx-1] - img_ts) < abs(gps_timestamps[idx] - img_ts):
            idx -= 1
        diffs.append(int(gps_timestamps[idx]) - int(img_ts))
    diffs.sort()
    return diffs[len(diffs) // 2]


def nearest_gps(ts: int, m_ts: np.ndarray):
    """Binary search for nearest GPS point. Returns (idx, diff_ms)."""
    idx = int(np.searchsorted(m_ts, ts))
    if idx >= len(m_ts):
        idx = len(m_ts) - 1
    elif idx > 0 and abs(int(m_ts[idx-1]) - ts) < abs(int(m_ts[idx]) - ts):
        idx -= 1
    return idx, abs(int(m_ts[idx]) - ts)


def sample_by_gps(folder: Path,
                  m_ts:         np.ndarray,
                  m_lat:        np.ndarray,
                  m_lon:        np.ndarray,
                  m_cum:        np.ndarray,
                  large_offset: int) -> list[dict]:
    """
    For each image try direct match AND match with large_offset.
    Use whichever gives the closer GPS point (within MAX_GPS_GAP_MS).
    Keep only frames >= MIN_DIST_M apart.
    """
    images   = sorted(folder.glob("*.jpg"), key=lambda p: int(p.stem))
    selected = []
    last_lat = last_lon = None

    for img in images:
        ts = int(img.stem)

        idx1, diff1 = nearest_gps(ts, m_ts)
        idx2, diff2 = nearest_gps(ts + large_offset, m_ts)

        if diff1 <= diff2:
            best_idx, best_diff = idx1, diff1
        else:
            best_idx, best_diff = idx2, diff2

        if best_diff > MAX_GPS_GAP_MS:
            continue

        lat = float(m_lat[best_idx])
        lon = float(m_lon[best_idx])

        if last_lat is None or haversine(last_lat, last_lon, lat, lon) >= MIN_DIST_M:
            selected.append({
                "path":        img,
                "lat":         round(lat, 6),
                "lon":         round(lon, 6),
                "cum_dist_km": round(float(m_cum[best_idx]) / 1000, 3),
            })
            last_lat, last_lon = lat, lon

    return selected


def fix_label(raw: str) -> str:
    return LABEL_FIX.get(raw.lower(), raw)


def main():
    # ── Load and merge all GPS files ─────────────────────────────────────────
    print("Loading GPS files …")
    chunks = []
    for folder_name, csv_name in GPS_CSV.items():
        gps_path = BASE_DIR / folder_name / csv_name
        if not gps_path.exists():
            print(f"  WARNING: {gps_path} not found — skipping.")
            continue
        gdf = load_gps(gps_path)
        chunks.append(gdf[["unixtime_ms", "lat", "lon", "cum_dist_m"]])
        print(f"  {folder_name}: {len(gdf)} GPS points.")

    if not chunks:
        print("No GPS files found. Exiting.")
        return

    merged = pd.concat(chunks).sort_values("unixtime_ms").reset_index(drop=True)
    m_ts   = merged["unixtime_ms"].to_numpy(dtype=np.int64)
    m_lat  = merged["lat"].to_numpy()
    m_lon  = merged["lon"].to_numpy()
    m_cum  = merged["cum_dist_m"].to_numpy()
    print(f"Merged GPS: {len(merged)} points  (range {m_ts[0]}…{m_ts[-1]})\n")

    # ── Detect large offset for old-clock (~1740...) images ──────────────────
    print("Detecting clock offset for old-clock images …")
    old_img_ts = []
    for folder_name in FOLDERS:
        folder = BASE_DIR / folder_name
        if folder.exists():
            for img in folder.glob("*.jpg"):
                ts = int(img.stem)
                if ts < OLD_CLOCK_THRESHOLD:
                    old_img_ts.append(ts)

    if old_img_ts:
        old_img_ts_np = np.array(sorted(old_img_ts), dtype=np.int64)
        large_offset  = detect_offset(old_img_ts_np, m_ts)
        print(f"Old-clock offset: {large_offset:,} ms  ({large_offset/86_400_000:.2f} days)\n")
    else:
        large_offset = 0
        print("No old-clock images found — using offset 0\n")

    # ── Load model ────────────────────────────────────────────────────────────
    print(f"Loading model: {MODEL_PATH}")
    model = YOLO(str(MODEL_PATH))

    # ── Run inference per folder ──────────────────────────────────────────────
    for folder_name in FOLDERS:
        folder = BASE_DIR / folder_name
        print(f"\n── {folder_name} ──")

        sampled = sample_by_gps(folder, m_ts, m_lat, m_lon, m_cum, large_offset)
        print(f"   {len(sampled)} frames selected  (min spacing {MIN_DIST_M} m)")

        if not sampled:
            print("   No frames matched GPS — skipping.")
            continue

        out = {}
        for i, rec in enumerate(sampled):
            if i % 100 == 0:
                print(f"   [{i}/{len(sampled)}]  {rec['path'].name}")

            results = model(str(rec["path"]), verbose=False)

            dets = []
            for r in results:
                for box in r.boxes:
                    raw_cls = r.names[int(box.cls)]
                    dets.append({
                        "class":      fix_label(raw_cls),
                        "confidence": round(float(box.conf), 4),
                        "bbox":       [round(v, 1) for v in box.xyxy[0].tolist()],
                    })

            out[rec["path"].name] = {
                "lat":         rec["lat"],
                "lon":         rec["lon"],
                "cum_dist_km": rec["cum_dist_km"],
                "detections":  dets,
            }

        save_path = folder / "detections.json"
        with open(save_path, "w") as f:
            json.dump(out, f, separators=(",", ":"))

        n_with = sum(1 for v in out.values() if v["detections"])
        print(f"   Saved → {save_path}")
        print(f"   {len(out)} frames,  {n_with} with detections")

    print("\nDone.")


if __name__ == "__main__":
    main()
