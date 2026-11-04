"""R1 regression retained for draft.3, including terminal observation 3600."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from check_integration_contract import ROOT, parse, matches, require, validate_report, sensor_reason
from contract_fixtures import TRIAL, EPOCH, long_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    schema = parse((ROOT/'contract-v0.schema.json').read_text(encoding='utf-8'))
    report = long_report()
    validate_report(report,schema,active_trial_id=TRIAL,active_epoch=EPOCH)
    last = report['trace'][3599]['observation']
    old = deepcopy(schema)
    for key in ('time_s','sampled_at_s'):
        old['$defs']['observation']['properties'][key]['maximum'] = 179.95
    try:
        matches(last,old['$defs']['observation'],old)
    except ValueError:
        pass
    else:
        raise AssertionError('old R1 bounds did not fail')
    cases = [(-.1,None),(-.1-5e-10,None),(5e-10,None),(-.1-2e-9,'STALE_SENSOR'),(2e-9,'STALE_SENSOR')]
    for age,expected in cases:
        obs = deepcopy(last)
        obs['sampled_at_s'] = obs['time_s']+age
        require(sensor_reason(obs,report['session']['profile']) == expected, 'sensor tolerance regression')
    result = {'kind':'draft3-clock-regression','old_R1_reproduced':True,
              'legal_advance_steps':3600,'terminal_observation_step':3600,
              'terminal_time_s':180.,'sensor_tolerance_cases':len(cases),
              'contract_accepted':False,'runtime_adapter_executed':False,'poc_executed':False}
    if args.output:
        root, output = ROOT.parents[1], args.output.resolve()
        require(not output.is_relative_to(root) or output.is_relative_to(root/'runs'),
                'write output under runs/ or outside checkout')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
