# LEITURA MJPEG: os pacotes da rede podem cortar um JPEG em qualquer posição.
# Este parser recompõe imagens por marcadores e tamanhos de segmentos, sem decodificar pixels.
"""Extrai JPEGs de um fluxo MJPEG, recuperando quadros incompletos.

Respeita tamanhos dos segmentos JPEG para não confundir uma miniatura EXIF
com o início do próximo quadro. Não valida a integridade dos dados comprimidos.
"""


# Máquina de estados que preserva bytes entre chamadas e reconhece os limites de cada JPEG.
class JPEGStreamParser:
    # Limita a memória e começa fora de qualquer imagem ou bloco de dados comprimidos.
    def __init__(self, max_frame_bytes):
        if max_frame_bytes < 4:
            raise ValueError('O limite de tamanho do JPEG deve ser pelo menos 4 bytes.')
        self.maximum = max_frame_bytes
        self.buffer = bytearray()
        self.position = 0
        self.started = False
        self.in_scan = False
        self.saw_scan = False

    # Descarta bytes até o ponto indicado e reinicia a busca por um início de imagem válido.
    def _restart(self, offset):
        del self.buffer[:offset]
        self.position = 0
        self.started = False
        self.in_scan = False
        self.saw_scan = False

    # Permite esperar mais bytes apenas enquanto o quadro não excede o limite de memória.
    def _incomplete(self):
        if len(self.buffer) > self.maximum:
            self._restart(1)
            return False
        return True

    # Acrescenta um pacote arbitrário e devolve todos os JPEGs completos encontrados nesse pacote e no anterior.
    def feed(self, chunk):
        self.buffer.extend(chunk)
        frames = []
        while True:
            # SOI (FF D8) abre o JPEG. Bytes HTTP/multipart antes dele são descartados.
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

            # Dentro dos dados comprimidos, procura FF para distinguir marcadores de bytes de imagem.
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
            # FF 00 é um FF escapado e D0–D7 são reinícios válidos da compressão, não um novo quadro.
            if self.in_scan and (code == 0 or 0xd0 <= code <= 0xd7):
                self.position = marker_end + 1
                continue
            if code == 0xd8:
                # Um novo SOI antes do EOI: abandone o quadro anterior.
                self._restart(marker_end - 1)
                continue
            # EOI (FF D9) fecha a imagem; só entrega imagens com dados de scan e tamanho permitido.
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
            # Pula segmentos pelo comprimento declarado, inclusive metadados com miniaturas JPEG internas.
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
            # SOS (FF DA) indica que os dados de imagem começam após este cabeçalho.
            self.in_scan = code == 0xda
            if self.in_scan:
                self.saw_scan = True
        return frames
