"""Regression evidence for R1 in the proposed wire contract, without an adapter.

Every generated exchange is a format fixture, never a measured robot run.
Run from any directory; --output optionally saves a reproducible JSON summary.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from check_integration_contract import ROOT, changed, parse, require, validate


def clock_exchange(base, step):
    time_s = step * base['session']['dt_s']
    return changed(base, [
        ('previous_step', step - 1),
        ('observation.step', step),
        ('observation.time_s', time_s),
        ('observation.sampled_at_s', time_s),
        ('command.step', step),
        ('command.expires_after_step', step + 1),
        ('result.metrics.steps', step),
        ('result.metrics.duration_s', time_s),
        ('result.metrics.distance_m', 0),
    ])


def rejected(exchange, schema):
    try:
        validate(exchange, schema)
    except ValueError:
        return True
    return False


def check():
    schema_raw = (ROOT / 'contract-v0.schema.json').read_bytes()
    examples_raw = (ROOT / 'contract-v0.examples.json').read_bytes()
    schema = parse(schema_raw.decode('utf-8'))
    examples = parse(examples_raw.decode('utf-8'))
    base = examples['base']
    require(base['session']['schema_version'] == 'scout-skillforge/0.1-draft.2',
            'test must follow the canonical candidate revision')

    # Prove that the old numerical maximum itself fails this legal input.
    # Keep the current version fields, so rejection cannot be a version mismatch.
    old_bounds = deepcopy(schema)
    for field in ('time_s', 'sampled_at_s'):
        old_bounds['$defs']['observation']['properties'][field]['maximum'] = 179.95
    last = clock_exchange(base, 3599)
    require(rejected(last, old_bounds), 'R1 no longer reproduced with draft.1 bounds')

    count = base['session']['max_steps']
    for step in range(count):
        validate(clock_exchange(base, step), schema)

    # Exercise the age tolerance near the last legal observation. Structural
    # headroom must preserve the context checks rather than accepting arbitrary t.
    age_positive = []
    for name, sampled_at in (
        ('oldest-fresh', last['observation']['time_s'] - 0.1),
        ('age-within-tolerance', last['observation']['time_s'] - 0.1 - 5e-10),
        ('future-within-tolerance', last['observation']['time_s'] + 5e-10),
    ):
        validate(changed(last, [('observation.sampled_at_s', sampled_at)]), schema)
        age_positive.append(name)

    negatives = [
        ('clock-is-not-180', [('observation.time_s', 180)]),
        ('sensor-is-not-180', [('observation.sampled_at_s', 180)]),
        ('clock-drift', [('observation.time_s', last['observation']['time_s'] + 2e-9)]),
        ('future-sensor', [('observation.sampled_at_s', last['observation']['time_s'] + 2e-9)]),
        ('stale-sensor', [('observation.sampled_at_s', last['observation']['time_s'] - 0.1 - 2e-9)]),
        ('expired-command', [('command.expires_after_step', 3599)]),
        ('ttl-exceeds-budget', [('command.expires_after_step', 3601)]),
        ('late-command', [('command.step', 3598)]),
        ('duplicate-step', [('previous_step', 3599)]),
        ('out-of-budget-step', [('observation.step', 3600)]),
        ('negative-step', [('observation.step', -1)]),
        ('old-version', [('command.schema_version', 'scout-skillforge/0.1-draft.1')]),
    ]
    for name, changes in negatives:
        require(rejected(changed(last, changes), schema), 'boundary accepted: ' + name)

    # A self-consistent beyond-budget exchange must still fail, even with clock,
    # TTL and result metrics changed together. No reset of the step budget.
    require(rejected(clock_exchange(base, count), schema), 'extra step accepted')
    require(schema_raw == (ROOT / 'contract-v0.schema.json').read_bytes(), 'schema mutated')
    require(examples_raw == (ROOT / 'contract-v0.examples.json').read_bytes(), 'examples mutated')
    return {
        'kind': 'contract-clock-regression',
        'execution': 'contract_fixture_checks',
        'schema_version': base['session']['schema_version'],
        'upstream_base_ref': '10817add66e15730f89599375132b2c08a4473f0',
        'skillforge_review_ref': '969ed414a761b701f21559ac68edcf9b7ac27b6b',
        'schema_sha256': hashlib.sha256(schema_raw).hexdigest(),
        'examples_sha256': hashlib.sha256(examples_raw).hexdigest(),
        'old_bounds_reproduce_R1': True,
        'legal_clock_steps_passed': count,
        'first_step': 0,
        'last_step': count - 1,
        'last_time_s': last['observation']['time_s'],
        'sensor_tolerance_positive_cases': age_positive,
        'negative_cases_rejected': [name for name, _ in negatives] + ['self-consistent-extra-step'],
        'runtime_adapter_executed': False,
        'poc_executed': False,
        'contract_accepted': False,
        'remaining_review_items': ['R2', 'R4'],
        'notice': 'Generated format fixtures only; no measured mission or photograph accuracy.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    # Refuse to overwrite source files with evidence, including script/schema
    # files, when the command is copied from the acceptance instructions.
    if args.output:
        root = ROOT.parents[1]
        output = args.output.resolve()
        require(not output.is_relative_to(root) or output.is_relative_to(root / 'runs'),
                'write evidence under runs/ or outside the checkout')
    result = check()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                               encoding='utf-8')
    print('PASS: R1 reproduced with old bounds; 3600 legal steps, 3 age-tolerance positives, '
          '13 boundaries rejected. No adapter or PoC executed.')


if __name__ == '__main__':
    main()
