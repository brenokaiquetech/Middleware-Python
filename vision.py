"""Captura da câmera, detecção, rastreamento e frames do vídeo."""
import config  # Deve carregar antes das bibliotecas numéricas.
import cv2
import numpy as np
import requests
import threading
import time
from sorting import sorter
from batch_weights import batch_weights
from mjpeg import JPEGStreamParser
from background import BackgroundFilter
from camera_buffer import LatestCameraFrame

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
background_filter = BackgroundFilter()
background_reset_requested = False


def request_background_capture():
    """A thread da câmera troca o fundo no próximo quadro, antes da detecção."""
    global background_reset_requested, latest_detections
    with lock:
        background_reset_requested = True
        latest_detections = []


def detect_objects(frame):
    """Detect colored regions inside the normalized ROI."""
    global next_id, tracks, background_filter, background_reset_requested

    height, width = frame.shape[:2]
    with lock:
        current_roi = dict(roi)
        if background_reset_requested:
            background_filter = BackgroundFilter()
            background_reset_requested = False
            tracks = []  # Preserve next_id para não reutilizar IDs já tratados.

    x1 = max(0, int(current_roi["x"] * width))
    y1 = max(0, int(current_roi["y"] * height))
    x2 = min(width, int((current_roi["x"] + current_roi["w"]) * width))
    y2 = min(height, int((current_roi["y"] + current_roi["h"]) * height))

    if x2 <= x1 or y2 <= y1:
        return [], (x1, y1, x2, y2)

    foreground = background_filter.foreground_mask(frame)
    if foreground is None:
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

            # Preserve o contorno HSV original, mas aceite apenas regiões que
            # mudaram desde o cenário vazio. Ruído nas bordas não vira peça.
            contour_mask = np.zeros((bh, bw), dtype=np.uint8)
            cv2.drawContours(contour_mask, [contour], -1, 255, cv2.FILLED,
                             offset=(-bx, -by))
            changed = foreground[y1 + by:y1 + by + bh, x1 + bx:x1 + bx + bw]
            changed_pixels = cv2.countNonZero(cv2.bitwise_and(changed, contour_mask))
            if changed_pixels / cv2.countNonZero(contour_mask) < config.BACKGROUND_MIN_CHANGED_RATIO:
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


def read_camera_images(response):
    """Descarte quadros inválidos e retome o próximo JPEG completo do fluxo."""
    parser = JPEGStreamParser(config.CAMERA_MAX_FRAME_BYTES)
    last_valid = time.monotonic()
    for chunk in response.iter_content(chunk_size=config.CAMERA_CHUNK_SIZE):
        if not running:
            return
        for jpg in parser.feed(chunk):
            try:
                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
            except cv2.error:
                continue
            if frame is None or not frame.size:
                continue
            last_valid = time.monotonic()
            yield frame
        if time.monotonic() - last_valid > config.CAMERA_VALID_FRAME_TIMEOUT:
            raise ValueError('Fluxo da câmera sem quadros JPEG decodificáveis')


def capture_camera(buffer):
    """Drene o vídeo continuamente, mesmo durante a análise de outro quadro."""
    global latest_frame, latest_detections
    session = requests.Session()
    while running:
        try:
            with session.get(CAMERA_URL, stream=True,
                             timeout=(config.CAMERA_CONNECT_TIMEOUT, config.CAMERA_READ_TIMEOUT)) as response:
                response.raise_for_status()
                for frame in read_camera_images(response):
                    buffer.publish(frame)
                if running:
                    raise ValueError('Fluxo da câmera encerrado')
        except Exception as exc:
            buffer.clear()
            with lock:
                latest_frame = None
                latest_detections = []
                sorter.observe([])
                batch_weights.observe([])
            print(f"[câmera] {exc}. Tentando reconectar em {config.CAMERA_RECONNECT_SECONDS} segundos...")
            time.sleep(config.CAMERA_RECONNECT_SECONDS)


def process_camera_frame(frame):
    """Crie o comando antes de desenhar as caixas e atualizar o vídeo."""
    global latest_frame, latest_detections
    frame = cv2.resize(frame, FRAME_SIZE)
    detections, bounds = detect_objects(frame)
    with lock:
        if background_reset_requested:
            detections = []
        sorter.observe(detections)
        batch_weights.observe(detections)

    x1, y1, x2, y2 = bounds
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 235, 136), 2)
    for item in detections:
        x, y, w, h = item['x'], item['y'], item['w'], item['h']
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 235, 136), 2)
        cv2.putText(frame, f'ID {item["id"]} - {item["color"]}',
                    (x, max(18, y - 7)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 235, 136), 2, cv2.LINE_AA)
    with lock:
        latest_frame = frame.copy()
        latest_detections = [] if background_reset_requested else [
            {k: v for k, v in item.items() if k not in ('cx', 'cy')}
            for item in detections
        ]


def camera_frames():
    """Analise o quadro mais recente, sem acumular imagens para processar."""
    buffer = LatestCameraFrame()
    threading.Thread(target=capture_camera, args=(buffer,), daemon=True).start()
    while running:
        packet = buffer.take(timeout=0.1)
        if packet is None:
            continue
        frame, received_at = packet
        if time.monotonic() - received_at > config.CAMERA_MAX_PENDING_FRAME_AGE_SECONDS:
            continue
        try:
            process_camera_frame(frame)
        except Exception as exc:
            print(f'[visão] Quadro descartado: {exc}')


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

