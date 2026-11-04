"""Procedural pixel fixtures, deliberately not labelled as photographs."""
from pathlib import Path
import cv2
import numpy as np
from .board import board_image, WIDTH, HEIGHT


def fixture_images():
    reference = board_image()
    # A flat, textured scene with repeatable colour and edges inside the ROI.
    cv2.rectangle(reference, (270, 260), (380, 410), (70, 130, 190), -1)
    cv2.line(reference, (270, 310), (380, 310), (35, 65, 90), 4)
    cv2.circle(reference, (610, 350), 45, (100, 160, 70), -1)
    changed = reference.copy()
    cv2.rectangle(changed, (460, 250), (540, 330), (180, 65, 50), -1)
    removed = reference.copy()
    removed[250:421, 260:391] = board_image()[250:421, 260:391]
    occluded = reference.copy()
    occluded[200:500, 220:780] = (30, 30, 120)
    missing = reference.copy()
    missing[20:180, 20:180] = 245
    transform = cv2.getPerspectiveTransform(
        np.float32([[0, 0], [WIDTH - 1, 0], [WIDTH - 1, HEIGHT - 1], [0, HEIGHT - 1]]),
        np.float32([[35, 20], [960, 35], [980, 665], [20, 680]]))
    shifted = cv2.warpPerspective(reference, transform, (WIDTH, HEIGHT), borderValue=(245, 245, 245))
    brighter = np.clip(reference.astype(np.int16) + 8, 0, 255).astype(np.uint8)
    return {'reference': reference, 'unchanged': reference.copy(), 'changed': changed,
            'removed': removed, 'perspective': shifted, 'brighter': brighter,
            'missing-marker': missing, 'occluded': occluded,
            'blurred': cv2.GaussianBlur(reference, (51, 51), 0),
            'dark': np.zeros_like(reference)}


def write_fixtures(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, image in fixture_images().items():
        (directory / (name + '.png')).write_bytes(cv2.imencode('.png', image)[1].tobytes())
