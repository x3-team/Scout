"""Exact, printable ArUco board; coordinates are canonical image pixels."""
from pathlib import Path
import cv2
import numpy as np

WIDTH, HEIGHT = 1000, 700
SIZE = 120
POSITIONS = {10: (40, 40), 20: (840, 40), 30: (840, 540), 40: (40, 540)}
ROI = (220, 200, 560, 300)
DICTIONARY_NAME = "DICT_4X4_50"


def dictionary():
    return cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def expected_corners(marker_id):
    x, y = POSITIONS[marker_id]
    return np.float32([[x, y], [x + SIZE - 1, y],
                       [x + SIZE - 1, y + SIZE - 1], [x, y + SIZE - 1]])


def board_image():
    image = np.full((HEIGHT, WIDTH, 3), 245, dtype=np.uint8)
    x, y, w, h = ROI
    image[y:y + h, x:x + w] = 235
    for xx in range(x + 20, x + w, 40):
        cv2.line(image, (xx, y), (xx, y + h - 1), (215, 215, 215), 1)
    for yy in range(y + 20, y + h, 40):
        cv2.line(image, (x, yy), (x + w - 1, yy), (215, 215, 215), 1)
    for marker_id, (xx, yy) in POSITIONS.items():
        marker = cv2.aruco.generateImageMarker(dictionary(), marker_id, SIZE)
        image[yy:yy + SIZE, xx:xx + SIZE] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return image


def board_svg():
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="207.9mm" '
             'viewBox="0 0 1000 700" shape-rendering="crispEdges">',
             '<rect width="1000" height="700" fill="#f5f5f5"/>',
             '<rect x="220" y="200" width="560" height="300" fill="#ebebeb"/>']
    for xx in range(240, 780, 40):
        parts.append(f'<path d="M{xx} 200V500" stroke="#d7d7d7"/>')
    for yy in range(220, 500, 40):
        parts.append(f'<path d="M220 {yy}H780" stroke="#d7d7d7"/>')
    for marker_id, (x, y) in POSITIONS.items():
        bits = cv2.aruco.generateImageMarker(dictionary(), marker_id, 6)
        parts.append(f'<rect x="{x}" y="{y}" width="120" height="120" fill="white"/>')
        for row in range(6):
            for col in range(6):
                if bits[row, col] == 0:
                    parts.append(f'<rect x="{x + col * 20}" y="{y + row * 20}" '
                                 'width="20" height="20" fill="black"/>')
    parts.append('</svg>')
    return ''.join(parts)


def write_board(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'board.svg').write_text(board_svg(), encoding='utf-8')
    (directory / 'board.png').write_bytes(cv2.imencode('.png', board_image())[1].tobytes())
