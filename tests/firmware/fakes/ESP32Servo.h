// SERVO FALSO: registra pulsos enviados pelo sketch; não gera PWM nem representa movimento físico.
#pragma once
#include "HostArduino.h"
struct Servo {
  // A lista é um registro de teste; não é a fila de objetos da operação.
  std::vector<int> pulses;
  void setPeriodHertz(unsigned) {}
  void attach(unsigned, unsigned, unsigned) {}
  // O fake declara inicialização bem-sucedida para exercitar os ciclos de funcionamento.
  bool attached() { return true; }
  void writeMicroseconds(int pulse) { pulses.push_back(pulse); }
};
