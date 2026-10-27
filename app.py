"""Servidor Flask e rotas da interface. Execute: python app.py."""
import config
import vision
from websocket_server import init_websocket
from flask import Flask, Response, jsonify, request, send_from_directory
import os
import threading
from sorting import sorter
from generate_esp32_config import write_esp32_config
from temperature import temperature
from batch_weights import batch_weights, BatchConflict

app = Flask(__name__, static_folder="static")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


def detection_snapshot():
    """Mesmo retrato das detecções para HTTP e WebSocket."""
    with vision.lock:
        detections = [dict(item) for item in vision.latest_detections]
        connected = vision.latest_frame is not None
        background_ready = vision.background_filter.ready and not vision.background_reset_requested
    for item in detections:
        target = config.SORT_TARGETS.get(item["color"])
        if target:
            item["material"] = target["material"]
            item["container"] = target["container"]
    counts = {name: 0 for name in config.COLOR_RANGES}
    for item in detections:
        counts[item["color"]] += 1
    motor_state = temperature.snapshot()
    return {
        "connected": connected,
        "background_ready": background_ready,
        "count": len(detections),
        "counts": counts,
        "detections": detections,
        "temperature": motor_state,
        "conveyor": {
            "running": motor_state["conveyor_running"],
            "state_known": motor_state["state_known"],
            "speed_m_s": (config.CONVEYOR_ESTIMATED_SPEED_M_S
                          if motor_state["conveyor_running"] else 0.0)
            if motor_state["state_known"] else None,
            "speed_estimated": True,
        },
        "batch": batch_weights.snapshot(),
    }


init_websocket(app, detection_snapshot, sorter, temperature)


@app.route("/api/detections")
def api_detections():
    return jsonify(detection_snapshot())


@app.route("/api/lote", methods=["GET", "POST"])
def api_batch():
    if request.method == "GET":
        return jsonify(batch_weights.snapshot())
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"erro": "Envie loteId e pesoTotalLoteGramas em um objeto JSON."}), 400
    try:
        return jsonify(batch_weights.start_lot(data.get("loteId"), data.get("pesoTotalLoteGramas")))
    except BatchConflict as exc:
        return jsonify({"erro": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400


@app.route("/api/lote/pecas", methods=["POST"])
def api_batch_piece():
    # Entrada local para simular eventos sem câmera, ainda sem backend externo.
    try:
        result = batch_weights.account_piece(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify(result), 200 if result["sucesso"] else 409


@app.route("/api/camera/background", methods=["POST"])
def capture_background():
    vision.request_background_capture()
    return jsonify({"ok": True, "background_ready": False}), 202


@app.route("/api/roi", methods=["POST"])
def update_roi():
    data = request.get_json(silent=True) or {}
    try:
        x = min(max(float(data["x"]), 0), 1)
        y = min(max(float(data["y"]), 0), 1)
        w = min(max(float(data["w"]), 0.05), 1 - x)
        h = min(max(float(data["h"]), 0.05), 1 - y)
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "ROI inválida"}), 400

    with vision.lock:
        vision.roi = {"x": x, "y": y, "w": w, "h": h}
    return jsonify({"ok": True})


@app.route("/video")
def video():
    return Response(
        vision.video_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


if __name__ == "__main__":
    write_esp32_config()
    os.makedirs(app.static_folder, exist_ok=True)
    thread = threading.Thread(target=vision.camera_frames, daemon=True)
    thread.start()
    print(f"EcoCycle: http://localhost:{config.PORT}")
    print(f"ESP32: ws://{config.SERVER_PUBLIC_HOST}:{config.PORT}{config.WS_PATH}")
    print(f"Separação: ws://{config.SERVER_PUBLIC_HOST}:{config.PORT}{config.SORT_WS_PATH}")
    print("Se não conectar, confira CAMERA_URL no arquivo config.py.")
    try:
        app.run(host=config.HOST, port=config.PORT, threaded=True, debug=False)
    finally:
        vision.running = False
