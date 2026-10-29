# VELOCIDADE SIMULADA: calcula um indicador visual usando o peso acumulado como carga.
# O resultado não altera o PWM nem mede a velocidade física da esteira.
"""Modelo didático de carga do servo e velocidade da esteira; sem sensores."""
import math

import config


# Transforma gramas em força fictícia e reduz a velocidade visual conforme a carga aumenta.
def simulated_motion(motor_state, batch):
    base = config.CONVEYOR_ESTIMATED_SPEED_M_S
    factor = config.SERVO_SIMULATED_FORCE_PER_KG_N
    reference = config.CONVEYOR_SIMULATED_FORCE_REFERENCE_N
    if (not all(math.isfinite(value) for value in (base, factor, reference))
            or base < 0 or factor < 0 or reference <= 0):
        raise ValueError('Configuração de velocidade/força simulada inválida em config.py.')
    # A carga é o peso já processado: dividir por 1000 converte gramas em quilogramas.
    load_g = batch.get('pesoProcessadoGramas', 0)
    force = load_g / 1000.0 * factor
    # A fórmula reduz suavemente a referência; força igual à referência resulta em metade da velocidade.
    speed = base / (1.0 + force / reference)
    known = motor_state['state_known']
    running = motor_state['conveyor_running']
    # Motor parado mostra zero; sem telemetria o valor é None, que o JSON transmite como null.
    return {
        'running': running,
        'state_known': known,
        'speed_m_s': (speed if running else 0.0) if known else None,
        'speed_estimated': True,
        'speed_simulated': True,
        'servo_force_n': round(force, 3),
        'servo_load_g': load_g,
    }
