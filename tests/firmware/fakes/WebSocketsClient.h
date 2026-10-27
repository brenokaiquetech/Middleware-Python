#pragma once
#include "HostArduino.h"
enum WStype_t { WStype_CONNECTED, WStype_DISCONNECTED, WStype_TEXT };
struct WebSocketsClient {
  std::vector<std::string> sent;
  void begin(const char*, unsigned, const char*) {}
  void onEvent(void (*)(WStype_t, uint8_t*, size_t)) {}
  void setReconnectInterval(unsigned) {}
  void loop() {}
  bool sendTXT(const String& text) { sent.push_back(text.value); return true; }
};
