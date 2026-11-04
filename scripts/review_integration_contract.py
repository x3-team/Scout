"""Reproduce known draft.2 gaps; a successful review is NOT contract acceptance.

No robot, controller, adapter or measured experiment is executed. This pins the
expected findings of the reviewed revision; fixes require a new review baseline.
"""
import argparse
import hashlib
import json
from pathlib import Path

from check_contract_clock import clock_exchange
from check_integration_contract import ROOT, changed, matches, parse, require, validate


def review():
    schema_raw = (ROOT / 'contract-v0.schema.json').read_bytes()
    schema = parse(schema_raw.decode('utf-8'))
    examples = parse((ROOT / 'contract-v0.examples.json').read_text(encoding='utf-8'))
    base = examples['base']
    require(base['session']['schema_version'] == 'scout-skillforge/0.1-draft.2',
            'review baseline must be updated for a new wire revision')
    # Positive control: R1 stays fixed. The final advance may originate at 3599.
    validate(clock_exchange(base, 3599), schema)
    probes = [
        ('R2-result-reused-for-other-target', 'R2', 'exchange', 'accept', 'reject',
         [('observation.target.id', 'B')]),
        ('R2-later-segment-local-step-count', 'R2', 'exchange', 'reject', 'accept',
         [('previous_step', 299), ('observation.step', 300),
          ('observation.time_s', 15), ('observation.sampled_at_s', 15),
          ('command.step', 300), ('command.expires_after_step', 301),
          ('result.metrics.steps', 20), ('result.metrics.duration_s', 1),
          ('result.metrics.distance_m', 0.1)]),
        ('R2-terminal-observation-at-budget', 'R2', 'observation', 'reject', 'accept',
         [('observation.step', 3600), ('observation.time_s', 180),
          ('observation.sampled_at_s', 180)]),
        ('R4-measured-claim-without-manifest', 'R4', 'exchange', 'accept', 'reject',
         [('result.execution', 'digital_simulation')]),
        ('SCOUT-C1-completed-with-sensor-fault-reason', 'SCOUT-C1', 'exchange', 'accept', 'reject',
         [('result.reason', 'SENSOR_UNAVAILABLE')]),
        ('SCOUT-C1-timeout-with-goal-reached-reason', 'SCOUT-C1', 'exchange', 'accept', 'reject',
         [('result.status', 'timeout')]),
    ]
    findings = []
    for name, group, kind, baseline, required, changes in probes:
        value = changed(base, changes)
        error = None
        try:
            if kind == 'observation':
                matches(value['observation'], schema, schema)
            else:
                validate(value, schema)
            observed = 'accept'
        except ValueError as exc:
            observed, error = 'reject', str(exc)
        require(observed == baseline, 'review finding changed; re-review: ' + name)
        findings.append({'name': name, 'group': group, 'kind': kind,
                         'changes': changes, 'observed': observed,
                         'required_in_next_revision': required, 'error': error})
    return {
        'kind': 'integration-contract-review',
        'schema_version': base['session']['schema_version'],
        'reviewed_source_ref': 'a880fac2d17a3eae541945640ee5a1d72d6cf202',
        'schema_sha256': hashlib.sha256(schema_raw).hexdigest(),
        'R1_final_command_step_positive_control_passed': True,
        'findings': findings,
        'blocking_groups': ['R2', 'R4', 'SCOUT-C1'],
        'decision': 'request-revision',
        'contract_accepted': False,
        'runtime_adapter_executed': False,
        'poc_executed': False,
        'notice': 'Exit 0 reproduces known gaps, not acceptance. Inputs are format fixtures. '
                  'Required next-revision behavior follows the proposed segment/manifest design, '
                  'not the current draft.2 schema. No real run or telemetry is claimed.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        root = ROOT.parents[1]
        output = args.output.resolve()
        require(not output.is_relative_to(root) or output.is_relative_to(root / 'runs'),
                'write review output under runs/ or outside the checkout')
    result = review()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                               encoding='utf-8')
    print('REVIEW REPRODUCED: R1 control passed; 6 probes confirm open R2/R4/SCOUT-C1. '
          'Decision=request-revision; contract_accepted=false; no adapter executed.')


if __name__ == '__main__':
    main()
