import unittest
from unittest.mock import patch

import app
import config
from motion import simulated_motion
from temperature import TemperatureSimulation


class ThermalTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.settings = patch.multiple(config, TEMP_CRITICAL_C=26.0, TEMP_RELEASE_C=25.5,
                                       TEMP_STATE_TIMEOUT_SECONDS=1000)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.sim = TemperatureSimulation(clock=lambda: self.now)

    def trip(self):
        self.sim.report(True, False)
        self.now = 10.0
        self.assertTrue(self.sim.snapshot()['thermal_blocked'])
        self.sim.report(False, True)

    def test_critical_temperature_latches_until_manual_release_after_cooling(self):
        self.trip()
        with self.assertRaises(ValueError):
            self.sim.release_thermal_block()
        self.now = 20.0
        state = self.sim.snapshot()
        self.assertAlmostEqual(state['temperature_c'], 25.5)
        self.assertTrue(state['thermal_blocked'])
        self.assertTrue(state['can_release'])
        self.sim.release_thermal_block()
        self.assertFalse(self.sim.snapshot()['thermal_blocked'])

    def test_disconnect_preserves_latch_and_requires_recent_stop_confirmation(self):
        self.trip()
        self.sim.disconnect()
        self.now = 50.0
        self.assertTrue(self.sim.snapshot()['thermal_blocked'])
        with self.assertRaises(ValueError):
            self.sim.release_thermal_block()
        self.sim.report(False)  # Firmware antigo não confirma o bloqueio.
        with self.assertRaisesRegex(ValueError, 'confirmação'):
            self.sim.release_thermal_block()
        self.sim.report(False, True)
        self.sim.release_thermal_block()
        self.assertFalse(self.sim.snapshot()['thermal_blocked'])

    def test_release_requires_motor_to_be_reported_stopped(self):
        self.trip()
        self.now = 20.0
        self.sim.report(True, True)
        self.assertFalse(self.sim.snapshot()['can_release'])
        with self.assertRaisesRegex(ValueError, 'confirmação'):
            self.sim.release_thermal_block()

    def test_thermal_release_api_rejects_hot_and_accepts_cooled_manual_release(self):
        self.trip()
        with patch.object(app, 'temperature', self.sim):
            http = app.app.test_client()
            self.assertEqual(http.get('/api/conveyor/thermal/reset').status_code, 405)
            response = http.post('/api/conveyor/thermal/reset')
            self.assertEqual(response.status_code, 409)
            self.assertTrue(response.json['temperature']['thermal_blocked'])
            self.now = 20.0
            response = http.post('/api/conveyor/thermal/reset')
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json['temperature']['thermal_blocked'])

    def test_invalid_thresholds_are_rejected(self):
        for critical, release in ((80, 50), (26, 26), (26, 24), (float('nan'), 25)):
            with self.subTest(critical=critical, release=release), \
                    patch.multiple(config, TEMP_CRITICAL_C=critical, TEMP_RELEASE_C=release):
                with self.assertRaises(ValueError):
                    TemperatureSimulation()

    def test_first_device_report_restores_latch_after_server_restart(self):
        self.sim.report(False, True)
        self.assertTrue(self.sim.snapshot()['thermal_blocked'])
        self.sim.release_thermal_block()
        # Uma mensagem antiga em transito nao anula a liberacao do operador.
        self.sim.report(False, True)
        self.assertFalse(self.sim.snapshot()['thermal_blocked'])
        self.sim.disconnect()
        self.sim.report(False, True)
        self.assertTrue(self.sim.snapshot()['thermal_blocked'])


class MotionTests(unittest.TestCase):
    def setUp(self):
        settings = patch.multiple(config, CONVEYOR_ESTIMATED_SPEED_M_S=.1,
                                  SERVO_SIMULATED_FORCE_PER_KG_N=2.0,
                                  CONVEYOR_SIMULATED_FORCE_REFERENCE_N=2.0)
        settings.start()
        self.addCleanup(settings.stop)

    def motion(self, weight, known=True, running=True):
        return simulated_motion({'state_known': known, 'conveyor_running': running},
                                {'pesoProcessadoGramas': weight})

    def test_accumulated_weight_increases_force_and_reduces_simulated_speed(self):
        empty, medium, heavy = (self.motion(weight) for weight in (0, 500, 1000))
        self.assertEqual(empty['servo_force_n'], 0)
        self.assertAlmostEqual(empty['speed_m_s'], .1)
        self.assertEqual(medium['servo_force_n'], 1)
        self.assertAlmostEqual(medium['speed_m_s'], .1 / 1.5)
        self.assertEqual(heavy['servo_force_n'], 2)
        self.assertAlmostEqual(heavy['speed_m_s'], .05)
        self.assertTrue(heavy['speed_simulated'])

    def test_stopped_speed_is_zero_and_missing_telemetry_is_unknown(self):
        self.assertEqual(self.motion(1000, running=False)['speed_m_s'], 0)
        self.assertIsNone(self.motion(1000, known=False)['speed_m_s'])

    def test_invalid_force_reference_is_rejected(self):
        with patch.object(config, 'CONVEYOR_SIMULATED_FORCE_REFERENCE_N', 0):
            with self.assertRaises(ValueError):
                self.motion(1000)
