import unittest
from unittest.mock import patch

import config
from background import BackgroundFilter
from batch_weights import BatchWeightSimulation
from sorting import SortingController
import vision

cv2 = vision.cv2
np = vision.np


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.settings = patch.multiple(
            config, BACKGROUND_WARMUP_SECONDS=2.0,
            BACKGROUND_DIFF_THRESHOLD=35, BACKGROUND_MIN_CHANGED_RATIO=0.60,
            BACKGROUND_MIN_FRAMES=3, BACKGROUND_IGNORE_MARGIN_PX=3,
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.filter = BackgroundFilter(clock=lambda: self.now)
        self.empty = np.full((120, 160, 3), 60, dtype=np.uint8)

    def learn(self, frame):
        self.assertIsNone(self.filter.foreground_mask(frame))
        self.now = 1.0
        self.assertIsNone(self.filter.foreground_mask(frame))
        self.now = 2.0
        self.assertFalse(self.filter.foreground_mask(frame).any())
        self.assertTrue(self.filter.ready)

    def test_startup_scene_is_ignored(self):
        frame = self.empty.copy()
        frame[20:60, 30:70] = (0, 140, 255)
        self.learn(frame)
        self.now += 10
        self.assertFalse(self.filter.foreground_mask(frame).any())

    def test_new_stationary_piece_is_not_absorbed_into_background(self):
        self.learn(self.empty)
        frame = self.empty.copy()
        frame[20:60, 30:70] = (0, 140, 255)
        for elapsed in (0.1, 1.0, 10.0, 60.0):
            self.now += elapsed
            self.assertEqual(self.filter.foreground_mask(frame)[40, 50], 255)
        self.assertFalse(self.filter.foreground_mask(self.empty).any())

    def test_small_image_noise_does_not_become_foreground(self):
        self.learn(self.empty)
        frame = self.empty + 5
        self.assertFalse(self.filter.foreground_mask(frame).any())

    def test_resolution_change_requires_new_background(self):
        self.learn(self.empty)
        resized = cv2.resize(self.empty, (80, 60))
        self.assertIsNone(self.filter.foreground_mask(resized))
        self.assertFalse(self.filter.ready)

    def test_video_pause_does_not_finish_capture_with_only_two_frames(self):
        self.assertIsNone(self.filter.foreground_mask(self.empty))
        self.now = 30.0
        self.assertIsNone(self.filter.foreground_mask(self.empty))
        self.assertFalse(self.filter.ready)
        self.now += 0.1
        self.assertIsNotNone(self.filter.foreground_mask(self.empty))
        self.assertTrue(self.filter.ready)


class BackgroundDetectionTests(unittest.TestCase):
    def setUp(self):
        BackgroundTests.setUp(self)
        for attribute, value in (
            ('background_filter', self.filter), ('tracks', []), ('next_id', 1),
            ('background_reset_requested', False), ('latest_detections', []),
            ('roi', {'x': 0.0, 'y': 0.0, 'w': 1.0, 'h': 1.0}),
        ):
            replacement = patch.object(vision, attribute, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def color(self, hue):
        return cv2.cvtColor(np.uint8([[[hue, 220, 220]]]), cv2.COLOR_HSV2BGR)[0, 0]

    def scene(self):
        frame = self.empty.copy()
        for x, hue in zip((10, 45, 80, 115), (15, 60, 100, 145)):
            frame[15:40, x:x + 22] = self.color(hue)
        return frame

    def learn_scene(self, frame):
        for moment in (0.0, 1.0, 2.0):
            self.now = moment
            detections, _ = vision.detect_objects(frame)
            self.assertEqual(detections, [])

    def test_background_of_all_material_colors_never_creates_commands_or_weights(self):
        frame = self.scene()
        sorter = SortingController()
        sorter.acquire_consumer()
        weights = BatchWeightSimulation()
        weights.start_lot('TESTE', 10000)
        for moment in (0.0, 1.0, 2.0, 2.1, 2.2, 2.3, 3.0):
            self.now = moment
            detections, _ = vision.detect_objects(frame)
            sorter.observe(detections)
            weights.observe(detections)
            self.assertEqual(detections, [])
        self.assertIsNone(sorter.current_command())
        self.assertEqual(weights.snapshot()['pesoProcessadoGramas'], 0)

    def test_stationary_background_is_ignored_after_large_exposure_change(self):
        frame = self.scene()
        self.learn_scene(frame)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        colored = hsv[:, :, 1] > 100
        hsv[:, :, 2][colored] = 120
        darker = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        detections, _ = vision.detect_objects(darker)
        self.assertEqual(detections, [])

    def test_background_stays_ignored_when_white_balance_changes_its_color(self):
        frame = self.scene()
        self.learn_scene(frame)
        frame[15:40, 10:32] = self.color(145)
        detections, _ = vision.detect_objects(frame)
        self.assertEqual(detections, [])

    def test_new_piece_is_processed_once_while_background_stays_ignored(self):
        frame = self.scene()
        self.learn_scene(frame)
        frame[70:100, 50:80] = self.color(15)
        sorter = SortingController()
        sorter.acquire_consumer()
        weights = BatchWeightSimulation()
        weights.start_lot('TESTE', 10000)
        with patch.object(vision.time, 'time', side_effect=lambda: self.now):
            for _ in range(config.SORT_CONFIRM_FRAMES):
                self.now += 0.1
                detections, _ = vision.detect_objects(frame)
                self.assertEqual(len(detections), 1)
                sorter.observe(detections)
                weights.observe(detections)
            command = sorter.current_command()
            self.assertEqual(command['material'], 'Plástico')
            sorter.acknowledge(command['command_id'], 'done')
            processed = weights.snapshot()['pesoProcessadoGramas']
            self.assertGreater(processed, 0)
            for _ in range(30):
                self.now += 0.1
                detections, _ = vision.detect_objects(frame)
                sorter.observe(detections)
                weights.observe(detections)
            self.assertIsNone(sorter.current_command())
            self.assertEqual(weights.snapshot()['pesoProcessadoGramas'], processed)

    def test_small_change_on_existing_colored_region_is_not_a_new_piece(self):
        frame = self.empty.copy()
        frame[20:80, 30:100] = self.color(15)
        self.learn_scene(frame)
        frame[20:28, 30:100] = self.color(20)
        detections, _ = vision.detect_objects(frame)
        self.assertEqual(detections, [])

    def test_new_piece_outside_roi_is_ignored(self):
        self.learn_scene(self.empty)
        frame = self.empty.copy()
        frame[70:100, 100:130] = self.color(15)
        with patch.object(vision, 'roi', {'x': 0, 'y': 0, 'w': .5, 'h': .5}):
            detections, _ = vision.detect_objects(frame)
        self.assertEqual(detections, [])

    def test_manual_capture_clears_detections_and_preserves_id_sequence(self):
        import app

        self.learn_scene(self.empty)
        old_filter = vision.background_filter
        vision.next_id = 42
        vision.latest_detections = [{'id': 41, 'color': 'Laranja'}]
        http = app.app.test_client()
        self.assertTrue(http.get('/api/detections').json['background_ready'])
        self.assertEqual(http.get('/api/camera/background').status_code, 405)
        response = http.post('/api/camera/background')
        self.assertEqual(response.status_code, 202)
        self.assertTrue(vision.background_reset_requested)
        snapshot = http.get('/api/detections').json
        self.assertFalse(snapshot['background_ready'])
        self.assertEqual(snapshot['detections'], [])
        detections, _ = vision.detect_objects(self.empty)
        self.assertEqual(detections, [])
        self.assertIsNot(vision.background_filter, old_filter)
        self.assertFalse(vision.background_filter.ready)
        self.assertFalse(vision.background_reset_requested)
        self.assertEqual(vision.next_id, 42)
