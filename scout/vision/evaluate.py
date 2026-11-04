"""Held-out image evaluation. Labels never enter the image algorithm."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from .engine import VisionConfig, analyze_pair


def evaluate_manifest(path, config=None):
    path = Path(path)
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'input_kind', 'pairs'} or data['input_kind'] not in ('photograph', 'synthetic'):
        raise ValueError('manifest requires input_kind and pairs')
    if not isinstance(data['pairs'], list) or not data['pairs']:
        raise ValueError('manifest requires nonempty pairs')
    config = config or VisionConfig()
    ids, scenes, seen_images, evaluated = set(), {}, {}, []
    # Validate the entire split before running any inference.
    for pair in data['pairs']:
        if not isinstance(pair, dict) or set(pair) != {'id', 'scene_id', 'split', 'reference', 'current', 'label'}:
            raise ValueError('each pair requires id, scene_id, split, reference, current, label')
        if not all(isinstance(pair[k], str) and pair[k] for k in pair):
            raise ValueError('manifest fields must be nonempty strings')
        if pair['id'] in ids:
            raise ValueError('duplicate sample ID')
        ids.add(pair['id'])
        if pair['split'] not in ('tuning', 'evaluation') or pair['label'] not in ('CHANGED', 'UNCHANGED'):
            raise ValueError('invalid split or label')
        previous = scenes.setdefault(pair['scene_id'], pair['split'])
        if previous != pair['split']:
            raise ValueError('scene leakage between tuning and evaluation')
        for key in ('reference', 'current'):
            image_path = (path.parent / pair[key]).resolve()
            if not image_path.is_file():
                raise ValueError('dataset image does not exist: ' + pair[key])
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if digest in seen_images and seen_images[digest] != pair['split']:
                raise ValueError('identical image bytes leak between splits')
            seen_images[digest] = pair['split']
    # Reused baselines are allowed; duplicate current images cannot inflate sample count.
    current_hashes = set()
    for pair in data['pairs']:
        if pair['split'] != 'evaluation':
            continue
        current_path = path.parent / pair['current']
        digest = hashlib.sha256(current_path.read_bytes()).hexdigest()
        if digest in current_hashes:
            raise ValueError('duplicate evaluation current image')
        current_hashes.add(digest)
        result, _ = analyze_pair(path.parent / pair['reference'], current_path,
                                 input_kind=data['input_kind'], config=config)
        evaluated.append({'id': pair['id'], 'scene_id': pair['scene_id'],
                          'expected': pair['label'], 'predicted': result['result'],
                          'reason': result['reason']})
    if not evaluated:
        raise ValueError('no evaluation samples')
    positives = sum(p['expected'] == 'CHANGED' for p in evaluated)
    negatives = len(evaluated) - positives
    tp = sum(p['expected'] == p['predicted'] == 'CHANGED' for p in evaluated)
    fp = sum(p['expected'] == 'UNCHANGED' and p['predicted'] == 'CHANGED' for p in evaluated)
    tn = sum(p['expected'] == p['predicted'] == 'UNCHANGED' for p in evaluated)
    inconclusive = sum(p['predicted'] == 'INCONCLUSIVE' for p in evaluated)
    recall = tp / positives if positives else None
    fpr = fp / negatives if negatives else None
    coverage = 1 - inconclusive / len(evaluated)
    eligible = data['input_kind'] == 'photograph' and positives >= 20 and negatives >= 20
    return {'evaluation_schema_version': '1.0', 'input_kind_declared': data['input_kind'],
            'authenticity_verified': False, 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
            'config': asdict(config), 'samples': evaluated,
            'metrics': {'positive_count': positives, 'negative_count': negatives, 'tp': tp,
                        'fp': fp, 'tn': tn, 'fn_including_inconclusive': positives - tp,
                        'inconclusive_count': inconclusive, 'coverage': coverage,
                        'recall': recall, 'false_positive_rate': fpr,
                        'accuracy_including_inconclusive_as_error': (tp + tn) / len(evaluated)},
            'eligible_for_lab_acceptance': eligible,
            'acceptance_passed': bool(eligible and recall >= .9 and fpr <= .1 and coverage >= .9),
            'notice': 'Counts and metrics refer only to this declared, held-out dataset; '
                      'synthetic image metrics never validate real photograph accuracy.'}
