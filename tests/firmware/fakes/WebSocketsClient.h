// WEBSOCKET FALSO: armazena os textos enviados, sem abrir conexão de rede.
#pragma once
#include "HostArduino.h"
// Eventos mínimos necessários para chamar o callback do sketch nos testes.
enum WStype_t { WStype_CONNECTED, WStype_DISCONNECTED, WStype_TEXT };
struct WebSocketsClient {
  // Os testes leem o último JSON desta lista para conferir ACKs e telemetria.
  std::vector<std::string> sent;
  // Configuração e loop são no-ops; o teste entrega mensagens manualmente pelo callback.
  void begin(const char*, unsigned, const char*) {}
  void onEvent(void (*)(WStype_t, uint8_t*, size_t)) {}
  void setReconnectInterval(unsigned) {}
  void loop() {}
  bool sendTXT(const String& text) { sent.push_back(text.value); return true; }
};
