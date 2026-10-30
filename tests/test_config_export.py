# CONFIGURAÇÃO: valida geração C++, limites de ângulo, isolamento de credenciais e escrita de headers temporários.
# Execução: python -m unittest discover -s tests -v. Não precisa ligar motores.
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import config
from generate_esp32_config import build_header, write_esp32_config


# Agrupa cenários deste componente; cada assert compara o resultado com a regra esperada.
class ConfigExportTests(unittest.TestCase):
    # Curso individual permanece 180°; só o prato soma 360° sem mudar os destinos atuais.
    def test_two_sg90_have_combined_360_degrees_and_keep_material_positions(self):
        self.assertEqual(config.SERVO_TRAVEL_DEG, 180)
        self.assertEqual(config.SERVO_TOP_TRAVEL_DEG, 180)
        self.assertEqual({color: target['angle_deg'] for color, target in config.SORT_TARGETS.items()}, {
            'Laranja': 0, 'Verde-claro': 90, 'Azul-claro': 180, 'Roxo': 270,
        })
        self.assertIn('SERVO_TRAVEL_DEG = 180.0f;', build_header())
        self.assertIn('SERVO_TOP_TRAVEL_DEG = 180.0f;', build_header())
        self.assertIn('PLATE_TRAVEL_DEG = 360.0f;', build_header())

    # O diagnóstico compartilha pinos com o cliente sem exportar credenciais de rede.
    def test_servo_diagnostic_header_uses_same_pins_without_wifi_credentials(self):
        source = build_header(include_network=False)
        self.assertNotIn('WIFI_PASSWORD', source)
        self.assertNotIn('WIFI_SSID', source)
        self.assertNotIn('SERVER_HOST', source)
        self.assertIn(f'SERVO_PIN = {config.SERVO_PIN}UL;', source)
        self.assertIn(f'SERVO_TOP_PIN = {config.SERVO_TOP_PIN}UL;', source)
        self.assertIn(f'CONVEYOR_PIN_IB = {config.CONVEYOR_PIN_IB}UL;', source)

    # Verifica a conversão das opções centrais para constantes C++ no header.
    def test_network_and_servo_are_exported_from_config(self):
        with patch.multiple(config, SERVER_PUBLIC_HOST='192.168.1.50', PORT=9001,
                            SORT_WS_PATH='/ws/test', SERVO_PIN=23,
                            SERVO_CALIBRATED=True, SORT_STOP_MS=300,
                            CONVEYOR_ENABLED=True, CONVEYOR_PIN_IA=25,
                            CONVEYOR_PIN_IB=26,
                            CONVEYOR_FORWARD_IA_HIGH=False):
            source = build_header()
        self.assertIn('SERVER_HOST = "192.168.1.50";', source)
        self.assertIn('SERVER_PORT = 9001UL;', source)
        self.assertIn('SERVER_PATH = "/ws/test";', source)
        self.assertIn('SERVO_PIN = 23UL;', source)
        self.assertIn('SERVO_CALIBRATED = true;', source)
        self.assertIn('DEFAULT_STOP_MS = 300UL;', source)
        self.assertIn('CONVEYOR_ENABLED = true;', source)
        self.assertIn('CONVEYOR_PIN_IA = 25UL;', source)
        self.assertIn('CONVEYOR_FORWARD_IA_HIGH = false;', source)
        self.assertNotIn('HOLD_MS', source)

    # Impedir dois atuadores de compartilhar GPIO evita uma configuração elétrica conflitante.
    def test_conflicting_motor_pins_are_rejected(self):
        with patch.object(config, 'CONVEYOR_PIN_IA', config.SERVO_PIN):
            with self.assertRaises(ValueError):
                build_header()

    # O novo sinal não pode compartilhar pino com o servo de baixo ou com o driver.
    def test_second_servo_pin_must_be_distinct_from_all_other_outputs(self):
        for pin in (config.SERVO_PIN, config.CONVEYOR_PIN_IA, config.CONVEYOR_PIN_IB):
            with self.subTest(pin=pin), patch.object(config, 'SERVO_TOP_PIN', pin):
                with self.assertRaises(ValueError):
                    build_header()

    # Cada servo pode precisar de extremos e sentido de pulso diferentes após a montagem.
    def test_two_servos_export_independent_calibration_and_direction(self):
        with patch.multiple(config, SERVO_TOP_PIN=23, SERVO_TOP_MIN_US=600,
                            SERVO_TOP_MAX_US=2400, SERVO_TOP_REVERSED=True,
                            SERVO_REVERSED=False):
            source = build_header()
        self.assertIn('SERVO_TOP_PIN = 23UL;', source)
        self.assertIn('SERVO_TOP_MIN_US = 600UL;', source)
        self.assertIn('SERVO_TOP_MAX_US = 2400UL;', source)
        self.assertIn('SERVO_TOP_REVERSED = true;', source)
        self.assertIn('SERVO_REVERSED = false;', source)

    # Os pulsos precisam ser ordenados e a inversão deve ser um booleano explícito.
    def test_invalid_second_servo_calibration_is_rejected(self):
        for options in ({'SERVO_TOP_MIN_US': 2500}, {'SERVO_TOP_MAX_US': 0},
                        {'SERVO_TOP_MIN_US': True}, {'SERVO_TOP_REVERSED': 'false'}):
            with self.subTest(options=options), patch.multiple(config, **options):
                with self.assertRaises(ValueError):
                    build_header()

    # Um destino acima do curso deve falhar na geração, antes de compilar a placa.
    def test_angle_outside_servo_travel_is_rejected_before_upload(self):
        with patch.multiple(config, SORT_TARGETS={'Roxo': {'angle_deg': 361}}):
            with self.assertRaisesRegex(ValueError, 'Roxo'):
                build_header()

    # 360° são a soma de dois cursos válidos de 180°, não o curso de um SG90.
    def test_360_degree_servo_accepts_upper_half_and_decimal_angles(self):
        with patch.multiple(config, SORT_TARGETS={
            'Laranja': {'angle_deg': 0}, 'Verde-claro': {'angle_deg': 123.5},
            'Azul-claro': {'angle_deg': 270}, 'Roxo': {'angle_deg': 360},
        }):
            self.assertIn('PLATE_TRAVEL_DEG = 360.0f;', build_header())

    # Mesmo sob configuração 360°, ângulos negativos, infinitos ou fora do curso são recusados.
    def test_360_degree_servo_rejects_invalid_color_positions(self):
        for angle in (-1, 360.1, float('nan'), float('inf'), True):
            with self.subTest(angle=angle), patch.multiple(
                config, SORT_TARGETS={'Roxo': {'angle_deg': angle}},
            ):
                with self.assertRaisesRegex(ValueError, 'Roxo'):
                    build_header()

    # Curso deve ser numérico, positivo e finito; booleanos não representam graus.
    def test_invalid_servo_travel_is_rejected(self):
        for name in ('SERVO_TRAVEL_DEG', 'SERVO_TOP_TRAVEL_DEG'):
            for travel in (0, -1, 180.1, 360, float('nan'), float('inf'), True):
                with self.subTest(name=name, travel=travel), patch.object(config, name, travel):
                    with self.assertRaises(ValueError):
                        build_header()

    # Aspas, barras e quebras de linha precisam virar strings C++ válidas sem expor credenciais reais.
    def test_wifi_strings_are_escaped_for_cpp(self):
        with patch.multiple(config, ESP32_WIFI_SSID='Rede "teste"',
                            ESP32_WIFI_PASSWORD='teste\\senha\nlinha'):
            source = build_header()
        self.assertIn('WIFI_SSID = "Rede \\"teste\\"";', source)
        self.assertIn('WIFI_PASSWORD = "teste\\\\senha\\nlinha";', source)

    # Só regrava quando há diferença de conteúdo e cria a pasta de saída quando necessário.
    def test_write_and_refresh_generated_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sketch' / 'EcoCycleConfig.h'
            self.assertEqual(write_esp32_config(path), path)
            self.assertEqual(path.read_text(encoding='utf-8'), build_header())
            modified = path.stat().st_mtime_ns
            write_esp32_config(path)
            self.assertEqual(path.stat().st_mtime_ns, modified)
            with patch.object(config, 'PORT', 9002):
                write_esp32_config(path)
            self.assertIn('SERVER_PORT = 9002UL;', path.read_text(encoding='utf-8'))
