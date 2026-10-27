"""Simula pesos por peça e lote conforme Lógica_Peso_Materiais.pdf.

Todos os cálculos usam gramas inteiras; não são medições de uma balança.
O backend externo ainda não participa desta implementação.
"""
import random
import threading
import uuid

import config

MAX_SAFE_INTEGER = 2**53 - 1


class BatchConflict(ValueError):
    pass


class BatchWeightSimulation:
    def __init__(self, rng=None):
        self.rng = random.Random() if rng is None else rng
        self.ranges = dict(config.BATCH_WEIGHT_RANGES_G)
        for minimum, maximum in self.ranges.values():
            if (type(minimum) is not int or type(maximum) is not int
                    or not 0 < minimum <= maximum <= MAX_SAFE_INTEGER):
                raise ValueError('Faixa de peso inválida em config.py.')
        self.lock = threading.RLock()
        self.session_id = uuid.uuid4().hex
        self.lot_id = None
        self.total = 0
        self.processed = 0
        self.status = 'AGUARDANDO_LOTE'
        self.totals = dict.fromkeys(self.ranges, 0)
        self.quantities = dict.fromkeys(self.ranges, 0)
        self.processed_events = set()
        self.known_lot_ids = set()
        self.last_piece = None
        self.confirmations = {}
        # IDs já pesados pela câmera não são novamente pesados em outro lote.
        self.weighed_tracks = set()

    def start_lot(self, lot_id, total_grams):
        if not isinstance(lot_id, str) or not lot_id.strip():
            raise ValueError('Identificador do lote inválido.')
        lot_id = lot_id.strip()
        if type(total_grams) is not int or not 0 < total_grams <= MAX_SAFE_INTEGER:
            raise ValueError('Peso do lote deve ser um inteiro positivo em gramas.')
        with self.lock:
            if self.lot_id == lot_id:
                if self.total != total_grams:
                    raise BatchConflict('O lote já foi cadastrado com outro peso.')
                return self.snapshot()  # Repetir o cadastro não zera a produção.
            if self.status == 'EM_PROCESSAMENTO':
                raise BatchConflict('Conclua o lote atual antes de iniciar outro.')
            if lot_id in self.known_lot_ids:
                raise BatchConflict('Esse identificador de lote já foi utilizado.')
            self.lot_id = lot_id
            self.known_lot_ids.add(lot_id)
            self.total = total_grams
            self.processed = 0
            self.status = 'EM_PROCESSAMENTO'
            self.totals = dict.fromkeys(self.ranges, 0)
            self.quantities = dict.fromkeys(self.ranges, 0)
            self.processed_events.clear()
            self.confirmations.clear()
            self.last_piece = None
            return self.snapshot()

    def account_piece(self, event):
        if not isinstance(event, dict):
            raise ValueError('Envie um objeto JSON com eventoId e material.')
        event_id = event.get('eventoId')
        material = event.get('material')
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError('Identificador do evento inválido.')
        if not isinstance(material, str) or material not in self.ranges:
            raise ValueError('Material não reconhecido.')
        event_id = event_id.strip()
        with self.lock:
            if self.lot_id is None:
                return {'sucesso': False, 'motivo': 'LOTE_NAO_CONFIGURADO'}
            if event_id in self.processed_events:
                return {'sucesso': False, 'motivo': 'EVENTO_DUPLICADO'}
            if self.status != 'EM_PROCESSAMENTO':
                return {'sucesso': False, 'motivo': 'LOTE_ENCERRADO'}
            remaining = self.total - self.processed
            minimum, maximum = self.ranges[material]
            if remaining < minimum:
                weight = remaining
                calculation = 'AJUSTE_SALDO'
            else:
                weight = self.rng.randint(minimum, min(maximum, remaining))
                calculation = 'ALEATORIO'
            self.processed += weight
            self.totals[material] += weight
            self.quantities[material] += 1
            self.processed_events.add(event_id)
            if self.processed == self.total:
                self.status = 'CONCLUIDO'
            self.last_piece = {
                'loteId': self.lot_id,
                'eventoId': event_id,
                'material': material,
                'pesoSimuladoGramas': weight,
                'tipoCalculo': calculation,
            }
            return {'sucesso': True, **self.snapshot(), **self.last_piece}

    def observe(self, detections):
        """Pesa uma vez por ID confirmado, independentemente da ESP32/site."""
        with self.lock:
            if self.status != 'EM_PROCESSAMENTO':
                self.confirmations.clear()
                return
            present = {item['id'] for item in detections}
            self.confirmations = {
                key: value for key, value in self.confirmations.items() if key in present
            }
            for item in detections:
                track_id, color = item['id'], item['color']
                material = config.BATCH_MATERIAL_BY_COLOR.get(color)
                if track_id in self.weighed_tracks or material not in self.ranges:
                    continue
                previous, count = self.confirmations.get(track_id, (color, 0))
                count = count + 1 if previous == color else 1
                self.confirmations[track_id] = (color, count)
                if count < config.SORT_CONFIRM_FRAMES:
                    continue
                result = self.account_piece({
                    'eventoId': f'camera:{self.session_id}:{track_id}',
                    'material': material,
                })
                if result['sucesso']:
                    self.weighed_tracks.add(track_id)
                    self.confirmations.pop(track_id, None)
                if self.status == 'CONCLUIDO':
                    break

    def snapshot(self):
        with self.lock:
            return {
                'simulado': True,
                'loteId': self.lot_id,
                'pesoTotalLoteGramas': self.total,
                'pesoProcessadoGramas': self.processed,
                'saldoLoteGramas': self.total - self.processed,
                'totaisPorMaterial': dict(self.totals),
                'quantidades': dict(self.quantities),
                'nomesMateriais': dict(config.BATCH_MATERIAL_LABELS),
                'statusLote': self.status,
                'ultimaPeca': dict(self.last_piece) if self.last_piece is not None else None,
            }


batch_weights = BatchWeightSimulation()
