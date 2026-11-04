"""Registered change detection on a planar, four-marker laboratory board."""
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import cv2
import numpy as np

from .board import WIDTH, HEIGHT, POSITIONS, ROI, SIZE, dictionary, expected_corners


@dataclass(frozen=True)
class VisionConfig:
    pixel_threshold: float = 25.0
    min_component_pixels: int = 200
    min_changed_fraction: float = 0.003
    max_changed_fraction: float = 0.60
    min_marker_sharpness: float = 35.0
    max_registration_rmse_px: float = 2.0
    max_light_offset: float = 35.0

    def __post_init__(self):
        import math
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in asdict(self).values()):
            raise ValueError('vision parameters must be finite numbers')
        if not 0 < self.pixel_threshold < 255:
            raise ValueError('pixel_threshold must be between 0 and 255')
        if not isinstance(self.min_component_pixels, int) or not 1 <= self.min_component_pixels < ROI[2] * ROI[3]:
            raise ValueError('invalid minimum component area')
        if not 0 < self.min_changed_fraction < self.max_changed_fraction < 1:
            raise ValueError('invalid changed area fractions')
        if min(self.min_marker_sharpness, self.max_registration_rmse_px, self.max_light_offset) <= 0:
            raise ValueError('quality thresholds must be positive')


class UnusableImage(ValueError):
    pass


def load_image(path):
    path = Path(path)
    if path.stat().st_size > 20_000_000:
        raise ValueError('input image exceeds 20 MB')
    data = path.read_bytes()
    if not data:
        raise ValueError(f'empty image: {path.name}')
    try:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as error:
        raise ValueError(f'cannot decode image: {path.name}') from error
    if image is None:
        raise ValueError(f'cannot decode image: {path.name}')
    h, w = image.shape[:2]
    if h * w > 24_000_000 or min(h, w) < 200:
        raise ValueError('input must be at least 200 px per side and at most 24 megapixels')
    if max(h, w) > 2400:
        ratio = 2400 / max(h, w)
        image = cv2.resize(image, (round(w * ratio), round(h * ratio)), interpolation=cv2.INTER_AREA)
    return image, {'name': path.name, 'sha256': hashlib.sha256(data).hexdigest(),
                   'original_dimensions': [w, h]}


def register(image, config):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.mean() < 8 or gray.mean() > 252:
        raise UnusableImage('EXPOSURE_OUT_OF_RANGE')
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(dictionary(), parameters)
    corners, ids, _ = detector.detectMarkers(gray)
    observed = {}
    for points, marker_id in zip(corners, [] if ids is None else ids.flatten()):
        marker_id = int(marker_id)
        if marker_id not in POSITIONS:
            continue
        if marker_id in observed:
            raise UnusableImage('DUPLICATE_MARKER_ID')
        points = points.reshape(4, 2)
        sides = np.linalg.norm(points - np.roll(points, 1, axis=0), axis=1)
        if min(sides) < 20 or max(sides) / min(sides) > 4:
            raise UnusableImage('MARKER_TOO_SMALL_OR_OBLIQUE')
        observed[marker_id] = points
    if set(observed) != set(POSITIONS):
        raise UnusableImage('MISSING_REQUIRED_MARKERS')
    src = np.concatenate([observed[i] for i in POSITIONS]).astype(np.float32)
    dst = np.concatenate([expected_corners(i) for i in POSITIONS])
    transform, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if transform is None or not np.isfinite(transform).all() or np.linalg.cond(transform) > 1e8:
        raise UnusableImage('REGISTRATION_FAILED')
    projected = cv2.perspectiveTransform(src.reshape(-1, 1, 2), transform).reshape(-1, 2)
    errors = np.linalg.norm(projected - dst, axis=1)
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    if inliers is None or int(inliers.sum()) < 14 or rmse > config.max_registration_rmse_px:
        raise UnusableImage('REGISTRATION_INCONSISTENT')
    canonical = cv2.warpPerspective(image, transform, (WIDTH, HEIGHT), flags=cv2.INTER_LINEAR)
    coverage = cv2.warpPerspective(np.full(gray.shape, 255, np.uint8), transform,
                                   (WIDTH, HEIGHT), flags=cv2.INTER_NEAREST)
    x, y, w, h = ROI
    if np.mean(coverage[y:y + h, x:x + w] == 255) < .995:
        raise UnusableImage('INCOMPLETE_INSPECTION_AREA')
    warped_gray = cv2.cvtColor(canonical, cv2.COLOR_BGR2GRAY)
    sharpness = min(float(cv2.Laplacian(warped_gray[yy:yy + SIZE, xx:xx + SIZE],
                                        cv2.CV_64F).var()) for xx, yy in POSITIONS.values())
    if sharpness < config.min_marker_sharpness:
        raise UnusableImage('BLURRED_IMAGE')
    inspection_gray = warped_gray[y:y + h, x:x + w]
    clipped = float(np.mean((inspection_gray < 4) | (inspection_gray > 251)))
    if clipped > .95:
        raise UnusableImage('INSPECTION_AREA_CLIPPED')
    return canonical, {'registration_rmse_px': round(rmse, 6),
                       'marker_sharpness': round(sharpness, 6),
                       'clipped_fraction': round(clipped, 6), 'marker_ids': list(POSITIONS)}


def analyze_pair(reference, current, *, input_kind, config=None):
    if input_kind not in ('photograph', 'synthetic'):
        raise ValueError('input_kind must explicitly be photograph or synthetic')
    config = VisionConfig() if config is None else config
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    ref, ref_meta = load_image(reference)
    new, new_meta = load_image(current)
    result = {
        'vision_schema_version': '1.0', 'algorithm': 'aruco_planar_lab_difference_v1',
        'result': 'INCONCLUSIVE', 'reason': None,
        'evidence': {'input_kind_declared': input_kind, 'synthetic': input_kind == 'synthetic',
                     'computer_vision_executed': True, 'authenticity_verified': False,
                     'reference': ref_meta, 'current': new_meta},
        'config': asdict(config), 'roi_xywh': list(ROI), 'quality': {},
        'metrics': {'changed_fraction': None, 'component_count': 0}, 'regions': [],
        'runtime': {'opencv': cv2.__version__, 'numpy': np.__version__, 'threads': 1},
        'limitations': [
            'Planar scene only: a homography does not compensate 3D parallax.',
            'Marker visibility and quality checks cannot detect every possible occlusion.',
            'Image provenance is declared by the operator, not authenticated.',
            'Change score is an area fraction, not a probability or semantic box detector.',
            'Real photograph accuracy requires a separate labelled evaluation dataset.'
        ]
    }
    pictures = {}
    for key, image in [('reference', ref), ('current', new)]:
        try:
            canonical, quality = register(image, config)
            pictures[key] = canonical
            result['quality'][key] = quality
        except UnusableImage as error:
            result['reason'] = key.upper() + '_' + str(error)
            return result, pictures
    x, y, w, h = ROI
    reference_lab = cv2.cvtColor(pictures['reference'], cv2.COLOR_BGR2LAB).astype(np.float32)
    current_lab = cv2.cvtColor(pictures['current'], cv2.COLOR_BGR2LAB).astype(np.float32)
    anchor = np.zeros((HEIGHT, WIDTH), dtype=bool)
    anchor[y - 30:y + h + 30, x - 30:x + w + 30] = True
    anchor[y:y + h, x:x + w] = False
    offset = float(np.median(reference_lab[:, :, 0][anchor]) -
                   np.median(current_lab[:, :, 0][anchor]))
    result['quality']['light_offset_lab'] = round(offset, 6)
    if abs(offset) > config.max_light_offset:
        result['reason'] = 'LIGHTING_CHANGE_TOO_LARGE'
        return result, pictures
    current_lab[:, :, 0] = np.clip(current_lab[:, :, 0] + offset, 0, 255)
    reference_lab = cv2.GaussianBlur(reference_lab[y:y + h, x:x + w], (3, 3), 0)
    current_lab = cv2.GaussianBlur(current_lab[y:y + h, x:x + w], (3, 3), 0)
    difference = np.abs(reference_lab - current_lab)
    score = np.maximum(difference[:, :, 0], .8 * difference[:, :, 1:].max(axis=2))
    mask = np.uint8(score > config.pixel_threshold) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    clean = np.zeros_like(mask)
    for i in range(1, count):
        xx, yy, ww, hh, area = map(int, stats[i])
        if area >= config.min_component_pixels:
            clean[labels == i] = 255
            result['regions'].append({'bbox_xywh': [x + xx, y + yy, ww, hh], 'area_pixels': area})
    fraction = float(np.count_nonzero(clean) / (w * h))
    result['metrics'] = {'changed_fraction': round(fraction, 8),
                         'component_count': len(result['regions'])}
    heatmap = np.full((HEIGHT, WIDTH, 3), 245, np.uint8)
    heatmap[y:y + h, x:x + w] = cv2.applyColorMap(np.uint8(np.clip(score * 4, 0, 255)), cv2.COLORMAP_TURBO)
    pictures['difference'] = heatmap
    pictures['overlay'] = pictures['current'].copy()
    for region in result['regions']:
        xx, yy, ww, hh = region['bbox_xywh']
        cv2.rectangle(pictures['overlay'], (xx, yy), (xx + ww - 1, yy + hh - 1), (0, 0, 255), 3)
    if fraction > config.max_changed_fraction:
        result['reason'] = 'SCENE_MISMATCH_OR_LARGE_OCCLUSION'
    else:
        result['result'] = 'CHANGED' if fraction >= config.min_changed_fraction else 'UNCHANGED'
        result['reason'] = 'SIGNIFICANT_DIFFERENCE' if result['result'] == 'CHANGED' else 'NO_SIGNIFICANT_DIFFERENCE'
    return result, pictures
