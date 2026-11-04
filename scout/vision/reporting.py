"""Portable local report; rendered images carry no original EXIF metadata."""
import base64
from html import escape
import json
from pathlib import Path
import cv2
from scout.report import atomic_write


def write_analysis(directory, result, pictures):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # A reused output directory must not expose masks from a previous result.
    for key in ('reference', 'current', 'difference', 'overlay'):
        if key not in pictures:
            (directory / (key + '.png')).unlink(missing_ok=True)
    atomic_write(directory / 'inspection.json', json.dumps(result, ensure_ascii=False,
                                                          indent=2, allow_nan=False) + '\n')
    figures = []
    titles = {'reference': 'Эталон', 'current': 'Новый снимок после выравнивания',
              'difference': 'Карта различий', 'overlay': 'Выделенные изменения'}
    for key, image in pictures.items():
        ok, encoded = cv2.imencode('.png', image)
        if not ok:
            raise ValueError('cannot encode report image')
        data = encoded.tobytes()
        (directory / (key + '.png')).write_bytes(data)
        uri = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
        figures.append('<figure><figcaption>' + titles[key] + '</figcaption><img alt="' +
                       titles[key] + '" src="' + uri + '"></figure>')
    status = {'CHANGED': 'Найдено изменение', 'UNCHANGED': 'Значимых изменений нет',
              'INCONCLUSIVE': 'Недостаточно данных'}[result['result']]
    provenance = ('СИНТЕТИЧЕСКИЕ ТЕСТОВЫЕ ИЗОБРАЖЕНИЯ' if result['evidence']['synthetic']
                  else 'ФОТОГРАФИИ — ПРОИСХОЖДЕНИЕ УКАЗАНО ОПЕРАТОРОМ')
    data = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    download = 'data:application/json;base64,' + base64.b64encode(data.encode()).decode()
    html = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    html += '<title>Scout 02 — инспекция изображений</title><style>'
    html += 'body{font:16px/1.5 system-ui;background:#101820;color:#e7eef4;max-width:1200px;margin:auto;padding:24px}h1{font-size:28px}.tag{color:#ffdc8c}main{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{min-width:0;margin:0;background:#19252f;padding:16px;border-radius:12px}img{width:100%;height:auto}a{color:#7ce0c1}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}@media(max-width:700px){main{grid-template-columns:1fr}body{padding:16px}}</style>'
    html += '<h1>Scout 02 · ' + status + '</h1><p class="tag">' + provenance + '</p>'
    html += '<p>OpenCV обработал пиксели изображений. Этот отчёт сам по себе не подтверждает точность на реальном объекте.</p>'
    html += '<p>Причина: <strong>' + escape(result['reason'] or '') + '</strong></p>'
    html += '<main>' + ''.join(figures) + '</main><p><a download="inspection.json" href="' + download + '">Скачать JSON</a></p>'
    html += '<details><summary>Метрики и параметры</summary><pre>' + escape(data) + '</pre></details></html>'
    atomic_write(directory / 'report.html', html)
