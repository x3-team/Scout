"""Paired four-scenario Scout baseline / public GoalSeeker full-route experiment."""
import argparse
from dataclasses import asdict
import hashlib
import html
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scout.models import load_scenario
from scout.integration.runner import run_route
from scout.integration.baseline import run_baseline
from scout.integration.provenance import source_record,SKILLFORGE_REF,canonical
from check_integration_contract import parse,ROOT as CONTRACT_ROOT,validate_report
from check_goal_bridge import write_json

CASES = ('normal','deviations','blocked','sensor-failure')
CONTROLLERS = ('scout_baseline','skillforge_goal_seeker')


def semantic(value):
    # Epochs are deliberately unique. No time, step, pose, input or action is removed.
    if isinstance(value,dict):
        return {k:semantic(v) for k,v in value.items() if k not in ('epoch','transport_canonical_sha256')}
    if isinstance(value,list):return [semantic(v) for v in value]
    return value


def same(a,b):
    if type(a) is not type(b):return False
    if isinstance(a,dict):return a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
    if isinstance(a,list):return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
    if type(a) is float:return math.isfinite(a) and math.isfinite(b) and abs(a-b)<=1e-9
    return a==b


def summarize(bundle,controller,scenario):
    r = bundle['report']
    if controller=='scout_baseline':
        advances = [x for x in bundle['audit'] if x['kind']=='advance']
        path = sum(math.hypot(x['after']['x']-x['before']['x'],x['after']['y']-x['before']['y']) for x in advances)
        status,reason = (r['status'].lower(),r['reason']) if r else ('fault','RUNNER_EXCEPTION')
        visited = r['visited_stations'] if r else []
        inspections = r['inspections'] if r else []
        complete = bool(r and r['returned_home'])
        guard = r['metrics']['collision_guard_activations'] if r else None
        normalized = sum(x['requested']!=x['applied'] for x in bundle['audit'] if x['kind']=='command')
        stop = bundle['runtime']['stop_confirmed']
        steps = bundle['runtime']['confirmed_advances']
    else:
        status,reason = r['outcome']['status'],r['outcome']['reason']
        visited = [i['station_id'] for i in bundle['inspections']]
        inspections = bundle['inspections']
        complete = bundle['runtime']['full_route_completed']
        guard = sum(t['guard_activated'] for t in r['trace'])
        normalized = sum(t['limitation']=='controller-normalized' for t in r['trace'])
        stop = r['stop']['confirmed']
        steps = r['last_confirmed_step']
        poses = [t['observation']['pose'] for t in r['trace']]
        path = sum(math.hypot(b['x_m']-a['x_m'],b['y_m']-a['y_m'])
                   for a,b in zip(poses,poses[1:]) if a is not None and b is not None)
    expected = ('completed' if scenario.name in ('normal','deviations') else
                'blocked' if scenario.name=='blocked' else 'fault')
    accepted = status==expected and stop and guard==0 and steps==bundle['runtime']['confirmed_advances']
    if expected=='completed':
        accepted = accepted and complete and visited==['A','B','C']
        accepted = accepted and [i['result'] for i in inspections]==(
            ['UNCHANGED']*3 if scenario.name=='normal' else ['UNCHANGED','CHANGED','CHANGED'])
        accepted = accepted and all(i['synthetic'] and i['evidence_source']=='scenario_fixture' for i in inspections)
    else:
        accepted = accepted and reason==('PATH_BLOCKED' if expected=='blocked' else 'SENSOR_UNAVAILABLE')
    return dict(controller=controller,scenario=scenario.name,status=status,reason=reason,steps=steps,
                duration_s=steps*.05,distance_m=path,visited_stations=visited,returned_home=complete,
                stop_confirmed=stop,guard_activations=guard,normalized_commands=normalized,
                distance_complete=bool(r and (controller=='scout_baseline' or r['report_complete'])),
                changed_stations=sum(i['result']=='CHANGED' for i in inspections),acceptance_passed=bool(accepted))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skillforge-root',type=Path,required=True)
    parser.add_argument('--skillforge-source-pin',type=Path)
    parser.add_argument('--scout-source-pin',type=Path)
    parser.add_argument('--output-dir',type=Path,default=Path('runs/route-bridge'))
    args = parser.parse_args()
    output,worker = args.output_dir.resolve(),args.skillforge_root.resolve()
    if output.is_relative_to(worker) or (output.is_relative_to(ROOT) and not output.is_relative_to(ROOT/'runs')):
        raise ValueError('output must be outside source trees or under Scout runs/')
    if output.exists() and any(output.iterdir()):raise ValueError('use a fresh output directory; preserve prior evidence')
    sources = dict(scout=source_record(ROOT,snapshot_pin=args.scout_source_pin),
                   skillforge=source_record(worker,snapshot_pin=args.skillforge_source_pin,expected_commit=SKILLFORGE_REF))
    schema = parse((CONTRACT_ROOT/'contract-v0.schema.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True,exist_ok=True)
    primary,repeats,all_runs = [],[],[]
    for name in CASES:
        scenario = load_scenario(ROOT/'scout/scenarios'/f'{name}.json')
        for controller in CONTROLLERS:
            normalized = []
            for repeat in (1,2):
                directory = output/name/controller/f'repeat-{repeat}'
                directory.mkdir(parents=True)
                bundle = (run_baseline(scenario,sources) if controller=='scout_baseline' else
                          run_route(scenario,[sys.executable,'-m','skillforge.scout_worker'],worker,sources))
                # Persist every attempt, including failures, before checking acceptance.
                for key,value in bundle.items():write_json(directory/f'{key}.json',value)
                validation_error = None
                if controller=='skillforge_goal_seeker':
                    r = bundle['report']
                    try:validate_report(r,schema,active_trial_id=r['trial_id'],active_epoch=r['epoch'])
                    except Exception as error:validation_error = str(error)
                row = summarize(bundle,controller,scenario)
                row.update(repeat=repeat,validation_error=validation_error,
                           scenario_sha256=scenario.digest,report=f'{name}/{controller}/repeat-{repeat}/report.json')
                row['acceptance_passed'] = row['acceptance_passed'] and validation_error is None
                all_runs.append(row)
                if repeat==1:primary.append(row)
                normalized.append(semantic(bundle))
            repeats.append(dict(scenario=name,controller=controller,tolerance=1e-9,
                                within_tolerance=same(*normalized),
                                semantic_sha256=[hashlib.sha256(canonical(x)).hexdigest() for x in normalized]))
    result = dict(kind='scout-skillforge-paired-full-route',sources=sources,seed=1,
                  cases=list(CASES),primary_runs=primary,all_runs=all_runs,reproducibility=repeats,
                  primary_count=8,executions_including_repeats=16,denominator_per_controller=4,
                  acceptance_passed=all(r['acceptance_passed'] for r in all_runs) and all(r['within_tolerance'] for r in repeats),
                  physics_owner='Scout SimRobot; stable exact arc',
                  sensor_policy='one sample per global boundary for both controllers',
                  synthetic_inspection=True,computer_vision_executed=False,hardware_executed=False,
                  normalization_notice='baseline uses legacy Scout report 1.0; canonical draft.3 is GoalSeeker-only',
                  reproducibility_ignored_fields=['epoch','transport_canonical_sha256'])
    write_json(output/'summary.json',result)
    rows = ''.join('<tr>'+''.join(f'<td>{html.escape(str(r[k]))}</td>' for k in
                   ('scenario','controller','reason','steps','duration_s','distance_m','visited_stations','stop_confirmed'))+
                   f'<td><a href="{r["report"]}">JSON</a></td></tr>' for r in primary)
    page = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scout × SkillForge — полный маршрут</title><style>body{font:16px system-ui;max-width:1200px;margin:32px auto;padding:0 16px;color:#172333}p{line-height:1.5}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border:1px solid #ccd3de;text-align:left}.scroll{overflow:auto}a{color:#075f80}</style>
<h1>Scout × SkillForge: A → B → C → HOME</h1><p>Четыре фиксированных сценария, два контроллера, по два запуска. Одна физика Scout; настоящий публичный worker SkillForge в отдельном процессе. Инспекция синтетическая, без камеры и оборудования.</p>'''
    page += f'<p>Автоматические критерии: {"ПРОЙДЕНЫ" if result["acceptance_passed"] else "НЕ ПРОЙДЕНЫ"}. Основных запусков: 8, с повторами: 16. Ошибки входят в знаменатель. Это не статистическое доказательство превосходства.</p>'
    page += '<p><a href="summary.json">Ревизии, хеши, все попытки и проверка повторов</a></p><div class="scroll"><table><thead><tr>'+''.join(f'<th>{x}</th>' for x in ('Сценарий','Контроллер','Исход','Шаги','Секунды модели','Путь, м','Станции','Stop','Отчёт'))+'</tr></thead><tbody>'+rows+'</tbody></table></div></html>'
    (output/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(dict(acceptance_passed=result['acceptance_passed'],primary=primary,reproducibility=repeats),ensure_ascii=False))
    return 0 if result['acceptance_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
