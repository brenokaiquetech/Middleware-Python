// DIAGNÓSTICO ISOLADO: substitui temporariamente o firmware principal.
// Não conecta à rede nem usa visão; serve para separar defeito elétrico de problema de comunicação.
// Diagnóstico temporário: mantém a esteira parada e movimenta os dois SG90.
// A configuração é gerada pelo mesmo config.py do projeto principal.
#include <ESP32Servo.h>
#include <math.h>
#include "EcoCycleConfig.h"

Servo testServo;
Servo topTestServo;
// Prato em 90°, 180° e 270°: ambos os eixos em 45°, 90° e 135°, sem testar os extremos.
const float positions[] = {0.25f, 0.5f, 0.75f};
unsigned positionIndex = 0;
uint32_t lastPositionAt = 0;
bool testReady = false;

// Converte a fração em pulso, registra no Serial e prepara a próxima posição do teste.
void applyTestPosition() {
  float fraction = positions[positionIndex];
  float baseFraction = SERVO_REVERSED ? 1.0f - fraction : fraction;
  float topFraction = SERVO_TOP_REVERSED ? 1.0f - fraction : fraction;
  int pulse = lroundf(SERVO_MIN_US + baseFraction * (SERVO_MAX_US - SERVO_MIN_US));
  int topPulse = lroundf(SERVO_TOP_MIN_US + topFraction * (SERVO_TOP_MAX_US - SERVO_TOP_MIN_US));
  testServo.writeMicroseconds(pulse);
  topTestServo.writeMicroseconds(topPulse);
  Serial.printf("[%lu ms] Prato %.1f graus | B baixo GPIO %lu: %.1f graus, %d us | A cima GPIO %lu: %.1f graus, %d us\n",
                (unsigned long)millis(), fraction * PLATE_TRAVEL_DEG,
                SERVO_PIN, fraction * SERVO_TRAVEL_DEG, pulse,
                SERVO_TOP_PIN, fraction * SERVO_TOP_TRAVEL_DEG, topPulse);
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
  topTestServo.setPeriodHertz(SERVO_FREQUENCY_HZ);
  topTestServo.attach(SERVO_TOP_PIN, SERVO_TOP_MIN_US, SERVO_TOP_MAX_US);
  // Falha ao alocar o PWM impede o teste; sucesso de PWM não confirma alimentação ou deslocamento.
  testReady = testServo.attached() && topTestServo.attached();
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
