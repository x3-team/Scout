"""Pixel-level fixtures exercise OpenCV. These are NOT real photograph benchmarks."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import cv2
import numpy as np

from scout.vision.board import board_image, board_svg, POSITIONS, dictionary
from scout.vision.engine import VisionConfig, analyze_pair, load_image
from scout.vision.evaluate import evaluate_manifest
from scout.vision.fixtures import write_fixtures
from scout.vision.reporting import write_analysis


class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        write_fixtures(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def inspect(self, current, **kwargs):
        return analyze_pair(self.root / 'reference.png', self.root / (current + '.png'),
                            input_kind='synthetic', **kwargs)

    def test_print_board_has_four_expected_ids_and_valid_svg(self):
        detector = cv2.aruco.ArucoDetector(dictionary())
        _, ids, _ = detector.detectMarkers(board_image())
        self.assertEqual(set(ids.flatten()), set(POSITIONS))
        svg = ET.fromstring(board_svg())
        self.assertEqual(svg.attrib['width'], '297mm')
        self.assertEqual(svg.attrib['viewBox'], '0 0 1000 700')

    def test_identical_pixels_are_unchanged(self):
        result, pictures = self.inspect('unchanged')
        self.assertEqual(result['result'], 'UNCHANGED')
        self.assertEqual(result['metrics']['changed_fraction'], 0)
        self.assertEqual(set(pictures), {'reference', 'current', 'difference', 'overlay'})

    def test_added_object_is_found_from_pixels(self):
        result, _ = self.inspect('changed')
        self.assertEqual(result['result'], 'CHANGED')
        self.assertGreater(result['metrics']['changed_fraction'], .02)
        self.assertTrue(any(r['bbox_xywh'][0] < 540 and r['bbox_xywh'][1] < 330
                            for r in result['regions']))

    def test_removed_object_is_found(self):
        result, _ = self.inspect('removed')
        self.assertEqual(result['result'], 'CHANGED')

    def test_planar_viewpoint_change_is_aligned(self):
        result, _ = self.inspect('perspective')
        self.assertEqual(result['result'], 'UNCHANGED', result)
        self.assertLess(result['quality']['current']['registration_rmse_px'], 2)

    def test_small_global_lighting_shift_is_normalized(self):
        result, _ = self.inspect('brighter')
        self.assertEqual(result['result'], 'UNCHANGED', result)

    def test_missing_marker_is_inconclusive(self):
        result, _ = self.inspect('missing-marker')
        self.assertEqual(result['result'], 'INCONCLUSIVE')
        self.assertIn('MARKER', result['reason'])
        self.assertIsNone(result['metrics']['changed_fraction'])

    def test_dark_image_is_inconclusive(self):
        result, _ = self.inspect('dark')
        self.assertEqual(result['result'], 'INCONCLUSIVE')
        self.assertIn('EXPOSURE', result['reason'])

    def test_heavy_blur_is_inconclusive(self):
        result, _ = self.inspect('blurred')
        self.assertEqual(result['result'], 'INCONCLUSIVE')

    def test_large_roi_occlusion_is_inconclusive(self):
        result, _ = self.inspect('occluded')
        self.assertEqual(result['result'], 'INCONCLUSIVE')
        self.assertEqual(result['reason'], 'SCENE_MISMATCH_OR_LARGE_OCCLUSION')

    def test_duplicate_required_marker_is_rejected(self):
        image = board_image()
        image[250:370, 450:570] = image[40:160, 40:160]
        path = self.root / 'duplicate.png'
        path.write_bytes(cv2.imencode('.png', image)[1].tobytes())
        result, _ = self.inspect('duplicate')
        self.assertEqual(result['result'], 'INCONCLUSIVE')
        self.assertIn('DUPLICATE', result['reason'])

    def test_inconsistent_marker_geometry_is_rejected(self):
        image = board_image()
        a, b = image[40:160, 40:160].copy(), image[40:160, 840:960].copy()
        image[40:160, 40:160], image[40:160, 840:960] = b, a
        (self.root / 'inconsistent.png').write_bytes(cv2.imencode('.png', image)[1].tobytes())
        result, _ = self.inspect('inconsistent')
        self.assertEqual(result['result'], 'INCONCLUSIVE')

    def test_provenance_is_explicit_and_accuracy_is_not_invented(self):
        result, _ = self.inspect('changed')
        self.assertTrue(result['evidence']['synthetic'])
        self.assertTrue(result['evidence']['computer_vision_executed'])
        self.assertFalse(result['evidence']['authenticity_verified'])
        self.assertNotIn('accuracy', result['metrics'])
        self.assertNotIn(str(self.root), json.dumps(result))
        with self.assertRaises(ValueError):
            analyze_pair(self.root / 'reference.png', self.root / 'changed.png', input_kind='unknown')

    def test_result_is_deterministic_on_same_runtime(self):
        first, _ = self.inspect('perspective')
        second, _ = self.inspect('perspective')
        self.assertEqual(first, second)

    def test_invalid_config_is_rejected(self):
        for kwargs in ({'pixel_threshold': float('nan')}, {'min_component_pixels': 1.2},
                       {'pixel_threshold': -1}, {'min_changed_fraction': .9},
                       {'max_registration_rmse_px': 0}, {'min_marker_sharpness': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                VisionConfig(**kwargs)

    def test_bad_image_and_too_small_image_are_rejected(self):
        path = self.root / 'invalid.png'
        for data in (b'', b'not an image'):
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                load_image(path)
        path.write_bytes(cv2.imencode('.png', np.zeros((20, 20, 3), np.uint8))[1].tobytes())
        with self.assertRaises(ValueError):
            load_image(path)

    def test_portable_report_escapes_text_and_removes_stale_images(self):
        result, pictures = self.inspect('changed')
        result['reason'] = '<script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_analysis(root, result, pictures)
            html = (root / 'report.html').read_text(encoding='utf-8')
            self.assertIn('СИНТЕТИЧЕСКИЕ', html)
            self.assertIn('data:image/png;base64,', html)
            self.assertNotIn('<script>alert(1)</script>', html)
            self.assertNotIn('https://', html)
            self.assertTrue((root / 'overlay.png').exists())
            bad, partial = self.inspect('dark')
            write_analysis(root, bad, partial)
            self.assertFalse((root / 'overlay.png').exists())
            self.assertEqual(json.loads((root / 'inspection.json').read_text(encoding='utf-8'))['result'], 'INCONCLUSIVE')

    def test_cli_exit_codes_and_input_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, expected in [('changed', 0), ('dark', 2)]:
                r = subprocess.run([sys.executable, '-m', 'scout.vision', 'inspect',
                                    '--reference', str(self.root / 'reference.png'),
                                    '--current', str(self.root / (name + '.png')),
                                    '--input-kind', 'synthetic', '--output-dir', str(Path(directory) / name)],
                                   capture_output=True, timeout=45)
                self.assertEqual(r.returncode, expected, r.stderr)
            before = (self.root / 'reference.png').read_bytes()
            r = subprocess.run([sys.executable, '-m', 'scout.vision', 'inspect',
                                '--reference', str(self.root / 'reference.png'),
                                '--current', str(self.root / 'changed.png'), '--input-kind', 'synthetic',
                                '--output-dir', str(self.root)], capture_output=True, timeout=45)
            self.assertEqual(r.returncode, 1)
            self.assertEqual((self.root / 'reference.png').read_bytes(), before)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        write_fixtures(self.root)
        self.pairs = [
            {'id': 'positive', 'scene_id': 'scene-1', 'split': 'evaluation',
             'reference': 'reference.png', 'current': 'changed.png', 'label': 'CHANGED'},
            {'id': 'negative', 'scene_id': 'scene-1', 'split': 'evaluation',
             'reference': 'reference.png', 'current': 'unchanged.png', 'label': 'UNCHANGED'}]

    def tearDown(self):
        self.temporary.cleanup()

    def evaluate(self, pairs=None, input_kind='synthetic'):
        path = self.root / 'manifest.json'
        path.write_text(json.dumps({'input_kind': input_kind, 'pairs': self.pairs if pairs is None else pairs}))
        return evaluate_manifest(path)

    def test_synthetic_metrics_never_pass_real_lab_acceptance(self):
        result = self.evaluate()
        self.assertEqual(result['metrics']['tp'], 1)
        self.assertEqual(result['metrics']['tn'], 1)
        self.assertFalse(result['eligible_for_lab_acceptance'])
        self.assertFalse(result['acceptance_passed'])

    def test_small_declared_photo_set_is_not_eligible(self):
        result = self.evaluate(input_kind='photograph')
        self.assertFalse(result['eligible_for_lab_acceptance'])
        self.assertFalse(result['authenticity_verified'])

    def test_inconclusive_positive_counts_as_miss(self):
        pairs = [dict(self.pairs[0], current='dark.png'), self.pairs[1]]
        result = self.evaluate(pairs)
        self.assertEqual(result['metrics']['fn_including_inconclusive'], 1)
        self.assertEqual(result['metrics']['inconclusive_count'], 1)
        self.assertEqual(result['metrics']['recall'], 0)
        self.assertEqual(result['metrics']['coverage'], .5)

    def test_scene_leakage_is_rejected(self):
        pairs = [dict(self.pairs[0], split='tuning'), self.pairs[1]]
        with self.assertRaisesRegex(ValueError, 'scene leakage'):
            self.evaluate(pairs)

    def test_byte_leakage_is_rejected_across_different_scene_names(self):
        pairs = [dict(self.pairs[0], split='tuning', scene_id='other'), self.pairs[1]]
        with self.assertRaisesRegex(ValueError, 'image bytes'):
            self.evaluate(pairs)

    def test_duplicate_current_images_cannot_inflate_evaluation(self):
        pairs = [self.pairs[0], dict(self.pairs[0], id='copy')]
        with self.assertRaisesRegex(ValueError, 'duplicate evaluation'):
            self.evaluate(pairs)

    def test_unknown_label_is_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate([dict(self.pairs[0], label='maybe')])


if __name__ == '__main__':
    unittest.main()
