import threading
import unittest
from unittest.mock import Mock, patch

import config
from camera_buffer import LatestCameraFrame
import vision


class LatestCameraFrameTests(unittest.TestCase):
    def test_slow_consumer_gets_latest_frame_instead_of_old_frames(self):
        now = 0.0
        buffer = LatestCameraFrame(clock=lambda: now)
        for number in range(100):
            now = float(number)
            buffer.publish(number)
        self.assertEqual(buffer.take(timeout=0), (99, 99.0))
        self.assertIsNone(buffer.take(timeout=0))

    def test_new_capture_wakes_waiting_consumer(self):
        buffer = LatestCameraFrame()
        waiting = threading.Event()
        result = []

        def consume():
            waiting.set()
            result.append(buffer.take(timeout=1))

        worker = threading.Thread(target=consume)
        worker.start()
        self.assertTrue(waiting.wait(timeout=1))
        frame = object()
        buffer.publish(frame)
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertIs(result[0][0], frame)

    def test_disconnect_discards_pending_frame(self):
        buffer = LatestCameraFrame()
        buffer.publish(object())
        buffer.clear()
        self.assertIsNone(buffer.take(timeout=0))


class CameraProcessingTests(unittest.TestCase):
    def test_processing_skips_stale_packet_and_does_not_wait_for_next_detection(self):
        buffer = Mock()
        old_frame, new_frame = object(), object()
        packets = iter([(old_frame, 90.0), (new_frame, 100.0)])

        def take(timeout):
            try:
                return next(packets)
            except StopIteration:
                vision.running = False
                return None

        buffer.take.side_effect = take
        with patch.object(vision, 'running', True), \
                patch.object(config, 'CAMERA_MAX_PENDING_FRAME_AGE_SECONDS', 0.5), \
                patch.object(vision, 'LatestCameraFrame', return_value=buffer), \
                patch.object(vision.threading, 'Thread'), \
                patch.object(vision.time, 'monotonic', return_value=100.0), \
                patch.object(vision, 'process_camera_frame') as process:
            vision.camera_frames()
        process.assert_called_once_with(new_frame)

    def test_command_is_created_before_video_annotation(self):
        frame = vision.np.zeros((120, 160, 3), dtype=vision.np.uint8)
        detection = {'id': 1, 'color': 'Laranja', 'x': 20, 'y': 20, 'w': 25, 'h': 25}
        sequence = []
        with patch.object(vision, 'background_reset_requested', False), \
                patch.object(vision, 'latest_frame', None), \
                patch.object(vision, 'latest_detections', []), \
                patch.object(vision, 'detect_objects', return_value=([detection], (0, 0, 160, 120))), \
                patch.object(vision.sorter, 'observe', side_effect=lambda _: sequence.append('command')), \
                patch.object(vision.batch_weights, 'observe'), \
                patch.object(vision.cv2, 'rectangle', side_effect=lambda *args: sequence.append('draw')):
            vision.process_camera_frame(frame)
        self.assertEqual(sequence[0], 'command')
        self.assertIn('draw', sequence)

    def test_background_recapture_does_not_dispatch_old_results(self):
        frame = vision.np.zeros((120, 160, 3), dtype=vision.np.uint8)
        with patch.object(vision, 'background_reset_requested', True), \
                patch.object(vision, 'latest_frame', None), \
                patch.object(vision, 'latest_detections', []), \
                patch.object(vision, 'detect_objects', return_value=([{'id': 1}], (0, 0, 160, 120))), \
                patch.object(vision.sorter, 'observe') as observe, \
                patch.object(vision.batch_weights, 'observe'):
            vision.process_camera_frame(frame)
            self.assertEqual(vision.latest_detections, [])
        observe.assert_called_once_with([])
