// DIAGNÓSTICO ISOLADO: substitui temporariamente o firmware principal.
// Não conecta à rede nem usa visão; serve para separar defeito elétrico de problema de comunicação.
// Diagnóstico temporário: mantém a esteira parada e alterna três posições.
// A configuração é gerada pelo mesmo config.py do projeto principal.
#include <ESP32Servo.h>
#include <math.h>
#include "EcoCycleConfig.h"

Servo testServo;
// Frações do curso: para 180°, a sequência resulta em 90°, 60° e 120° sem testar os extremos.
const float positions[] = {0.5f, 1.0f / 3.0f, 2.0f / 3.0f};
unsigned positionIndex = 0;
uint32_t lastPositionAt = 0;
bool testReady = false;

// Converte a fração em pulso, registra no Serial e prepara a próxima posição do teste.
void applyTestPosition() {
  float fraction = positions[positionIndex];
  int pulse = lroundf(SERVO_MIN_US + fraction * (SERVO_MAX_US - SERVO_MIN_US));
  testServo.writeMicroseconds(pulse);
  Serial.printf("[%lu ms] GPIO %lu | %.1f graus | %d us\n",
                (unsigned long)millis(), SERVO_PIN, fraction * SERVO_TRAVEL_DEG, pulse);
  // O módulo 3 faz a sequência voltar ao início; não cria posições adicionais.
  positionIndex = (positionIndex + 1) % 3;
  lastPositionAt = millis();
}

// Inicializa o Serial, mantém o motor parado e só conecta o PWM se a calibração estiver habilitada.
void setup() {
  Serial.begin(SERIAL_BAUD);
  if (CONVEYOR_ENABLED) {
    pinMode(CONVEYOR_PIN_IA, OUTPUT);
    pinMode(CONVEYOR_PIN_IB, OUTPUT);
    digitalWrite(CONVEYOR_PIN_IA, LOW);
    digitalWrite(CONVEYOR_PIN_IB, LOW);
  }
  if (!SERVO_CALIBRATED) {
    Serial.println("Teste desabilitado: confira SERVO_CALIBRATED em config.py.");
    return;
  }
  testServo.setPeriodHertz(SERVO_FREQUENCY_HZ);
  testServo.attach(SERVO_PIN, SERVO_MIN_US, SERVO_MAX_US);
  // Falha ao alocar o PWM impede o teste; sucesso de PWM não confirma alimentação ou deslocamento.
  testReady = testServo.attached();
  if (!testReady) {
    Serial.println("FALHA: nao foi possivel inicializar o PWM do servo.");
    return;
  }
  Serial.println("Teste do servo sem camera ou Wi-Fi. Esteira parada.");
  applyTestPosition();
}

// Espera pelo relógio sem delay; troca a posição quando vence SERVO_TEST_STEP_MS.
void loop() {
  if (testReady && (uint32_t)(millis() - lastPositionAt) >= SERVO_TEST_STEP_MS) {
    applyTestPosition();
  }
}
