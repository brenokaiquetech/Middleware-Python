"""Envio das detecções por WebSocket para clientes como a ESP32."""
import json
import time

from flask_sock import Sock
from simple_websocket import ConnectionClosed

import config


def init_websocket(app, get_snapshot, sorter, temperature=None):
    app.config["SOCK_SERVER_OPTIONS"] = {
        "ping_interval": config.WS_PING_INTERVAL,
        "max_message_size": 4096,
    }
    sock = Sock(app)

    @sock.route(config.WS_PATH)
    def detections(ws):
        try:
            while ws.connected:
                ws.send(json.dumps(get_snapshot(), ensure_ascii=False))
                time.sleep(config.WS_SEND_INTERVAL)
        except ConnectionClosed:
            # Desconectar/reconectar a placa faz parte do uso normal.
            pass

    @sock.route(config.SORT_WS_PATH)
    def sorting_commands(ws):
        # Apenas uma placa controla o prato. Clientes de monitoramento usam
        # /ws/detections e não recebem instruções de movimento.
        if not sorter.acquire_consumer():
            ws.send(json.dumps({'type': 'error', 'reason': 'sorter_already_connected'}))
            ws.close()
            return
        try:
            ws.send(json.dumps({'type': 'hello', 'session_id': sorter.session_id}))
            sent_command = None
            deadline = None
            while ws.connected:
                if sent_command is None:
                    command = sorter.current_command()
                    if command is not None:
                        ws.send(json.dumps(command, ensure_ascii=False))
                        sent_command = command['command_id']
                        deadline = time.monotonic() + config.SORT_ACK_TIMEOUT_SECONDS
                if deadline is not None and time.monotonic() >= deadline:
                    sorter.cancel_command(sent_command)
                    ws.close()
                    return
                # Receba estado também quando não há um ciclo em andamento.
                raw = ws.receive(timeout=config.SORT_POLL_INTERVAL_SECONDS)
                if raw is None:
                    continue
                try:
                    message = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if (not isinstance(message, dict)
                        or message.get('session_id') != sorter.session_id):
                    continue
                if message.get('type') == 'conveyor_state':
                    running = message.get('running')
                    if temperature is not None and isinstance(running, bool):
                        temperature.report(running)
                elif (message.get('type') == 'ack'
                      and sent_command is not None
                      and message.get('command_id') == sent_command
                      and sorter.acknowledge(sent_command, message.get('status'))):
                    running = message.get('conveyor_running')
                    if temperature is not None and isinstance(running, bool):
                        temperature.report(running)
                    sent_command = None
                    deadline = None
        except ConnectionClosed:
            pass
        finally:
            if temperature is not None:
                temperature.disconnect()
            sorter.release_consumer()

    return sock
