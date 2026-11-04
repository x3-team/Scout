"""Canonical draft.3 offline consistency checks; no controller or adapter.

Source metadata is a recorded claim, not authenticated execution. Active trial
and epoch are trusted caller inputs, never inferred from the report under test.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from contract_schema import ROOT, finite, matches, parse, require, schema_supported

VERSION = 'scout-skillforge/0.1-draft.3'
FAULTS = ('STOP_NOT_CONFIRMED', 'FOOTPRINT_GUARD', 'INVALID_OBSERVATION',
          'LOCALIZATION_UNAVAILABLE', 'SENSOR_UNAVAILABLE', 'STALE_SENSOR',
          'CONTROLLER_TIMEOUT', 'CONTROLLER_EXCEPTION', 'INVALID_COMMAND', 'RUNNER_EXCEPTION')
OUTCOMES = {'completed': ('GOAL_REACHED',), 'blocked': ('PATH_BLOCKED',),
            'timeout': ('MISSION_TIMEOUT',), 'fault': FAULTS}


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def close(a, b):
    return abs(a-b) <= 1e-9


def zero(v):
    return v['v_mps'] == 0 and v['omega_rad_s'] == 0


def outcome(value):
    require(value['reason'] in OUTCOMES[value['status']], 'status/reason mismatch')


def check_stop(stop):
    require(stop['attempted'], 'independent local stop not attempted')
    if stop['confirmed']:
        require(stop['telemetry'] is not None and zero(stop['telemetry']),
                'stop confirmation needs checked zero telemetry')


def check_point(pose, world):
    x, y, r = pose['x_m'], pose['y_m'], world['radius_m']
    require(r < x < world['width_m']-r and r < y < world['height_m']-r, 'footprint outside world')
    for box in world['obstacles']:
        nx = min(max(x, box['x_min']), box['x_max'])
        ny = min(max(y, box['y_min']), box['y_max'])
        require(math.hypot(x-nx, y-ny) > r, 'footprint intersects obstacle')


def sensor_reason(obs, profile):
    if obs['pose'] is None:
        return 'LOCALIZATION_UNAVAILABLE'
    if obs['sensor_status'] == 'unavailable':
        return 'SENSOR_UNAVAILABLE'
    age = obs['time_s']-obs['sampled_at_s']
    if not -1e-9 <= age <= 2*profile['dt_s']+1e-9:
        return 'STALE_SENSOR'
    if obs['front_body_clearance_m'] <= profile['stop_clearance_m']:
        return 'PATH_BLOCKED'
    return None


def check_command(command, obs, schema):
    matches(command, schema['$defs']['command'], schema)
    for key in ('trial_id', 'epoch', 'segment_id', 'target_id', 'step'):
        require(command[key] == obs[key], 'command correlation: '+key)
    require(command['expires_after_step'] == obs['step']+1, 'command TTL')
    require(command['mode'] == ('stop' if zero(command['velocity']) else 'drive'), 'command mode')
    require(obs['motion_enabled'] or zero(command['velocity']), 'motion disabled requires stop')
    require(len(json.dumps(command).encode('utf-8')) <= 65536, 'wire message too large')


def terminal_reason(row, report):
    if not row['local_stop']['confirmed']:
        return 'STOP_NOT_CONFIRMED'
    if row['guard_activated']:
        return 'FOOTPRINT_GUARD'
    obs, profile = row['observation'], report['session']['profile']
    fault = sensor_reason(obs, profile)
    if fault and fault != 'PATH_BLOCKED':
        return fault
    if row['controller_fault']:
        return row['controller_fault']
    if fault:
        return fault
    if obs['step'] == profile['max_steps']:
        return 'MISSION_TIMEOUT'
    return 'GOAL_REACHED'


def validate_report(report, schema, *, active_trial_id, active_epoch):
    finite(report)
    require(len(json.dumps(report, ensure_ascii=False).encode('utf-8')) <= 16*1024*1024,
            'experiment report too large')
    matches(report, schema['$defs']['experiment_report'], schema)
    require(report['trial_id'] == active_trial_id and report['epoch'] == active_epoch, 'inactive trial/epoch')
    session, manifest, plan, trace = (report[k] for k in ('session', 'manifest', 'plan', 'trace'))
    for obj in (session, manifest):
        require(all(obj[k] == report[k] for k in ('trial_id', 'epoch')), 'manifest/session identity')
    require(manifest['wire_schema_sha256'] == hashlib.sha256(
        (ROOT/'contract-v0.schema.json').read_bytes()).hexdigest(), 'wire schema digest')
    require(manifest['profile'] == session['profile'], 'manifest profile mismatch')
    require(manifest['seed']['value'] == session['seed'], 'manifest seed mismatch')
    scene = manifest['scene']
    require(session['plan'] == plan, 'session/plan mismatch')
    require(scene['world'] == session['world'] and scene['start_pose'] == session['start_pose']
            and scene['plan'] == plan, 'scene/session/plan mismatch')
    require(manifest['scene_sha256'] == digest(scene), 'scene digest')
    if report['execution'] == 'digital_simulation':
        for source in manifest['sources'].values():
            require(all(source.values()), 'measured source provenance incomplete')
        require(all(manifest['environment'].values()), 'measured environment incomplete')
    world, profile = session['world'], session['profile']
    for box in world['obstacles']:
        require(0 <= box['x_min'] < box['x_max'] <= world['width_m'], 'invalid box x')
        require(0 <= box['y_min'] < box['y_max'] <= world['height_m'], 'invalid box y')
    check_point(session['start_pose'], world)
    ids = [p['segment_id'] for p in plan]
    require(len(set(ids)) == len(ids), 'duplicate planned segment')
    require(len({p['target_id'] for p in plan}) == len(plan), 'duplicate planned target')
    by_id = {p['segment_id']:p for p in plan}
    for p in plan:
        check_point(p, world)
    advances, current_index, seen_starts, inspected = 0, 0, {}, set()
    for i, row in enumerate(trace):
        obs = row['observation']
        require(obs['step'] == i and close(obs['time_s'], i*profile['dt_s']), 'global clock/sequence')
        require(i == advances, 'record after non-advance or terminal')
        require(all(obs[k] == report[k] for k in ('trial_id', 'epoch')), 'observation identity')
        require(obs['segment_id'] in by_id, 'unplanned segment')
        p = by_id[obs['segment_id']]
        require(obs['target_id'] == p['target_id'], 'observation target mismatch')
        index = ids.index(obs['segment_id'])
        if index != current_index:
            require(index == current_index+1 and ids[current_index] in inspected, 'segment transition without inspection')
            current_index = index
        seen_starts.setdefault(obs['segment_id'], i)
        require((obs['sensor_status'] == 'unavailable') == (obs['front_body_clearance_m'] is None), 'sensor status/null mismatch')
        if obs['pose'] is not None:
            check_point(obs['pose'], world)
        if i == 0 and obs['pose'] is not None:
            require(obs['pose'] == session['start_pose'], 'initial pose')
        require(obs['velocity'] == (trace[i-1]['applied'] if i else {'v_mps':0,'omega_rad_s':0}),
                'observation velocity does not match previous applied action')
        if i and obs['pose'] is not None and trace[i-1]['observation']['pose'] is not None:
            a, b = trace[i-1]['observation']['pose'], obs['pose']
            require(math.hypot(a['x_m']-b['x_m'], a['y_m']-b['y_m']) <=
                    trace[i-1]['applied']['v_mps']*profile['dt_s']+1e-9, 'pose exceeds applied speed')
            angle = (b['yaw_rad']-a['yaw_rad']+math.pi) % (2*math.pi)-math.pi
            require(abs(angle) <= abs(trace[i-1]['applied']['omega_rad_s'])*profile['dt_s']+1e-9,
                    'pose exceeds applied turn rate')
        require(len(json.dumps(obs).encode('utf-8')) <= 65536, 'wire observation too large')
        phase = row['phase']
        require(not row['guard_activated'] or phase == 'terminal', 'guard must terminate')
        if phase in ('terminal', 'interrupted'):
            require(i == len(trace)-1 and not row['advance'] and row['applied'] is None, 'terminal/interrupted advance')
            require((not obs['motion_enabled'] or row['guard_activated']) and row['local_stop'] is not None, 'terminal stop required')
            check_stop(row['local_stop'])
            require(row['limitation'] == ('interrupted' if phase == 'interrupted' else 'safety-stop'), 'terminal limitation reason')
            if not row['guard_activated']:
                require(row['requested'] is None and row['raw_action'] is None, 'new terminal command')
            else:
                require(i < 3600 and obs['motion_enabled'] and sensor_reason(obs,profile) is None
                        and row['requested'] is not None and row['raw_action'] is not None,
                        'guard attempt context')
            if phase == 'interrupted':
                require(not report['report_complete'], 'interrupted report marked complete')
        else:
            require(i < 3600 and row['advance'], 'advance outside budget')
            require(sensor_reason(obs, profile) is None, 'advance after safety fault')
            require(not row['controller_fault'] and row['rejected_response'] is None, 'advance after controller fault')
            require(row['requested'] is not None, 'missing requested command')
            require(row['applied'] == row['requested']['velocity'], 'applied/requested mismatch')
            if phase == 'inspection':
                require(not obs['motion_enabled'] and row['raw_action'] is None and zero(row['applied']), 'inspection must not call GoalSeeker or move')
                require(row['local_stop'] is not None, 'inspection local stop missing')
                check_stop(row['local_stop'])
                require(row['local_stop']['confirmed'], 'unconfirmed inspection stop')
                require(row['limitation'] == 'inspection-stop', 'inspection limitation')
                require(obs['segment_id'] not in inspected, 'repeated inspection')
                inspected.add(obs['segment_id'])
            else:
                require(obs['motion_enabled'] and row['raw_action'] is not None and row['local_stop'] is None, 'navigate context')
                require(obs['segment_id'] not in inspected, 'motion after completed segment')
            advances += 1
        if row['requested'] is not None:
            check_command(row['requested'], obs, schema)
        if row['raw_action'] is not None:
            raw = row['raw_action']
            requested = {'v_mps':min(.15,max(0,raw['v_mps'])), 'omega_rad_s':min(.8,max(-.8,raw['omega_rad_s']))}
            require(row['requested'] is not None and row['requested']['velocity'] == requested, 'raw/normalized command mismatch')
            if phase == 'navigate':
                require(row['limitation'] == ('none' if raw == requested else 'controller-normalized'), 'normalization reason')
        if row['controller_fault'] == 'INVALID_COMMAND':
            require(row['rejected_response'] is not None, 'invalid response evidence missing')
        else:
            require(row['rejected_response'] is None, 'unexpected rejected response')
    require(report['last_confirmed_step'] == advances, 'last confirmed advance boundary')
    check_stop(report['stop'])
    outcome(report['outcome'])
    if trace and trace[-1]['phase'] in ('terminal','interrupted'):
        require(report['stop'] == trace[-1]['local_stop'], 'final stop evidence mismatch')
    results = report['results']
    result_ids = [r['segment_id'] for r in results]
    require(len(set(result_ids)) == len(result_ids), 'duplicate result')
    require(result_ids == ids[:len(results)], 'result order')
    classified = result_ids+report['missing_results']+report['not_started_segments']
    require(len(classified) == len(set(classified)) and set(classified) == set(ids), 'results/missing/not-started partition')
    require(set(report['not_started_segments']) == set(ids)-set(seen_starts), 'not-started truth')
    require(set(report['missing_results']) == set(seen_starts)-set(result_ids), 'missing results truth')
    for result in results:
        require(all(result[k] == report[k] for k in ('trial_id','epoch')), 'result identity')
        sid, a, b = result['segment_id'], result['start_step'], result['end_step']
        require(sid in seen_starts and a == seen_starts[sid] and a <= b < len(trace), 'segment interval')
        require(result['target_id'] == by_id[sid]['target_id'], 'result target mismatch')
        require(all(t['observation']['segment_id'] == sid for t in trace[a:b+1]), 'segment trace correlation')
        end = trace[b]
        require(end['phase'] in ('inspection','terminal'), 'result without segment end')
        outcome(result['outcome'])
        require(end['local_stop'] is not None and result['stop_confirmed'] == end['local_stop']['confirmed'], 'result stop evidence')
        reason = terminal_reason(end,report) if end['phase'] == 'terminal' else 'GOAL_REACHED'
        require(result['outcome']['reason'] == reason, 'result safety priority')
        if reason == 'GOAL_REACHED':
            pose, target = end['observation']['pose'], by_id[sid]
            require(pose is not None and math.hypot(pose['x_m']-target['x_m'],pose['y_m']-target['y_m']) <= profile['arrival_tolerance_m'], 'goal not reached')
        metrics = result['metrics']
        require(metrics['steps'] == b-a and close(metrics['duration_s'],(b-a)*profile['dt_s']), 'segment clock')
        path = 0.
        for j in range(a,b):
            require(trace[j]['advance'], 'missing segment advance')
            p, q = trace[j]['observation']['pose'],trace[j+1]['observation']['pose']
            require(p is not None and q is not None, 'distance requires valid recorded poses')
            path += math.hypot(q['x_m']-p['x_m'],q['y_m']-p['y_m'])
        require(close(metrics['distance_m'],path), 'distance/trace mismatch')
        require(metrics['distance_m'] <= .15*metrics['duration_s']+1e-9, 'distance/time bound')
        require(metrics['collision_guard_activations'] == sum(t['guard_activated'] for t in trace[a:b+1]), 'guard count mismatch')
    if report['report_complete']:
        require(report['error'] is None, 'complete report carries serialization/runner error')
        require(trace and trace[-1]['phase'] == 'terminal' and not report['missing_results'], 'complete report lacks terminal or result')
        require(results and results[-1]['end_step'] == len(trace)-1, 'final result missing')
        require(report['outcome'] == results[-1]['outcome'], 'mission/final result mismatch')
        if report['outcome']['status'] == 'completed':
            require(len(results) == len(plan) and all(r['outcome']['status'] == 'completed' for r in results), 'premature mission completion')
    else:
        error = report['error']
        require(error is not None and error['at_step'] == advances, 'partial report error/boundary')
        require(report['outcome']['status'] == 'fault', 'partial report cannot be success')
        expected = error['code'] if report['stop']['confirmed'] else 'STOP_NOT_CONFIRMED'
        if trace and trace[-1]['phase'] == 'interrupted' and report['stop']['confirmed']:
            priority = terminal_reason(trace[-1],report)
            if priority in FAULTS:
                expected = min(error['code'],priority,key=FAULTS.index)
        require(report['outcome']['reason'] == expected, 'partial report fault/stop priority')
        require(not any(t['phase'] == 'terminal' for t in trace), 'partial report has completed terminal row')
    if not report['stop']['confirmed']:
        require(report['outcome'] == {'status':'fault','reason':'STOP_NOT_CONFIRMED'}, 'stop outcome priority')
    else:
        require(report['outcome']['reason'] != 'STOP_NOT_CONFIRMED', 'false unconfirmed-stop reason')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('runs/contract-draft3-check.json'))
    parser.add_argument('--examples-dir',type=Path)
    args = parser.parse_args()
    from contract_checks import run_checks
    result = run_checks()
    destination, checkout = args.output.resolve(), ROOT.parents[1]
    require(not destination.is_relative_to(checkout) or destination.is_relative_to(checkout/'runs'), 'write output under runs/ or outside checkout')
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if args.examples_dir:
        directory = args.examples_dir.resolve()
        require(not directory.is_relative_to(checkout) or directory.is_relative_to(checkout/'runs'),
                'write examples under runs/ or outside checkout')
        from contract_fixtures import examples
        directory.mkdir(parents=True,exist_ok=True)
        for name,report in examples().items():
            (directory/(name+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
