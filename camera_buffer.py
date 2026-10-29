# CAPTURA SEM FILA: compartilha somente o quadro pendente mais recente entre duas threads.
# O instante de publicação permite descartar imagens que ficaram velhas no processamento local.
"""Um único quadro pendente: substitua o antigo quando a captura avançar."""
import threading
import time


# Uma posição de memória compartilhada substitui uma fila de imagens antigas.
class LatestCameraFrame:
    # Condition combina lock e aviso para acordar quem espera o próximo quadro.
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.condition = threading.Condition()
        self.pending = None

    # Sobrescreve o quadro pendente com a nova imagem e seu horário, acordando o consumidor.
    def publish(self, frame):
        with self.condition:
            self.pending = (frame, self.clock())
            self.condition.notify()

    # Espera até o timeout e retira o único quadro pendente; None significa que nada chegou a tempo.
    def take(self, timeout):
        with self.condition:
            if not self.condition.wait_for(lambda: self.pending is not None, timeout):
                return None
            frame = self.pending
            self.pending = None
            return frame

    # Apaga o quadro ainda não consumido para não analisar imagem antiga depois da desconexão.
    def clear(self):
        with self.condition:
            self.pending = None
