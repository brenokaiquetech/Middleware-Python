# FUNDO FIXO: aprende o cenário inicial com a esteira vazia e depois congela essa referência.
# A máscara resultante informa à visão quais pixels mudaram sem reaprender uma peça parada.
"""Fundo fixo da câmera para ignorar as cores presentes ao iniciar."""
import time

import config  # Limita as threads antes de importar as bibliotecas numéricas.
import cv2
import numpy as np


# Separa pixels novos das regiões que já pertenciam ao cenário inicial.
class BackgroundFilter:
    # Carrega sensibilidade e tempo de aprendizado; ainda não há imagem de referência.
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.warmup = config.BACKGROUND_WARMUP_SECONDS
        self.threshold = config.BACKGROUND_DIFF_THRESHOLD
        self.minimum_frames = config.BACKGROUND_MIN_FRAMES
        self.ignore_margin = config.BACKGROUND_IGNORE_MARGIN_PX
        if (self.warmup <= 0 or not 0 < self.threshold <= 255
                or self.minimum_frames < 2 or self.ignore_margin < 0):
            raise ValueError('Configuração do fundo da câmera inválida.')
        self.reference = None
        self.ignored_colors = None
        self.frame_count = 0
        self.started_at = None
        self.ready = False

    # Acumula as regiões inicialmente coloridas para ignorá-las mesmo com variação de exposição.
    def _remember_background_colors(self, frame):
        """Reserve as regiões já coloridas mesmo se a exposição mudar depois."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        colors = np.zeros(frame.shape[:2], dtype=np.uint8)
        for ranges in config.COLOR_RANGES.values():
            for low, high in ranges:
                colors = cv2.bitwise_or(colors, cv2.inRange(hsv, np.array(low), np.array(high)))
        self.ignored_colors = cv2.bitwise_or(self.ignored_colors, colors)

    # Retorna None durante aprendizado ou uma máscara 0/255 das mudanças aceitas quando pronto.
    def foreground_mask(self, frame):
        """Aprenda o cenário vazio; depois preserve objetos mesmo parados."""
        # Suavização reduz pequenas diferenças de ruído antes da comparação com o fundo.
        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        now = self.clock()
        # O primeiro quadro, ou uma resolução nova, reinicia o aprendizado da referência.
        if self.reference is None or self.reference.shape != blurred.shape:
            self.reference = blurred.astype(np.float32)
            self.ignored_colors = np.zeros(frame.shape[:2], dtype=np.uint8)
            self._remember_background_colors(blurred)
            self.frame_count = 1
            self.started_at = now
            self.ready = False
            return None
        # É preciso cumprir tempo mínimo e quantidade de quadros; um vídeo congelado não basta.
        if not self.ready:
            self.frame_count += 1
            self._remember_background_colors(blurred)
            # Média incremental, sem guardar vários frames na memória.
            if now - self.started_at < self.warmup or self.frame_count < self.minimum_frames:
                cv2.accumulateWeighted(blurred, self.reference, 0.2)
                return None
            # Dilatar a região ignorada inclui suas bordas, evitando que pequenos deslocamentos virem peça.
            size = self.ignore_margin * 2 + 1
            self.ignored_colors = cv2.dilate(
                self.ignored_colors, np.ones((size, size), dtype=np.uint8)
            )
            self.ready = True
        # Depois de pronta, a referência não é atualizada: uma peça parada continua diferente do fundo.
        difference = cv2.absdiff(blurred, cv2.convertScaleAbs(self.reference))
        # Compare os três canais, inclusive cores com brilho semelhante.
        changed = np.max(difference, axis=2) >= self.threshold
        foreground = changed.astype(np.uint8) * 255
        return cv2.bitwise_and(foreground, cv2.bitwise_not(self.ignored_colors))
