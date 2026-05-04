# SENTINEL — Surveillance Video Intelligence System

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                      FRONTEND (React)                 │
│   Upload → Poll → Sidebar → Video Player → Timeline  │
└─────────────────────────┬────────────────────────────┘
                           │  REST API (JSON + multipart)
┌─────────────────────────▼────────────────────────────┐
│                    BACKEND (FastAPI)                  │
│  /upload → /jobs/{id} → /persons → /search           │
└─────────────────────────┬────────────────────────────┘
                           │
┌─────────────────────────▼────────────────────────────┐
│              TRACKING PIPELINE (Python)               │
│                                                       │
│   Video frames                                        │
│       │                                               │
│       ▼                                               │
│   YOLOv8m ──→ person detections (bbox + confidence)  │
│       │                                               │
│       ▼                                               │
│   DeepSORT ──→ confirmed tracks (with ReID embeddings)│
│       │                                               │
│       ├──→ ID mapping  (track_id → P1, P2, P3…)     │
│       ├──→ Thumbnails  (first clear crop per person)  │
│       ├──→ JSON store  (timestamps, bboxes, frames)   │
│       └──→ Heatmaps    (Gaussian blur on centers)     │
└──────────────────────────────────────────────────────┘
```

## Project Structure

```
surveillance-system/
├── backend/
│   ├── main.py                  # FastAPI app, all endpoints
│   ├── process_video.py         # Standalone CLI tool
│   ├── requirements.txt
│   ├── Dockerfile
│   └── tracker/
│       ├── __init__.py
│       └── pipeline.py          # YOLOv8 + DeepSORT + heatmap
│
├── frontend/
│   ├── package.json
│   ├── public/index.html
│   └── src/
│       ├── index.js
│       └── App.jsx              # Full React UI
│
├── docker-compose.yml
└── README.md
```

## Quick Start

### Option A — CLI (offline processing only)

```bash
cd backend
pip install -r requirements.txt

# Process a video
python process_video.py --video /path/to/cctv.mp4 --output ./output
# Results written to ./output/tracking_data.json
```

### Option B — Full Stack (API + UI)

```bash
# 1. Start backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 2. Start frontend (new terminal)
cd frontend
npm install
npm start          # opens http://localhost:3000
```

### Option C — Docker

```bash
docker-compose up --build
# Frontend: http://localhost:3000
# API docs:  http://localhost:8000/docs
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload` | Upload video, returns `{job_id}` |
| GET | `/api/jobs/{job_id}` | Poll processing status + progress % |
| GET | `/api/persons` | List all tracked persons |
| GET | `/api/persons/{id}` | Full data for one person |
| GET | `/api/persons/{id}/bboxes?start=&end=` | Bboxes in time range |
| GET | `/api/search?q=P1` | Search by person ID |
| GET | `/api/video/{job_id}` | Stream original video |
| GET | `/api/video/{job_id}/annotated?person_id=P1` | Stream annotated video |

## Output JSON Format

```json
{
  "P1": {
    "first_seen":   2.1,
    "last_seen":   15.4,
    "total_time":  13.3,
    "appearances": 312,
    "timestamps":  [2.1, 2.13, 2.16, "..."],
    "frames":      [45, 46, 47, "..."],
    "bboxes": [
      { "frame": 45, "timestamp": 2.1, "bbox": [120, 80, 200, 310] }
    ],
    "thumbnail":   "output/thumbnails/P1.jpg",
    "heatmap":     "output/heatmaps/heatmap_P1.png"
  }
}
```

## Tracking Accuracy Improvements

### 1. Use a Better ReID Model
Replace `embedder="mobilenet"` in DeepSORT with a proper OSNet model:
```python
# pip install torchreid
tracker = DeepSort(embedder="torchreid", embedder_model_name="osnet_x1_0")
```

### 2. Increase MAX_AGE for Slow Scenes
If people leave frame briefly, raising `max_age=120` keeps their track alive longer.

### 3. Tune Cosine Distance Threshold
- `max_cosine_distance=0.3` → stricter (fewer false re-IDs, more ID switches)
- `max_cosine_distance=0.5` → looser  (better re-ID, risk of merging tracks)

### 4. Use YOLOv8x for Higher Accuracy
Swap `yolov8m.pt` → `yolov8x.pt` (slower but more detections at distance).

### 5. Non-Maximum Suppression Tuning
Add `iou=0.5` to `detector()` call to reduce duplicate boxes in crowds.

### 6. Frame Skipping for Long Videos
Process every Nth frame for speed, interpolate bboxes between:
```python
if frame_idx % 2 != 0:   # process every 2nd frame
    frame_idx += 1
    continue
```

### 7. Camera Calibration
If camera is fixed, apply background subtraction (MOG2) to pre-filter detections
to moving objects only — reduces false positives from static mannequins, posters.

### 8. Confidence Filtering per Zone
Define ROI zones and only track persons entering specific areas (reduces edge noise).

## Limitations & Notes

- **Re-ID across long occlusions**: DeepSORT's appearance model may still assign
  a new ID if a person was hidden for >60 frames. Use StrongSORT or ByteTrack
  for improved long-gap re-identification.

- **Crowd scenes**: Performance degrades above ~15 people per frame. Consider
  using ByteTrack which handles dense scenes better.

- **GPU**: Highly recommended. YOLOv8 + DeepSORT can process ~20–30 fps on
  an RTX 3060, vs ~3–5 fps on CPU only.
