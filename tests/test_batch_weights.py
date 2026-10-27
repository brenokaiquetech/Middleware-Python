from concurrent.futures import ThreadPoolExecutor
import random
import unittest
from unittest.mock import Mock, patch

import app
import config
from batch_weights import BatchConflict, BatchWeightSimulation


class BatchWeightTests(unittest.TestCase):
    def setUp(self):
        self.rng = Mock()
        self.sim = BatchWeightSimulation(rng=self.rng)

    def piece(self, event_id, material='PLASTICO'):
        return self.sim.account_piece({'eventoId': event_id, 'material': material})

    def confirm(self, track_id, color='Laranja'):
        for _ in range(config.SORT_CONFIRM_FRAMES):
            self.sim.observe([{'id': track_id, 'color': color}])

    def test_pdf_example_remaining_eighty_grams(self):
        self.sim.start_lot('LOTE-001', 1000)
        self.rng.randint.side_effect = [300, 620]
        self.piece('EVT-001')
        self.piece('EVT-002', 'METAL')
        result = self.piece('EVT-003')
        self.assertEqual(result['pesoSimuladoGramas'], 80)
        self.assertEqual(result['tipoCalculo'], 'AJUSTE_SALDO')
        self.assertEqual(result['pesoProcessadoGramas'], 1000)
        self.assertEqual(result['saldoLoteGramas'], 0)
        self.assertEqual(result['statusLote'], 'CONCLUIDO')
        self.assertEqual(result['totaisPorMaterial']['PLASTICO'], 380)
        self.assertEqual(result['totaisPorMaterial']['METAL'], 620)
        self.assertEqual(result['quantidades']['PLASTICO'], 2)
        self.assertEqual(self.rng.randint.call_count, 2)

    def test_ranges_are_inclusive_and_limited_to_balance(self):
        self.sim.start_lot('LOTE-001', 250)
        self.rng.randint.return_value = 250
        result = self.piece('EVT-001')
        self.rng.randint.assert_called_once_with(100, 250)
        self.assertEqual(result['tipoCalculo'], 'ALEATORIO')
        self.assertEqual(result['statusLote'], 'CONCLUIDO')

    def test_balance_equal_to_minimum_is_not_adjusted(self):
        self.sim.start_lot('L', 100)
        self.rng.randint.return_value = 100
        result = self.piece('E')
        self.rng.randint.assert_called_once_with(100, 100)
        self.assertEqual(result['tipoCalculo'], 'ALEATORIO')

    def test_tiny_lot_is_closed_by_adjustment(self):
        self.sim.start_lot('L', 1)
        result = self.piece('E')
        self.assertEqual(result['pesoSimuladoGramas'], 1)
        self.assertEqual(result['tipoCalculo'], 'AJUSTE_SALDO')
        self.assertEqual(result['saldoLoteGramas'], 0)
        self.rng.randint.assert_not_called()

    def test_duplicate_and_closed_lot_never_change_totals(self):
        self.sim.start_lot('L', 100)
        self.rng.randint.return_value = 100
        self.piece('E')
        before = self.sim.snapshot()
        self.assertEqual(self.piece('E')['motivo'], 'EVENTO_DUPLICADO')
        self.assertEqual(self.piece('E2')['motivo'], 'LOTE_ENCERRADO')
        self.assertEqual(self.sim.snapshot(), before)
        self.rng.randint.assert_called_once()

    def test_all_materials_never_exceed_lot_total(self):
        sim = BatchWeightSimulation(rng=random.Random(7))
        sim.start_lot('L', 10000)
        materials = list(config.BATCH_WEIGHT_RANGES_G)
        for index in range(1000):
            material = materials[index % len(materials)]
            result = sim.account_piece({'eventoId': str(index), 'material': material})
            self.assertTrue(result['sucesso'])
            self.assertLessEqual(result['pesoProcessadoGramas'], 10000)
            self.assertGreater(result['pesoSimuladoGramas'], 0)
            self.assertEqual(sum(result['totaisPorMaterial'].values()), result['pesoProcessadoGramas'])
            self.assertEqual(sum(result['quantidades'].values()), index + 1)
            if result['tipoCalculo'] == 'ALEATORIO':
                low, high = config.BATCH_WEIGHT_RANGES_G[material]
                self.assertGreaterEqual(result['pesoSimuladoGramas'], low)
                self.assertLessEqual(result['pesoSimuladoGramas'], high)
            if result['statusLote'] == 'CONCLUIDO':
                break
        self.assertEqual(sim.snapshot()['pesoProcessadoGramas'], 10000)

    def test_lot_validation_and_repeated_registration(self):
        for invalid in (0, -1, 1.5, True, '1000', 2**53, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.sim.start_lot('L', invalid)
        for invalid in ('', ' ', None, 123):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.sim.start_lot(invalid, 1000)
        self.sim.start_lot('L', 1000)
        self.rng.randint.return_value = 100
        self.piece('E')
        before = self.sim.snapshot()
        self.assertEqual(self.sim.start_lot('L', 1000), before)
        with self.assertRaises(BatchConflict):
            self.sim.start_lot('L', 2000)
        with self.assertRaises(BatchConflict):
            self.sim.start_lot('L2', 1000)

    def test_new_lot_requires_new_id_and_resets_subtotals(self):
        self.sim.start_lot('L1', 1)
        self.piece('E')
        data = self.sim.start_lot('L2', 1)
        self.assertEqual(data['pesoProcessadoGramas'], 0)
        self.assertEqual(sum(data['quantidades'].values()), 0)
        self.piece('E2')
        with self.assertRaises(BatchConflict):
            self.sim.start_lot('L1', 1)

    def test_incomplete_events_and_no_lot(self):
        self.assertEqual(self.piece('E')['motivo'], 'LOTE_NAO_CONFIGURADO')
        for event in (None, [], {}, {'eventoId': ''}, {'eventoId': 1, 'material': 'PLASTICO'},
                      {'eventoId': 'E', 'material': 'DESCONHECIDO'}, {'eventoId': 'E', 'material': []}):
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.sim.account_piece(event)

    def test_camera_weights_each_confirmed_track_once_without_esp32(self):
        self.sim.start_lot('L', 5000)
        self.rng.randint.side_effect = lambda low, high: low
        for track_id, (color, material) in enumerate(config.BATCH_MATERIAL_BY_COLOR.items(), 1):
            self.confirm(track_id, color)
            self.confirm(track_id, color)
            self.sim.observe([])
            self.confirm(track_id, color)
            self.assertEqual(self.sim.snapshot()['quantidades'][material], 1)
        self.assertEqual(sum(self.sim.snapshot()['quantidades'].values()), 4)

    def test_camera_noise_does_not_create_weight(self):
        self.sim.start_lot('L', 1000)
        for _ in range(config.SORT_CONFIRM_FRAMES - 1):
            self.sim.observe([{'id': 1, 'color': 'Laranja'}])
        self.sim.observe([])
        self.sim.observe([{'id': 1, 'color': 'Laranja'}])
        self.assertEqual(self.sim.snapshot()['pesoProcessadoGramas'], 0)
        self.rng.randint.assert_not_called()

    def test_same_camera_object_is_not_reweighed_in_next_lot(self):
        self.sim.start_lot('L1', 1)
        self.confirm(1)
        self.sim.start_lot('L2', 1)
        self.confirm(1)
        self.assertEqual(self.sim.snapshot()['pesoProcessadoGramas'], 0)
        self.confirm(2)
        self.assertEqual(self.sim.snapshot()['statusLote'], 'CONCLUIDO')

    def test_concurrent_duplicate_events_are_counted_once(self):
        self.sim.start_lot('L', 10000)
        self.rng.randint.return_value = 100
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: self.piece('E'), range(24)))
        self.assertEqual(sum(result['sucesso'] for result in results), 1)
        self.assertEqual(self.sim.snapshot()['pesoProcessadoGramas'], 100)
        self.rng.randint.assert_called_once()

    def test_summary_cannot_be_used_to_mutate_internal_totals(self):
        self.sim.start_lot('L', 1000)
        data = self.sim.snapshot()
        data['totaisPorMaterial']['PLASTICO'] = 9999
        self.assertEqual(self.sim.snapshot()['totaisPorMaterial']['PLASTICO'], 0)


class BatchApiTests(unittest.TestCase):
    def setUp(self):
        self.sim = BatchWeightSimulation(rng=random.Random(2))
        self.patch = patch.object(app, 'batch_weights', self.sim)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = app.app.test_client()

    def test_register_read_and_account_piece(self):
        response = self.client.post('/api/lote', json={'loteId': 'L', 'pesoTotalLoteGramas': 80})
        self.assertEqual(response.status_code, 200)
        event = {'eventoId': 'E', 'material': 'PLASTICO'}
        result = self.client.post('/api/lote/pecas', json=event)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['pesoSimuladoGramas'], 80)
        self.assertEqual(result.json['tipoCalculo'], 'AJUSTE_SALDO')
        self.assertEqual(self.client.get('/api/lote').json['statusLote'], 'CONCLUIDO')
        self.assertEqual(self.client.post('/api/lote/pecas', json=event).status_code, 409)
        self.assertEqual(self.client.get('/api/detections').json['batch']['pesoProcessadoGramas'], 80)

    def test_invalid_payloads_and_conflicts(self):
        self.assertEqual(self.client.get('/api/lote').json['statusLote'], 'AGUARDANDO_LOTE')
        self.assertEqual(self.client.post('/api/lote', json=[]).status_code, 400)
        self.assertEqual(self.client.post('/api/lote', json={'loteId': 'L', 'pesoTotalLoteGramas': True}).status_code, 400)
        self.assertEqual(self.client.post('/api/lote/pecas', json={'eventoId': 'E', 'material': 'PLASTICO'}).status_code, 409)
        self.assertEqual(self.client.post('/api/lote/pecas', json=None).status_code, 400)
        self.client.post('/api/lote', json={'loteId': 'L', 'pesoTotalLoteGramas': 1000})
        self.assertEqual(self.client.post('/api/lote', json={'loteId': 'L2', 'pesoTotalLoteGramas': 1000}).status_code, 409)
