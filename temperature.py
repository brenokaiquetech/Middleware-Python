"""Temperatura fictícia calculada pelo tempo no estado ligado/desligado."""
import threading
import time

import config


class TemperatureSimulation:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.ambient = config.TEMP_AMBIENT_C
        self.maximum = config.TEMP_MAX_C
        self.heating = config.TEMP_HEATING_C_PER_SECOND
        self.cooling = config.TEMP_COOLING_C_PER_SECOND
        self.timeout = config.TEMP_STATE_TIMEOUT_SECONDS
        if (self.maximum < self.ambient or self.heating < 0 or self.cooling < 0
                or self.timeout <= 0):
            raise ValueError('Configuração de temperatura simulada inválida.')
        self.lock = threading.Lock()
        self.value = self.ambient
        self.updated_at = self.clock()
        self.last_report = None
        self.running = False
        self.running_since = None

    def _integrate(self, seconds):
        rate = self.heating if self.running else -self.cooling
        self.value = min(self.maximum, max(self.ambient, self.value + rate * seconds))

    def _advance(self, now):
        # Integre até o último estado válido; depois esfrie se a telemetria sumir.
        if self.running and self.last_report is not None:
            expires_at = self.last_report + self.timeout
            if expires_at < now:
                self._integrate(max(0, expires_at - self.updated_at))
                self.updated_at = max(self.updated_at, expires_at)
                self.running = False
                self.running_since = None
        self._integrate(max(0, now - self.updated_at))
        self.updated_at = now

    def report(self, running):
        if not isinstance(running, bool):
            raise ValueError('O estado da esteira deve ser booleano.')
        with self.lock:
            now = self.clock()
            self._advance(now)
            if running and not self.running:
                self.running_since = now
            elif not running:
                self.running_since = None
            self.running = running
            self.last_report = now

    def disconnect(self):
        with self.lock:
            self._advance(self.clock())
            self.running = False
            self.running_since = None
            self.last_report = None

    def snapshot(self):
        with self.lock:
            now = self.clock()
            self._advance(now)
            return {
                'simulated': True,
                'temperature_c': round(self.value, 2),
                'ambient_c': self.ambient,
                'conveyor_running': self.running,
                'continuous_run_seconds': round(now - self.running_since, 1)
                if self.running_since is not None else 0.0,
                'state_known': self.last_report is not None
                and now - self.last_report <= self.timeout,
            }


temperature = TemperatureSimulation()
