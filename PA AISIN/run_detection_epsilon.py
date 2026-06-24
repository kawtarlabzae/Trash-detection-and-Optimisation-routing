"""
YOLO detection on Route Epsilon (20260205e_blurred) only.

- Uses merged GPS pool from all 5 folders for timestamp matching.
- Spatially samples images >= MIN_DIST_M apart (no redundant near-duplicates).
- Fixes swapped labels: model says "bin" → we save "garbage", and vice-versa.
- Saves annotated images (bounding boxes drawn) to annotated/ subfolder.
- Writes detections.json compatible with the dashboard.
"""

import json
import cv2
import numpy as np
import pandas as pd
from pathlib import Path
from math import radians, sin, cos, sqrt, atan2
from ultralytics import YOLO

BASE_DIR       = Path("f:/AISIN/20260205")
MODEL_PATH     = BASE_DIR / "best.pt"
FOLDER         = "20260205e_blurred"
MIN_DIST_M     = 10.0
MAX_GPS_GAP_MS = 1_000
MIN_IMG_TS     = 1_770_000_000_000   # only 177... images (correct clock)

GPS_CSV = {
    "20260205a_blurred": "GPS_1770276300096.csv",
    "20260205b_blurred": "GPS_1770279422095.csv",
    "20260205c_blurred": "GPS_1770283224395.csv",
    "20260205d_blurred": "GPS_1770288210103.csv",
    "20260205e_blurred": "GPS_1770294010100.csv",
}

LABEL_FIX = {
    "bins": "bin",   # normalise plural → singular
}


def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    f1, f2 = radians(lat1), radians(lat2)
    a = sin(radians(lat2-lat1)/2)**2 + cos(f1)*cos(f2)*sin(radians(lon2-lon1)/2)**2
    return 2*R*atan2(sqrt(a), sqrt(1-a))


def fix_label(raw: str) -> str:
    return LABEL_FIX.get(raw.lower(), raw)


def main():
    # ── Merged GPS pool ───────────────────────────────────────────────────────
    print("Loading GPS files …")
    chunks = []
    for fname, csv in GPS_CSV.items():
        path = BASE_DIR / fname / csv
        if not path.exists():
            print(f"  WARNING: {path} not found — skipping.")
            continue
        gdf = pd.read_csv(path).sort_values("unixtime_ms").reset_index(drop=True)
        chunks.append(gdf[["unixtime_ms", "lat", "lon"]])
        print(f"  {fname}: {len(gdf)} pts  ({gdf['unixtime_ms'].iloc[0]} … {gdf['unixtime_ms'].iloc[-1]})")

    merged = pd.concat(chunks).sort_values("unixtime_ms").reset_index(drop=True)
    m_ts  = merged["unixtime_ms"].to_numpy(dtype=np.int64)
    m_lat = merged["lat"].to_numpy()
    m_lon = merged["lon"].to_numpy()
    print(f"Merged: {len(merged)} pts\n")

    # ── Spatial sampling of Route Epsilon images ──────────────────────────────
    folder = BASE_DIR / FOLDER
    images = sorted(
        [img for img in folder.glob("*.jpg") if int(img.stem) >= MIN_IMG_TS],
        key=lambda p: int(p.stem),
    )
    print(f"Route Epsilon: {len(images)} images with 177… timestamps")

    selected = []
    last_lat = last_lon = None
    for img in images:
        ts  = int(img.stem)
        idx = int(np.searchsorted(m_ts, ts))
        if idx >= len(m_ts):
            idx = len(m_ts) - 1
        elif idx > 0 and abs(int(m_ts[idx-1])-ts) < abs(int(m_ts[idx])-ts):
            idx -= 1

        if abs(int(m_ts[idx])-ts) > MAX_GPS_GAP_MS:
            continue

        lat = float(m_lat[idx])
        lon = float(m_lon[idx])
        if last_lat is None or haversine(last_lat, last_lon, lat, lon) >= MIN_DIST_M:
            selected.append({"path": img, "lat": round(lat, 6), "lon": round(lon, 6)})
            last_lat, last_lon = lat, lon

    print(f"Spatially sampled: {len(selected)} frames (≥{MIN_DIST_M} m apart)\n")
    if not selected:
        print("No frames matched GPS — exiting.")
        return

    # ── Load model ────────────────────────────────────────────────────────────
    print(f"Loading model: {MODEL_PATH}")
    model = YOLO(str(MODEL_PATH))

    # ── Output directory for annotated images ─────────────────────────────────
    annotated_dir = folder / "annotated"
    annotated_dir.mkdir(exist_ok=True)

    # ── Inference ─────────────────────────────────────────────────────────────
    out = {}
    n_det = 0
    for i, rec in enumerate(selected):
        if i % 50 == 0:
            print(f"  [{i}/{len(selected)}]  {rec['path'].name}")

        results = model(str(rec["path"]), verbose=False)

        dets = []
        for r in results:
            for box in r.boxes:
                dets.append({
                    "class":      fix_label(r.names[int(box.cls)]),
                    "confidence": round(float(box.conf), 4),
                    "bbox":       [round(v, 1) for v in box.xyxy[0].tolist()],
                })
            # Save annotated image only when detections exist
            if r.boxes and len(r.boxes) > 0:
                cv2.imwrite(
                    str(annotated_dir / rec["path"].name),
                    r.plot(),   # BGR numpy array with boxes drawn
                )

        has_det = len(dets) > 0
        if has_det:
            n_det += 1

        out[rec["path"].name] = {
            "lat":        rec["lat"],
            "lon":        rec["lon"],
            "detections": dets,
            "annotated":  has_det,
        }

    # ── Save ──────────────────────────────────────────────────────────────────
    save_path = folder / "detections.json"
    with open(save_path, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"\nDone.")
    print(f"  {len(out)} frames processed,  {n_det} with detections.")
    print(f"  detections.json → {save_path}")
    print(f"  annotated images → {annotated_dir}")


if __name__ == "__main__":
    main()
