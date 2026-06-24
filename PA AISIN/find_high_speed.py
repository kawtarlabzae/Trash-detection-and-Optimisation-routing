import pandas as pd
from pathlib import Path

# ── EDIT THESE ─────────────────────────────────────────────────────────────
ROOT_DIRECTORY = '.'          # '.' means it will start in the current folder
SPEED_THRESHOLD = 90.0        # Flag any speed greater than or equal to this
# ──────────────────────────────────────────────────────────────────────────

def find_high_speeds():
    root = Path(ROOT_DIRECTORY)
    
    # rglob recursively searches all subdirectories for files matching the pattern
    gps_files = list(root.rglob('GPS*.csv'))
    print(gps_files)
    if not gps_files:
        print("No files starting with 'GPS' found in any subfolders.")
        return

    print(f"Found {len(gps_files)} GPS files. Scanning for speeds >= {SPEED_THRESHOLD}...\n")
    
    total_anomalies = 0

    for file_path in gps_files:
        try:
            # Read the CSV file
            df = pd.read_csv(file_path)
            
            # Check if the 'spd' column exists
            if 'spd' in df.columns:
                # Filter for rows where speed is dangerously/impossibly high
                glitches = df[df['spd'] >= SPEED_THRESHOLD]
                
                if not glitches.empty:
                    print(f"⚠️ FOUND {len(glitches)} ANOMALIES IN: {file_path}")
                    
                    # Print the specific rows so you can see the timestamps and coordinates
                    # We just print the relevant columns to keep the terminal clean
                    cols_to_show = ['unixtime_ms', 'spd', 'lat', 'lon']
                    # Keep only columns that actually exist in the dataframe
                    cols_to_show = [c for c in cols_to_show if c in df.columns]
                    
                    print(glitches[cols_to_show].to_string(index=False))
                    print("-" * 60)
                    
                    total_anomalies += len(glitches)
            else:
                print(f"Skipping {file_path.name} - No 'spd' column found.")
                
        except Exception as e:
            print(f"❌ Error reading {file_path.name}: {e}")

    print(f"\n✅ Scan complete. Total high-speed glitches found: {total_anomalies}")

if __name__ == '__main__':
    find_high_speeds()