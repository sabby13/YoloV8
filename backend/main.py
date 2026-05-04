"""
surveillance_system/backend/main.py

FastAPI application — REST API for the surveillance system.
"""

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
import cv2
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tracker.pipeline import process_video

# ─────────────────────────────────────────────
app = FastAPI(title="Surveillance Analysis API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR   = Path("output")
UPLOAD_DIR   = Path("uploads")
OUTPUT_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(OUTPUT_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# ── in-memory job state (use Redis for production) ──
jobs: dict[str, dict] = {}

# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class JobStatus(BaseModel):
    job_id: str
    status: str          # "pending" | "processing" | "done" | "error"
    progress: int = 0
    message: str = ""
    result: Optional[dict] = None


class SearchResult(BaseModel):
    person_id: str
    first_seen: float
    last_seen: float
    total_time: float
    appearances: int
    timestamps: list[float]
    thumbnail: Optional[str]
    heatmap: Optional[str]


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def load_tracking_data() -> dict:
    path = OUTPUT_DIR / "tracking_data.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def url_for_file(path: Optional[str]) -> Optional[str]:
    """Convert local filesystem path to a static URL."""
    if not path:
        return None
    p = Path(path)
    # Return relative URL under /static/
    try:
        rel = p.relative_to(OUTPUT_DIR)
        return f"/static/{rel}"
    except ValueError:
        return None


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Upload & Process Video ───────────────────

@app.post("/api/upload", response_model=JobStatus)
async def upload_video(file: UploadFile = File(...)):
    """Upload a CCTV video and kick off background processing."""

    if not file.filename.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
        raise HTTPException(400, "Unsupported video format")

    job_id   = str(uuid.uuid4())
    vid_path = UPLOAD_DIR / f"{job_id}_{file.filename}"

    # stream-write uploaded file
    async with aiofiles.open(vid_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):   # 1 MB chunks
            await f.write(chunk)

    jobs[job_id] = {"status": "pending", "progress": 0,
                    "message": "Queued", "result": None}

    # run pipeline in background thread (non-blocking)
    asyncio.create_task(_run_pipeline(job_id, str(vid_path)))

    return JobStatus(job_id=job_id, status="pending", message="Processing queued")


async def _run_pipeline(job_id: str, video_path: str):
    """Background task that runs the tracking pipeline."""
    jobs[job_id]["status"] = "processing"

    def on_progress(pct: int, msg: str):
        jobs[job_id]["progress"] = pct
        jobs[job_id]["message"]  = msg

    try:
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: process_video(video_path, str(OUTPUT_DIR), on_progress)
        )
        jobs[job_id].update({"status": "done", "progress": 100,
                              "message": "Complete", "result": result})
    except Exception as e:
        jobs[job_id].update({"status": "error", "message": str(e)})


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    j = jobs[job_id]
    return JobStatus(job_id=job_id, **j)


# ── Tracking Data ────────────────────────────

@app.get("/api/persons")
def list_persons():
    """Return summary list of all tracked persons."""
    data = load_tracking_data()
    result = []
    for pid, d in data.items():
        result.append({
            "person_id":   pid,
            "first_seen":  d["first_seen"],
            "last_seen":   d["last_seen"],
            "total_time":  d.get("total_time", 0),
            "appearances": d.get("appearances", len(d["timestamps"])),
            "thumbnail":   url_for_file(d.get("thumbnail")),
            "heatmap":     url_for_file(d.get("heatmap")),
        })
    # sort by first appearance
    result.sort(key=lambda x: x["first_seen"])
    return result


@app.get("/api/persons/{person_id}", response_model=SearchResult)
def get_person(person_id: str):
    """Full data for a single person."""
    data = load_tracking_data()
    pid  = person_id.upper()

    if pid not in data:
        raise HTTPException(404, f"{pid} not found in tracking data")

    d = data[pid]
    return SearchResult(
        person_id   = pid,
        first_seen  = d["first_seen"],
        last_seen   = d["last_seen"],
        total_time  = d.get("total_time", 0),
        appearances = d.get("appearances", len(d["timestamps"])),
        timestamps  = d["timestamps"],
        thumbnail   = url_for_file(d.get("thumbnail")),
        heatmap     = url_for_file(d.get("heatmap")),
    )


@app.get("/api/persons/{person_id}/bboxes")
def get_bboxes(person_id: str, start: float = 0, end: float = 9999):
    """Return bounding boxes for a person in a timestamp range."""
    data = load_tracking_data()
    pid  = person_id.upper()

    if pid not in data:
        raise HTTPException(404, f"{pid} not found")

    bboxes = [
        b for b in data[pid].get("bboxes", [])
        if start <= b["timestamp"] <= end
    ]
    return {"person_id": pid, "bboxes": bboxes}


@app.get("/api/search")
def search(q: str = Query(..., description="Person ID e.g. P1")):
    """Search for a person by ID (case-insensitive)."""
    return get_person(q)


# ── Video Streaming ──────────────────────────

@app.get("/api/video/{job_id}")
def stream_video(job_id: str):
    """Stream the original uploaded video."""
    matches = list(UPLOAD_DIR.glob(f"{job_id}_*"))
    if not matches:
        raise HTTPException(404, "Video not found")
    video_path = matches[0]
    return FileResponse(str(video_path), media_type="video/mp4",
                        headers={"Accept-Ranges": "bytes"})


@app.get("/api/video/{job_id}/annotated")
def stream_annotated(
    job_id: str,
    person_id: Optional[str] = Query(None, description="Highlight only this person"),
):
    """
    Stream a version of the video with bounding box overlays.
    Highlights the selected person (if given) or all persons.
    """
    matches = list(UPLOAD_DIR.glob(f"{job_id}_*"))
    if not matches:
        raise HTTPException(404, "Video not found")

    data       = load_tracking_data()
    video_path = str(matches[0])

    def annotated_frames():
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

        # build frame→bboxes lookup
        frame_map: dict[int, list] = {}
        for pid, d in data.items():
            if person_id and pid != person_id.upper():
                continue
            for b in d.get("bboxes", []):
                fi = b["frame"]
                frame_map.setdefault(fi, []).append((pid, b["bbox"]))

        colors = {
            pid: (
                (hash(pid) * 37) % 255,
                (hash(pid) * 73) % 255,
                (hash(pid) * 113) % 255,
            )
            for pid in data
        }

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            for (pid, bbox) in frame_map.get(frame_idx, []):
                x1, y1, x2, y2 = bbox
                color = colors.get(pid, (0, 255, 0))
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, pid, (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n"
                   + buf.tobytes()
                   + b"\r\n")
            frame_idx += 1

        cap.release()

    return StreamingResponse(
        annotated_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
