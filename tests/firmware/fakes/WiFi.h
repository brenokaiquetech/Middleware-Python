#pragma once
#include "HostArduino.h"
constexpr int WIFI_STA = 1, WL_CONNECTED = 3;
struct HostWiFi {
  void mode(int) {}
  void setAutoReconnect(bool) {}
  void begin(const char*, const char*) {}
  int status() const { return WL_CONNECTED; }
  String localIP() const { return "127.0.0.1"; }
};
inline HostWiFi WiFi;
