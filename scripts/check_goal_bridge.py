"""Run four actual one-goal Scout/SkillForge cases from pinned source snapshots."""
import argparse
from dataclasses import replace
import hashlib
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scout.models import load_scenario
from scout.integration.runner import run_goal
from scout.integration.provenance import source_record,SKILLFORGE_REF
from check_integration_contract import validate_report,parse,ROOT as CONTRACT_ROOT


def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skillforge-root',type=Path,required=True)
    parser.add_argument('--skillforge-source-pin',type=Path,
                        help='Verified immutable snapshot receipt; unnecessary for a clean Git checkout')
    parser.add_argument('--scout-source-pin',type=Path,
                        help='Verified Scout snapshot receipt for an API-prepared checkout')
    parser.add_argument('--output-dir',type=Path,default=Path('runs/goal-bridge'))
    args = parser.parse_args()
    output,worker = args.output_dir.resolve(),args.skillforge_root.resolve()
    if output.is_relative_to(worker) or (output.is_relative_to(ROOT) and not output.is_relative_to(ROOT/'runs')):
        raise ValueError('output must be outside source trees or under Scout runs/')
    sources = dict(scout=source_record(ROOT,snapshot_pin=args.scout_source_pin),skillforge=source_record(worker,
                   snapshot_pin=args.skillforge_source_pin,expected_commit=SKILLFORGE_REF))
    schema = parse((CONTRACT_ROOT/'contract-v0.schema.json').read_text(encoding='utf-8'))
    normal = load_scenario(ROOT/'scout/scenarios/normal.json')
    turn = replace(normal,name='turn',stations=(replace(normal.stations[0],x=.6,y=1.8),*normal.stations[1:]))
    cases = [('forward',normal,'GOAL_REACHED'),('turn',turn,'GOAL_REACHED'),
             ('blocked',load_scenario(ROOT/'scout/scenarios/blocked.json'),'PATH_BLOCKED'),
             ('sensor-failure',load_scenario(ROOT/'scout/scenarios/sensor-failure.json'),'SENSOR_UNAVAILABLE')]
    output.mkdir(parents=True,exist_ok=True)
    summary,figures = [],[]
    for name,scenario,expected in cases:
        bundle = run_goal(scenario,[sys.executable,'-m','skillforge.scout_worker'],worker,sources)
        report = bundle['report']
        validate_report(report,schema,active_trial_id=report['trial_id'],active_epoch=report['epoch'])
        if (report['outcome']['reason'] != expected or not report['stop']['confirmed']
                or bundle['runtime']['worker_alive_after_cleanup']
                or bundle['runtime']['confirmed_advances'] != report['last_confirmed_step']):
            raise AssertionError('one-goal acceptance failed: '+name)
        directory = output/name;directory.mkdir(exist_ok=True)
        for key,filename in [('report','report.json'),('transport','transport.json'),
                             ('source_scenario','scenario.json'),('runtime','runtime.json')]:
            write_json(directory/filename,bundle[key])
        metrics = report['results'][0]['metrics']
        summary.append(dict(case=name,status=report['outcome']['status'],reason=expected,
                            **metrics,stop_confirmed=True,report_sha256=hashlib.sha256((directory/'report.json').read_bytes()).hexdigest()))
        world = report['session']['world'];scale = 120
        points = ' '.join(f"{r['observation']['pose']['x_m']*scale:.4f},{(world['height_m']-r['observation']['pose']['y_m'])*scale:.4f}"
                          for r in report['trace'])
        boxes = ''.join(f'<rect x="{b["x_min"]*scale}" y="{(world["height_m"]-b["y_max"])*scale}" width="{(b["x_max"]-b["x_min"])*scale}" height="{(b["y_max"]-b["y_min"])*scale}" fill="#a1aab8"/>' for b in world['obstacles'])
        target = report['plan'][0]
        figures.append(f'<article><h2>{html.escape(name)}</h2><p>{html.escape(expected)} · {metrics["steps"]} steps · {metrics["duration_s"]:.2f} s · {metrics["distance_m"]:.3f} m</p>'
                       f'<svg viewBox="0 0 {world["width_m"]*scale} {world["height_m"]*scale}" role="img" aria-label="Recorded Scout trajectory">'
                       f'<rect width="100%" height="100%" fill="#edf1f7"/>{boxes}<polyline points="{points}" fill="none" stroke="#087f72" stroke-width="2"/>'
                       f'<circle cx="{target["x_m"]*scale}" cy="{(world["height_m"]-target["y_m"])*scale}" r="4" fill="#dc6b22"/></svg>'
                       f'<a href="{name}/report.json">Canonical report</a> · <a href="{name}/transport.json">Process transcript</a></article>')
    result = dict(kind='scout-skillforge-one-goal-checkpoint',sources=sources,cases=summary,
                  single_goal_integration_executed=True,physics_owner='Scout SimRobot',
                  full_route_A_B_C_HOME_executed=False,baseline_comparison_executed=False,
                  hardware_executed=False,notice='Four actual single-goal process/physics runs; not full mission acceptance.')
    write_json(output/'summary.json',result)
    page = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Scout × SkillForge — one goal</title><style>body{font:16px system-ui;margin:32px auto;padding:0 20px;max-width:1000px;color:#172333}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}article{border:1px solid #cbd3dd;border-radius:12px;padding:16px}svg{width:100%;height:auto}a{color:#075f80}h1{font-size:28px}p{line-height:1.5}</style><h1>Scout × SkillForge: четыре реальные проверки одной цели</h1><p>Настоящий GoalSeeker в отдельном процессе; единственная физика — Scout. Зелёная линия — записанная траектория, оранжевая точка — цель. Это не полный маршрут A/B/C/HOME и не испытание оборудования.</p><p><a href="summary.json">Source receipts and summary</a></p><main>'+''.join(figures)+'</main></html>'
    (output/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
