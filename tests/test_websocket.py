# MONITORAMENTO: inicia um servidor local e compara os retratos recebidos por HTTP e WebSocket.
# Execução: python -m unittest discover -s tests -v. Não precisa ligar motores.
"""Integração HTTP/WebSocket, sem precisar da câmera ou da ESP32.

Execute: python -m unittest discover -s tests -v
"""
import json
import threading
import time
import unittest

from werkzeug.serving import make_server
from simple_websocket import Client

import app
import config
import vision


# Casos de comunicação: servidor e clientes locais reais, sem conexão à ESP32 física.
class WebSocketTests(unittest.TestCase):
    # Prepara os recursos compartilhados uma única vez para os testes desta classe.
    @classmethod
    def setUpClass(cls):
        cls.server = make_server('127.0.0.1', 0, app.app, threaded=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'ws://127.0.0.1:{cls.server.server_port}{config.WS_PATH}'

    # Encerra o servidor compartilhado e aguarda sua thread ao terminar os testes da classe.
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    # Prepara um cenário isolado antes de cada teste; patches são restaurados para não contaminar os demais.
    def setUp(self):
        self.clients = []
        with vision.lock:
            self.previous = (vision.latest_frame, vision.latest_detections, vision.roi)
            vision.latest_frame = None
            vision.latest_detections = []

    # Fecha conexões e restaura o estado modificado pelo cenário, liberando recursos de rede/thread.
    def tearDown(self):
        for client in self.clients:
            if client.connected:
                client.close()
        with vision.lock:
            vision.latest_frame, vision.latest_detections, vision.roi = self.previous

    # Abre um cliente no servidor local do teste e guarda a conexão para fechar ao final.
    def connect(self):
        client = Client.connect(self.url)
        self.clients.append(client)
        return client

    # Espera a mensagem com prazo limitado e a converte de texto JSON para um objeto Python.
    def receive(self, client):
        message = client.receive(timeout=3)
        self.assertIsInstance(message, str)
        return json.loads(message)

    # HTTP e WebSocket devem publicar o mesmo estado, inclusive após reconectar.
    def test_updates_match_http_and_reconnect(self):
        client = self.connect()
        self.assertEqual(self.receive(client), app.app.test_client().get('/api/detections').json)
        # As atualizações continuam mesmo sem enviar uma inscrição ou comando.
        started = time.monotonic()
        self.assertEqual(self.receive(client)['count'], 0)
        self.assertGreaterEqual(time.monotonic() - started, config.WS_SEND_INTERVAL * 0.5)
        detection = {
            'id': 7, 'color': 'Azul-claro', 'x': 120, 'y': 150,
            'w': 40, 'h': 40, 'area': 1521,
            'material': 'Categoria estimada pela cor',
        }
        with vision.lock:
            vision.latest_frame = object()
            vision.latest_detections = [detection]
        data = self.receive(client)
        self.assertEqual(data, app.app.test_client().get('/api/detections').json)
        self.assertTrue(data['connected'])
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['counts']['Azul-claro'], 1)
        expected = {**detection, 'material': 'Metal', 'container': 'C'}
        self.assertEqual(data['detections'], [expected])
        client.close()
        reconnected = self.connect()
        self.assertEqual(self.receive(reconnected), data)

    # Observadores simultâneos recebem o mesmo retrato e a API valida o ajuste de ROI.
    def test_multiple_clients_and_roi(self):
        first = self.connect()
        second = self.connect()
        self.assertEqual(self.receive(first), self.receive(second))
        http = app.app.test_client()
        roi = {'x': .2, 'y': .25, 'w': .5, 'h': .4}
        self.assertEqual(http.post('/api/roi', json=roi).status_code, 200)
        self.assertEqual(vision.roi, roi)
        self.assertEqual(http.post('/api/roi', json={}).status_code, 400)
        with http.get('/') as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.receive(first), self.receive(second))


if __name__ == '__main__':
    unittest.main()
