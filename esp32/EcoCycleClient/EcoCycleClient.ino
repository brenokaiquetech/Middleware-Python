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
bool servoReady = false;
bool thermalBlocked = true;  // Aguarde o estado térmico enviado pelo servidor.
bool thermalStateKnown = false;
bool triageEnabled = false;  // Só o clique em Iniciar triagem autoriza o motor.
uint32_t phaseStarted = 0;
uint32_t stopDuration = 0;
uint32_t settleDuration = 0;
int targetPulseUs = 0;
uint32_t lastTelemetryAt = 0;

bool hardwareReady() {
  return SERVO_CALIBRATED && servoReady && CONVEYOR_ENABLED;
}

void reportConveyorState() {
  if (!serverReady) return;
  JsonDocument message;
  message["type"] = "conveyor_state";
  message["session_id"] = serverSession;
  message["running"] = conveyorRunning;
  message["thermal_blocked"] = thermalBlocked;
  message["triage_enabled"] = triageEnabled;
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
  if (conveyorRunning || !hardwareReady() || !serverReady || thermalBlocked || !triageEnabled || phase != IDLE) return;
  digitalWrite(CONVEYOR_PIN_IA, CONVEYOR_FORWARD_IA_HIGH ? HIGH : LOW);
  digitalWrite(CONVEYOR_PIN_IB, CONVEYOR_FORWARD_IA_HIGH ? LOW : HIGH);
  conveyorRunning = true;
  reportConveyorState();
  Serial.printf("[%lu ms] Esteira ligada. Aguardando novo material.\n", (unsigned long)millis());
}

void acknowledge(const String& session, const String& command, const char* status) {
  JsonDocument ack;
  ack["type"] = "ack";
  ack["session_id"] = session;
  ack["command_id"] = command;
  ack["status"] = status;
  ack["conveyor_running"] = conveyorRunning;
  ack["thermal_blocked"] = thermalBlocked;
  ack["triage_enabled"] = triageEnabled;
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
  else if (!servoReady) reason = "PWM do servo nao inicializado";
  else if (!CONVEYOR_ENABLED) reason = "esteira desabilitada";
  else if (!serverReady) reason = "servidor indisponivel";
  else if (thermalBlocked) reason = "bloqueio por temperatura critica";
  else if (!triageEnabled) reason = "triagem nao iniciada pelo operador";
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

  // Converte o ângulo dentro do curso configurado em pulso para o servo posicional.
  // Converta o ângulo recebido em pulso calibrado e use writeMicroseconds().
  targetPulseUs = lroundf(SERVO_MIN_US +
                         (angle / SERVO_TRAVEL_DEG) * (SERVO_MAX_US - SERVO_MIN_US));
  activeCommand = command;
  activeSession = session;
  stopDuration = stopMs;
  settleDuration = settleMs;
  phase = STOPPING_CONVEYOR;
  phaseStarted = millis();
  stopConveyor();
  const char* container = doc["container"] | "";
  const char* material = doc["material"] | "";
  Serial.printf("[%lu ms] Esteira parada. Recipiente %s | %s | %.1f graus | %d us | espera %lu ms\n",
                (unsigned long)phaseStarted, container, material, angle, targetPulseUs,
                (unsigned long)stopDuration);
}

void onWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED: {
      serverReady = false;
      triageEnabled = false;
      stopConveyor();
      Serial.println("WebSocket conectado.");
      JsonDocument client;
      client["type"] = "client_hello";
      client["protocol"] = 2;
      client["operator_start"] = true;
      String text;
      serializeJson(client, text);
      webSocket.sendTXT(text);
      break;
    }
    case WStype_DISCONNECTED:
      serverReady = false;
      triageEnabled = false;
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
        bool serverBlocked = !doc["thermal_blocked"].is<bool>() || doc["thermal_blocked"].as<bool>();
        // Um hello de reconexao nao substitui a liberacao manual explicita.
        thermalBlocked = thermalStateKnown ? thermalBlocked || serverBlocked : serverBlocked;
        thermalStateKnown = true;
        triageEnabled = doc["triage_enabled"].is<bool>() && doc["triage_enabled"].as<bool>();
        if (thermalBlocked || !triageEnabled) stopConveyor();
        startConveyor();
        reportConveyorState();
        if (!triageEnabled) Serial.println("Aguardando selecao do lote e Iniciar triagem no painel.");
      } else if (strcmp(messageType, "triage_control") == 0) {
        String session = doc["session_id"] | "";
        if (!serverReady || session != serverSession || !doc["enabled"].is<bool>()) return;
        triageEnabled = doc["enabled"].as<bool>();
        if (triageEnabled) {
          startConveyor();
          Serial.println("Triagem autorizada pelo operador.");
        } else {
          stopConveyor();
          Serial.println("Triagem pausada ou lote concluido. Esteira parada.");
        }
        reportConveyorState();
      } else if (strcmp(messageType, "thermal_control") == 0) {
        String session = doc["session_id"] | "";
        if (!serverReady || session != serverSession || !doc["blocked"].is<bool>()) return;
        thermalBlocked = doc["blocked"].as<bool>();
        if (thermalBlocked) {
          stopConveyor();
          Serial.println("Parada termica: aguarde resfriamento e liberacao manual no painel.");
        } else {
          startConveyor();
          Serial.println("Bloqueio termico liberado pelo operador.");
        }
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
    servoReady = plateServo.attached();
    Serial.printf("Servo GPIO %lu: PWM %s | curso %.1f graus | %lu Hz | %lu a %lu us\n",
                  SERVO_PIN, servoReady ? "ativo" : "FALHOU",
                  SERVO_TRAVEL_DEG, SERVO_FREQUENCY_HZ, SERVO_MIN_US, SERVO_MAX_US);
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
    Serial.printf("[%lu ms] Servo recebeu %d us. Espera apos parada: %lu ms. Acomodacao: %lu ms.\n",
                  (unsigned long)millis(), targetPulseUs, (unsigned long)elapsed,
                  (unsigned long)settleDuration);
  } else if (phase == POSITIONING_CONTAINER && elapsed >= settleDuration) {
    phase = IDLE;
    completedCommand = activeCommand;
    completedSession = activeSession;
    startConveyor();
    // Se estiver offline, mantem a esteira parada. Na reconexao, hello
    // retoma a esteira e a repeticao do comando recebe ack sem novo movimento.
    if (serverReady) acknowledge(completedSession, completedCommand, "done");
    Serial.println(!triageEnabled ? "Recipiente pronto. Aguardando Iniciar triagem."
                   : thermalBlocked ? "Recipiente pronto. Esteira bloqueada por temperatura."
                   : conveyorRunning ? "Recipiente pronto. Esteira retomada."
                   : "Recipiente pronto. Aguardando conexao.");
  }
  // O estado livre mantem a esteira ligada, mesmo sem imagens/deteccoes e
  // depois de uma rejeicao. startConveyor so escreve os pinos ao mudar de estado.
  if (phase == IDLE) startConveyor();
  if (serverReady && (uint32_t)(millis() - lastTelemetryAt) >= TELEMETRY_INTERVAL_MS) {
    reportConveyorState();
  }
}
