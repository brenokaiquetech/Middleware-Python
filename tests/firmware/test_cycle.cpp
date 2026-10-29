// TESTE DO FIRMWARE REAL EM C++: inclui o .ino e troca apenas periféricos/relógio por fakes.
// As asserções verificam pinos, pulsos, estados e JSON; não simulam a mecânica ou a eletricidade.
// Compilar com C++17, fakes/ e a biblioteca ArduinoJson 7 nos includes.
// Inclui o firmware de produção; somente os periféricos e o relógio são falsos.
#include <cassert>
#include <iostream>
#include "../../esp32/EcoCycleClient/EcoCycleClient.ino"

// Entrega um JSON diretamente ao mesmo callback usado pelo WebSocket no hardware.
void receive(const std::string& text) {
  onWebSocketEvent(WStype_TEXT,
                  reinterpret_cast<uint8_t*>(const_cast<char*>(text.data())), text.size());
}

// Simula a mensagem inicial do servidor com autorização configurável da triagem.
void hello(bool enabled = true) {
  receive(enabled
    ? R"({"type":"hello","session_id":"test","thermal_blocked":false,"triage_enabled":true})"
    : R"({"type":"hello","session_id":"test","thermal_blocked":false,"triage_enabled":false})");
}

// Monta um sort_cycle com identidade, ângulo e intervalos usados pelos cenários.
void cycle(const char* id, float angle = 90) {
  JsonDocument message;
  message["type"] = "sort_cycle";
  message["session_id"] = "test";
  message["command_id"] = id;
  message["angle_deg"] = angle;
  message["stop_ms"] = 200;
  message["settle_ms"] = 1500;
  std::string text;
  serializeJson(message, text);
  receive(text);
}

// Avança o relógio falso e executa loop, dispensando espera real de segundos.
void advance(uint32_t elapsed) { fakeNow += elapsed; loop(); }

// Confere tanto a variável de software quanto o nível aplicado a cada entrada do L9110S.
void assertMotor(bool running) {
  assert(conveyorRunning == running);
  assert(pinStates[CONVEYOR_PIN_IA] == (running && CONVEYOR_FORWARD_IA_HIGH ? HIGH : LOW));
  assert(pinStates[CONVEYOR_PIN_IB] == (running && !CONVEYOR_FORWARD_IA_HIGH ? HIGH : LOW));
}

// Decodifica a última mensagem enviada e compara ID, resultado e estado do motor.
void assertAck(const char* id, const char* status) {
  JsonDocument message;
  assert(!deserializeJson(message, webSocket.sent.back()));
  assert(message["type"] == "ack");
  assert(message["command_id"] == id);
  assert(message["status"] == status);
  assert(message["conveyor_running"].as<bool>() == conveyorRunning);
}

// Executa cenários sucessivos sobre o mesmo firmware: partida, ciclo, duplicação e bloqueios.
int main() {
  assert(SERVO_CALIBRATED && CONVEYOR_ENABLED);
  setup();
  assertMotor(false);
  advance(500);
  assertMotor(false);
  hello(false);
  advance(1000);
  assertMotor(false);
  cycle("before-start");
  assertAck("before-start", "error");
  assertMotor(false);
  receive(R"({"type":"triage_control","session_id":"test","enabled":true})");
  assertMotor(true);
  auto writes = gpioWrites;
  for (int i = 0; i < 20; ++i) advance(1000);
  assertMotor(true);  // Nenhum objeto/comando é necessário para manter a esteira.
  assert(gpioWrites == writes);
  assert(plateServo.pulses.empty());
  std::cout << "PASS: partida e transporte continuo sem deteccoes\n";

  // O primeiro ciclo usa o fim do curso: o pulso esperado deve ser exatamente SERVO_MAX_US.
  cycle("first", SERVO_TRAVEL_DEG);
  assertMotor(false);
  advance(199);
  assert(plateServo.pulses.empty());
  advance(1);
  assertMotor(false);
  assert(plateServo.pulses.back() == static_cast<int>(SERVO_MAX_US));
  advance(1499);
  assertMotor(false);
  advance(1);
  assertMotor(true);
  assertAck("first", "done");
  advance(10000);
  assertMotor(true);
  std::cout << "PASS: parada de 200 ms, servo, espera de 1500 ms e retomada\n";

  // A quantidade de pulsos permite descobrir se uma mensagem repetida movimentou o servo novamente.
  auto moves = plateServo.pulses.size();
  cycle("first", SERVO_TRAVEL_DEG);
  assertMotor(true);
  assert(plateServo.pulses.size() == moves);
  assertAck("first", "done");
  std::cout << "PASS: comando repetido nao para a esteira nem move o servo\n";

  cycle("upper-half", SERVO_TRAVEL_DEG * .75f);
  advance(200);
  assertMotor(false);
  assert(plateServo.pulses.back() > static_cast<int>((SERVO_MIN_US + SERVO_MAX_US) / 2));
  assert(plateServo.pulses.back() < static_cast<int>(SERVO_MAX_US));
  advance(1500);
  assertMotor(true);
  assertAck("upper-half", "done");
  std::cout << "PASS: posicao em 75% do curso usa a metade superior dos pulsos\n";

  // Um ângulo além do curso precisa ser rejeitado sem congelar o transporte.
  cycle("invalid", SERVO_TRAVEL_DEG + 90);
  assertMotor(true);
  assert(phase == IDLE);
  assertAck("invalid", "error");
  advance(5000);
  assertMotor(true);
  std::cout << "PASS: angulo invalido nao trava o transporte\n";

  stopConveyor();
  assertMotor(false);
  loop();
  assertMotor(true);
  std::cout << "PASS: estado livre retoma sem aguardar outro material\n";

  cycle("active");
  advance(200);
  cycle("busy");
  assertAck("busy", "error");
  assertMotor(false);
  assert(phase == POSITIONING_CONTAINER);
  advance(1500);
  assertMotor(true);
  assertAck("active", "done");
  std::cout << "PASS: rejeicao durante ciclo preserva o posicionamento ativo\n";

  // A desconexão durante um ciclo mantém o transporte parado; a reconexão não repete o movimento.
  cycle("offline");
  onWebSocketEvent(WStype_DISCONNECTED, nullptr, 0);
  advance(200);
  advance(1500);
  assert(phase == IDLE);
  advance(10000);
  assertMotor(false);
  hello();
  assertMotor(true);
  moves = plateServo.pulses.size();
  cycle("offline");
  assert(plateServo.pulses.size() == moves);
  assertAck("offline", "done");
  std::cout << "PASS: desconexao para; reconexao retoma sem repetir movimento\n";

  // Força o relógio a atravessar o limite de uint32_t para validar a temporização por diferença.
  fakeNow = UINT32_MAX - 100;
  cycle("wrap");
  advance(199);
  assert(phase == STOPPING_CONVEYOR);
  advance(1);
  assert(phase == POSITIONING_CONTAINER);
  advance(1500);
  assertMotor(true);
  assertAck("wrap", "done");
  std::cout << "PASS: temporizacao funciona no estouro do millis\n";

  receive(R"({"type":"thermal_control","session_id":"test","blocked":true})");
  assertMotor(false);
  advance(10000);
  assertMotor(false);  // O estado IDLE nao contorna o bloqueio termico.
  cycle("hot");
  assertAck("hot", "error");
  assertMotor(false);
  receive(R"({"type":"hello","session_id":"test","thermal_blocked":true})");
  assertMotor(false);
  hello();  // Mesmo um novo servidor frio nao libera o bloqueio local.
  assertMotor(false);
  receive(R"({"type":"thermal_control","session_id":"wrong","blocked":false})");
  assertMotor(false);
  receive(R"({"type":"thermal_control","session_id":"test","blocked":false})");
  assertMotor(true);
  std::cout << "PASS: bloqueio termico persiste ate liberacao explicita da sessao\n";

  // A conclusão do posicionamento não deve contornar uma trava térmica aplicada durante o ciclo.
  cycle("heat-in-cycle");
  receive(R"({"type":"thermal_control","session_id":"test","blocked":true})");
  advance(200);
  advance(1500);
  assertAck("heat-in-cycle", "done");
  assertMotor(false);
  advance(10000);
  assertMotor(false);
  receive(R"({"type":"thermal_control","session_id":"test","blocked":false})");
  assertMotor(true);
  std::cout << "PASS: fim do ciclo nao religa durante bloqueio termico\n";

  // Pausa do operador permanece válida após o ciclo e após uma liberação térmica.
  cycle("pause-in-cycle");
  receive(R"({"type":"triage_control","session_id":"test","enabled":false})");
  advance(200);
  advance(1500);
  assertAck("pause-in-cycle", "done");
  advance(10000);
  assertMotor(false);
  receive(R"({"type":"thermal_control","session_id":"test","blocked":true})");
  receive(R"({"type":"thermal_control","session_id":"test","blocked":false})");
  assertMotor(false);
  receive(R"({"type":"triage_control","session_id":"wrong","enabled":true})");
  assertMotor(false);
  receive(R"({"type":"triage_control","session_id":"test","enabled":true})");
  assertMotor(true);
  std::cout << "PASS: inicio explicito e pausa persistem no fim do ciclo e na liberacao termica\n";
}
