"""Extrai JPEGs de um fluxo MJPEG, recuperando quadros incompletos.

Respeita tamanhos dos segmentos JPEG para não confundir uma miniatura EXIF
com o início do próximo quadro. Não valida a integridade dos dados comprimidos.
"""


class JPEGStreamParser:
    def __init__(self, max_frame_bytes):
        if max_frame_bytes < 4:
            raise ValueError('O limite de tamanho do JPEG deve ser pelo menos 4 bytes.')
        self.maximum = max_frame_bytes
        self.buffer = bytearray()
        self.position = 0
        self.started = False
        self.in_scan = False
        self.saw_scan = False

    def _restart(self, offset):
        del self.buffer[:offset]
        self.position = 0
        self.started = False
        self.in_scan = False
        self.saw_scan = False

    def _incomplete(self):
        if len(self.buffer) > self.maximum:
            self._restart(1)
            return False
        return True

    def feed(self, chunk):
        self.buffer.extend(chunk)
        frames = []
        while True:
            if not self.started:
                start = self.buffer.find(b'\xff\xd8')
                if start < 0:
                    # Preserve um FF final: o D8 pode vir no próximo chunk.
                    tail = b'\xff' if self.buffer.endswith(b'\xff') else b''
                    self.buffer[:] = tail
                    break
                del self.buffer[:start]
                self.started = True
                self.position = 2

            if self.position >= len(self.buffer):
                if self._incomplete():
                    break
                continue

            if self.in_scan:
                marker_start = self.buffer.find(b'\xff', self.position)
                if marker_start < 0:
                    self.position = len(self.buffer)
                    if self._incomplete():
                        break
                    continue
                self.position = marker_start
            elif self.buffer[self.position] != 0xff:
                self._restart(1)
                continue

            marker_end = self.position + 1
            while marker_end < len(self.buffer) and self.buffer[marker_end] == 0xff:
                marker_end += 1
            if marker_end >= len(self.buffer):
                if self._incomplete():
                    break
                continue
            code = self.buffer[marker_end]
            if self.in_scan and (code == 0 or 0xd0 <= code <= 0xd7):
                self.position = marker_end + 1
                continue
            if code == 0xd8:
                # Um novo SOI antes do EOI: abandone o quadro anterior.
                self._restart(marker_end - 1)
                continue
            if code == 0xd9:
                end = marker_end + 1
                if self.saw_scan and end <= self.maximum:
                    frames.append(bytes(self.buffer[:end]))
                self._restart(end)
                continue
            if code == 0 or 0xd0 <= code <= 0xd7:
                self._restart(1)
                continue
            if code == 1:  # TEM: marcador sem comprimento.
                self.position = marker_end + 1
                continue

            # SOF/DHT/APP/SOS etc. têm comprimento de 2 bytes, incluindo o próprio campo.
            length_start = marker_end + 1
            if length_start + 2 > len(self.buffer):
                if self._incomplete():
                    break
                continue
            length = int.from_bytes(self.buffer[length_start:length_start + 2], 'big')
            end = length_start + length
            if length < 2 or end > self.maximum:
                self._restart(1)
                continue
            if end > len(self.buffer):
                if self._incomplete():
                    break
                continue
            self.position = end
            self.in_scan = code == 0xda
            if self.in_scan:
                self.saw_scan = True
        return frames
