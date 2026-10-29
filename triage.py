# OPERAÇÃO: coordena seleção, início, pausa e conclusão do lote.
# Relaciona os controladores de peso, separação e temperatura; não faz reconhecimento de imagem.
"""Seleção do lote e autorização explícita do operador para ligar a esteira."""
import math
import threading
import time

import config
from batch_weights import batch_weights, BatchConflict, MAX_SAFE_INTEGER
from sorting import sorter
from temperature import temperature


# Guarda o lote escolhido e a autorização explícita de funcionamento da operação.
class TriageController:
    # Valida o catálogo, cria o lock reentrante e inicia a separação sem autorização de operação.
    def __init__(self, batches, sorting, thermal, catalog=None, clock=time.monotonic):
        self.batches = batches
        self.sorting = sorting
        self.thermal = thermal
        self.catalog = [dict(item) for item in (config.AVAILABLE_BATCHES if catalog is None else catalog)]
        ids = set()
        for item in self.catalog:
            lot_id, weight = item.get('loteId'), item.get('pesoTotalLoteGramas')
            if (not isinstance(lot_id, str) or not lot_id.strip() or lot_id in ids
                    or type(weight) is not int or not 0 < weight <= MAX_SAFE_INTEGER):
                raise ValueError('Lote inválido ou duplicado em AVAILABLE_BATCHES no config.py.')
            ids.add(lot_id)
            item.setdefault('nome', lot_id)
        self.finish_seconds = config.BATCH_FINISH_RUN_SECONDS
        if not math.isfinite(self.finish_seconds) or self.finish_seconds < 0:
            raise ValueError('BATCH_FINISH_RUN_SECONDS deve ser finito e não negativo.')
        self.clock = clock
        # RLock permite que um método chame outro que também usa o mesmo lock, como select → snapshot.
        self.lock = threading.RLock()
        self.selected = None
        self.started = False
        self.started_once = False
        self.finished = False
        self.finish_since = None
        self.device_ready = False
        self.sorting.set_operation_enabled(False)

    # Registra o handshake da placa; a perda de conexão interrompe a contagem do transporte final.
    def set_device_ready(self, ready):
        with self.lock:
            self.device_ready = ready
            if not ready:
                self.finish_since = None

    # Ao fechar o peso do lote, aguarda o ciclo ativo e o transporte final antes de desautorizar o motor.
    def _refresh(self):
        batch = self.batches.snapshot()
        if self.selected and self.selected['loteId'] == batch['loteId']:
            self.selected['pesoTotalLoteGramas'] = batch['pesoTotalLoteGramas']
        # Fechar o peso interrompe novas peças; a última ainda precisa completar o movimento e o transporte.
        if self.started and batch['statusLote'] == 'CONCLUIDO':
            self.sorting.set_operation_enabled(False)
            motor = self.thermal.snapshot()
            # Sem ACK, conexão, telemetria ligada ou com calor, o período final precisa ser contado novamente.
            if (self.sorting.current_command() is not None or not self.device_ready
                    or not motor['state_known'] or not motor['conveyor_running']
                    or motor['thermal_blocked']):
                self.finish_since = None
            else:
                now = self.clock()
                if self.finish_since is None:
                    self.finish_since = now
                if now - self.finish_since >= self.finish_seconds:
                    self.started = False
                    self.sorting.set_operation_enabled(False)
                    self.finished = True
                    self.finish_since = None
        return batch

    # Calcula a etapa atual e o motivo que permite ou impede o botão Iniciar triagem.
    def snapshot(self):
        with self.lock:
            batch = self._refresh()
            motor = self.thermal.snapshot()
            # A etapa exibida é derivada do estado interno; não depende de uma página permanecer aberta.
            if self.selected is None:
                stage = 'AGUARDANDO_LOTE'
            elif self.finished:
                stage = 'CONCLUIDO'
            elif self.started:
                stage = 'FINALIZANDO' if batch['statusLote'] == 'CONCLUIDO' else 'EM_TRIAGEM'
            else:
                stage = 'PAUSADO' if self.started_once else 'SELECIONADO'
            if not self.selected:
                reason = 'Escolha um lote para preparar a triagem.'
            elif self.finished:
                reason = 'Lote concluído. Escolha outro lote.'
            elif self.started:
                reason = 'Triagem em andamento.'
            elif not self.device_ready:
                reason = 'Conecte a ESP32 com o firmware atualizado.'
            elif not motor['state_known']:
                reason = 'Aguarde o estado recente da ESP32.'
            elif motor['thermal_blocked']:
                reason = 'Libere o bloqueio térmico após o resfriamento.'
            elif motor['conveyor_running']:
                reason = 'Aguarde a confirmação de parada da esteira.'
            else:
                reason = ''
            return {
                'loteId': self.selected['loteId'] if self.selected else None,
                'nome': self.selected['nome'] if self.selected else None,
                'pesoTotalLoteGramas': self.selected['pesoTotalLoteGramas'] if self.selected else 0,
                'status': stage,
                'enabled': self.started,
                'device_ready': self.device_ready,
                'can_start': not reason,
                'start_reason': reason,
            }

    # Combina o catálogo com o lote cadastrado pela API e marca concluídos, ativos e selecionáveis.
    def available_lots(self):
        with self.lock:
            batch = self._refresh()
            items = [dict(item) for item in self.catalog]
            if batch['loteId'] and not any(item['loteId'] == batch['loteId'] for item in items):
                items.append({'loteId': batch['loteId'], 'nome': batch['loteId'],
                              'pesoTotalLoteGramas': batch['pesoTotalLoteGramas']})
            with self.batches.lock:
                used = set(self.batches.known_lot_ids)
            for item in items:
                if item['loteId'] == batch['loteId']:
                    item['pesoTotalLoteGramas'] = batch['pesoTotalLoteGramas']
                same = self.selected is not None and item['loteId'] == self.selected['loteId']
                active = item['loteId'] == batch['loteId'] and batch['statusLote'] == 'EM_PROCESSAMENTO'
                done = item['loteId'] in used and not active
                other_active = batch['statusLote'] == 'EM_PROCESSAMENTO' and not active
                item['status'] = 'CONCLUIDO' if done else 'EM_ANDAMENTO' if active else 'SELECIONADO' if same else 'DISPONIVEL'
                # Só há um lote em processamento; escolher outro não pode abandonar silenciosamente o atual.
                item['can_select'] = same or not (done or other_active or self.started)
            return items

    # Reserva um lote permitido; trocar a seleção não cadastra pesos nem inicia o motor.
    def select(self, lot_id):
        with self.lock:
            item = next((item for item in self.available_lots() if item['loteId'] == lot_id), None)
            if item is None:
                raise ValueError('Lote não encontrado na lista disponível.')
            if not item['can_select']:
                raise BatchConflict('Conclua o lote atual antes de escolher outro lote.')
            if self.selected and self.selected['loteId'] == lot_id:
                return self.snapshot()
            self.selected = {key: item[key] for key in ('loteId', 'nome', 'pesoTotalLoteGramas')}
            self.started = self.started_once = self.finished = False
            self.sorting.set_operation_enabled(False)
            self.finish_since = None
            return self.snapshot()

    # Confere a seleção, inicia/retoma o mesmo lote e habilita a criação de comandos.
    def start(self, lot_id):
        with self.lock:
            state = self.snapshot()
            if not lot_id or lot_id != state['loteId']:
                raise BatchConflict('Escolha o lote e abra o dashboard correspondente antes de iniciar.')
            if self.started:
                return state
            if not state['can_start']:
                raise BatchConflict(state['start_reason'])
            self.batches.start_lot(lot_id, self.selected['pesoTotalLoteGramas'])
            self.started = self.started_once = True
            self.sorting.set_operation_enabled(True)
            self.finish_since = None
            return self.snapshot()

    # Desabilita novos comandos preservando seleção e pesos para uma retomada posterior.
    def pause(self):
        with self.lock:
            self.started = False
            self.sorting.set_operation_enabled(False)
            self.finish_since = None
            return self.snapshot()

    # Libera contabilização e comandos somente durante operação válida e com telemetria recente.
    def processing_allowed(self):
        with self.lock:
            batch = self._refresh()
            motor = self.thermal.snapshot()
            return (self.started and batch['statusLote'] == 'EM_PROCESSAMENTO'
                    and self.device_ready and motor['state_known'] and not motor['thermal_blocked'])


# Instância compartilhada: app.py, vision.py e WebSocket consultam esta mesma operação.
triage = TriageController(batch_weights, sorter, temperature)
