#pragma once
#include "HostArduino.h"
struct Servo {
  std::vector<int> pulses;
  void setPeriodHertz(unsigned) {}
  void attach(unsigned, unsigned, unsigned) {}
  bool attached() { return true; }
  void writeMicroseconds(int pulse) { pulses.push_back(pulse); }
};
