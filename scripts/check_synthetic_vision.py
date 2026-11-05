"""Fixed procedural pixel stress matrix, not a real-camera accuracy benchmark."""
import argparse
from dataclasses import asdict
import hashlib
from html import escape
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
from scout.vision.fixtures import fixture_images
from scout.vision.engine import analyze_pair,VisionConfig


def cases():
    images = fixture_images()
    for name,image in images.items():
        if name=='reference':continue
        yield name,image,('CHANGED' if name in ('changed','removed') else
                         'INCONCLUSIVE' if name in ('missing-marker','occluded','blurred','dark') else 'UNCHANGED'),'.png',None
    src=np.float32([[0,0],[999,0],[999,699],[0,699]])
    destinations=[src,np.float32([[20,15],[975,20],[985,680],[15,685]]),
                  np.float32([[35,20],[960,35],[980,665],[20,680]])]
    for kind in ('unchanged','changed','removed'):
        expected='UNCHANGED' if kind=='unchanged' else 'CHANGED'
        for view,dst in enumerate(destinations):
            for light in (-8,0,8):
                frame=np.clip(images[kind].astype(np.int16)+light,0,255).astype(np.uint8)
                frame=cv2.warpPerspective(frame,cv2.getPerspectiveTransform(src,dst),(1000,700),borderValue=(245,245,245))
                yield f'{kind}-view{view}-light{light}',frame,expected,'.png',None
        for sigma in (1,3):
            rng=np.random.default_rng(20261105+sigma)
            frame=np.clip(images[kind].astype(float)+rng.normal(0,sigma,images[kind].shape),0,255).astype(np.uint8)
            yield f'{kind}-noise{sigma}',frame,expected,'.png',None
        for quality in (75,95):
            yield f'{kind}-jpeg{quality}',images[kind],expected,'.jpg',[cv2.IMWRITE_JPEG_QUALITY,quality]
    for marker,(x,y) in {10:(40,40),20:(840,40),30:(840,540),40:(40,540)}.items():
        frame=images['reference'].copy();frame[y-10:y+130,x-10:x+130]=245
        yield f'missing-{marker}',frame,'INCONCLUSIVE','.png',None
    duplicate=images['reference'].copy();duplicate[250:370,450:570]=duplicate[40:160,40:160]
    yield 'duplicate-id',duplicate,'INCONCLUSIVE','.png',None
    swapped=images['reference'].copy()
    swapped[40:160,40:160],swapped[40:160,840:960]=swapped[40:160,840:960].copy(),swapped[40:160,40:160].copy()
    yield 'swapped-markers',swapped,'INCONCLUSIVE','.png',None
    yield 'white-frame',np.full_like(images['reference'],255),'INCONCLUSIVE','.png',None
    yield 'cropped-marker',images['reference'][:,100:],'INCONCLUSIVE','.png',None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path('runs/synthetic-vision'))
    args=parser.parse_args();out=args.output_dir.resolve()
    if out.is_relative_to(ROOT) and not out.is_relative_to(ROOT/'runs'):raise ValueError('output outside sources or under runs/')
    if out.exists() and any(out.iterdir()):raise ValueError('fresh output directory required')
    out.mkdir(parents=True,exist_ok=True)
    reference=out/'reference.png';reference.write_bytes(cv2.imencode('.png',fixture_images()['reference'])[1].tobytes())
    rows=[]
    for name,image,expected,suffix,encoding in cases():
        folder=out/name;folder.mkdir()
        path=folder/('current'+suffix)
        path.write_bytes(cv2.imencode(suffix,image,encoding or [])[1].tobytes())
        result,pictures=analyze_pair(reference,path,input_kind='synthetic')
        repeated,_=analyze_pair(reference,path,input_kind='synthetic')
        (folder/'inspection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if 'overlay' in pictures:
            thumb=cv2.resize(pictures['overlay'],(500,350))
            (folder/'overlay.jpg').write_bytes(cv2.imencode('.jpg',thumb)[1].tobytes())
        rows.append(dict(case=name,expected=expected,actual=result['result'],reason=result['reason'],
                         passed=result['result']==expected,repeated_equal=result==repeated,
                         current=f'{name}/current{suffix}',overlay=f'{name}/overlay.jpg' if 'overlay' in pictures else None,
                         input_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    # Bad reference quality must also refuse to compare, even with a good current.
    for name in ('dark','blurred','missing-marker','occluded'):
        bad=out/name/ 'current.png'
        result,_=analyze_pair(bad,reference,input_kind='synthetic')
        (out/f'bad-reference-{name}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        rows.append(dict(case='bad-reference-'+name,expected='INCONCLUSIVE',actual=result['result'],
                         reason=result['reason'],passed=result['result']=='INCONCLUSIVE',repeated_equal=None,current='reference.png',overlay=None))
    summary=dict(kind='procedural-synthetic-vision-matrix',seed=20261105,config=asdict(VisionConfig()),
                 environment=dict(python=platform.python_version(),opencv=cv2.__version__,numpy=np.__version__,os=platform.platform()),
                 source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted([* (ROOT/'scout/vision').glob('*.py'),Path(__file__).resolve()])},
                 count=len(rows),passed=sum(r['passed'] for r in rows),
                 repeat_checks=sum(r['repeated_equal'] is not None for r in rows),
                 all_passed=all(r['passed'] and r['repeated_equal'] is not False for r in rows),cases=rows,
                 real_photographs_tested=False,real_lab_acceptance=False,
                 notice='Fixed synthetic coverage only; not all possible conditions or measured photo accuracy.')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    cards=[]
    for r in rows:
        cards.append(f'<article><h2>{escape(r["case"])}</h2><p>Ожидание: {r["expected"]}; результат: {r["actual"]}; {escape(r["reason"] or "")}</p>'
                     f'<a href="{r["current"]}"><img src="{r["current"]}" alt="Синтетический вход"></a>'+
                     (f'<img src="{r["overlay"]}" alt="Выделенные изменения">' if r['overlay'] else '')+'</article>')
    page='<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Scout — синтетическая матрица</title><style>body{font:16px system-ui;max-width:1100px;margin:24px auto;padding:16px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}article{border:1px solid #bbb;padding:12px;border-radius:10px}h2{font-size:18px}img{width:100%}</style><h1>Scout: процедурные синтетические проверки</h1>'
    page+=f'<p>Пройдено {summary["passed"]}/{summary["count"]}. Это искусственные пиксели, не фотографии и не обучение модели.</p><p><a href="summary.json">Все исходы, параметры и хеши</a> · <a href="reference.png">Эталон</a></p><main>'+''.join(cards)+'</main></html>'
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('count','passed','repeat_checks','all_passed')}))
    for r in rows:
        if not r['passed']:print(json.dumps(r))
    return 0 if summary['all_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
