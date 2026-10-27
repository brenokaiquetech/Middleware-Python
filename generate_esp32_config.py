"""Gera as constantes C++ da placa a partir de config.py, sem dependências extras."""
import json
from pathlib import Path

import config

OUTPUT_PATH = Path(__file__).resolve().parent / 'esp32' / 'EcoCycleClient' / 'EcoCycleConfig.h'


def build_header():
    lines = [
        '#pragma once',
        '// GERADO a partir de config.py. Edite config.py, nao este arquivo.',
        '// Apos gerar novamente, recompile e reenvie o firmware para a ESP32.',
        '',
    ]
    strings = {
        'WIFI_SSID': config.ESP32_WIFI_SSID,
        'WIFI_PASSWORD': config.ESP32_WIFI_PASSWORD,
        'SERVER_HOST': config.SERVER_PUBLIC_HOST,
        'SERVER_PATH': config.SORT_WS_PATH,
    }
    for name, value in strings.items():
        lines.append(f'constexpr const char* {name} = {json.dumps(value, ensure_ascii=False)};')
    integers = {
        'SERVER_PORT': config.PORT,
        'SERVO_PIN': config.SERVO_PIN,
        'SERVO_FREQUENCY_HZ': config.SERVO_FREQUENCY_HZ,
        'SERVO_MIN_US': config.SERVO_MIN_US,
        'SERVO_MAX_US': config.SERVO_MAX_US,
        'CONVEYOR_PIN_IA': config.CONVEYOR_PIN_IA,
        'CONVEYOR_PIN_IB': config.CONVEYOR_PIN_IB,
        'SERIAL_BAUD': config.ESP32_SERIAL_BAUD,
        'WS_RECONNECT_MS': config.ESP32_RECONNECT_MS,
        'WIFI_WAIT_MS': config.ESP32_WIFI_WAIT_MS,
        'DEFAULT_SETTLE_MS': config.SORT_SETTLE_MS,
        'DEFAULT_STOP_MS': config.SORT_STOP_MS,
        'MAX_MOVEMENT_STAGE_MS': config.ESP32_MAX_MOVEMENT_STAGE_MS,
        'TELEMETRY_INTERVAL_MS': config.ESP32_TELEMETRY_INTERVAL_MS,
    }
    for name, value in integers.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f'{name} deve ser um inteiro não negativo em config.py.')
        lines.append(f'constexpr unsigned long {name} = {value}UL;')
    lines.extend([
        f'constexpr bool SERVO_CALIBRATED = {str(config.SERVO_CALIBRATED).lower()};',
        f'constexpr bool CONVEYOR_ENABLED = {str(config.CONVEYOR_ENABLED).lower()};',
        f'constexpr bool CONVEYOR_FORWARD_IA_HIGH = {str(config.CONVEYOR_FORWARD_IA_HIGH).lower()};',
        f'constexpr float SERVO_TRAVEL_DEG = {float(config.SERVO_TRAVEL_DEG)!r}f;',
        '',
    ])
    if len({config.SERVO_PIN, config.CONVEYOR_PIN_IA, config.CONVEYOR_PIN_IB}) != 3:
        raise ValueError('SERVO_PIN e os dois pinos da esteira devem ser diferentes.')
    return '\n'.join(lines)


def write_esp32_config(path=OUTPUT_PATH):
    path = Path(path)
    source = build_header()
    if not path.exists() or path.read_text(encoding='utf-8') != source:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    return path


if __name__ == '__main__':
    print(f'Configuração ESP32 gerada: {write_esp32_config()}')
