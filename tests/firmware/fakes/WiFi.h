// WI-FI FALSO: substitui a biblioteca no teste C++ e não acessa SSID, senha ou placa reais.
#pragma once
#include "HostArduino.h"
constexpr int WIFI_STA = 1, WL_CONNECTED = 3;
struct HostWiFi {
  void mode(int) {}
  void setAutoReconnect(bool) {}
  void begin(const char*, const char*) {}
  // Simula conexão pronta para que setup não fique esperando uma rede durante o teste.
  int status() const { return WL_CONNECTED; }
  // Endereço ilustrativo de loopback; não serve para configurar uma ESP32 física.
  String localIP() const { return "127.0.0.1"; }
};
inline HostWiFi WiFi;
