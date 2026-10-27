"""Um único quadro pendente: substitua o antigo quando a captura avançar."""
import threading
import time


class LatestCameraFrame:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.condition = threading.Condition()
        self.pending = None

    def publish(self, frame):
        with self.condition:
            self.pending = (frame, self.clock())
            self.condition.notify()

    def take(self, timeout):
        with self.condition:
            if not self.condition.wait_for(lambda: self.pending is not None, timeout):
                return None
            frame = self.pending
            self.pending = None
            return frame

    def clear(self):
        with self.condition:
            self.pending = None
