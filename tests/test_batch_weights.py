# PESO SIMULADO: testa faixas, saldo final, duplicatas, concorrência e as rotas HTTP de lote/peça.
# Execução: python -m unittest discover -s tests -v. Não precisa ligar motores.
from concurrent.futures import ThreadPoolExecutor
import random
import unittest
from unittest.mock import Mock, patch

import app
import config
from batch_weights import BatchConflict, BatchWeightSimulation


# Agrupa cenários deste componente; cada assert compara o resultado com a regra esperada.
class BatchWeightTests(unittest.TestCase):
    # Prepara um cenário isolado antes de cada teste; patches são restaurados para não contaminar os demais.
    def setUp(self):
        self.rng = Mock()
        self.sim = BatchWeightSimulation(rng=self.rng)

    # Cria o evento mínimo de uma peça para chamar diretamente o simulador de peso.
    def piece(self, event_id, material='PLASTICO'):
        return self.sim.account_piece({'eventoId': event_id, 'material': material})

    # Repete observações pelo número de quadros exigido para simular uma peça estável na câmera.
    def confirm(self, track_id, color='Laranja'):
        for _ in range(config.SORT_CONFIRM_FRAMES):
            self.sim.observe([{'id': track_id, 'color': color}])

    # Reproduz o saldo de 80 g do documento e fecha o lote sem ultrapassar o total.
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

    # O sorteio inclui os extremos e limita o máximo ao saldo que resta no lote.
    def test_ranges_are_inclusive_and_limited_to_balance(self):
        self.sim.start_lot('LOTE-001', 250)
        self.rng.randint.return_value = 250
        result = self.piece('EVT-001')
        self.rng.randint.assert_called_once_with(100, 250)
        self.assertEqual(result['tipoCalculo'], 'ALEATORIO')
        self.assertEqual(result['statusLote'], 'CONCLUIDO')

    # Saldo igual ao mínimo ainda usa o sorteio, sem classificar como ajuste final.
    def test_balance_equal_to_minimum_is_not_adjusted(self):
        self.sim.start_lot('L', 100)
        self.rng.randint.return_value = 100
        result = self.piece('E')
        self.rng.randint.assert_called_once_with(100, 100)
        self.assertEqual(result['tipoCalculo'], 'ALEATORIO')

    # Um lote menor que a faixa do material usa todo o saldo sem chamar o gerador aleatório.
    def test_tiny_lot_is_closed_by_adjustment(self):
        self.sim.start_lot('L', 1)
        result = self.piece('E')
        self.assertEqual(result['pesoSimuladoGramas'], 1)
        self.assertEqual(result['tipoCalculo'], 'AJUSTE_SALDO')
        self.assertEqual(result['saldoLoteGramas'], 0)
        self.rng.randint.assert_not_called()

    # Eventos repetidos ou posteriores ao encerramento não alteram as somas.
    def test_duplicate_and_closed_lot_never_change_totals(self):
        self.sim.start_lot('L', 100)
        self.rng.randint.return_value = 100
        self.piece('E')
        before = self.sim.snapshot()
        self.assertEqual(self.piece('E')['motivo'], 'EVENTO_DUPLICADO')
        self.assertEqual(self.piece('E2')['motivo'], 'LOTE_ENCERRADO')
        self.assertEqual(self.sim.snapshot(), before)
        self.rng.randint.assert_called_once()

    # Uma sequência de materiais mantém subtotais e quantidades coerentes até o fechamento exato.
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

    # Rejeita pesos/IDs inválidos e preserva o progresso quando o mesmo cadastro é repetido.
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

    # Um lote seguinte limpa seus próprios totais e não pode reutilizar um ID já concluído.
    def test_new_lot_requires_new_id_and_resets_subtotals(self):
        self.sim.start_lot('L1', 1)
        self.piece('E')
        data = self.sim.start_lot('L2', 1)
        self.assertEqual(data['pesoProcessadoGramas'], 0)
        self.assertEqual(sum(data['quantidades'].values()), 0)
        self.piece('E2')
        with self.assertRaises(BatchConflict):
            self.sim.start_lot('L1', 1)

    # Sem lote ou com evento incompleto, não deve haver contabilização de peso.
    def test_incomplete_events_and_no_lot(self):
        self.assertEqual(self.piece('E')['motivo'], 'LOTE_NAO_CONFIGURADO')
        for event in (None, [], {}, {'eventoId': ''}, {'eventoId': 1, 'material': 'PLASTICO'},
                      {'eventoId': 'E', 'material': 'DESCONHECIDO'}, {'eventoId': 'E', 'material': []}):
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.sim.account_piece(event)

    # O simulador isolado pesa cada ID uma única vez sem depender do hardware.
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

    # Uma observação curta que desaparece antes da confirmação não deve criar peso.
    def test_camera_noise_does_not_create_weight(self):
        self.sim.start_lot('L', 1000)
        for _ in range(config.SORT_CONFIRM_FRAMES - 1):
            self.sim.observe([{'id': 1, 'color': 'Laranja'}])
        self.sim.observe([])
        self.sim.observe([{'id': 1, 'color': 'Laranja'}])
        self.assertEqual(self.sim.snapshot()['pesoProcessadoGramas'], 0)
        self.rng.randint.assert_not_called()

    # Trocar o lote não permite pesar novamente o mesmo ID ainda visível.
    def test_same_camera_object_is_not_reweighed_in_next_lot(self):
        self.sim.start_lot('L1', 1)
        self.confirm(1)
        self.sim.start_lot('L2', 1)
        self.confirm(1)
        self.assertEqual(self.sim.snapshot()['pesoProcessadoGramas'], 0)
        self.confirm(2)
        self.assertEqual(self.sim.snapshot()['statusLote'], 'CONCLUIDO')

    # Requisições concorrentes do mesmo evento precisam resultar em uma única peça.
    def test_concurrent_duplicate_events_are_counted_once(self):
        self.sim.start_lot('L', 10000)
        self.rng.randint.return_value = 100
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: self.piece('E'), range(24)))
        self.assertEqual(sum(result['sucesso'] for result in results), 1)
        self.assertEqual(self.sim.snapshot()['pesoProcessadoGramas'], 100)
        self.rng.randint.assert_called_once()

    # Alterar o snapshot recebido não pode modificar o estado interno do simulador.
    def test_summary_cannot_be_used_to_mutate_internal_totals(self):
        self.sim.start_lot('L', 1000)
        data = self.sim.snapshot()
        data['totaisPorMaterial']['PLASTICO'] = 9999
        self.assertEqual(self.sim.snapshot()['totaisPorMaterial']['PLASTICO'], 0)


# Casos da API HTTP: cliente Flask em memória, com controladores substituídos por instâncias de teste.
class BatchApiTests(unittest.TestCase):
    # Prepara um cenário isolado antes de cada teste; patches são restaurados para não contaminar os demais.
    def setUp(self):
        self.sim = BatchWeightSimulation(rng=random.Random(2))
        self.patch = patch.object(app, 'batch_weights', self.sim)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = app.app.test_client()

    # Exercita cadastro, consulta, peça simulada e rejeição de duplicata pelas rotas HTTP.
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

    # A API distingue dados inválidos (400) de conflitos com o lote atual (409).
    def test_invalid_payloads_and_conflicts(self):
        self.assertEqual(self.client.get('/api/lote').json['statusLote'], 'AGUARDANDO_LOTE')
        self.assertEqual(self.client.post('/api/lote', json=[]).status_code, 400)
        self.assertEqual(self.client.post('/api/lote', json={'loteId': 'L', 'pesoTotalLoteGramas': True}).status_code, 400)
        self.assertEqual(self.client.post('/api/lote/pecas', json={'eventoId': 'E', 'material': 'PLASTICO'}).status_code, 409)
        self.assertEqual(self.client.post('/api/lote/pecas', json=None).status_code, 400)
        self.client.post('/api/lote', json={'loteId': 'L', 'pesoTotalLoteGramas': 1000})
        self.assertEqual(self.client.post('/api/lote', json={'loteId': 'L2', 'pesoTotalLoteGramas': 1000}).status_code, 409)
