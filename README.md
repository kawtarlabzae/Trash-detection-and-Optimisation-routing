# 🗑️ TrashVision — Intelligent Urban Waste Detection & Route Optimization

> **Computer vision meets operations research.** A field-deployed intelligence system that watches waste collection trucks navigate Casablanca, detects bins and garbage with a fine-tuned RT-DETR model, enriches each detection with a Vision Language Model, and then solves an Orienteering Problem to hand dispatchers the optimal collection route — all visualized on an interactive web dashboard.

---

<div align="center">

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Dashboard-000000?style=for-the-badge&logo=flask&logoColor=white)
![RT-DETR](https://img.shields.io/badge/RT--DETR-Ultralytics-00FFFF?style=for-the-badge)
![Gemini](https://img.shields.io/badge/Gemini_4-VLM-4285F4?style=for-the-badge&logo=google&logoColor=white)
![PuLP](https://img.shields.io/badge/PuLP-CBC_Solver-FF6B35?style=for-the-badge)
![Leaflet](https://img.shields.io/badge/Leaflet.js-Maps-199900?style=for-the-badge)

</div>

---

## 📖 What Is This?

Urban waste collection is expensive and inefficient when trucks follow fixed schedules regardless of actual fill levels. **TrashVision** changes that by:

1. **Watching** — video frames from 5 truck routes (Alpha through Epsilon) across Casablanca are collected alongside GPS timestamps
2. **Detecting** — a fine-tuned RT-DETR model identifies bins and garbage piles in every frame
3. **Understanding** — a Vision Language Model (Gemini 4 or InternVL2) inspects each cropped detection and classifies fill level and quantity
4. **Optimizing** — a constrained Orienteering Problem solver picks the highest-priority stops within the truck's distance budget and weight capacity
5. **Showing** — a live Flask dashboard maps everything: routes, images, detections, and the computed optimal path

The result is an end-to-end, field-validated system that turns raw street footage into actionable dispatch instructions.

---

## 🗂️ Project Structure

```
Trash-detection-and-Optimisation-routing/
│
├── PA AISIN/                          # Main working directory
│   │
│   ├── 📊 dashboard/                  # Flask web dashboard
│   │   ├── app.py                     #   Server, API endpoints, GPS merging
│   │   ├── requirements.txt           #   Flask-specific dependencies
│   │   ├── templates/
│   │   │   ├── index.html             #   5-route overview page
│   │   │   └── epsilon.html           #   Route Epsilon detail page
│   │   └── static/
│   │       ├── css/style.css          #   Dashboard styling
│   │       ├── js/app.js              #   Leaflet.js map + Chart.js logic
│   │       └── optimal_route.json     #   Latest solver output (auto-generated)
│   │
│   ├── 🔍 run_detection.py            # RT-DETR inference — all 5 routes
│   ├── 🔍 run_detection_epsilon.py    # RT-DETR inference — Route Epsilon only
│   ├── 🧮 solve_routing.py            # Orienteering Problem solver
│   ├── 🛰️  check.py                   # GPS clock-offset auto-detection
│   ├── ⚡ find_high_speed.py          # GPS anomaly / glitch detector
│
└── 📓 Final Notebooks/
    ├── Layout_Final.ipynb             # RT-DETR training + Gemini/InternVL analysis
    └── Hyperparam_Trials.ipynb        # Hyperparameter search experiments
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.12
- The trained RT-DETR model checkpoint (`best.pt`) — see [📦 Data & Models](#-data--models) below
- Route image folders + GPS CSVs — see [📦 Data & Models](#-data--models) below
- A [Google AI Studio](https://aistudio.google.com/) API key (for the Gemini VLM step)
- _(Optional)_ InternVL2-8B weights downloaded locally + [lmdeploy](https://github.com/InternLM/lmdeploy) installed (only needed if using Option B in step 4)

---

### 1. Install Dependencies

```bash
# Clone the repo
git clone https://github.com/your-username/Trash-detection-and-Optimisation-routing.git
cd Trash-detection-and-Optimisation-routing
```

Install all dependencies at once:

```bash
pip install flask pandas numpy ultralytics google-generativeai openai pillow pulp requests
```

Here is what each package is for:

| Package | Version | Used for |
|---|---|---|
| `flask` | ≥ 3.0 | Web dashboard server and REST API |
| `pandas` | ≥ 2.0 | GPS CSV loading, timestamp merging, data wrangling |
| `numpy` | ≥ 1.24 | Numerical operations and array handling |
| `ultralytics` | latest | Loading and running the RT-DETR model (`best.pt`) |
| `pillow` | latest | Image cropping for VLM input |
| `google-generativeai` | latest | Gemini 4 VLM API client |
| `openai` | latest | InternVL2 via lmdeploy OpenAI-compatible API |
| `pulp` | latest | Orienteering Problem formulation and CBC solver |
| `requests` | latest | OSRM API calls for road distances and geometry |

> **Note:** The dashboard's [`requirements.txt`](PA%20AISIN/dashboard/requirements.txt) only covers the web server itself (`flask`, `pandas`, `numpy`). For the full pipeline — detection, VLM, and solver — install from the table above.

---

### 2. Place Your Data

See [📦 Data & Models](#-data--models) for download links.

Expected layout (paths are configurable at the top of each script):

```
f:/AISIN/20260205/
├── alpha/
│   ├── images/          # JPEG frames from the truck camera
│   └── gps.csv          # Columns: timestamp_ms, lat, lon, speed_kmh
├── beta/   ...
├── gamma/  ...
├── delta/  ...
├── epsilon/
│   ├── images/
│   └── gps.csv
└── best.pt              # RT-DETR model weights
```

For now the link only contains grouped images, not divided by route. We will try to recover the route-specified data and add it to out links

---

### 3. Run Object Detection

Detects bins and garbage in every frame across all 5 routes. Spatially samples frames (≥ 10 m apart) so redundant near-duplicates are skipped automatically.

```bash
python "PA AISIN/run_detection.py"
```

**Output:** `detections.json` in each route folder — bounding boxes, confidence scores, GPS coordinates, and image paths.

To run only Route Epsilon (faster, good for a first test):

```bash
python "PA AISIN/run_detection_epsilon.py"
```

---

### 4. Enrich with a Vision Language Model

Crops each detected region and asks the VLM to classify it. **Choose one backend:**

#### Option A — Gemini 4 (recommended, cloud)

1. Open [PA AISIN/run_vlm_analysis.py](PA%20AISIN/run_vlm_analysis.py)
2. Set your API key: `GEMINI_API_KEY = "your-key-here"`
3. Run:

```bash
python "PA AISIN/run_vlm_analysis.py"
```

#### Option B — InternVL2-8B (local model, downloaded manually)

The model weights are downloaded locally and served through [lmdeploy](https://github.com/InternLM/lmdeploy), which exposes an OpenAI-compatible API on `localhost:23333`. The script connects to that server.

1. Download the InternVL2-8B weights and serve them with lmdeploy:

```bash
lmdeploy serve api_server /path/to/InternVL2-8B --server-port 23333
```

2. Run:

```bash
python "PA AISIN/run_internvl_analysis.py"
```

**Output:** `detections.json` updated with:
- **Bins** → `fill_level`: `"empty"` | `"mid full"` | `"full"`
- **Garbage** → `amount`: `"a little"` | `"a lot"`

---

### 5. Solve the Optimal Route

Runs the Orienteering Problem solver against enriched detections. Fetches real-world road distances from the public OSRM API and selects the highest-priority stops within budget.

```bash
python "PA AISIN/solve_routing.py"
```

**Configurable parameters** (environment variables or edit at the top of the script):

| Variable | Default | Meaning |
|---|---|---|
| `BUDGET_KM` | `2.0` | Max travel distance (km) |
| `CAPACITY_KG` | `500` | Truck weight limit (kg) |
| `CLUSTER_M` | `40` | Cluster nearby stops within this radius (m) |
| `P_BIN_FULL` | `10` | Priority score — full bin |
| `P_BIN_MID` | `5` | Priority score — half-full bin |
| `P_GARBAGE_LOT` | `8` | Priority score — large garbage pile |
| `P_GARBAGE_LITTLE` | `2` | Priority score — small garbage pile |
| `W_BIN_FULL` | `80` | Estimated weight — full bin (kg) |
| `W_BIN_MID` | `40` | Estimated weight — mid-full bin (kg) |
| `W_GARBAGE_LOT` | `120` | Estimated weight — large pile (kg) |
| `W_GARBAGE_LITTLE` | `25` | Estimated weight — small pile (kg) |
| `DEPOT_LAT / DEPOT_LON` | _(none)_ | Optional depot for closed-loop routing |

**Output:** `PA AISIN/dashboard/static/optimal_route.json` — ordered stop list with OSRM road geometry for the map overlay.

---

### 6. Launch the Dashboard

```bash
cd "PA AISIN/dashboard"
python app.py
```

Open your browser at **[http://localhost:5000](http://localhost:5000)**

The server preloads all route data in a background thread on startup. The map populates automatically once ready (typically 10–30 s depending on route size).

---

## 🗺️ Dashboard Walkthrough

### Main View — `http://localhost:5000`

| Panel | What You See |
|---|---|
| **Map** | 5 color-coded polylines (green = slow → red = fast), clickable image & bin markers |
| **Left sidebar** | Route selector + statistics (total km, duration, avg/max speed) |
| **Marker popup** | Thumbnail, GPS coordinates, RT-DETR detections with VLM fill levels |
| **Optimal route overlay** | Blue polyline showing the solver's computed optimal collection path |
| **Speed chart** | Distance vs. km/h profile for the selected route |

### Route Epsilon Detail — `http://localhost:5000/epsilon`

A focused single-route view with the full image browser, all detections, and a live solver panel where you can tweak parameters and re-run via the **Solve** button — no terminal needed.

### REST API Endpoints

```
GET  /api/data                  →  Route stats, GPS arrays, image list
GET  /api/optimal_route         →  Latest solver output (JSON)
POST /api/solve                 →  Run solver with custom parameters
     Body: { "budget_km": 3.0, "capacity_kg": 600, "cluster_m": 50, ... }
```

---

## 📓 Notebooks

### [`Final Notebooks/Layout_Final.ipynb`](Final%20Notebooks/Layout_Final.ipynb)

The main research notebook — open in Jupyter or Google Colab:

- **RT-DETR-L training** — full training loop on the merged trash detection dataset, with loss curves and confusion matrices
- **Gemini 4 analysis** — visual grid of predictions with VLM labels overlaid on the validation set
- **InternVL2 analysis** — the same grid using the local model for a side-by-side comparison
- **Validation samples** — bounding box visualizations on held-out images

### [`Final Notebooks/Hyperparam_Trials.ipynb`](Final%20Notebooks/Hyperparam_Trials.ipynb)

Ablation study — experiments with different learning rates, augmentation strengths, and anchor configurations for the RT-DETR model.

---

## 🧠 How the Optimization Works

The routing problem is modeled as an **Orienteering Problem (OP)** — a variant of the Travelling Salesman Problem where you *cannot* visit all nodes and must instead pick which stops to visit to maximize a reward function under hard constraints.

```
maximize   Σ priority(stop_i) × x_i
subject to:
  Σ road_distance(i → j) × x_ij  ≤  BUDGET_KM
  Σ weight(stop_i) × x_i          ≤  CAPACITY_KG
  flow conservation at every node
  (optional) start and end at depot
```

- **Solver:** [PuLP](https://coin-or.github.io/pulp/) with [CBC](https://github.com/coin-or/Cbc) (COIN-OR Branch and Cut)
- **Distance matrix:** [OSRM](http://project-osrm.org/) public API — real road distances, not straight-line approximations
- **Road geometry:** OSRM `/route/` endpoint returns the actual path polyline per segment for the map overlay
- **Traffic zones:** If a segment's midpoint falls within a defined zone, its effective distance is multiplied by a configurable slowdown factor

---

## 🏗️ Architecture & Data Flow

```
┌──────────────────────────────────────────────────────────┐
│                   FIELD DATA COLLECTION                  │
│  5 Truck Routes (Alpha–Epsilon) in Casablanca, Morocco   │
│  📷 JPEG frames  +  🛰️ GPS CSV (lat, lon, speed, time)   │
└─────────────────────────┬────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│              DETECTION  (run_detection.py)               │
│  • Haversine spatial sampling (≥ 10 m between frames)    │
│  • Clock-offset auto-correction between camera & GPS     │
│  • RT-DETR inference → bounding boxes + confidence scores │
│  Output: detections.json per route                       │
└─────────────────────────┬────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│          VLM ENRICHMENT  (run_vlm_analysis.py)           │
│  • Crop each detected region with padding                │
│  • Send to Gemini 4 (or InternVL2) with structured prompt│
│  • Bins → fill level  |  Garbage → amount               │
│  Output: detections.json enriched with semantic labels   │
└─────────────────────────┬────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│          ROUTE OPTIMIZATION  (solve_routing.py)          │
│  • Cluster nearby stops (configurable radius)            │
│  • Fetch real road distances from OSRM API               │
│  • Solve Orienteering Problem with PuLP + CBC            │
│  • Retrieve OSRM road geometry for the optimal path      │
│  Output: optimal_route.json                              │
└─────────────────────────┬────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│            INTERACTIVE DASHBOARD  (app.py)               │
│  • Flask server + background data loader                 │
│  • Leaflet.js map: routes, markers, optimal path         │
│  • Chart.js: speed profiles                              │
│  • REST API: /api/data · /api/optimal_route · /api/solve │
└──────────────────────────────────────────────────────────┘
```

---

## 📦 Data & Models

> ⬇️ **Download these assets and place them as described in step 2 before running.**

| Asset | Description | Link |
|---|---|---|
| **Route Images + GPS** | JPEG frames and GPS CSVs for all 5 routes (Alpha–Epsilon), Casablanca Feb 2026 | [DataMerged](https://um6p-my.sharepoint.com/:f:/g/personal/mounia_baddou_um6p_ma/IgCkC8w3Z4b8R7vbbc-s-JslAfk-u-xyenJkwZrjpobNWJk?e=5wpaJD) |
| **RT-DETR Model (`best.pt`)** | RT-DETR-L fine-tuned on the merged trash detection dataset (classes: `bin`, `garbage`) — trained in `Layout_Final.ipynb` | [best.pt](https://drive.google.com/file/d/1U9uouxf_-Ts7Qr8kqdcy0ZOqUtABUfFQ/view?usp=drive_link) |

---

## 🛠️ Utility Scripts

| Script | Purpose |
|---|---|
| [`check.py`](PA%20AISIN/check.py) | Diagnose GPS ↔ image clock offset; run this first if timestamp matching looks wrong |
| [`find_high_speed.py`](PA%20AISIN/find_high_speed.py) | Flag GPS entries with physically impossible speeds (useful for spotting data glitches) |

---

## ⚙️ Configuration Reference

All tunable constants live at the top of each script. The most important ones:

**Detection** — [`run_detection.py`](PA%20AISIN/run_detection.py):
```python
MIN_DIST_M       = 10.0    # Minimum meters between sampled frames
MAX_GPS_GAP_MS   = 1000    # Max allowed gap for GPS interpolation (ms)
```

**VLM** — [`run_vlm_analysis.py`](PA%20AISIN/run_vlm_analysis.py):
```python
MIN_GARBAGE_CONF = 0.75    # Only run VLM on high-confidence detections
CROP_PAD         = 8       # Pixel padding around bounding boxes before crop
```

**Solver** — [`solve_routing.py`](PA%20AISIN/solve_routing.py):
```python
BUDGET_KM        = 2.0
CAPACITY_KG      = 500
CLUSTER_M        = 40
OSRM_URL         = "http://router.project-osrm.org"
```

---

## 📝 A Note on Model Performance

`best.pt` was trained entirely on images collected from the streets of Casablanca, Morocco. Waste management in Morocco is informal enough that bins and garbage piles don't follow consistent patterns — varying containers, mixed dumping spots, and cluttered backgrounds all make the detection task harder than it would be with cleaner, more standardized data. This directly limits the model's precision and recall in edge cases.

The approach itself is sound; the bottleneck is data quality. With a richer, more diverse annotated dataset the same pipeline would yield noticeably better detection results.

---


<div align="center">
  <sub>Built with RT-DETR · Gemini · PuLP · Flask · Leaflet.js · OSRM</sub>
</div>
