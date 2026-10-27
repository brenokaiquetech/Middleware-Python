// Adaptadores de teste: executam o sketch real no computador, sem GPIOs reais.
#pragma once
#include <ArduinoJson.h>
#include <cstdint>
#include <cstdio>
#include <map>
#include <string>
#include <vector>

class String {
 public:
  std::string value;
  String(const char* text = "") : value(text ? text : "") {}
  bool isEmpty() const { return value.empty(); }
  bool operator==(const String& other) const { return value == other.value; }
  bool operator!=(const String& other) const { return !(*this == other); }
  size_t write(uint8_t byte) { value.push_back(static_cast<char>(byte)); return 1; }
  size_t write(const uint8_t* bytes, size_t size) {
    value.append(reinterpret_cast<const char*>(bytes), size);
    return size;
  }
};

inline void convertToJson(const String& source, JsonVariant target) {
  target.set(source.value);
}

inline void convertFromJson(JsonVariantConst source, String& target) {
  target.value = source.as<std::string>();
}

inline uint32_t fakeNow = 0;
inline std::map<int, int> pinStates;
inline unsigned gpioWrites = 0;
constexpr int LOW = 0, HIGH = 1, OUTPUT = 1;
inline uint32_t millis() { return fakeNow; }
inline void delay(uint32_t duration) { fakeNow += duration; }
inline void pinMode(unsigned, int) {}
inline void digitalWrite(unsigned pin, int state) {
  pinStates[pin] = state;
  ++gpioWrites;
}

struct HostSerial {
  void begin(unsigned) {}
  void print(const char*) {}
  void println() {}
  void println(const char*) {}
  void println(const String&) {}
  template <typename... Args> void printf(const char*, Args...) {}
};
inline HostSerial Serial;
