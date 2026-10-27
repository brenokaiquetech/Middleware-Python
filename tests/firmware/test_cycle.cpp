// Compilar com C++17, fakes/ e a biblioteca ArduinoJson 7 nos includes.
// Inclui o firmware de produção; somente os periféricos e o relógio são falsos.
#include <cassert>
#include <iostream>
#include "../../esp32/EcoCycleClient/EcoCycleClient.ino"

void receive(const std::string& text) {
  onWebSocketEvent(WStype_TEXT,
                  reinterpret_cast<uint8_t*>(const_cast<char*>(text.data())), text.size());
}

void hello() { receive(R"({"type":"hello","session_id":"test"})"); }

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

void advance(uint32_t elapsed) { fakeNow += elapsed; loop(); }

void assertMotor(bool running) {
  assert(conveyorRunning == running);
  assert(pinStates[CONVEYOR_PIN_IA] == (running && CONVEYOR_FORWARD_IA_HIGH ? HIGH : LOW));
  assert(pinStates[CONVEYOR_PIN_IB] == (running && !CONVEYOR_FORWARD_IA_HIGH ? HIGH : LOW));
}

void assertAck(const char* id, const char* status) {
  JsonDocument message;
  assert(!deserializeJson(message, webSocket.sent.back()));
  assert(message["type"] == "ack");
  assert(message["command_id"] == id);
  assert(message["status"] == status);
  assert(message["conveyor_running"].as<bool>() == conveyorRunning);
}

int main() {
  assert(SERVO_CALIBRATED && CONVEYOR_ENABLED);
  setup();
  assertMotor(false);
  advance(500);
  assertMotor(false);
  hello();
  assertMotor(true);
  auto writes = gpioWrites;
  for (int i = 0; i < 20; ++i) advance(1000);
  assertMotor(true);  // Nenhum objeto/comando é necessário para manter a esteira.
  assert(gpioWrites == writes);
  assert(plateServo.pulses.empty());
  std::cout << "PASS: partida e transporte continuo sem deteccoes\n";

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

  auto moves = plateServo.pulses.size();
  cycle("first", SERVO_TRAVEL_DEG);
  assertMotor(true);
  assert(plateServo.pulses.size() == moves);
  assertAck("first", "done");
  std::cout << "PASS: comando repetido nao para a esteira nem move o servo\n";

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
}
