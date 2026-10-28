"""Edite aqui as configurações do computador e da ESP32.

Ao executar app.py, as opções da placa são exportadas para EcoCycleConfig.h.
Também é possível gerar somente esse arquivo: python generate_esp32_config.py.
Após mudar opções da ESP32, recompile e reenvie o sketch pela Arduino IDE.
"""
import os

# Configure antes de importar OpenCV/NumPy para limitar os buffers do OpenBLAS.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

# REDE: valores que normalmente mudam ao instalar em outro local.
CAMERA_URL = "http://10.99.137.209:8080/video"
SERVER_PUBLIC_HOST = "192.168.43.37"  # IPv4 do computador na rede da ESP32.
HOST = "0.0.0.0"  # Interface em que o servidor escuta; não é o IP da ESP32.
PORT = 8000  # Usada pelo site e pelos WebSockets.
ESP32_WIFI_SSID = "Uaifai Gratis"
ESP32_WIFI_PASSWORD = "1122334455"

# ESP32 / SERVO POSICIONAL: calibre segundo o modelo e a montagem.
SERVO_CALIBRATED = True
SERVO_PIN = 18
SERVO_FREQUENCY_HZ = 50
SERVO_MIN_US = 500  # Exemplo; confirme o pulso mínimo do modelo.
SERVO_MAX_US = 2500  # Exemplo; confirme o pulso máximo do modelo.
SERVO_TRAVEL_DEG = 360.0  # Servo POSICIONAL 0–360°.
SERVO_TEST_STEP_MS = 2000  # Intervalo do sketch de diagnóstico do servo.

# ESTEIRA / L9110S: entradas IA e IB de um mesmo canal do driver.
# Confira os pinos da sua montagem antes de habilitar.
CONVEYOR_ENABLED = True
CONVEYOR_PIN_IA = 26
CONVEYOR_PIN_IB = 25  # Ligue fisicamente IB do mesmo canal do L9110S a este GPIO.
CONVEYOR_FORWARD_IA_HIGH = True  # False inverte o sentido de transporte.
CONVEYOR_ESTIMATED_SPEED_M_S = 0.10  # Referência visual enquanto ligada; não é medida por sensor.
SERVO_SIMULATED_FORCE_PER_KG_N = 2.0  # Modelo fictício: força equivalente por kg do lote.
CONVEYOR_SIMULATED_FORCE_REFERENCE_N = 2.0  # Nesta força, a velocidade simulada cai à metade.
ESP32_SERIAL_BAUD = 115200
ESP32_RECONNECT_MS = 5000
ESP32_WIFI_WAIT_MS = 500
ESP32_MAX_MOVEMENT_STAGE_MS = 10000
ESP32_TELEMETRY_INTERVAL_MS = 1000

# TEMPERATURA SIMULADA: não corresponde a um sensor ou modelo físico calibrado.
TEMP_AMBIENT_C = 25.0
TEMP_MAX_C = 70.0
TEMP_HEATING_C_PER_SECOND = 0.15
TEMP_COOLING_C_PER_SECOND = 0.10
TEMP_STATE_TIMEOUT_SECONDS = 3.0  # Sem telemetria, considerar parada na simulação.
TEMP_CRITICAL_C = 60.0  # Temperatura simulada que bloqueia a esteira.
TEMP_RELEASE_C = 50.0  # Liberação manual permitida somente nesta temperatura ou abaixo.

# PESO SIMULADO POR LOTE: faixas ilustrativas do documento, em gramas inteiras.
BATCH_WEIGHT_RANGES_G = {
    "PLASTICO": (100, 300),
    "METAL": (300, 700),
    "OUTRO_METAL": (200, 600),
    "REJEITO": (50, 250),
}
BATCH_MATERIAL_BY_COLOR = {
    "Laranja": "PLASTICO",
    "Verde-claro": "OUTRO_METAL",  # Alumínio na classificação atual.
    "Azul-claro": "METAL",
    "Roxo": "REJEITO",
}
BATCH_MATERIAL_LABELS = {
    "PLASTICO": "Plástico",
    "METAL": "Metal",
    "OUTRO_METAL": "Alumínio",
    "REJEITO": "Rejeito",
}

# WEBSOCKETS
WS_PATH = "/ws/detections"
WS_SEND_INTERVAL = 0.5  # Segundos entre atualizações para a ESP32.
WS_PING_INTERVAL = 25

SORT_WS_PATH = "/ws/sorter"

# SEPARAÇÃO: tempos e posições precisam de calibração na esteira.
SORT_CONFIRM_FRAMES = 3
SORT_ACK_TIMEOUT_SECONDS = 15
SORT_POLL_INTERVAL_SECONDS = 0.01  # Espera máxima entre consultas do comando atual.
SORT_STOP_MS = 200  # Intervalo entre mandar parar e movimentar o prato.
SORT_SETTLE_MS = 1500  # Aguarde o posicionamento; ajuste com a carga real.

# EDITE angle_deg DE CADA COR para alinhar os recipientes com a saída.
# Aceita valores decimais de 0 até SERVO_TRAVEL_DEG (360° atualmente).
# Os ângulos são enviados pelo servidor; reinicie o Python após alterá-los.
SORT_TARGETS = {
    "Laranja": {"container": "A", "material": "Plástico", "angle_deg": 0},
    "Verde-claro": {"container": "B", "material": "Alumínio", "angle_deg": 90},
    "Azul-claro": {"container": "C", "material": "Metal", "angle_deg": 180},
    "Roxo": {"container": "D", "material": "Rejeito", "angle_deg": 270},
}

# CÂMERA / VISÃO: parâmetros mantidos do processamento original.
CAMERA_CONNECT_TIMEOUT = 5
CAMERA_READ_TIMEOUT = 15
CAMERA_RECONNECT_SECONDS = 2
CAMERA_CHUNK_SIZE = 4096
CAMERA_MAX_FRAME_BYTES = 2_000_000
CAMERA_VALID_FRAME_TIMEOUT = 15  # Reconectar se houver dados, mas nenhum quadro decodificável.
CAMERA_MAX_PENDING_FRAME_AGE_SECONDS = 0.5  # Descarte quadro parado no processamento local.
VIDEO_JPEG_QUALITY = 80
VIDEO_FRAME_INTERVAL = 0.03
FRAME_SIZE = (640, 480)
DEFAULT_ROI = {"x": 0.15, "y": 0.15, "w": 0.70, "h": 0.70}

# Câmera fixa: mantenha a esteira vazia durante a captura inicial do fundo.
BACKGROUND_WARMUP_SECONDS = 2.0
BACKGROUND_MIN_FRAMES = 10  # Uma pausa do vídeo não basta para concluir a captura.
BACKGROUND_IGNORE_MARGIN_PX = 3  # Margem nas regiões coloridas do cenário inicial.
BACKGROUND_DIFF_THRESHOLD = 35  # Diferença mínima em um canal BGR (0–255).
BACKGROUND_MIN_CHANGED_RATIO = 0.60  # Fração do contorno diferente do fundo.

# Limites HSV: ajuste conforme a iluminação e os objetos reais.
COLOR_RANGES = {
    "Laranja": [((8, 90, 70), (24, 255, 255))],
    "Verde-claro": [((35, 45, 100), (85, 255, 255))],
    "Azul-claro": [((85, 35, 100), (110, 255, 255))],
    "Roxo": [((125, 40, 45), (165, 255, 255))],
}

MIN_CONTOUR_AREA = 180
MIN_BOX_WIDTH = 8
MIN_BOX_HEIGHT = 8
TRACK_DISTANCE = 45
TRACK_TIMEOUT = 1.5
