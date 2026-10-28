from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import config
from generate_esp32_config import build_header, write_esp32_config


class ConfigExportTests(unittest.TestCase):
    def test_sg90_has_three_material_positions_within_180_degrees(self):
        self.assertEqual(config.SERVO_TRAVEL_DEG, 180)
        self.assertEqual({color: target['angle_deg'] for color, target in config.SORT_TARGETS.items()}, {
            'Laranja': 0, 'Verde-claro': 90, 'Azul-claro': 180,
        })
        self.assertIn('SERVO_TRAVEL_DEG = 180.0f;', build_header())

    def test_servo_diagnostic_header_uses_same_pins_without_wifi_credentials(self):
        source = build_header(include_network=False)
        self.assertNotIn('WIFI_PASSWORD', source)
        self.assertNotIn('WIFI_SSID', source)
        self.assertNotIn('SERVER_HOST', source)
        self.assertIn(f'SERVO_PIN = {config.SERVO_PIN}UL;', source)
        self.assertIn(f'CONVEYOR_PIN_IB = {config.CONVEYOR_PIN_IB}UL;', source)

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

    def test_conflicting_motor_pins_are_rejected(self):
        with patch.object(config, 'CONVEYOR_PIN_IA', config.SERVO_PIN):
            with self.assertRaises(ValueError):
                build_header()

    def test_angle_outside_servo_travel_is_rejected_before_upload(self):
        with patch.multiple(config, SERVO_TRAVEL_DEG=180,
                            SORT_TARGETS={'Roxo': {'angle_deg': 270}}):
            with self.assertRaisesRegex(ValueError, 'Roxo'):
                build_header()

    def test_360_degree_servo_accepts_upper_half_and_decimal_angles(self):
        with patch.multiple(config, SERVO_TRAVEL_DEG=360.0, SORT_TARGETS={
            'Laranja': {'angle_deg': 0}, 'Verde-claro': {'angle_deg': 123.5},
            'Azul-claro': {'angle_deg': 270}, 'Roxo': {'angle_deg': 360},
        }):
            self.assertIn('SERVO_TRAVEL_DEG = 360.0f;', build_header())

    def test_360_degree_servo_rejects_invalid_color_positions(self):
        for angle in (-1, 360.1, float('nan'), float('inf'), True):
            with self.subTest(angle=angle), patch.multiple(
                config, SERVO_TRAVEL_DEG=360.0, SORT_TARGETS={'Roxo': {'angle_deg': angle}},
            ):
                with self.assertRaisesRegex(ValueError, 'Roxo'):
                    build_header()

    def test_invalid_servo_travel_is_rejected(self):
        for travel in (0, -1, float('nan'), float('inf'), True):
            with self.subTest(travel=travel), patch.object(config, 'SERVO_TRAVEL_DEG', travel):
                with self.assertRaises(ValueError):
                    build_header()

    def test_wifi_strings_are_escaped_for_cpp(self):
        with patch.multiple(config, ESP32_WIFI_SSID='Rede "teste"',
                            ESP32_WIFI_PASSWORD='teste\\senha\nlinha'):
            source = build_header()
        self.assertIn('WIFI_SSID = "Rede \\"teste\\"";', source)
        self.assertIn('WIFI_PASSWORD = "teste\\\\senha\\nlinha";', source)

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
