"""Captura da câmera, detecção, rastreamento e frames do vídeo."""
import config  # Deve carregar antes das bibliotecas numéricas.
import cv2
import numpy as np
import requests
import threading
import time
from sorting import sorter
from batch_weights import batch_weights

from config import (
    CAMERA_URL, FRAME_SIZE, MIN_CONTOUR_AREA, MIN_BOX_WIDTH,
    MIN_BOX_HEIGHT, TRACK_DISTANCE, TRACK_TIMEOUT,
)

COLOR_RANGES = {
    name: [(np.array(low), np.array(high)) for low, high in ranges]
    for name, ranges in config.COLOR_RANGES.items()
}

lock = threading.Lock()
latest_frame = None
latest_detections = []
next_id = 1
tracks = []
roi = dict(config.DEFAULT_ROI)
running = True


def detect_objects(frame):
    """Detect colored regions inside the normalized ROI."""
    global next_id, tracks

    height, width = frame.shape[:2]
    with lock:
        current_roi = dict(roi)

    x1 = max(0, int(current_roi["x"] * width))
    y1 = max(0, int(current_roi["y"] * height))
    x2 = min(width, int((current_roi["x"] + current_roi["w"]) * width))
    y2 = min(height, int((current_roi["y"] + current_roi["h"]) * height))

    if x2 <= x1 or y2 <= y1:
        return [], (x1, y1, x2, y2)

    crop = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    kernel = np.ones((3, 3), np.uint8)

    found = []
    for color_name, ranges in COLOR_RANGES.items():
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for low, high in ranges:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, low, high))

        # Reduce isolated noise while preserving most object edges.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < MIN_CONTOUR_AREA:
                continue

            bx, by, bw, bh = cv2.boundingRect(contour)
            if bw < MIN_BOX_WIDTH or bh < MIN_BOX_HEIGHT:
                continue

            # Ignore extremely thin noise-like contours.
            if max(bw / max(bh, 1), bh / max(bw, 1)) > 8:
                continue

            found.append({
                "x": x1 + bx,
                "y": y1 + by,
                "w": bw,
                "h": bh,
                "cx": x1 + bx + bw / 2,
                "cy": y1 + by + bh / 2,
                "color": color_name,
                "area": int(area),
            })

    # Basic centroid tracking. This is a lightweight tracker, not a guarantee
    # of unique identity when objects touch, cross, or leave/re-enter the ROI.
    now = time.time()
    old_tracks = [t for t in tracks if now - t["seen"] < TRACK_TIMEOUT]
    used_old_ids = set()

    for item in found:
        best = None
        best_dist = TRACK_DISTANCE
        for old in old_tracks:
            if old["id"] in used_old_ids:
                continue
            if old["color"] != item["color"]:
                continue
            dist = ((item["cx"] - old["cx"]) ** 2 +
                    (item["cy"] - old["cy"]) ** 2) ** 0.5
            if dist < best_dist:
                best = old
                best_dist = dist

        if best is not None:
            item["id"] = best["id"]
            used_old_ids.add(best["id"])
        else:
            item["id"] = next_id
            next_id += 1

        item["material"] = "Categoria estimada pela cor"

    new_tracks = []
    for item in found:
        new_tracks.append({
            "id": item["id"],
            "cx": item["cx"],
            "cy": item["cy"],
            "color": item["color"],
            "seen": now,
        })
    # Keep briefly unseen tracks for small frame-to-frame detection gaps.
    for old in old_tracks:
        if old["id"] not in {t["id"] for t in new_tracks}:
            new_tracks.append(old)
    tracks = new_tracks

    return found, (x1, y1, x2, y2)


def camera_frames():
    """Read JPEG frames from the phone's MJPEG stream and annotate them."""
    global latest_frame, latest_detections

    session = requests.Session()
    while running:
        try:
            with session.get(CAMERA_URL, stream=True,
                             timeout=(config.CAMERA_CONNECT_TIMEOUT, config.CAMERA_READ_TIMEOUT)) as response:
                response.raise_for_status()
                buffer = b""
                for chunk in response.iter_content(chunk_size=4096):
                    if not running:
                        break
                    if not chunk:
                        continue
                    buffer += chunk
                    while True:
                        start = buffer.find(b"\xff\xd8")
                        end = buffer.find(b"\xff\xd9", start + 2)
                        if start < 0 or end < 0:
                            if start > 0:
                                buffer = buffer[start:]
                            if len(buffer) > 2_000_000:
                                buffer = buffer[-100_000:]
                            break

                        jpg = buffer[start:end + 2]
                        buffer = buffer[end + 2:]
                        frame = cv2.imdecode(
                            np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR
                        )
                        if frame is None:
                            continue

                        # Processing resolution keeps CPU usage modest.
                        frame = cv2.resize(frame, FRAME_SIZE)
                        detections, bounds = detect_objects(frame)
                        x1, y1, x2, y2 = bounds

                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 235, 136), 2)

                        for item in detections:
                            x, y, w, h = item["x"], item["y"], item["w"], item["h"]
                            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 235, 136), 2)
                            label = f'ID {item["id"]} - {item["color"]}'
                            cv2.putText(
                                frame, label, (x, max(18, y - 7)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                                (0, 235, 136), 2, cv2.LINE_AA
                            )

                        with lock:
                            latest_frame = frame.copy()
                            latest_detections = [
                                {k: v for k, v in d.items()
                                 if k not in ("cx", "cy")}
                                for d in detections
                            ]
                        sorter.observe(detections)
                        batch_weights.observe(detections)
        except Exception as exc:
            print(f"[câmera] {exc}. Tentando reconectar em {config.CAMERA_RECONNECT_SECONDS} segundos...")
            time.sleep(config.CAMERA_RECONNECT_SECONDS)


def video_frames():
    while running:
        with lock:
            frame = None if latest_frame is None else latest_frame.copy()
        if frame is None:
            time.sleep(0.1)
            continue
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, config.VIDEO_JPEG_QUALITY])
        if not ok:
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" +
               encoded.tobytes() + b"\r\n")
        time.sleep(config.VIDEO_FRAME_INTERVAL)

