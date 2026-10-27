import unittest
from unittest.mock import patch

import config
from temperature import TemperatureSimulation
import app


class TemperatureTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        with patch.object(config, 'TEMP_STATE_TIMEOUT_SECONDS', 10000):
            self.sim = TemperatureSimulation(clock=lambda: self.now)

    def test_heats_by_elapsed_time_and_counts_continuous_run(self):
        self.sim.report(True)
        self.now = 10
        data = self.sim.snapshot()
        self.assertAlmostEqual(data['temperature_c'], self.sim.ambient + 10 * self.sim.heating, places=2)
        self.assertEqual(data['continuous_run_seconds'], 10)
        self.assertTrue(data['simulated'])
        self.assertTrue(data['state_known'])

    def test_cools_without_resetting_heat_and_restarts_run_counter(self):
        self.sim.report(True)
        self.now = 20
        warm = self.sim.snapshot()['temperature_c']
        self.sim.report(False)
        self.assertEqual(self.sim.snapshot()['temperature_c'], warm)
        self.assertEqual(self.sim.snapshot()['continuous_run_seconds'], 0)
        self.now = 25
        cooled = self.sim.snapshot()['temperature_c']
        self.assertAlmostEqual(cooled, warm - 5 * self.sim.cooling, places=2)
        self.sim.report(True)
        self.now = 27
        self.assertEqual(self.sim.snapshot()['continuous_run_seconds'], 2)
        self.assertAlmostEqual(self.sim.snapshot()['temperature_c'], cooled + 2 * self.sim.heating, places=2)

    def test_limits_temperature_to_ambient_and_maximum(self):
        self.sim.report(True)
        self.now = 1000
        self.assertEqual(self.sim.snapshot()['temperature_c'], self.sim.maximum)
        self.sim.report(False)
        self.now = 3000
        self.assertEqual(self.sim.snapshot()['temperature_c'], self.sim.ambient)

    def test_sampling_and_repeated_telemetry_do_not_reset_runtime(self):
        with patch.object(config, 'TEMP_STATE_TIMEOUT_SECONDS', 10000):
            other = TemperatureSimulation(clock=lambda: self.now)
        self.sim.report(True)
        other.report(True)
        for instant in [1, 2, 5, 8]:
            self.now = instant
            self.sim.snapshot()
            self.sim.report(True)
        self.now = 10
        self.assertEqual(self.sim.snapshot()['temperature_c'], other.snapshot()['temperature_c'])
        self.assertEqual(self.sim.snapshot()['continuous_run_seconds'], 10)

    def test_missing_telemetry_switches_to_cooling_at_timeout(self):
        self.sim.timeout = 3
        self.sim.report(True)
        self.now = 4
        data = self.sim.snapshot()
        self.assertFalse(data['state_known'])
        self.assertFalse(data['conveyor_running'])
        self.assertEqual(data['continuous_run_seconds'], 0)
        self.assertAlmostEqual(data['temperature_c'], self.sim.ambient + 3 * self.sim.heating - self.sim.cooling, places=2)

    def test_disconnect_cools_and_invalid_state_is_rejected(self):
        self.sim.report(True)
        self.now = 10
        warm = self.sim.snapshot()['temperature_c']
        self.sim.disconnect()
        self.now = 12
        data = self.sim.snapshot()
        self.assertFalse(data['state_known'])
        self.assertAlmostEqual(data['temperature_c'], warm - 2 * self.sim.cooling, places=2)
        with self.assertRaises(ValueError):
            self.sim.report('true')


class DashboardStateTests(unittest.TestCase):
    def test_speed_is_estimated_only_when_motor_state_is_known(self):
        for known, running, expected in [(True, True, .23), (True, False, 0), (False, False, None)]:
            with self.subTest(known=known, running=running):
                with patch.object(app.temperature, 'snapshot', return_value={
                    'state_known': known, 'conveyor_running': running,
                }), patch.object(config, 'CONVEYOR_ESTIMATED_SPEED_M_S', .23):
                    state = app.detection_snapshot()['conveyor']
                self.assertEqual(state['speed_m_s'], expected)
                self.assertTrue(state['speed_estimated'])
                self.assertEqual(state['state_known'], known)
