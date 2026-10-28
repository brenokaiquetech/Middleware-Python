"""Converte novos IDs em comandos; não altera o algoritmo de visão."""
import logging
import threading
import time
import uuid

import config

logger = logging.getLogger(__name__)


class SortingController:
    def __init__(self, targets=None, clock=time.monotonic):
        self.targets = config.SORT_TARGETS if targets is None else targets
        self.clock = clock
        self.session_id = uuid.uuid4().hex
        self.lock = threading.Lock()
        self.confirmations = {}
        self.handled_ids = set()
        self.active = None
        self.active_created = None
        self.consumer_connected = False
        self.thermal_blocked = False

    def observe(self, detections):
        """Chamado uma vez por frame, mesmo sem navegador aberto."""
        with self.lock:
            # Sem fila: outra peça só será considerada em novos frames quando
            # a placa estiver livre. O mesmo ID já tratado permanece bloqueado.
            if self.active is not None or not self.consumer_connected or self.thermal_blocked:
                self.confirmations.clear()
                return
            present = {item['id'] for item in detections}
            self.confirmations = {
                key: value for key, value in self.confirmations.items() if key in present
            }
            for item in detections:
                track_id = item['id']
                color = item['color']
                if track_id in self.handled_ids or color not in self.targets:
                    continue
                previous_color, count = self.confirmations.get(track_id, (color, 0))
                count = count + 1 if previous_color == color else 1
                self.confirmations[track_id] = (color, count)
                if count < config.SORT_CONFIRM_FRAMES:
                    continue
                self.handled_ids.add(track_id)
                self.confirmations.pop(track_id, None)
                target = self.targets[color]
                command = {
                    'type': 'sort_cycle',
                    'session_id': self.session_id,
                    'command_id': uuid.uuid4().hex,
                    'track_id': track_id,
                    'color': color,
                    **target,
                    'stop_ms': config.SORT_STOP_MS,
                    'settle_ms': config.SORT_SETTLE_MS,
                }
                self.active = command
                self.active_created = self.clock()
                break

    def acquire_consumer(self):
        with self.lock:
            if self.consumer_connected:
                return False
            self.consumer_connected = True
            return True

    def set_thermal_blocked(self, blocked):
        with self.lock:
            self.thermal_blocked = blocked
            if blocked:
                self.confirmations.clear()

    def release_consumer(self):
        with self.lock:
            self.consumer_connected = False

    def current_command(self):
        with self.lock:
            # Só existe o comando do ciclo atual, sem objetos aguardando.
            if self.active is not None:
                if self.clock() - self.active_created <= config.SORT_ACK_TIMEOUT_SECONDS:
                    return dict(self.active)
                logger.warning('Comando ativo vencido: %s.', self.active['command_id'])
                self.active = None
                self.active_created = None
            return None

    def cancel_command(self, command_id, allow_retry=False):
        with self.lock:
            if self.active is not None and self.active['command_id'] == command_id:
                logger.warning('Ciclo sem confirmação cancelado: %s.', command_id)
                if allow_retry:
                    self.handled_ids.discard(self.active['track_id'])
                self.active = None
                self.active_created = None

    def acknowledge(self, command_id, status):
        with self.lock:
            if self.active is None or self.active['command_id'] != command_id:
                return False
            if status not in ('done', 'error'):
                return False
            if status == 'error':
                logger.error('ESP32 rejeitou o comando %s.', command_id)
            self.active = None
            self.active_created = None
            return True


sorter = SortingController()
