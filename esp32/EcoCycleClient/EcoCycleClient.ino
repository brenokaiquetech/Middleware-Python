// FIRMWARE PRINCIPAL: recebe comandos do Python, controla o L9110S e posiciona o servo.
// Fluxo: handshake → autorização do operador → parada → pulso do servo → espera → retomada.
// O JSON e os tempos controlam a sequência; não há sensores confirmando posição ou rotação.
// Bibliotecas: WebSockets, ArduinoJson 7 e ESP32Servo.
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <math.h>
// Constantes geradas de config.py: não duplique aqui rede, GPIOs ou calibração.
#include "EcoCycleConfig.h"

// Objetos das bibliotecas: webSocket mantém a conexão e plateServo gera o PWM do servo posicional.
WebSocketsClient webSocket;
Servo plateServo;
// Sessões e IDs distinguem servidor atual, ciclo em execução e último ciclo já concluído.
String serverSession;
String activeCommand;
String activeSession;
String completedCommand;
String completedSession;
// Máquina de estados: livre → acomodação da parada → acomodação do recipiente → livre.
enum CyclePhase { IDLE, STOPPING_CONVEYOR, POSITIONING_CONTAINER };
CyclePhase phase = IDLE;
// Condições de liberação independentes: conexão, hardware, trava térmica e início pelo operador.
bool serverReady = false;
bool conveyorRunning = false;
bool servoReady = false;
bool thermalBlocked = true;  // Aguarde o estado térmico enviado pelo servidor.
bool thermalStateKnown = false;
bool triageEnabled = false;  // Só o clique em Iniciar triagem autoriza o motor.
// Instantes e durações usam millis(); subtração unsigned tolera o estouro do contador.
uint32_t phaseStarted = 0;
uint32_t stopDuration = 0;
uint32_t settleDuration = 0;
int targetPulseUs = 0;
uint32_t lastTelemetryAt = 0;

// Só permite transportar quando servo habilitado, PWM inicializado e esteira habilitada.
bool hardwareReady() {
  return SERVO_CALIBRATED && servoReady && CONVEYOR_ENABLED;
}

// Publica acionamento declarado e bloqueios; o Python usa essa telemetria na simulação térmica.
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

// Coloca as duas entradas do driver em LOW e informa ao servidor se houve mudança de estado.
void stopConveyor() {
  bool changed = conveyorRunning;
  if (CONVEYOR_ENABLED) {
    digitalWrite(CONVEYOR_PIN_IA, LOW);
    digitalWrite(CONVEYOR_PIN_IB, LOW);
  }
  conveyorRunning = false;
  if (changed) reportConveyorState();
}

// Religa uma única vez e somente se todas as permissões estiverem válidas e não houver ciclo ativo.
void startConveyor() {
  if (conveyorRunning || !hardwareReady() || !serverReady || thermalBlocked || !triageEnabled || phase != IDLE) return;
  digitalWrite(CONVEYOR_PIN_IA, CONVEYOR_FORWARD_IA_HIGH ? HIGH : LOW);
  digitalWrite(CONVEYOR_PIN_IB, CONVEYOR_FORWARD_IA_HIGH ? LOW : HIGH);
  conveyorRunning = true;
  reportConveyorState();
  Serial.printf("[%lu ms] Esteira ligada. Aguardando novo material.\n", (unsigned long)millis());
}

// ACK relaciona done/error ao comando e à sessão; done não comprova alinhamento físico.
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

// Valida a instrução, calcula o pulso de destino e inicia imediatamente a parada do motor.
void startSortCycle(JsonDocument& doc) {
  String command = doc["command_id"] | "";
  String session = doc["session_id"] | "";
  if (command.isEmpty() || session != serverSession) return;

  // Uma retransmissão do último comando concluído recebe ACK sem repetir parada ou giro.
  if (command == completedCommand && session == completedSession) {
    acknowledge(session, command, "done");
    return;
  }
  if (phase != IDLE && command == activeCommand && session == activeSession) return;

  // Ângulo é absoluto dentro do curso; os tempos chegam em milissegundos ou usam os padrões do header.
  float angle = doc["angle_deg"].as<float>();
  uint32_t stopMs = doc["stop_ms"] | DEFAULT_STOP_MS;
  uint32_t settleMs = doc["settle_ms"] | DEFAULT_SETTLE_MS;
  // Um comando inválido recebe error; não deve desfazer um ciclo válido já em andamento.
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
  // Interpolação linear: 0° usa SERVO_MIN_US e o fim do curso usa SERVO_MAX_US.
  targetPulseUs = lroundf(SERVO_MIN_US +
                         (angle / SERVO_TRAVEL_DEG) * (SERVO_MAX_US - SERVO_MIN_US));
  activeCommand = command;
  activeSession = session;
  stopDuration = stopMs;
  settleDuration = settleMs;
  // Guarda o relógio antes da telemetria para medir a acomodação desde a ordem de parada.
  phase = STOPPING_CONVEYOR;
  phaseStarted = millis();
  stopConveyor();
  const char* container = doc["container"] | "";
  const char* material = doc["material"] | "";
  Serial.printf("[%lu ms] Esteira parada. Recipiente %s | %s | %.1f graus | %d us | espera %lu ms\n",
                (unsigned long)phaseStarted, container, material, angle, targetPulseUs,
                (unsigned long)stopDuration);
}

// Callback da biblioteca: trata conexão, queda e cada mensagem JSON recebida.
void onWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    // Conectar à rede não autoriza o motor. A placa primeiro anuncia suporte ao protocolo 2.
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
    // Ao perder a conexão, remove a autorização e para o transporte; loop ainda pode concluir o servo.
    case WStype_DISCONNECTED:
      serverReady = false;
      triageEnabled = false;
      stopConveyor();
      Serial.println("WebSocket desconectado. Tentando reconectar...");
      break;
    // Mensagens de texto devem ser JSON válido; type escolhe a ação e session_id valida sua origem lógica.
    case WStype_TEXT: {
      JsonDocument doc;
      DeserializationError error = deserializeJson(doc, payload, length);
      if (error) {
        Serial.printf("JSON invalido: %s\n", error.c_str());
        return;
      }

      const char* messageType = doc["type"] | "";
      // hello estabelece a sessão e sincroniza as permissões iniciais antes de tentar ligar a esteira.
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
      // Início/pausa/conclusão alteram a autorização; startConveyor continua verificando os outros bloqueios.
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
      // O servidor arma/desarma a trava térmica. Resfriar sozinho não envia uma liberação automática.
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
      // Encaminha o ciclo ao validador; a função não executa esperas bloqueantes.
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

// Roda uma vez: configura pinos parados, PWM, Wi-Fi e o cliente WebSocket.
void setup() {
  Serial.begin(SERIAL_BAUD);
  if (CONVEYOR_ENABLED) {
    pinMode(CONVEYOR_PIN_IA, OUTPUT);
    pinMode(CONVEYOR_PIN_IB, OUTPUT);
  }
  stopConveyor();
  if (SERVO_CALIBRATED) {
    plateServo.setPeriodHertz(SERVO_FREQUENCY_HZ);
    // attached confirma a alocação do PWM, e não o movimento físico do eixo.
    plateServo.attach(SERVO_PIN, SERVO_MIN_US, SERVO_MAX_US);
    servoReady = plateServo.attached();
    Serial.printf("Servo GPIO %lu: PWM %s | curso %.1f graus | %lu Hz | %lu a %lu us\n",
                  SERVO_PIN, servoReady ? "ativo" : "FALHOU",
                  SERVO_TRAVEL_DEG, SERVO_FREQUENCY_HZ, SERVO_MIN_US, SERVO_MAX_US);
  } else {
    Serial.println("Servo desabilitado: calibre em config.py, gere a configuracao e reenvie o firmware.");
  }
  // A ESP32 entra como cliente da rede configurada; durante a conexão a esteira permanece parada.
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

  // IP, porta e rota apontam para o computador com app.py; onEvent recebe os eventos de comunicação.
  webSocket.begin(SERVER_HOST, SERVER_PORT, SERVER_PATH);
  webSocket.onEvent(onWebSocketEvent);
  webSocket.setReconnectInterval(WS_RECONNECT_MS);
}

// Executa continuamente: atende rede, avança a máquina de estados e publica telemetria periódica.
void loop() {
  // Precisa rodar frequentemente para receber bloqueios e manter a conexão durante os intervalos do ciclo.
  webSocket.loop();
  // Etapas sem delay: a conexao continua sendo atendida durante a parada.
  uint32_t elapsed = (uint32_t)(millis() - phaseStarted);
  // Após acomodar a parada, aplica o destino uma vez e começa a espera de posicionamento.
  if (phase == STOPPING_CONVEYOR && elapsed >= stopDuration) {
    plateServo.writeMicroseconds(targetPulseUs);
    phase = POSITIONING_CONTAINER;
    phaseStarted = millis();
    Serial.printf("[%lu ms] Servo recebeu %d us. Espera apos parada: %lu ms. Acomodacao: %lu ms.\n",
                  (unsigned long)millis(), targetPulseUs, (unsigned long)elapsed,
                  (unsigned long)settleDuration);
  // Depois da espera, libera o ciclo e tenta retomar respeitando pausa, calor e conexão.
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
  // Telemetria também é transmitida sem objetos na câmera, mantendo o estado atualizado no Python.
  if (serverReady && (uint32_t)(millis() - lastTelemetryAt) >= TELEMETRY_INTERVAL_MS) {
    reportConveyorState();
  }
}
