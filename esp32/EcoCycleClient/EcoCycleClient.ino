// Bibliotecas: WebSockets, ArduinoJson 7 e ESP32Servo.
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <math.h>
#include "EcoCycleConfig.h"

WebSocketsClient webSocket;
Servo plateServo;
String serverSession;
String activeCommand;
String activeSession;
String completedCommand;
String completedSession;
enum CyclePhase { IDLE, STOPPING_CONVEYOR, POSITIONING_CONTAINER };
CyclePhase phase = IDLE;
bool serverReady = false;
bool conveyorRunning = false;
uint32_t phaseStarted = 0;
uint32_t stopDuration = 0;
uint32_t settleDuration = 0;
int targetPulseUs = 0;
uint32_t lastTelemetryAt = 0;

bool hardwareReady() {
  return SERVO_CALIBRATED && CONVEYOR_ENABLED;
}

void reportConveyorState() {
  if (!serverReady) return;
  JsonDocument message;
  message["type"] = "conveyor_state";
  message["session_id"] = serverSession;
  message["running"] = conveyorRunning;
  String text;
  serializeJson(message, text);
  webSocket.sendTXT(text);
  lastTelemetryAt = millis();
}

void stopConveyor() {
  bool changed = conveyorRunning;
  if (CONVEYOR_ENABLED) {
    digitalWrite(CONVEYOR_PIN_IA, LOW);
    digitalWrite(CONVEYOR_PIN_IB, LOW);
  }
  conveyorRunning = false;
  if (changed) reportConveyorState();
}

void startConveyor() {
  if (conveyorRunning || !hardwareReady() || !serverReady || phase != IDLE) return;
  digitalWrite(CONVEYOR_PIN_IA, CONVEYOR_FORWARD_IA_HIGH ? HIGH : LOW);
  digitalWrite(CONVEYOR_PIN_IB, CONVEYOR_FORWARD_IA_HIGH ? LOW : HIGH);
  conveyorRunning = true;
  reportConveyorState();
  Serial.println("Esteira ligada. Aguardando novo material.");
}

void acknowledge(const String& session, const String& command, const char* status) {
  JsonDocument ack;
  ack["type"] = "ack";
  ack["session_id"] = session;
  ack["command_id"] = command;
  ack["status"] = status;
  ack["conveyor_running"] = conveyorRunning;
  String text;
  serializeJson(ack, text);
  webSocket.sendTXT(text);
}

void startSortCycle(JsonDocument& doc) {
  String command = doc["command_id"] | "";
  String session = doc["session_id"] | "";
  if (command.isEmpty() || session != serverSession) return;

  if (command == completedCommand && session == completedSession) {
    acknowledge(session, command, "done");
    return;
  }
  if (phase != IDLE && command == activeCommand && session == activeSession) return;

  float angle = doc["angle_deg"].as<float>();
  uint32_t stopMs = doc["stop_ms"] | DEFAULT_STOP_MS;
  uint32_t settleMs = doc["settle_ms"] | DEFAULT_SETTLE_MS;
  const char* reason = nullptr;
  if (!SERVO_CALIBRATED) reason = "servo desabilitado";
  else if (!CONVEYOR_ENABLED) reason = "esteira desabilitada";
  else if (!serverReady) reason = "servidor indisponivel";
  else if (phase != IDLE) reason = "ciclo em andamento";
  else if (doc["angle_deg"].isNull() || !isfinite(angle)
           || angle < 0 || angle > SERVO_TRAVEL_DEG) reason = "angulo fora do curso do servo";
  else if (settleMs > MAX_MOVEMENT_STAGE_MS || stopMs > MAX_MOVEMENT_STAGE_MS)
    reason = "tempo acima do limite";
  if (reason != nullptr) {
    // Rejeitar um comando nao deve parar o transporte nem interromper um
    // ciclo valido. A parada por desconexao continua sendo tratada separadamente.
    Serial.printf("Comando rejeitado: %s.\n", reason);
    acknowledge(session, command, "error");
    return;
  }

  // write(270) seria limitado a 180 pela ESP32Servo. Use pulsos calibrados.
  targetPulseUs = lroundf(SERVO_MIN_US +
                         (angle / SERVO_TRAVEL_DEG) * (SERVO_MAX_US - SERVO_MIN_US));
  activeCommand = command;
  activeSession = session;
  stopDuration = stopMs;
  settleDuration = settleMs;
  stopConveyor();
  phase = STOPPING_CONVEYOR;
  phaseStarted = millis();
  const char* container = doc["container"] | "";
  const char* material = doc["material"] | "";
  Serial.printf("Esteira parada. Recipiente %s | %s | %.1f graus | %d us\n",
                container, material, angle, targetPulseUs);
}

void onWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("WebSocket conectado.");
      break;
    case WStype_DISCONNECTED:
      serverReady = false;
      stopConveyor();
      Serial.println("WebSocket desconectado. Tentando reconectar...");
      break;
    case WStype_TEXT: {
      JsonDocument doc;
      DeserializationError error = deserializeJson(doc, payload, length);
      if (error) {
        Serial.printf("JSON invalido: %s\n", error.c_str());
        return;
      }

      const char* messageType = doc["type"] | "";
      if (strcmp(messageType, "hello") == 0) {
        serverSession = doc["session_id"] | "";
        serverReady = !serverSession.isEmpty();
        startConveyor();
        reportConveyorState();
      } else if (strcmp(messageType, "sort_cycle") == 0) {
        startSortCycle(doc);
      } else if (strcmp(messageType, "error") == 0) {
        serverReady = false;
        stopConveyor();
        Serial.println(doc["reason"].as<const char*>());
      }
      break;
    }
    default:
      break;
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  if (CONVEYOR_ENABLED) {
    pinMode(CONVEYOR_PIN_IA, OUTPUT);
    pinMode(CONVEYOR_PIN_IB, OUTPUT);
  }
  stopConveyor();
  if (SERVO_CALIBRATED) {
    plateServo.setPeriodHertz(SERVO_FREQUENCY_HZ);
    plateServo.attach(SERVO_PIN, SERVO_MIN_US, SERVO_MAX_US);
  } else {
    Serial.println("Servo desabilitado: calibre em config.py, gere a configuracao e reenvie o firmware.");
  }
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Conectando ao Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(WIFI_WAIT_MS);
    Serial.print(".");
  }
  Serial.println();
  Serial.println(WiFi.localIP());

  webSocket.begin(SERVER_HOST, SERVER_PORT, SERVER_PATH);
  webSocket.onEvent(onWebSocketEvent);
  webSocket.setReconnectInterval(WS_RECONNECT_MS);
}

void loop() {
  webSocket.loop();
  // Etapas sem delay: a conexao continua sendo atendida durante a parada.
  uint32_t elapsed = (uint32_t)(millis() - phaseStarted);
  if (phase == STOPPING_CONVEYOR && elapsed >= stopDuration) {
    plateServo.writeMicroseconds(targetPulseUs);
    phase = POSITIONING_CONTAINER;
    phaseStarted = millis();
    Serial.println("Posicionando recipiente com a esteira parada.");
  } else if (phase == POSITIONING_CONTAINER && elapsed >= settleDuration) {
    phase = IDLE;
    completedCommand = activeCommand;
    completedSession = activeSession;
    startConveyor();
    // Se estiver offline, mantem a esteira parada. Na reconexao, hello
    // retoma a esteira e a repeticao do comando recebe ack sem novo movimento.
    if (serverReady) acknowledge(completedSession, completedCommand, "done");
    Serial.println(conveyorRunning ? "Recipiente pronto. Esteira retomada." : "Recipiente pronto. Aguardando conexao.");
  }
  // O estado livre mantem a esteira ligada, mesmo sem imagens/deteccoes e
  // depois de uma rejeicao. startConveyor so escreve os pinos ao mudar de estado.
  if (phase == IDLE) startConveyor();
  if (serverReady && (uint32_t)(millis() - lastTelemetryAt) >= TELEMETRY_INTERVAL_MS) {
    reportConveyorState();
  }
}
