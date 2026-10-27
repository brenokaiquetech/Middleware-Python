import json
import threading
import time
import unittest

from flask import Flask
from simple_websocket import Client
from werkzeug.serving import make_server

import config
from sorting import SortingController
from websocket_server import init_websocket
from temperature import TemperatureSimulation


def confirm(controller, track_id=1, color='Laranja'):
    for _ in range(config.SORT_CONFIRM_FRAMES):
        controller.observe([{'id': track_id, 'color': color}])


class SortingTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.sorter = SortingController(clock=lambda: self.now)
        self.sorter.acquire_consumer()

    def test_colors_and_unique_ids(self):
        for track_id, (color, target) in enumerate(config.SORT_TARGETS.items(), 1):
            confirm(self.sorter, track_id, color)
            confirm(self.sorter, track_id, color)
            command = self.sorter.current_command()
            self.assertEqual(command['track_id'], track_id)
            self.assertEqual(command['container'], target['container'])
            self.assertEqual(command['material'], target['material'])
            self.assertEqual(command['angle_deg'], target['angle_deg'])
            self.assertEqual(command['type'], 'sort_cycle')
            self.assertEqual(command['stop_ms'], config.SORT_STOP_MS)
            self.assertEqual(command['settle_ms'], config.SORT_SETTLE_MS)
            self.assertNotIn('hold_ms', command)
            self.assertEqual(self.sorter.current_command(), command)
            self.assertTrue(self.sorter.acknowledge(command['command_id'], 'done'))
            self.sorter.observe([])
            confirm(self.sorter, track_id, color)
            self.assertIsNone(self.sorter.current_command())

    def test_noise_is_not_a_command(self):
        for _ in range(config.SORT_CONFIRM_FRAMES - 1):
            self.sorter.observe([{'id': 1, 'color': 'Laranja'}])
        self.assertIsNone(self.sorter.current_command())
        self.sorter.observe([])
        self.sorter.observe([{'id': 1, 'color': 'Laranja'}])
        self.assertIsNone(self.sorter.current_command())
        self.sorter.observe([{'id': 2, 'color': 'Desconhecida'}])
        self.assertIsNone(self.sorter.current_command())

    def test_busy_objects_are_rechecked_in_new_frames_without_queue(self):
        confirm(self.sorter, 1)
        confirm(self.sorter, 2, 'Roxo')
        first = self.sorter.current_command()
        self.assertFalse(self.sorter.acknowledge('wrong', 'done'))
        self.assertFalse(self.sorter.acknowledge(first['command_id'], 'received'))
        self.assertEqual(self.sorter.current_command(), first)
        self.assertFalse(self.sorter.acquire_consumer())
        self.sorter.release_consumer()
        self.assertTrue(self.sorter.acquire_consumer())
        self.assertTrue(self.sorter.acknowledge(first['command_id'], 'done'))
        self.assertIsNone(self.sorter.current_command())
        # Nenhum comando foi guardado. Uma peça ainda visível precisa ser
        # confirmada novamente nos frames recebidos depois da retomada.
        confirm(self.sorter, 2, 'Roxo')
        second = self.sorter.current_command()
        self.assertEqual(second['track_id'], 2)
        self.sorter.acknowledge(second['command_id'], 'done')
        confirm(self.sorter, 3)
        self.assertEqual(self.sorter.current_command()['track_id'], 3)
        self.now += config.SORT_ACK_TIMEOUT_SECONDS + 1
        self.assertIsNone(self.sorter.current_command())

    def test_offline_detections_require_new_frames_after_reconnection(self):
        self.sorter.release_consumer()
        confirm(self.sorter, 1)
        self.sorter.acquire_consumer()
        self.assertIsNone(self.sorter.current_command())
        confirm(self.sorter, 1)
        self.assertEqual(self.sorter.current_command()['track_id'], 1)

    def test_cancel_current_command(self):
        confirm(self.sorter, 1)
        self.sorter.cancel_command('wrong')
        command = self.sorter.current_command()
        self.assertIsNotNone(command)
        self.sorter.cancel_command(command['command_id'])
        self.assertIsNone(self.sorter.current_command())


class SortingSocketTests(unittest.TestCase):
    def setUp(self):
        self.sorter = SortingController()
        self.temperature = TemperatureSimulation()
        application = Flask(__name__)
        init_websocket(application, lambda: {}, self.sorter, self.temperature)
        self.server = make_server('127.0.0.1', 0, application, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'ws://127.0.0.1:{self.server.server_port}{config.SORT_WS_PATH}'
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            if client.connected:
                client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def connect(self):
        client = Client.connect(self.url)
        self.clients.append(client)
        return client

    def receive(self, client):
        return json.loads(client.receive(timeout=3))

    def wait_for_temperature(self, expected_running, known=True):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = self.temperature.snapshot()
            if state['conveyor_running'] == expected_running and state['state_known'] == known:
                return
            threading.Event().wait(.01)
        self.fail('A telemetria de estado da esteira não chegou.')

    def test_motor_telemetry_is_received_while_idle_and_during_cycle(self):
        client = self.connect()
        hello = self.receive(client)
        client.send(json.dumps({'type': 'conveyor_state', 'session_id': 'wrong', 'running': True}))
        client.send(json.dumps({'type': 'conveyor_state', 'session_id': hello['session_id'], 'running': 'true'}))
        self.assertIsNone(client.receive(timeout=.1))
        self.assertFalse(self.temperature.snapshot()['state_known'])
        client.send(json.dumps({'type': 'conveyor_state', 'session_id': hello['session_id'], 'running': True}))
        self.wait_for_temperature(True)
        confirm(self.sorter, 1)
        command = self.receive(client)
        client.send(json.dumps({'type': 'conveyor_state', 'session_id': hello['session_id'], 'running': False}))
        self.wait_for_temperature(False)
        client.send(json.dumps({'type': 'ack', 'session_id': hello['session_id'],
                                'command_id': command['command_id'], 'status': 'done',
                                'conveyor_running': True}))
        self.wait_for_temperature(True)
        client.close()
        self.wait_for_temperature(False, known=False)

    def test_commands_wait_for_ack_and_reconnect(self):
        client = self.connect()
        self.assertEqual(self.receive(client)['type'], 'hello')
        confirm(self.sorter, 1)
        first = self.receive(client)
        self.assertEqual(first['container'], 'A')
        self.assertEqual(first['type'], 'sort_cycle')
        self.assertEqual(first['stop_ms'], config.SORT_STOP_MS)
        self.assertNotIn('hold_ms', first)
        confirm(self.sorter, 2, 'Roxo')
        self.assertIsNone(client.receive(timeout=.15))
        client.send(json.dumps({'type': 'ack', 'session_id': 'wrong',
                                'command_id': first['command_id'], 'status': 'done'}))
        self.assertIsNone(client.receive(timeout=.15))
        client.close()
        # O handler libera o consumidor ao receber a desconexão.
        deadline = time.monotonic() + 3
        while self.sorter.consumer_connected and time.monotonic() < deadline:
            threading.Event().wait(.01)
        client = self.connect()
        self.assertEqual(self.receive(client)['type'], 'hello')
        self.assertEqual(self.receive(client), first)
        client.send(json.dumps({'type': 'ack', 'session_id': first['session_id'],
                                'command_id': first['command_id'], 'status': 'done'}))
        self.assertIsNone(client.receive(timeout=.15))
        confirm(self.sorter, 3, 'Roxo')
        second = self.receive(client)
        self.assertEqual(second['container'], 'D')
        self.assertEqual(second['angle_deg'], 270)
        self.assertNotEqual(second['command_id'], first['command_id'])

    def test_second_motor_client_is_rejected(self):
        first = self.connect()
        self.assertEqual(self.receive(first)['type'], 'hello')
        second = self.connect()
        self.assertEqual(self.receive(second)['reason'], 'sorter_already_connected')


    def test_same_object_does_not_stop_the_belt_again(self):
        client = self.connect()
        self.assertEqual(self.receive(client)['type'], 'hello')
        confirm(self.sorter, 1)
        first = self.receive(client)
        client.send(json.dumps({'type': 'ack', 'session_id': first['session_id'],
                                'command_id': first['command_id'], 'status': 'done',
                                'conveyor_running': True}))
        self.assertIsNone(client.receive(timeout=.15))
        confirm(self.sorter, 1)
        self.assertIsNone(client.receive(timeout=.15))
        confirm(self.sorter, 2, 'Azul-claro')
        second = self.receive(client)
        self.assertEqual(second['track_id'], 2)
        self.assertEqual(second['container'], 'C')
