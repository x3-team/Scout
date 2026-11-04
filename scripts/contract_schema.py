"""Offline checks of the proposed contract fixtures; no controller or adapter.

The schema walker implements only the keywords used by this document, rejecting
unsupported keywords. It is not a general JSON Schema implementation or runtime
input validator. Run from any working directory with Python 3.12+.
"""
from copy import deepcopy
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'docs' / 'integration'
KEYWORDS = {'$schema', '$defs', '$ref', 'title', 'type', 'required', 'properties',
            'additionalProperties', 'oneOf', 'const', 'enum', 'minimum', 'maximum',
            'exclusiveMaximum', 'minLength', 'maxLength', 'maxItems', 'minItems', 'items', 'pattern'}


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


def parse(raw, max_bytes=65536):
    require(len(raw.encode('utf-8')) <= max_bytes, 'message too large')
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except RecursionError as error:
        raise ValueError('JSON nesting too deep') from error
    finite(result)
    return result


def finite(value, depth=0):
    require(depth <= 32, 'JSON nesting too deep')
    if isinstance(value, float):
        require(math.isfinite(value), 'nonfinite number')
    elif isinstance(value, dict):
        for item in value.values():
            finite(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            finite(item, depth + 1)


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
        require(len(value) >= rule.get('minItems', 0), 'too few items')
        require(len(value) <= rule.get('maxItems', math.inf), 'too many items')
        for child in value:
            matches(child, rule.get('items', {}), schema)
    if isinstance(value, str):
        require(rule.get('minLength', 0) <= len(value) <= rule.get('maxLength', math.inf), 'string length')
        if 'pattern' in rule:
            require(re.search(rule['pattern'], value) is not None, 'string pattern')
    if type(value) in (int, float):
        require(rule.get('minimum', -math.inf) <= value <= rule.get('maximum', math.inf), 'number range')
        if 'exclusiveMaximum' in rule:
            require(value < rule['exclusiveMaximum'], 'exclusive maximum')

