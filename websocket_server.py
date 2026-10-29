# COMUNICAÇÃO: /ws/detections transmite o estado; /ws/sorter troca comandos e confirmações.
# A autorização do operador e o bloqueio térmico também chegam à ESP32 por essa conexão.
"""Envio das detecções por WebSocket para clientes como a ESP32."""
import json
import time

from flask_sock import Sock
from simple_websocket import ConnectionClosed

import config


# Registra duas rotas; recebe os controladores por parâmetro para permitir testes isolados.
def init_websocket(app, get_snapshot, sorter, temperature=None, triage=None):
    # Ping mantém a conexão monitorada; o limite de mensagem evita JSONs excessivamente grandes.
    app.config["SOCK_SERVER_OPTIONS"] = {
        "ping_interval": config.WS_PING_INTERVAL,
        "max_message_size": 4096,
    }
    sock = Sock(app)

    # Publica retratos periódicos do estado para observadores; não envia instruções de movimento.
    @sock.route(config.WS_PATH)
    def detections(ws):
        try:
            while ws.connected:
                ws.send(json.dumps(get_snapshot(), ensure_ascii=False))
                time.sleep(config.WS_SEND_INTERVAL)
        except ConnectionClosed:
            # Desconectar/reconectar a placa faz parte do uso normal.
            pass

    # Reserva uma única ESP32, valida o protocolo e acompanha o ciclo até ACK ou timeout.
    @sock.route(config.SORT_WS_PATH)
    def sorting_commands(ws):
        # Apenas uma placa controla o prato. Clientes de monitoramento usam
        # /ws/detections e não recebem instruções de movimento.
        if not sorter.acquire_consumer():
            ws.send(json.dumps({'type': 'error', 'reason': 'sorter_already_connected'}))
            ws.close()
            return
        try:
            # O handshake de protocolo 2 comprova que o firmware exige início explícito por lote.
            if triage is not None:
                triage.set_device_ready(False)
                raw = ws.receive(timeout=config.ESP32_HANDSHAKE_TIMEOUT_SECONDS)
                try:
                    client = json.loads(raw) if raw else None
                except (ValueError, TypeError):
                    client = None
                if (not isinstance(client, dict) or client.get('type') != 'client_hello'
                        or client.get('protocol') != 2 or client.get('operator_start') is not True):
                    # Firmware antigo não recebe hello: assim não pode partir sozinho.
                    ws.send(json.dumps({'type': 'error', 'reason': 'Atualize o firmware para iniciar por lote.'}))
                    ws.close()
                    return
                triage.set_device_ready(True)
            # O hello estabelece a sessão e os bloqueios antes de qualquer comando de movimento.
            thermal_blocked = temperature.snapshot()['thermal_blocked'] if temperature is not None else False
            triage_enabled = triage.snapshot()['enabled'] if triage is not None else True
            sorter.set_thermal_blocked(thermal_blocked)
            ws.send(json.dumps({'type': 'hello', 'session_id': sorter.session_id,
                                'thermal_blocked': thermal_blocked, 'triage_enabled': triage_enabled}))
            # Marca apenas o comando já transmitido; o ACK precisa corresponder a ele e à sessão atual.
            sent_command = None
            deadline = None
            while ws.connected:
                # Esta verificação independe da câmera e do navegador.
                blocked = temperature.snapshot()['thermal_blocked'] if temperature is not None else False
                sorter.set_thermal_blocked(blocked)
                if blocked != thermal_blocked:
                    ws.send(json.dumps({'type': 'thermal_control', 'session_id': sorter.session_id,
                                        'blocked': blocked}))
                    thermal_blocked = blocked
                enabled = triage.snapshot()['enabled'] if triage is not None else True
                if enabled != triage_enabled:
                    ws.send(json.dumps({'type': 'triage_control', 'session_id': sorter.session_id,
                                        'enabled': enabled}))
                    triage_enabled = enabled
                # Um ciclo novo só é enviado após o anterior terminar; nenhuma peça fica em fila.
                if sent_command is None:
                    command = sorter.current_command()
                    if command is not None:
                        if blocked or not enabled:
                            # Não guarde uma peça esperando a liberação térmica.
                            sorter.cancel_command(command['command_id'], allow_retry=True)
                        else:
                            ws.send(json.dumps(command, ensure_ascii=False))
                            sent_command = command['command_id']
                            deadline = time.monotonic() + config.SORT_ACK_TIMEOUT_SECONDS
                # Sem confirmação até o prazo, cancela e desconecta; a placa trata a queda parando o transporte.
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
                # Telemetria informa o acionamento declarado pela placa; não é leitura de sensor de movimento.
                if message.get('type') == 'conveyor_state':
                    running = message.get('running')
                    if temperature is not None and isinstance(running, bool):
                        temperature.report(running, message.get('thermal_blocked'))
                elif (message.get('type') == 'ack'
                      and sent_command is not None
                      and message.get('command_id') == sent_command
                      and sorter.acknowledge(sent_command, message.get('status'))):
                    running = message.get('conveyor_running')
                    if temperature is not None and isinstance(running, bool):
                        temperature.report(running, message.get('thermal_blocked'))
                    sent_command = None
                    deadline = None
        except ConnectionClosed:
            pass
        # A limpeza acontece tanto em desconexão normal quanto em erro, liberando a vaga da placa.
        finally:
            if triage is not None:
                triage.set_device_ready(False)
            if temperature is not None:
                temperature.disconnect()
            sorter.release_consumer()

    return sock
