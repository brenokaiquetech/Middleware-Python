# VÍDEO: fabrica JPEGs e pacotes fragmentados/corrompidos para testar parser e recuperação de quadros.
# Execução: python -m unittest discover -s tests -v. Não precisa ligar motores.
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import vision
from mjpeg import JPEGStreamParser

cv2 = vision.cv2
np = vision.np


# Agrupa cenários deste componente; cada assert compara o resultado com a regra esperada.
class JPEGStreamTests(unittest.TestCase):
    # Prepara os recursos compartilhados uma única vez para os testes desta classe.
    @classmethod
    def setUpClass(cls):
        cls.image = np.full((24, 32, 3), (60, 120, 200), dtype=np.uint8)
        ok, encoded = cv2.imencode('.jpg', cls.image)
        assert ok
        cls.jpeg = encoded.tobytes()

    # Cria um parser novo com limite de memória configurável para cada cenário.
    def parser(self, maximum=100000):
        return JPEGStreamParser(maximum)

    # Cabeçalhos HTTP entre imagens não devem impedir a extração de JPEGs consecutivos.
    def test_multiple_frames_with_multipart_headers(self):
        header = b'--camera\r\nContent-Type: image/jpeg\r\n\r\n'
        frames = self.parser().feed(header + self.jpeg + b'\r\n' + header + self.jpeg)
        self.assertEqual(frames, [self.jpeg, self.jpeg])

    # Mesmo um pacote por byte deve recompor exatamente o JPEG original.
    def test_every_byte_can_arrive_separately(self):
        parser = self.parser()
        frames = []
        for byte in self.jpeg:
            frames.extend(parser.feed(bytes([byte])))
        self.assertEqual(frames, [self.jpeg])

    # Marcadores separados entre pacotes e lixo antes do SOI precisam ser tolerados.
    def test_split_markers_and_garbage_prefix(self):
        parser = self.parser()
        self.assertEqual(parser.feed(b'HTTP garbage\xff'), [])
        self.assertEqual(parser.feed(self.jpeg[1:-1]), [])
        self.assertEqual(parser.feed(self.jpeg[-1:]), [self.jpeg])

    # O começo de uma imagem nova abandona a anterior incompleta sem perder o quadro seguinte.
    def test_frame_without_end_does_not_swallow_next_jpeg(self):
        parser = self.parser()
        incomplete = self.jpeg[:-2]
        self.assertEqual(parser.feed(incomplete), [])
        frames = parser.feed(self.jpeg)
        self.assertEqual(frames, [self.jpeg])
        decoded = cv2.imdecode(np.frombuffer(frames[0], dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, self.image.shape)

    # A recuperação também funciona quando o SOI seguinte está dividido entre pacotes.
    def test_nested_start_split_across_chunks_resynchronizes(self):
        parser = self.parser()
        self.assertEqual(parser.feed(self.jpeg[:-2] + b'\xff'), [])
        self.assertEqual(parser.feed(self.jpeg[1:]), [self.jpeg])

    # Uma miniatura JPEG dentro de metadados não deve ser confundida com outro quadro do vídeo.
    def test_embedded_thumbnail_markers_are_not_mistaken_for_next_frame(self):
        payload = b'embedded-thumbnail:' + self.jpeg
        app_segment = b'\xff\xe2' + (len(payload) + 2).to_bytes(2, 'big') + payload
        frame = self.jpeg[:2] + app_segment + self.jpeg[2:]
        parser = self.parser()
        result = []
        for offset in range(0, len(frame), 19):
            result.extend(parser.feed(frame[offset:offset + 19]))
        self.assertEqual(result, [frame])
        self.assertIsNotNone(cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR))

    # JPEG progressivo com múltiplos scans precisa ser extraído como uma imagem inteira.
    def test_progressive_jpeg_is_supported(self):
        ok, encoded = cv2.imencode('.jpg', self.image, [cv2.IMWRITE_JPEG_PROGRESSIVE, 1])
        self.assertTrue(ok)
        frame = encoded.tobytes()
        parser = self.parser()
        result = []
        for offset in range(0, len(frame), 11):
            result.extend(parser.feed(frame[offset:offset + 11]))
        self.assertEqual(result, [frame])

    # Descarta JPEG vazio ou com comprimento de segmento inválido e recupera o próximo válido.
    def test_bad_header_lengths_and_empty_jpeg_are_discarded(self):
        corrupt = b'\xff\xd8\xff\xe0\x00\x01garbage\xff\xd9'
        self.assertEqual(self.parser().feed(b'\xff\xd8\xff\xd9' + corrupt + self.jpeg), [self.jpeg])

    # Lixo ou quadro sem fim não podem provocar crescimento ilimitado de memória.
    def test_noise_and_oversized_frame_do_not_grow_buffer_forever(self):
        parser = self.parser(maximum=len(self.jpeg) + 100)
        parser.feed(b'noise' * 10000)
        self.assertLessEqual(len(parser.buffer), 1)
        parser.feed(self.jpeg[:-2] + b'x' * 10000)
        self.assertLessEqual(len(parser.buffer), parser.maximum)
        self.assertEqual(parser.feed(self.jpeg), [self.jpeg])

    # Comprimento excessivo no cabeçalho precisa permitir voltar a procurar um JPEG válido.
    def test_declared_segment_larger_than_limit_resynchronizes(self):
        parser = self.parser(maximum=len(self.jpeg) + 100)
        corrupt = b'\xff\xd8\xff\xe0\xff\xff' + b'x' * 10
        self.assertEqual(parser.feed(corrupt + self.jpeg), [self.jpeg])

    # Várias imagens pequenas em um pacote grande devem respeitar o limite individual por quadro.
    def test_frame_limit_is_per_frame_not_per_chunk(self):
        parser = self.parser(maximum=len(self.jpeg))
        self.assertEqual(parser.feed(self.jpeg * 5), [self.jpeg] * 5)

    # Pacote vazio não deve alterar o parser ou impedir receber a imagem seguinte.
    def test_empty_chunks_are_allowed(self):
        parser = self.parser()
        self.assertEqual(parser.feed(b''), [])
        self.assertEqual(parser.feed(self.jpeg), [self.jpeg])


# Agrupa cenários deste componente; cada assert compara o resultado com a regra esperada.
class CameraReaderTests(unittest.TestCase):
    # Prepara um cenário isolado antes de cada teste; patches são restaurados para não contaminar os demais.
    def setUp(self):
        self.image = np.zeros((24, 32, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode('.jpg', self.image)
        self.assertTrue(ok)
        self.jpeg = encoded.tobytes()

    # Imita a resposta HTTP usando uma sequência conhecida de pacotes, sem câmera real.
    def response(self, chunks):
        return SimpleNamespace(iter_content=Mock(return_value=iter(chunks)))

    # Erro do OpenCV em um quadro não deve encerrar a leitura do próximo.
    def test_decoder_exception_does_not_abort_following_frame(self):
        with patch.object(vision, 'running', True), patch.object(cv2, 'imdecode', side_effect=[cv2.error('bad frame'), self.image]):
            result = list(vision.read_camera_images(self.response([self.jpeg * 2])))
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], self.image)

    # Retornos nulos ou vazios do decodificador precisam ser ignorados.
    def test_none_and_empty_decodes_are_skipped(self):
        with patch.object(vision, 'running', True), patch.object(cv2, 'imdecode', side_effect=[None, np.array([]), self.image]):
            result = list(vision.read_camera_images(self.response([self.jpeg * 3])))
        self.assertEqual(len(result), 1)

    # Dados recebidos sem imagem válida até o prazo devem forçar reconexão.
    def test_stream_without_decodable_images_requests_reconnection(self):
        with patch.object(vision, 'running', True), patch.object(vision.time, 'monotonic', side_effect=[0, 100]):
            with self.assertRaisesRegex(ValueError, 'sem quadros JPEG'):
                list(vision.read_camera_images(self.response([b'not an image'])))

    # O encerramento evita decodificações extras depois da sinalização de parada.
    def test_reader_stops_without_decoding_when_shutting_down(self):
        with patch.object(vision, 'running', False), patch.object(cv2, 'imdecode') as decode:
            self.assertEqual(list(vision.read_camera_images(self.response([self.jpeg]))), [])
        decode.assert_not_called()
