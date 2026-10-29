# PONTO DE ENTRADA: entrega as páginas, expõe a API HTTP e registra os WebSockets.
# A visão roda em segundo plano; abrir uma página não inicia a triagem automaticamente.
"""Servidor Flask e rotas da interface. Execute: python app.py."""
# Config precisa carregar primeiro: limita threads numéricas antes de a visão importar OpenCV/NumPy.
import config
import vision
from websocket_server import init_websocket
from flask import Flask, Response, jsonify, request, send_from_directory, redirect, url_for
import os
import threading
from sorting import sorter
from generate_esp32_config import write_esp32_configs
from temperature import temperature
from batch_weights import batch_weights, BatchConflict
from motion import simulated_motion
from triage import triage

# Uma única aplicação compartilha os controladores em memória entre HTTP, vídeo e WebSockets.
app = Flask(__name__, static_folder="static")


# Abre a escolha de lotes; a primeira tela não autoriza os motores.
@app.route("/")
def index():
    return send_from_directory("static", "lotes.html")


# Só entrega o painel quando o lote selecionado corresponde à URL.
@app.route('/dashboard')
def dashboard():
    selected = triage.snapshot()['loteId']
    if not selected or request.args.get('lote', selected) != selected:
        return redirect(url_for('index'))
    return send_from_directory('static', 'index.html')


# Copia a visão sob lock e reúne detecções, pesos, temperatura e operação em um JSON.
def detection_snapshot():
    """Mesmo retrato das detecções para HTTP e WebSocket."""
    # Copiar sob lock evita ler metade de uma atualização feita pela thread da câmera.
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
    batch = batch_weights.snapshot()
    return {
        "connected": connected,
        "background_ready": background_ready,
        "count": len(detections),
        "counts": counts,
        "detections": detections,
        "temperature": motor_state,
        "conveyor": simulated_motion(motor_state, batch),
        "batch": batch,
        "triagem": triage.snapshot(),
    }


# As duas rotas WebSocket usam o mesmo estado que a API HTTP; não há outro servidor de comandos.
init_websocket(app, detection_snapshot, sorter, temperature, triage)


# Retorna o catálogo local e as permissões de seleção; ainda não consulta backend externo.
@app.route('/api/lotes')
def available_lots():
    return jsonify({'lotes': triage.available_lots(), 'triagem': triage.snapshot(),
                    'fonte': 'demonstracao_local'})


# Valida o JSON, seleciona o lote e devolve a URL do dashboard sem ligar a esteira.
@app.route('/api/lotes/selecionar', methods=['POST'])
def select_lot():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('loteId'), str):
        return jsonify({'error': 'Informe loteId em um objeto JSON.'}), 400
    try:
        state = triage.select(data['loteId'])
    except BatchConflict as exc:
        return jsonify({'error': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404
    return jsonify({'triagem': state, 'url': url_for('dashboard', lote=state['loteId'])})


# Exige câmera e fundo prontos; o controlador confere lote, placa e trava térmica.
@app.route('/api/triagem/iniciar', methods=['POST'])
def start_triage():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Informe loteId em um objeto JSON.'}), 400
    with vision.lock:
        camera_ready = (vision.latest_frame is not None and vision.background_filter.ready
                        and not vision.background_reset_requested)
    if not camera_ready:
        return jsonify({'error': 'Aguarde a câmera e o registro do fundo antes de iniciar.'}), 409
    try:
        return jsonify({'triagem': triage.start(data.get('loteId'))})
    except BatchConflict as exc:
        return jsonify({'error': str(exc)}), 409


# Retira a autorização de transporte sem apagar o lote ou seu peso já processado.
@app.route('/api/triagem/pausar', methods=['POST'])
def pause_triage():
    return jsonify({'triagem': triage.pause()})


# Fornece ao navegador o mesmo estado que o canal WebSocket de monitoramento.
@app.route("/api/detections")
def api_detections():
    return jsonify(detection_snapshot())


# Atende o clique de liberação; HTTP 409 informa que ainda falta alguma condição.
@app.route("/api/conveyor/thermal/reset", methods=["POST"])
def release_thermal_block():
    try:
        temperature.release_thermal_block()
    except ValueError as exc:
        return jsonify({'error': str(exc), 'temperature': temperature.snapshot()}), 409
    return jsonify({'ok': True, 'temperature': temperature.snapshot()})


# Consulta ou cadastra um lote de simulação, preservando a validação de conflitos.
@app.route("/api/lote", methods=["GET", "POST"])
def api_batch():
    if request.method == "GET":
        return jsonify(batch_weights.snapshot())
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"erro": "Envie loteId e pesoTotalLoteGramas em um objeto JSON."}), 400
    if triage.snapshot()['enabled'] and data.get('loteId') != batch_weights.snapshot()['loteId']:
        return jsonify({'erro': 'Pause a triagem antes de cadastrar outro lote.'}), 409
    try:
        return jsonify(batch_weights.start_lot(data.get("loteId"), data.get("pesoTotalLoteGramas")))
    except BatchConflict as exc:
        return jsonify({"erro": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400


# Permite simular uma peça por JSON, sem precisar produzir uma imagem da câmera.
@app.route("/api/lote/pecas", methods=["POST"])
def api_batch_piece():
    # Entrada local para simular eventos sem câmera, ainda sem backend externo.
    try:
        result = batch_weights.account_piece(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify(result), 200 if result["sucesso"] else 409


# Agenda a recaptura na thread da câmera; HTTP 202 indica pedido aceito, não concluído.
@app.route("/api/camera/background", methods=["POST"])
def capture_background():
    vision.request_background_capture()
    return jsonify({"ok": True, "background_ready": False}), 202


# Recebe x/y/largura/altura normalizados de 0 a 1 e atualiza a área analisada sob lock.
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


# Transmite JPEGs sucessivos via HTTP multipart, formato exibido pelo elemento img da página.
@app.route("/video")
def video():
    return Response(
        vision.video_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# Executado apenas por python app.py: exporta a configuração, inicia a visão e abre o servidor.
if __name__ == "__main__":
    write_esp32_configs()
    os.makedirs(app.static_folder, exist_ok=True)
    thread = threading.Thread(target=vision.camera_frames, daemon=True)
    thread.start()
    print(f"EcoCycle: http://localhost:{config.PORT}")
    print(f"ESP32: ws://{config.SERVER_PUBLIC_HOST}:{config.PORT}{config.WS_PATH}")
    print(f"Separação: ws://{config.SERVER_PUBLIC_HOST}:{config.PORT}{config.SORT_WS_PATH}")
    print("Se não conectar, confira CAMERA_URL no arquivo config.py.")
    try:
        app.run(host=config.HOST, port=config.PORT, threaded=True, debug=False)
    # Ao encerrar o servidor, sinaliza às rotinas de captura e vídeo para terminarem.
    finally:
        vision.running = False
