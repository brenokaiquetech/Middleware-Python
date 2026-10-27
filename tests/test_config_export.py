from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import config
from generate_esp32_config import build_header, write_esp32_config


class ConfigExportTests(unittest.TestCase):
    def test_network_and_servo_are_exported_from_config(self):
        with patch.multiple(config, SERVER_PUBLIC_HOST='192.168.1.50', PORT=9001,
                            SORT_WS_PATH='/ws/test', SERVO_PIN=23,
                            SERVO_CALIBRATED=True, SORT_STOP_MS=300,
                            CONVEYOR_ENABLED=True, CONVEYOR_PIN_IA=25,
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
