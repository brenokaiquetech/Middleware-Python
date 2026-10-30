# EXPORTAÇÃO: converte os ajustes Python em constantes C++ para os dois sketches.
# Alterações destinadas à placa só entram em uso após gerar, compilar e regravar o firmware.
"""Gera as constantes C++ da placa a partir de config.py, sem dependências extras."""
import json
import math
from pathlib import Path

import config

# Resolve a pasta pelo próprio script para funcionar mesmo se o terminal estiver em outro diretório.
OUTPUT_PATH = Path(__file__).resolve().parent / 'esp32' / 'EcoCycleClient' / 'EcoCycleConfig.h'
SERVO_TEST_OUTPUT_PATH = OUTPUT_PATH.parents[1] / 'TesteServo' / 'EcoCycleConfig.h'


# Valida curso/ângulos/pinos e monta constantes C++; o teste isolado pode omitir credenciais de rede.
def build_header(include_network=True):
    # Cada SG90 tem até 180° físicos; apenas a soma dos eixos alcança 360°.
    for name in ('SERVO_TRAVEL_DEG', 'SERVO_TOP_TRAVEL_DEG'):
        travel = getattr(config, name)
        if (not isinstance(travel, (int, float)) or isinstance(travel, bool)
                or not math.isfinite(travel) or not 0 < travel <= 180):
            raise ValueError(f'{name} deve ser finito e estar entre 0 e 180 graus.')
    travel = config.SERVO_TRAVEL_DEG + config.SERVO_TOP_TRAVEL_DEG
    for prefix in ('SERVO', 'SERVO_TOP'):
        low, high = getattr(config, f'{prefix}_MIN_US'), getattr(config, f'{prefix}_MAX_US')
        if type(low) is not int or type(high) is not int or not 0 < low < high:
            raise ValueError(f'Pulsos de {prefix} devem ser inteiros positivos com MIN_US < MAX_US.')
        if type(getattr(config, f'{prefix}_REVERSED')) is not bool:
            raise ValueError(f'{prefix}_REVERSED deve ser booleano.')
    for color, target in config.SORT_TARGETS.items():
        angle = target.get('angle_deg')
        if (not isinstance(angle, (int, float)) or isinstance(angle, bool)
                or not math.isfinite(angle) or not 0 <= angle <= travel):
            raise ValueError(f'Ângulo de {color} fora do curso de 0 a {travel} graus em config.py.')
    lines = [
        '#pragma once',
        '// GERADO a partir de config.py. Edite config.py, nao este arquivo.',
        '// Apos gerar novamente, recompile e reenvie o firmware para a ESP32.',
        '// Rede: credenciais e destino WebSocket so no cliente; o diagnostico omite credenciais.',
        '// GPIOs: numeros dos pinos; servo: frequencia em Hz, pulsos em us e curso em graus.',
        '// Tempos: constantes terminadas em MS usam milissegundos; SERIAL_BAUD e a taxa do monitor.',
        '// Habilitacoes e sentido sao booleanos. Constantes nao medem o estado fisico dos motores.',
        '',
    ]
    # json.dumps escapa aspas e barras para que SSID/senha gerem strings C++ válidas.
    strings = {
        'WIFI_SSID': config.ESP32_WIFI_SSID,
        'WIFI_PASSWORD': config.ESP32_WIFI_PASSWORD,
        'SERVER_HOST': config.SERVER_PUBLIC_HOST,
        'SERVER_PATH': config.SORT_WS_PATH,
    } if include_network else {}
    for name, value in strings.items():
        lines.append(f'constexpr const char* {name} = {json.dumps(value, ensure_ascii=False)};')
    # UL indica unsigned long em C++; tempos são milissegundos e pinos são números GPIO.
    integers = {
        'SERVER_PORT': config.PORT,
        'SERVO_PIN': config.SERVO_PIN,
        'SERVO_TOP_PIN': config.SERVO_TOP_PIN,
        'SERVO_FREQUENCY_HZ': config.SERVO_FREQUENCY_HZ,
        'SERVO_MIN_US': config.SERVO_MIN_US,
        'SERVO_MAX_US': config.SERVO_MAX_US,
        'SERVO_TOP_MIN_US': config.SERVO_TOP_MIN_US,
        'SERVO_TOP_MAX_US': config.SERVO_TOP_MAX_US,
        'SORT_PROTOCOL_VERSION': config.ESP32_PROTOCOL_VERSION,
        'SERVO_TEST_STEP_MS': config.SERVO_TEST_STEP_MS,
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
        f'constexpr bool SERVO_REVERSED = {str(config.SERVO_REVERSED).lower()};',
        f'constexpr bool SERVO_TOP_REVERSED = {str(config.SERVO_TOP_REVERSED).lower()};',
        f'constexpr bool CONVEYOR_ENABLED = {str(config.CONVEYOR_ENABLED).lower()};',
        f'constexpr bool CONVEYOR_FORWARD_IA_HIGH = {str(config.CONVEYOR_FORWARD_IA_HIGH).lower()};',
        f'constexpr float SERVO_TRAVEL_DEG = {float(config.SERVO_TRAVEL_DEG)!r}f;',
        f'constexpr float SERVO_TOP_TRAVEL_DEG = {float(config.SERVO_TOP_TRAVEL_DEG)!r}f;',
        f'constexpr float PLATE_TRAVEL_DEG = {float(travel)!r}f;',
        '',
    ])
    # Cada função elétrica usa seu próprio GPIO; o gerador recusa pinos compartilhados.
    if len({config.SERVO_PIN, config.SERVO_TOP_PIN, config.CONVEYOR_PIN_IA, config.CONVEYOR_PIN_IB}) != 4:
        raise ValueError('Os dois servos e os dois pinos da esteira devem usar GPIOs diferentes.')
    return '\n'.join(lines)


# Grava o header só quando o conteúdo mudou, preservando a data de arquivos idênticos.
def write_esp32_config(path=OUTPUT_PATH, include_network=True):
    path = Path(path)
    source = build_header(include_network=include_network)
    if not path.exists() or path.read_text(encoding='utf-8') != source:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    return path


# Gera tanto a configuração do cliente principal quanto a do diagnóstico sem Wi-Fi.
def write_esp32_configs():
    return write_esp32_config(), write_esp32_config(SERVO_TEST_OUTPUT_PATH, include_network=False)


# Rodar este script só exporta arquivos: não abre servidor e não envia firmware à ESP32.
if __name__ == '__main__':
    for path in write_esp32_configs():
        print(f'Configuração ESP32 gerada: {path}')
