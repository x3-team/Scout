"""Offline checks of the proposed contract fixtures; no controller or adapter.

The schema walker implements only the keywords used by this document, rejecting
unsupported keywords. It is not a general JSON Schema implementation or runtime
input validator. Run from any working directory with Python 3.12+.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'docs' / 'integration'
KEYWORDS = {'$schema', '$defs', '$ref', 'title', 'type', 'required', 'properties',
            'additionalProperties', 'oneOf', 'const', 'enum', 'minimum', 'maximum',
            'exclusiveMaximum', 'minLength', 'maxLength', 'maxItems', 'items'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('nonfinite JSON constant: ' + value)


def parse(raw):
    require(len(raw.encode('utf-8')) <= 65536, 'message too large')
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    finite(result)
    return result


def finite(value):
    if isinstance(value, float):
        require(math.isfinite(value), 'nonfinite number')
    elif isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, list):
        for item in value:
            finite(item)


def equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def schema_supported(node):
    require(not set(node) - KEYWORDS, 'unsupported schema keyword')
    for key in ('$defs', 'properties'):
        for child in node.get(key, {}).values():
            schema_supported(child)
    for child in node.get('oneOf', []):
        schema_supported(child)
    if 'items' in node:
        schema_supported(node['items'])


def matches(value, rule, schema):
    if '$ref' in rule:
        require(rule['$ref'].startswith('#/$defs/'), 'only local refs supported')
        return matches(value, schema['$defs'][rule['$ref'].split('/')[-1]], schema)
    if 'oneOf' in rule:
        successes = 0
        for candidate in rule['oneOf']:
            try:
                matches(value, candidate, schema)
                successes += 1
            except ValueError:
                pass
        require(successes == 1, 'oneOf mismatch')
    if 'const' in rule:
        require(equal(value, rule['const']), 'const mismatch')
    if 'enum' in rule:
        require(any(equal(value, item) for item in rule['enum']), 'enum mismatch')
    kinds = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'boolean': isinstance(value, bool),
             'null': value is None,
             'number': type(value) in (int, float),
             'integer': type(value) in (int, float) and int(value) == value}
    # int(value) must never run on NaN/Inf; finite() is called before schema checks.
    if 'type' in rule:
        require(kinds[rule['type']], 'type mismatch')
    if isinstance(value, dict):
        require(set(rule.get('required', [])) <= set(value), 'required field missing')
        properties = rule.get('properties', {})
        if rule.get('additionalProperties') is False:
            require(set(value) <= set(properties), 'unknown field')
        for key, child in value.items():
            if key in properties:
                matches(child, properties[key], schema)
    if isinstance(value, list):
        require(len(value) <= rule.get('maxItems', math.inf), 'too many items')
        for child in value:
            matches(child, rule.get('items', {}), schema)
    if isinstance(value, str):
        require(rule.get('minLength', 0) <= len(value) <= rule.get('maxLength', math.inf), 'string length')
    if type(value) in (int, float):
        require(rule.get('minimum', -math.inf) <= value <= rule.get('maximum', math.inf), 'number range')
        if 'exclusiveMaximum' in rule:
            require(value < rule['exclusiveMaximum'], 'exclusive maximum')


def validate(exchange, schema):
    finite(exchange)
    session, obs, command, result = (exchange[k] for k in ('session', 'observation', 'command', 'result'))
    for item in (session, obs, command, result):
        matches(item, schema, schema)
        require(item['session_id'] == session['session_id'], 'session mismatch')
    require(obs['step'] == exchange['previous_step'] + 1, 'step sequence')
    require(command['step'] == obs['step'], 'command step mismatch')
    require(command['expires_after_step'] == obs['step'] + 1, 'command TTL')
    require(abs(obs['time_s'] - obs['step'] * session['dt_s']) <= 1e-9, 'model clock')
    age = obs['time_s'] - obs['sampled_at_s']
    require(-1e-9 <= age <= 2 * session['dt_s'] + 1e-9, 'sensor age')
    distance = obs['front_body_clearance_m']
    require((obs['sensor_status'] == 'unavailable') == (distance is None), 'sensor null/status mismatch')
    moving = command['v_mps'] != 0 or command['omega_rad_s'] != 0
    require(command['mode'] != 'stop' or not moving, 'nonzero stop command')
    if moving:
        require(distance is not None and distance > session['stop_clearance_m'], 'safety stop required')
    world = session['world']
    for box in world['obstacles']:
        require(0 <= box['x_min'] < box['x_max'] <= world['width_m'], 'invalid box x')
        require(0 <= box['y_min'] < box['y_max'] <= world['height_m'], 'invalid box y')
    for point in (obs['pose'], obs['target']):
        x, y, r = point['x_m'], point['y_m'], world['radius_m']
        require(r < x < world['width_m'] - r and r < y < world['height_m'] - r, 'footprint outside world')
        for box in world['obstacles']:
            nearest_x = min(max(x, box['x_min']), box['x_max'])
            nearest_y = min(max(y, box['y_min']), box['y_max'])
            require(math.hypot(x - nearest_x, y - nearest_y) > r, 'footprint intersects obstacle')
    require(result['status'] == 'fault' or result['stop_confirmed'], 'unconfirmed stop must be fault')
    metrics = result['metrics']
    require(abs(metrics['duration_s'] - metrics['steps'] * session['dt_s']) <= 1e-9, 'result model clock')


def changed(base, changes):
    result = deepcopy(base)
    for dotted, value in changes:
        keys = dotted.split('.')
        current = result
        for key in keys[:-1]:
            current = current[key]
        current[keys[-1]] = value
    return result


def main():
    schema = parse((ROOT / 'contract-v0.schema.json').read_text(encoding='utf-8'))
    examples = parse((ROOT / 'contract-v0.examples.json').read_text(encoding='utf-8'))
    schema_supported(schema)
    for case in examples['positive_cases']:
        validate(changed(examples['base'], case['changes']), schema)
    for case in examples['negative_cases']:
        try:
            validate(changed(examples['base'], case['changes']), schema)
        except ValueError:
            continue
        raise AssertionError('negative case accepted: ' + case['name'])
    for raw in ('{"step":0,"step":1}', '{"v":NaN}', '{"v":Infinity}', '{"v":1e999}'):
        try:
            parse(raw)
        except ValueError:
            continue
        raise AssertionError('invalid JSON accepted')
    for value in (float('nan'), float('inf'), -float('inf')):
        try:
            validate(changed(examples['base'], [('command.v_mps', value)]), schema)
        except ValueError:
            continue
        raise AssertionError('nonfinite native value accepted')
    print(f"PASS: {len(examples['positive_cases'])} positive, {len(examples['negative_cases'])} negative, 7 strict/nonfinite checks. Contract fixtures only; no adapter executed.")


if __name__ == '__main__':
    main()
