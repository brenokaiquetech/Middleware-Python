#pragma once
// GERADO a partir de config.py. Edite config.py, nao este arquivo.
// Apos gerar novamente, recompile e reenvie o firmware para a ESP32.

constexpr unsigned long SERVER_PORT = 8000UL;
constexpr unsigned long SERVO_PIN = 18UL;
constexpr unsigned long SERVO_FREQUENCY_HZ = 50UL;
constexpr unsigned long SERVO_MIN_US = 500UL;
constexpr unsigned long SERVO_MAX_US = 2500UL;
constexpr unsigned long SERVO_TEST_STEP_MS = 2000UL;
constexpr unsigned long CONVEYOR_PIN_IA = 26UL;
constexpr unsigned long CONVEYOR_PIN_IB = 25UL;
constexpr unsigned long SERIAL_BAUD = 115200UL;
constexpr unsigned long WS_RECONNECT_MS = 5000UL;
constexpr unsigned long WIFI_WAIT_MS = 500UL;
constexpr unsigned long DEFAULT_SETTLE_MS = 1500UL;
constexpr unsigned long DEFAULT_STOP_MS = 200UL;
constexpr unsigned long MAX_MOVEMENT_STAGE_MS = 10000UL;
constexpr unsigned long TELEMETRY_INTERVAL_MS = 1000UL;
constexpr bool SERVO_CALIBRATED = true;
constexpr bool CONVEYOR_ENABLED = true;
constexpr bool CONVEYOR_FORWARD_IA_HIGH = true;
constexpr float SERVO_TRAVEL_DEG = 180.0f;
