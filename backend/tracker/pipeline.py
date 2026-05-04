"""
surveillance_system/backend/tracker/pipeline.py

Core detection + tracking pipeline.
- YOLOv8 for person detection
- DeepSORT for identity-consistent tracking
- JSON output with timestamps, thumbnails, heatmap data
"""

import cv2
import json
import time
import numpy as np
from pathlib import Path
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
YOLO_MODEL        = "yolov8m.pt"       # m = medium, balance of speed/accuracy
CONFIDENCE_THRESH = 0.45               # minimum detection confidence
PERSON_CLASS_ID   = 0                  # COCO class 0 = person
MAX_AGE           = 60                 # frames to keep a lost track alive
N_INIT            = 3                  # frames before a track is confirmed
MAX_COSINE_DIST   = 0.4               # ReID appearance threshold (lower = stricter)
NN_BUDGET         = 100               # max appearance descriptors per track


def load_models(model_path: str = YOLO_MODEL):
    """Load YOLO detector and initialize DeepSORT tracker."""
    detector = YOLO(model_path)

    tracker = DeepSort(
        max_age=MAX_AGE,
        n_init=N_INIT,
        max_cosine_distance=MAX_COSINE_DIST,
        nn_budget=NN_BUDGET,
        embedder="mobilenet",           # fast ReID embedder built into deep-sort-realtime
        half=True,                      # FP16 inference where supported
        bgr=True,                       # OpenCV frames are BGR
    )

    return detector, tracker


def detect_persons(detector, frame: np.ndarray) -> list[dict]:
    """
    Run YOLOv8 on a frame and return only person detections.

    Returns list of:
        { "bbox": [x1,y1,x2,y2], "confidence": float }
    """
    results = detector(frame, verbose=False, classes=[PERSON_CLASS_ID])[0]
    detections = []

    for box in results.boxes:
        conf = float(box.conf[0])
        if conf < CONFIDENCE_THRESH:
            continue
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        detections.append({"bbox": [x1, y1, x2, y2], "confidence": conf})

    return detections


def convert_to_deepsort_format(detections: list[dict]) -> list:
    """
    Convert detection dicts to DeepSORT input format:
        [ ([left, top, w, h], confidence, class_label), ... ]
    """
    ds_input = []
    for d in detections:
        x1, y1, x2, y2 = d["bbox"]
        w, h = x2 - x1, y2 - y1
        ds_input.append(([x1, y1, w, h], d["confidence"], "person"))
    return ds_input


def save_thumbnail(frame: np.ndarray, bbox: list[int], person_id: str,
                   output_dir: Path) -> str:
    """Crop and save a thumbnail for the given person bounding box."""
    x1, y1, x2, y2 = bbox
    # add small padding
    pad = 10
    h, w = frame.shape[:2]
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)

    crop = frame[y1:y2, x1:x2]
    thumb_path = output_dir / f"{person_id}.jpg"
    cv2.imwrite(str(thumb_path), crop)
    return str(thumb_path)


def generate_heatmap(frame_shape: tuple, track_data: dict,
                     output_dir: Path) -> dict[str, str]:
    """
    Build a presence heatmap per person from accumulated bbox center points.

    Returns { person_id: heatmap_image_path }
    """
    import matplotlib.pyplot as plt
    from scipy.ndimage import gaussian_filter

    h, w = frame_shape[:2]
    heatmap_paths = {}

    for person_id, data in track_data.items():
        heat = np.zeros((h, w), dtype=np.float32)

        for (cx, cy) in data.get("centers", []):
            if 0 <= cy < h and 0 <= cx < w:
                heat[cy, cx] += 1

        heat = gaussian_filter(heat, sigma=30)

        if heat.max() > 0:
            heat /= heat.max()

        fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=100)
        ax.imshow(cv2.cvtColor(
            cv2.imread("placeholder_bg.jpg") if False else np.zeros((h, w, 3), np.uint8),
            cv2.COLOR_BGR2RGB
        ), alpha=0.3)
        ax.imshow(heat, cmap="hot", alpha=0.7, vmin=0, vmax=1)
        ax.axis("off")
        ax.set_title(f"Presence Heatmap — {person_id}", color="white")
        fig.patch.set_facecolor("#111")

        hm_path = output_dir / f"heatmap_{person_id}.png"
        plt.savefig(str(hm_path), bbox_inches="tight", pad_inches=0.1,
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        heatmap_paths[person_id] = str(hm_path)

    return heatmap_paths


# ─────────────────────────────────────────────
# Main Processing Function
# ─────────────────────────────────────────────

def process_video(
    video_path: str,
    output_dir: str = "output",
    progress_callback=None
) -> dict:
    """
    Full pipeline: detect → track → store JSON.

    Args:
        video_path:        Path to input CCTV video.
        output_dir:        Where to write thumbnails, heatmaps, JSON.
        progress_callback: Optional fn(percent: int, message: str) for progress updates.

    Returns:
        Structured tracking data dict.
    """
    out = Path(output_dir)
    thumb_dir  = out / "thumbnails"
    heatmap_dir = out / "heatmaps"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    heatmap_dir.mkdir(parents=True, exist_ok=True)

    detector, tracker = load_models()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    fps        = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_shape  = None

    # ── tracking state ────────────────────────
    track_data: dict[str, dict] = {}   # person_id → data blob
    tracker_to_person: dict[int, str] = {}  # deep-sort track_id → P1/P2/…
    person_counter = 0
    saved_thumbnails: set[str] = set()

    print(f"[Pipeline] Processing {total_frames} frames @ {fps:.1f} fps …")

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_shape is None:
            frame_shape = frame.shape

        timestamp = round(frame_idx / fps, 2)

        # ── detect ────────────────────────────
        detections = detect_persons(detector, frame)
        ds_input   = convert_to_deepsort_format(detections)

        # ── track ─────────────────────────────
        tracks = tracker.update_tracks(ds_input, frame=frame)

        for track in tracks:
            if not track.is_confirmed():
                continue

            tid = track.track_id
            ltrb = track.to_ltrb()                            # [x1, y1, x2, y2]
            bbox = [int(v) for v in ltrb]
            cx   = (bbox[0] + bbox[2]) // 2
            cy   = (bbox[1] + bbox[3]) // 2

            # assign friendly ID
            if tid not in tracker_to_person:
                person_counter += 1
                pid = f"P{person_counter}"
                tracker_to_person[tid] = pid
            else:
                pid = tracker_to_person[tid]

            # initialize record
            if pid not in track_data:
                track_data[pid] = {
                    "first_seen": timestamp,
                    "last_seen":  timestamp,
                    "timestamps": [],
                    "frames":     [],
                    "bboxes":     [],     # per-frame bboxes for playback overlay
                    "centers":    [],     # for heatmap
                    "thumbnail":  None,
                }

            entry = track_data[pid]
            entry["last_seen"] = timestamp
            entry["timestamps"].append(timestamp)
            entry["frames"].append(frame_idx)
            entry["bboxes"].append({"frame": frame_idx, "bbox": bbox,
                                    "timestamp": timestamp})
            entry["centers"].append([cx, cy])

            # save first clear thumbnail
            if pid not in saved_thumbnails:
                thumb_path = save_thumbnail(frame, bbox, pid, thumb_dir)
                entry["thumbnail"] = thumb_path
                saved_thumbnails.add(pid)

        frame_idx += 1

        if progress_callback and frame_idx % 30 == 0:
            pct = int(frame_idx / total_frames * 100)
            progress_callback(pct, f"Processed {frame_idx}/{total_frames} frames")

    cap.release()

    # ── generate heatmaps ─────────────────────
    if frame_shape:
        hm_paths = generate_heatmap(frame_shape, track_data, heatmap_dir)
        for pid, hm_path in hm_paths.items():
            track_data[pid]["heatmap"] = hm_path

    # ── clean output (remove internal "centers" from JSON) ──
    clean_data = {}
    for pid, d in track_data.items():
        clean_data[pid] = {
            "first_seen":  d["first_seen"],
            "last_seen":   d["last_seen"],
            "total_time":  round(d["last_seen"] - d["first_seen"], 2),
            "appearances": len(d["timestamps"]),
            "timestamps":  d["timestamps"],
            "frames":      d["frames"],
            "bboxes":      d["bboxes"],
            "thumbnail":   d.get("thumbnail"),
            "heatmap":     d.get("heatmap"),
        }

    # ── save JSON ─────────────────────────────
    json_path = out / "tracking_data.json"
    with open(json_path, "w") as f:
        json.dump(clean_data, f, indent=2)

    print(f"[Pipeline] Done. Tracked {len(clean_data)} people → {json_path}")
    if progress_callback:
        progress_callback(100, f"Complete — {len(clean_data)} people tracked")

    return clean_data
