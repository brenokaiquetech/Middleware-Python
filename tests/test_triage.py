# OPERAÇÃO: testa seleção/início/pausa/conclusão nos controladores, HTTP e WebSocket, sem acionar hardware.
# Execução: python -m unittest discover -s tests -v. Não precisa ligar motores.
import json
import threading
import time
import unittest
from unittest.mock import patch

from flask import Flask
from simple_websocket import Client
from werkzeug.serving import make_server

import app
import config
import vision
from batch_weights import BatchWeightSimulation, BatchConflict
from sorting import SortingController
from temperature import TemperatureSimulation
from triage import TriageController
from websocket_server import init_websocket


# Preparação reutilizada pelos testes unitários, HTTP e WebSocket da operação.
class TriageFixture:
    # Monta controladores novos com relógio falso, catálogo pequeno e telemetria inicial de placa parada.
    def prepare(self):
        self.now = 0.0
        self.settings = patch.multiple(config, BATCH_FINISH_RUN_SECONDS=3.0,
                                      TEMP_STATE_TIMEOUT_SECONDS=1000,
                                      ESP32_HANDSHAKE_TIMEOUT_SECONDS=.2)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.batches = BatchWeightSimulation()
        self.sorter = SortingController(clock=lambda: self.now)
        self.sorter.acquire_consumer()
        self.thermal = TemperatureSimulation(clock=lambda: self.now)
        self.thermal.report(False, False)
        self.operation = TriageController(self.batches, self.sorter, self.thermal, catalog=[
            {'loteId': 'A', 'nome': 'Lote A', 'pesoTotalLoteGramas': 1},
            {'loteId': 'B', 'nome': 'Lote B', 'pesoTotalLoteGramas': 1000},
        ], clock=lambda: self.now)
        self.operation.set_device_ready(True)

    # Repete observações pelo número de quadros exigido para simular uma peça estável na câmera.
    def confirm(self, track_id=1):
        for _ in range(config.SORT_CONFIRM_FRAMES):
            self.sorter.observe([{'id': track_id, 'color': 'Laranja'}])

    # Insere uma peça suficiente para fechar o pequeno lote usado no cenário de conclusão.
    def complete_weight(self):
        self.batches.account_piece({'eventoId': 'LAST', 'material': 'PLASTICO'})


# Agrupa cenários deste componente; cada assert compara o resultado com a regra esperada.
class TriageTests(TriageFixture, unittest.TestCase):
    # Prepara um cenário isolado antes de cada teste; patches são restaurados para não contaminar os demais.
    def setUp(self):
        self.prepare()

    # Selecionar um lote apenas prepara a operação, sem peso ou comando antes do início.
    def test_selection_does_not_start_motor_commands_or_weight_simulation(self):
        self.operation.select('A')
        self.confirm()
        self.assertFalse(self.operation.snapshot()['enabled'])
        self.assertEqual(self.batches.snapshot()['statusLote'], 'AGUARDANDO_LOTE')
        self.assertIsNone(self.sorter.current_command())

    # Iniciar exige selecionar; repetir início do mesmo lote não apaga o progresso.
    def test_explicit_start_activates_selected_lot_and_is_idempotent(self):
        with self.assertRaises(BatchConflict):
            self.operation.start('A')
        self.operation.select('A')
        self.assertTrue(self.operation.start('A')['enabled'])
        self.confirm()
        self.assertEqual(self.sorter.current_command()['track_id'], 1)
        self.assertEqual(self.batches.snapshot()['loteId'], 'A')
        self.assertTrue(self.operation.start('A')['enabled'])

    # Placa sem handshake ou bloqueio térmico impedem a autorização inicial.
    def test_start_requires_ready_device_and_cleared_thermal_block(self):
        self.operation.select('A')
        self.operation.set_device_ready(False)
        with self.assertRaises(BatchConflict):
            self.operation.start('A')
        self.operation.set_device_ready(True)
        self.thermal.thermal_blocked = True
        with self.assertRaises(BatchConflict):
            self.operation.start('A')

    # Pausa mantém o lote e permite retomada explícita, bloqueando comandos enquanto parado.
    def test_pause_blocks_new_pieces_without_losing_selected_lot(self):
        self.operation.select('A')
        self.operation.start('A')
        self.operation.pause()
        self.confirm()
        self.assertIsNone(self.sorter.current_command())
        self.assertEqual(self.operation.snapshot()['status'], 'PAUSADO')
        self.assertEqual(self.batches.snapshot()['loteId'], 'A')
        self.assertTrue(self.operation.start('A')['enabled'])

    # Pode trocar antes de iniciar, mas um lote incompleto bloqueia a escolha de outro.
    def test_another_lot_cannot_replace_unfinished_processing(self):
        self.operation.select('A')
        self.operation.select('B')  # Pode trocar antes de iniciar.
        with self.assertRaises(BatchConflict):
            self.operation.start('A')  # Dashboard antigo não inicia outro lote.
        self.operation.start('B')
        self.operation.pause()
        with self.assertRaises(BatchConflict):
            self.operation.select('A')

    # Fechar o peso aguarda o intervalo de transporte final antes de retirar a autorização.
    def test_completion_waits_for_final_transport_then_disables_motor_authorization(self):
        self.operation.select('A')
        self.operation.start('A')
        self.complete_weight()
        self.thermal.report(True, False)
        self.assertEqual(self.operation.snapshot()['status'], 'FINALIZANDO')
        self.now = 2.9
        self.assertTrue(self.operation.snapshot()['enabled'])
        self.now = 3.0
        self.assertFalse(self.operation.snapshot()['enabled'])
        self.assertEqual(self.operation.snapshot()['status'], 'CONCLUIDO')
        self.assertFalse(self.sorter.operation_enabled)
        self.thermal.report(False, False)
        self.operation.select('B')
        self.assertTrue(self.operation.start('B')['enabled'])
        self.assertEqual(self.batches.snapshot()['pesoProcessadoGramas'], 0)

    # Ciclo pendente e parada térmica não podem contar como entrega da última peça.
    def test_completion_waits_for_servo_ack_and_does_not_count_cooling_as_transport(self):
        self.operation.select('A')
        self.operation.start('A')
        self.confirm()
        command = self.sorter.current_command()
        self.complete_weight()
        self.thermal.report(True, False)
        self.now = 10
        self.assertTrue(self.operation.snapshot()['enabled'])
        self.sorter.acknowledge(command['command_id'], 'done')
        self.thermal.report(False, True)
        self.now = 50
        self.assertTrue(self.operation.snapshot()['enabled'])
        self.thermal.report(False, True)
        self.thermal.release_thermal_block()
        self.thermal.report(True, False)
        self.operation.snapshot()
        self.now = 53
        self.assertFalse(self.operation.snapshot()['enabled'])

    # O catálogo indica conclusão e recusa IDs duplicados na configuração.
    def test_catalog_marks_done_and_disallows_duplicate_entries(self):
        self.operation.select('A')
        self.operation.start('A')
        self.complete_weight()
        self.thermal.report(True, False)
        self.operation.snapshot()
        self.now = 3
        self.operation.snapshot()
        self.assertEqual(self.operation.available_lots()[0]['status'], 'CONCLUIDO')
        with self.assertRaises(ValueError):
            TriageController(self.batches, self.sorter, self.thermal, catalog=[
                {'loteId': 'X', 'pesoTotalLoteGramas': 1},
                {'loteId': 'X', 'pesoTotalLoteGramas': 2},
            ])

    # O peso cadastrado na API prevalece sobre o exemplo sem reiniciar a produção.
    def test_lot_registered_by_existing_api_overrides_demo_weight_without_reset(self):
        self.operation.select('A')
        self.batches.start_lot('A', 50)
        self.assertEqual(self.operation.available_lots()[0]['pesoTotalLoteGramas'], 50)
        self.assertEqual(self.operation.snapshot()['pesoTotalLoteGramas'], 50)
        self.assertTrue(self.operation.start('A')['enabled'])
        self.assertEqual(self.batches.snapshot()['pesoTotalLoteGramas'], 50)


# Casos da API HTTP: cliente Flask em memória, com controladores substituídos por instâncias de teste.
class TriageApiTests(TriageFixture, unittest.TestCase):
    # Prepara um cenário isolado antes de cada teste; patches são restaurados para não contaminar os demais.
    def setUp(self):
        self.prepare()
        for target, name, value in (
            (app, 'triage', self.operation), (app, 'batch_weights', self.batches),
            (app, 'temperature', self.thermal), (vision, 'latest_frame', object()),
            (vision, 'latest_detections', []), (vision.background_filter, 'ready', True),
            (vision, 'background_reset_requested', False),
        ):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.http = app.app.test_client()

    # A raiz entrega seleção e o painel exige lote correspondente, sem autorizar motores.
    def test_root_is_lot_selection_and_dashboard_requires_selected_lot(self):
        with self.http.get('/') as response:
            self.assertIn('Qual lote'.encode(), response.data)
        self.assertEqual(self.http.get('/dashboard').status_code, 302)
        response = self.http.post('/api/lotes/selecionar', json={'loteId': 'A'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['triagem']['enabled'])
        with self.http.get(response.json['url']) as dashboard:
            self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(self.http.get('/dashboard?lote=B').status_code, 302)
        self.assertFalse(self.http.get('/api/detections').json['triagem']['enabled'])

    # As rotas verificam seleção e câmera; pausa não apaga os pesos do lote.
    def test_start_requires_selection_and_camera_then_pause_preserves_progress(self):
        self.assertEqual(self.http.post('/api/triagem/iniciar', json={'loteId': 'A'}).status_code, 409)
        self.http.post('/api/lotes/selecionar', json={'loteId': 'A'})
        with patch.object(vision, 'latest_frame', None):
            self.assertEqual(self.http.post('/api/triagem/iniciar', json={'loteId': 'A'}).status_code, 409)
        response = self.http.post('/api/triagem/iniciar', json={'loteId': 'A'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['triagem']['enabled'])
        self.assertFalse(self.http.post('/api/triagem/pausar').json['triagem']['enabled'])
        self.assertEqual(self.batches.snapshot()['loteId'], 'A')

    # Dados incorretos e uma aba de lote antigo não podem iniciar uma operação diferente.
    def test_invalid_selection_and_stale_dashboard_do_not_start(self):
        self.assertEqual(self.http.post('/api/lotes/selecionar', json=[]).status_code, 400)
        self.assertEqual(self.http.post('/api/lotes/selecionar', json={'loteId': 'X'}).status_code, 404)
        self.http.post('/api/lotes/selecionar', json={'loteId': 'A'})
        self.http.post('/api/lotes/selecionar', json={'loteId': 'B'})
        self.assertEqual(self.http.post('/api/triagem/iniciar', json={'loteId': 'A'}).status_code, 409)
        self.assertFalse(self.operation.snapshot()['enabled'])
        self.assertEqual(len(self.http.get('/api/lotes').json['lotes']), 2)


# Casos de comunicação: servidor e clientes locais reais, sem conexão à ESP32 física.
class TriageSocketTests(TriageFixture, unittest.TestCase):
    # Prepara um cenário isolado antes de cada teste; patches são restaurados para não contaminar os demais.
    def setUp(self):
        self.prepare()
        self.sorter.release_consumer()
        self.operation.set_device_ready(False)
        application = Flask(__name__)
        init_websocket(application, lambda: {}, self.sorter, self.thermal, self.operation)
        self.server = make_server('127.0.0.1', 0, application, threaded=True)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.url = f'ws://127.0.0.1:{self.server.server_port}{config.SORT_WS_PATH}'
        self.clients = []

    # Fecha conexões e restaura o estado modificado pelo cenário, liberando recursos de rede/thread.
    def tearDown(self):
        for client in self.clients:
            if client.connected:
                client.close()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)

    # Abre um cliente no servidor local do teste e guarda a conexão para fechar ao final.
    def connect(self, modern=True):
        client = Client.connect(self.url)
        self.clients.append(client)
        if modern:
            client.send(json.dumps({'type': 'client_hello', 'protocol': 2, 'operator_start': True}))
        return client

    # Espera a mensagem com prazo limitado e a converte de texto JSON para um objeto Python.
    def receive(self, client):
        return json.loads(client.receive(timeout=3))

    # Firmware sem protocolo de início por operador recebe erro antes de qualquer hello.
    def test_old_firmware_never_receives_auto_start_hello(self):
        client = self.connect(modern=False)
        self.assertEqual(self.receive(client)['type'], 'error')
        self.assertFalse(self.operation.snapshot()['device_ready'])

    # Somente o início explícito produz triage_control habilitado pela conexão da placa.
    def test_selecting_and_opening_do_not_authorize_until_explicit_start(self):
        client = self.connect()
        hello = self.receive(client)
        self.assertFalse(hello['triage_enabled'])
        self.operation.select('A')
        self.confirm()
        self.assertIsNone(client.receive(timeout=.1))
        self.operation.start('A')
        control = self.receive(client)
        self.assertEqual(control['type'], 'triage_control')
        self.assertTrue(control['enabled'])
        self.operation.pause()
        self.assertFalse(self.receive(client)['enabled'])

    # Mesmo sem dashboard, o WebSocket detecta conclusão e envia a pausa após o transporte final.
    def test_lot_completion_stops_without_browser_after_last_piece_transport(self):
        client = self.connect()
        hello = self.receive(client)
        self.operation.select('A')
        self.operation.start('A')
        self.assertTrue(self.receive(client)['enabled'])
        self.complete_weight()
        client.send(json.dumps({'type': 'conveyor_state', 'session_id': hello['session_id'],
                                'running': True, 'thermal_blocked': False, 'triage_enabled': True}))
        deadline = time.monotonic() + 2
        while self.operation.finish_since is None and time.monotonic() < deadline:
            threading.Event().wait(.01)
        self.assertIsNotNone(self.operation.finish_since)
        self.now = 3
        control = self.receive(client)
        self.assertEqual(control['type'], 'triage_control')
        self.assertFalse(control['enabled'])
        self.assertEqual(self.operation.snapshot()['status'], 'CONCLUIDO')
