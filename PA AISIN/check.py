"""
GPS Coverage Checker v2
========================
Handles:
  - Multiple GPS CSV files per folder
  - Cross-folder search (pool ALL GPS from ALL subfolders)
  - Auto-detects the clock offset between images and GPS
  - Applies offset so matching actually works

Usage:
    # Basic: pool all GPS, auto-detect offset
    python check_gps_coverage_v2.py --root "F:/AISIN/20260205"

    # Save full report
    python check_gps_coverage_v2.py --root "F:/AISIN/20260205" --out report.csv

    # Skip auto-detect, apply a known fixed offset manually (in ms)
    python check_gps_coverage_v2.py --root "F:/AISIN/20260205" --offset 29827433834

    # Adjust tolerance (default 500ms)
    python check_gps_coverage_v2.py --root "F:/AISIN/20260205" --tol 500
"""

import os
import re
import csv
import bisect
import argparse
from pathlib import Path
from collections import defaultdict

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".jp", ".bmp", ".webp"}


# ─── helpers ──────────────────────────────────────────────────────────────────

def find_gps_files(folder: Path) -> list:
    """Return ALL csv files in a folder that look like GPS data."""
    all_csv = list(folder.glob("*.csv"))
    gps = [f for f in all_csv if re.search(r'GPS|gps|6AX', f.name)]
    return gps if gps else all_csv  # fallback: any csv


def load_gps_timestamps(csv_path: Path) -> list:
    """Read unixtime_ms column, return sorted list of ints."""
    timestamps = []
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            ts_key = None
            for row in reader:
                if ts_key is None:
                    ts_key = next((k for k in row if "unixtime" in k.lower()), None)
                    if ts_key is None:
                        break
                v = row[ts_key].strip()
                if v.isdigit():
                    timestamps.append(int(v))
    except Exception as e:
        print(f"    [!] Could not read {csv_path.name}: {e}")
    return sorted(timestamps)


def extract_ts(filename: str):
    """Extract the longest digit sequence (>=10 digits) from a filename."""
    candidates = re.findall(r"\d{10,}", Path(filename).stem)
    return int(max(candidates, key=len)) if candidates else None


def nearest_diff(ts: int, sorted_list: list) -> tuple:
    """Return (nearest_ts, diff_ms) from a sorted list."""
    if not sorted_list:
        return None, float("inf")
    pos = bisect.bisect_left(sorted_list, ts)
    best_ts, best_diff = None, float("inf")
    for p in [pos - 1, pos]:
        if 0 <= p < len(sorted_list):
            d = abs(sorted_list[p] - ts)
            if d < best_diff:
                best_diff = d
                best_ts = sorted_list[p]
    return best_ts, best_diff


# ─── offset detection ─────────────────────────────────────────────────────────

def detect_offset(img_timestamps: list, gps_timestamps: list, sample: int = 200) -> int:
    """
    Estimate the clock offset (gps_ts - img_ts) by sampling N image timestamps,
    finding their nearest GPS match, and taking the median difference.
    Returns offset in ms to ADD to image timestamps before matching.
    """
    if not img_timestamps or not gps_timestamps:
        return 0
    step = max(1, len(img_timestamps) // sample)
    diffs = []
    for img_ts in img_timestamps[::step]:
        gps_ts, _ = nearest_diff(img_ts, gps_timestamps)
        if gps_ts is not None:
            diffs.append(gps_ts - img_ts)
    if not diffs:
        return 0
    diffs.sort()
    median = diffs[len(diffs) // 2]
    return median


# ─── main logic ───────────────────────────────────────────────────────────────

def collect_all_gps(subfolders: list):
    """
    Returns:
      all_ts_sorted : sorted list of ALL GPS timestamps (ints) for bisect
      ts_to_source  : dict  ts -> "folder_name/file_name"
      gps_file_map  : {csv_path: [timestamps]}  for summary reporting
    """
    gps_file_map = {}
    ts_to_source = {}
    all_ts = []
    for folder in subfolders:
        gps_files = find_gps_files(folder)
        for gf in gps_files:
            ts_list = load_gps_timestamps(gf)
            gps_file_map[gf] = ts_list
            label = f"{gf.parent.name}/{gf.name}"
            for ts in ts_list:
                ts_to_source[ts] = label
            all_ts.extend(ts_list)
            print(f"    GPS: {label}  ->  {len(ts_list):,} rows")
    return sorted(all_ts), ts_to_source, gps_file_map


def scan_images(folder: Path) -> list:
    """Return sorted list of (filename, timestamp_or_None) for all images in folder."""
    results = []
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
            results.append((f.name, extract_ts(f.name)))
    return results


def run(root, tol_ms, manual_offset, out_path):

    # find subfolders
    subfolders = sorted([f for f in root.iterdir() if f.is_dir() and not f.name.startswith(".")])
    if not subfolders:
        subfolders = [root]

    print(f"\n{'='*62}")
    print(f"  ROOT : {root}")
    print(f"  Found {len(subfolders)} subfolder(s)")
    print(f"{'='*62}\n")

    # ── collect ALL GPS ──
    print("[ Step 1 ] Loading ALL GPS files across all subfolders...\n")
    all_gps_sorted, ts_to_source, gps_file_map = collect_all_gps(subfolders)
    total_gps_rows = len(all_gps_sorted)
    print(f"\n  → Total GPS timestamps pooled: {total_gps_rows:,}")
    if total_gps_rows == 0:
        print("  [!] No GPS data found at all. Check your folder structure.")
        return

    # ── collect ALL image timestamps for offset detection ──
    print("\n[ Step 2 ] Collecting image timestamps for offset detection...")
    all_img_ts = []
    folder_images = {}
    for folder in subfolders:
        imgs = scan_images(folder)
        folder_images[folder] = imgs
        all_img_ts.extend([ts for _, ts in imgs if ts is not None])
    all_img_ts.sort()
    print(f"  → Total images found: {sum(len(v) for v in folder_images.values()):,}")

    # ── offset ──
    if manual_offset is not None:
        offset = manual_offset
        print(f"\n[ Step 3 ] Using manual offset: {offset:,} ms")
    else:
        print("\n[ Step 3 ] Auto-detecting clock offset between images and GPS...")
        offset = detect_offset(all_img_ts, all_gps_sorted)
        offset_days = offset / 86_400_000
        print(f"  → Detected offset: {offset:,} ms  ({offset_days:.1f} days)")
        print(f"  → Images appear to be {'BEHIND' if offset > 0 else 'AHEAD OF'} GPS clock by {abs(offset_days):.1f} days")
        print(f"  → Applying this offset to all image timestamps before matching")

    # ── match ──
    print(f"\n[ Step 4 ] Matching images to GPS (tolerance ±{tol_ms} ms after offset)...\n")

    report_rows = []
    summary = []

    for folder in subfolders:
        imgs = folder_images[folder]
        matched, unmatched, no_ts = [], [], []

        for fname, ts in imgs:
            if ts is None:
                no_ts.append(fname)
                report_rows.append([folder.name, fname, "", "", "", "", "no_timestamp"])
                continue
            adjusted_ts = ts + offset
            gps_ts, diff = nearest_diff(adjusted_ts, all_gps_sorted)
            source = ts_to_source.get(gps_ts, "unknown") if gps_ts is not None else "unknown"
            if diff <= tol_ms:
                matched.append((fname, ts, adjusted_ts, diff, source))
                report_rows.append([folder.name, fname, ts, adjusted_ts, diff, source, "matched"])
            else:
                unmatched.append((fname, ts, adjusted_ts, diff, source))
                report_rows.append([folder.name, fname, ts, adjusted_ts, diff, source, "UNMATCHED"])

        summary.append({
            "folder": folder.name,
            "total": len(imgs),
            "matched": matched,
            "unmatched": unmatched,
            "no_ts": no_ts,
        })

    # ── print report ──
    total_imgs   = sum(s["total"] for s in summary)
    total_match  = sum(len(s["matched"]) for s in summary)
    total_unmatch= sum(len(s["unmatched"]) for s in summary)
    total_no_ts  = sum(len(s["no_ts"]) for s in summary)

    print(f"\n{'='*62}")
    print(f"  GPS COVERAGE REPORT  (offset={offset:,} ms, tol=±{tol_ms} ms)")
    print(f"{'='*62}")
    print(f"  GPS timestamps (pooled)  : {total_gps_rows:,}")
    print(f"  Images scanned           : {total_imgs:,}")
    print(f"  Matched                  : {total_match:,}  ({100*total_match/max(total_imgs,1):.1f}%)")
    print(f"  UNMATCHED                : {total_unmatch:,}")
    print(f"  No timestamp in filename : {total_no_ts:,}")
    print(f"{'='*62}")

    for s in summary:
        pct = 100 * len(s["matched"]) / max(s["total"], 1)
        status = "OK" if pct > 90 else ("PARTIAL" if pct > 0 else "ALL MISSING")
        print(f"\n  📁  {s['folder']}  [{status}]")
        print(f"      Images   : {s['total']:,}")
        print(f"      Matched  : {len(s['matched']):,}  ({pct:.1f}%)")
        if s["unmatched"]:
            print(f"      Unmatched: {len(s['unmatched']):,}")
            for fname, ts, adj, diff, source in s["unmatched"][:5]:
                print(f"        - {fname}  (nearest GPS diff={diff:,} ms, closest file={source})")
            if len(s["unmatched"]) > 5:
                print(f"        ... and {len(s['unmatched'])-5} more")
        if s["matched"]:
            # show breakdown of which GPS files the matches came from
            from collections import Counter
            src_counts = Counter(source for _, _, _, _, source in s["matched"])
            print(f"      Matched from GPS sources:")
            for src, cnt in src_counts.most_common():
                print(f"        {cnt:>6,} images  <-  {src}")
        if s["no_ts"]:
            print(f"      No TS in name: {len(s['no_ts'])}")

    # ── save CSV ──
    if out_path:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["folder", "filename", "image_ts", "adjusted_ts", "nearest_gps_diff_ms", "status"])
            writer.writerows(report_rows)
        print(f"\n  Full report saved to: {out_path}")


# ─── entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root",   required=True, help="Root folder containing your subfolders")
    parser.add_argument("--tol",    type=int, default=500, help="Tolerance in ms (default 500)")
    parser.add_argument("--offset", type=int, default=None, help="Manual clock offset in ms to add to image timestamps")
    parser.add_argument("--out",    default=None, help="Save full report to this CSV file")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"Error: {root} does not exist.")
        return

    run(root, args.tol, args.offset, args.out)


if __name__ == "__main__":
    main()