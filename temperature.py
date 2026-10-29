# TEMPERATURA SIMULADA: integra aquecimento/resfriamento pelo tempo e pela telemetria.
# A trava térmica fica ativa até liberação manual, mesmo depois de esfriar.
"""Temperatura fictícia calculada pelo tempo no estado ligado/desligado."""
import threading
import time
import math

import config


# Modelo térmico fictício associado ao estado de transporte informado pela ESP32.
class TemperatureSimulation:
    # Valida limites e taxas e começa na temperatura ambiente, ainda sem telemetria.
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.ambient = config.TEMP_AMBIENT_C
        self.maximum = config.TEMP_MAX_C
        self.heating = config.TEMP_HEATING_C_PER_SECOND
        self.cooling = config.TEMP_COOLING_C_PER_SECOND
        self.timeout = config.TEMP_STATE_TIMEOUT_SECONDS
        self.critical = config.TEMP_CRITICAL_C
        self.release_limit = config.TEMP_RELEASE_C
        if (self.maximum < self.ambient or self.heating < 0 or self.cooling < 0
                or self.timeout <= 0
                or not all(math.isfinite(value) for value in (
                    self.maximum, self.ambient, self.heating, self.cooling,
                    self.timeout, self.critical, self.release_limit))
                or not self.ambient <= self.release_limit < self.critical <= self.maximum):
            raise ValueError('Configuração de temperatura simulada inválida.')
        self.lock = threading.Lock()
        self.value = self.ambient
        # monotonic mede intervalos sem ser afetado por mudança no relógio de data/hora do computador.
        self.updated_at = self.clock()
        self.last_report = None
        self.running = False
        self.running_since = None
        self.thermal_blocked = False
        self.last_thermal_report = None
        self.awaiting_device_interlock = True

    # Aplica taxa × segundos, limita a temperatura e arma a trava ao alcançar o valor crítico.
    def _integrate(self, seconds):
        rate = self.heating if self.running else -self.cooling
        self.value = min(self.maximum, max(self.ambient, self.value + rate * seconds))
        if self.value >= self.critical:
            self.thermal_blocked = True

    # Avança o tempo sem contar calor duas vezes; telemetria vencida muda a simulação para resfriamento.
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

    # Atualiza o estado ligado/parado e recupera o bloqueio da placa na primeira telemetria da conexão.
    def report(self, running, thermal_blocked=None):
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
            if isinstance(thermal_blocked, bool):
                # Na reconexão, recupera a trava da placa; relatórios atrasados não anulam uma liberação já feita.
                if self.awaiting_device_interlock and thermal_blocked:
                    self.thermal_blocked = True
                self.awaiting_device_interlock = False
                self.last_thermal_report = thermal_blocked

    # Integra o intervalo válido, passa a resfriar e preserva uma trava térmica já existente.
    def disconnect(self):
        with self.lock:
            self._advance(self.clock())
            self.running = False
            self.running_since = None
            self.last_report = None
            self.last_thermal_report = None
            self.awaiting_device_interlock = True

    # Só libera após esfriar e receber confirmação recente de parada com bloqueio na ESP32.
    def release_thermal_block(self):
        """Liberação humana após esfriar; o resfriamento sozinho não religa."""
        with self.lock:
            now = self.clock()
            self._advance(now)
            if not self.thermal_blocked:
                return
            if self.value > self.release_limit:
                raise ValueError(f'Aguarde a temperatura chegar a {self.release_limit:g} °C ou menos.')
            if self.last_report is None or now - self.last_report > self.timeout:
                raise ValueError('Aguarde a comunicação recente com a ESP32 para liberar.')
            if self.running or self.last_thermal_report is not True:
                raise ValueError('Aguarde a confirmação da parada térmica pela ESP32.')
            self.thermal_blocked = False

    # Avança a simulação e informa temperatura, duração ligada e condições da liberação manual.
    def snapshot(self):
        with self.lock:
            now = self.clock()
            self._advance(now)
            return {
                'simulated': True,
                'temperature_c': round(self.value, 2),
                'ambient_c': self.ambient,
                'critical_c': self.critical,
                'release_c': self.release_limit,
                'thermal_blocked': self.thermal_blocked,
                'thermal_block_confirmed': self.last_thermal_report is True
                and self.last_report is not None and now - self.last_report <= self.timeout,
                'can_release': self.thermal_blocked and self.value <= self.release_limit
                and not self.running and self.last_thermal_report is True
                and self.last_report is not None and now - self.last_report <= self.timeout,
                'conveyor_running': self.running,
                'continuous_run_seconds': round(now - self.running_since, 1)
                if self.running_since is not None else 0.0,
                # Estado conhecido exige telemetria recente; ausência de informação não significa motor confirmado parado.
                'state_known': self.last_report is not None
                and now - self.last_report <= self.timeout,
            }


# A mesma simulação atende a API e o loop WebSocket, mesmo quando o navegador está fechado.
temperature = TemperatureSimulation()
