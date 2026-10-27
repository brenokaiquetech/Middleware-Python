#pragma once
#include "HostArduino.h"
struct Servo {
  std::vector<int> pulses;
  void setPeriodHertz(unsigned) {}
  void attach(unsigned, unsigned, unsigned) {}
  void writeMicroseconds(int pulse) { pulses.push_back(pulse); }
};
