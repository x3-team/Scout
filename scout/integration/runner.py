"""One-goal offline checkpoint: actual public GoalSeeker process + Scout physics.

Full multi-station mission/inspection/baseline comparison is a later checkpoint.
The current canonical plan deliberately contains only the first station.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
import platform
import sys
import uuid
from .bridge import ProcessController,ControllerFailure,VERSION,SCHEMA_SHA256
from .digital import DigitalProbeRobot,session_for,observation_for,local_stop
from .provenance import canonical
from ..simulator import CollisionGuardError


def run_goal(scenario,worker_command,worker_root,sources,*,seed=1,epoch=None,
             execution='digital_simulation',robot_type=DigitalProbeRobot,timeout_s=1.):
    if (scenario.dt_s != .05 or scenario.robot.max_speed_mps != .15 or scenario.robot.max_turn_rps != .8
            or scenario.sensor_range_m != 1 or scenario.stop_clearance_m != .22 or scenario.arrival_tolerance_m != .025):
        raise ValueError('scenario outside the reviewed digital profile')
    session = session_for(scenario,seed,epoch or uuid.uuid4().hex)
    session['trial_id'] = 'goal-'+hashlib.sha256(scenario.name.encode()).hexdigest()[:12]+'-'+str(seed)
    session['plan'] = session['plan'][:1]
    ProcessController.check_session(session)
    scene = dict(world=deepcopy(session['world']),start_pose=deepcopy(session['start_pose']),
                 plan=deepcopy(session['plan']),sensor_noise_m=scenario.sensor_noise_m,
                 sensor_failure_at_s=scenario.sensor_failure_at_s)
    report = dict(schema_version=VERSION,type='experiment_report',trial_id=session['trial_id'],epoch=session['epoch'],
                  execution=execution,session=session,plan=deepcopy(session['plan']),trace=[],results=[],
                  not_started_segments=[],missing_results=[],report_complete=True,last_confirmed_step=0,
                  outcome=dict(status='fault',reason='RUNNER_EXCEPTION'),stop=None,error=None,
                  manifest=dict(trial_id=session['trial_id'],epoch=session['epoch'],wire_revision=VERSION,
                    wire_schema_sha256=SCHEMA_SHA256,sources=deepcopy(sources),scene=scene,
                    scene_sha256=hashlib.sha256(canonical(scene)).hexdigest(),
                    seed=dict(value=seed,derivation='identity-u64-v1'),profile=deepcopy(session['profile']),
                    normalization='si-lab-yaw-clamp-v1',environment=dict(python=platform.python_version(),os=platform.platform())))
    robot = robot_type(scenario,seed)
    controller = ProcessController(worker_command,cwd=worker_root,timeout_s=timeout_s)
    transport = []
    current_obs = None
    step = 0
    try:
        robot.stop()
        controller.start(session)
        for step in range(3601):
            telemetry = robot.read()
            current_obs = observation_for(telemetry,step,session)
            controller.check_observation(current_obs)
            reason = controller.expected_reason(current_obs)
            target = session['plan'][0]
            pose = current_obs['pose']
            reached = pose is not None and math.hypot(pose['x_m']-target['x_m'],pose['y_m']-target['y_m']) <= .025
            if reason or reached:
                current_obs['motion_enabled'] = False
                stop = local_stop(robot)
                reply = None
                if reason:
                    # Public worker proves it produces no new command for the
                    # terminal/safety observation; Scout has already stopped.
                    transport.append(dict(observation=deepcopy(current_obs),response=None))
                    reply = controller.act(current_obs)
                    transport[-1]['response'] = deepcopy(reply)
                reason = 'STOP_NOT_CONFIRMED' if not stop['confirmed'] else (reason or 'GOAL_REACHED')
                row = dict(observation=current_obs,phase='terminal',raw_action=None,requested=None,
                           rejected_response=None,applied=None,limitation='safety-stop',advance=False,
                           guard_activated=False,controller_fault=None,local_stop=stop)
                report['trace'].append(row)
                break
            transport.append(dict(observation=deepcopy(current_obs),response=None))
            reply = controller.act(current_obs)
            transport[-1]['response'] = deepcopy(reply)
            v = reply['command']['velocity']
            row = dict(observation=current_obs,phase='navigate',raw_action=reply['raw_action'],
                       requested=reply['command'],rejected_response=None,applied=deepcopy(v),
                       limitation=reply['limitation'],advance=True,guard_activated=False,
                       controller_fault=None,local_stop=None)
            robot.command(v['v_mps'],v['omega_rad_s'])
            try:
                robot.advance(.05)
            except CollisionGuardError:
                row.update(phase='terminal',applied=None,limitation='safety-stop',advance=False,
                           guard_activated=True,local_stop=local_stop(robot))
                report['trace'].append(row)
                reason = 'FOOTPRINT_GUARD' if row['local_stop']['confirmed'] else 'STOP_NOT_CONFIRMED'
                break
            report['trace'].append(row)
            report['last_confirmed_step'] += 1
        stop = report['trace'][-1]['local_stop']
        report['stop'] = stop
        status = ('completed' if reason == 'GOAL_REACHED' else 'blocked' if reason == 'PATH_BLOCKED'
                  else 'timeout' if reason == 'MISSION_TIMEOUT' else 'fault')
        report['outcome'] = dict(status=status,reason=reason)
        if current_obs['pose'] is None:
            # No invented end position or distance when localization is lost.
            raise ControllerFailure('LOCALIZATION_UNAVAILABLE','Missing terminal pose; pending request retained in transport')
        trace = report['trace']
        distance = sum(math.hypot(b['observation']['pose']['x_m']-a['observation']['pose']['x_m'],
                                  b['observation']['pose']['y_m']-a['observation']['pose']['y_m'])
                       for a,b in zip(trace,trace[1:]))
        report['results'] = [dict(schema_version=VERSION,type='result',trial_id=session['trial_id'],epoch=session['epoch'],
                                segment_id=target['segment_id'],target_id=target['target_id'],start_step=0,end_step=step,
                                scope='segment',outcome=deepcopy(report['outcome']),stop_confirmed=stop['confirmed'],
                                metrics=dict(steps=step,duration_s=step*.05,distance_m=distance,
                                             collision_guard_activations=sum(r['guard_activated'] for r in trace)))]
    except (ControllerFailure,ValueError,TypeError,KeyError,AttributeError) as error:
        code = error.code if isinstance(error,ControllerFailure) else 'INVALID_OBSERVATION'
        report['report_complete'] = False
        # Retain the confirmed prefix. In-flight requests and rejected/absent
        # replies stay in the transport sidecar; never invent a stopped input.
        if report['trace'] and not report['trace'][-1]['advance']:
            report['trace'].pop()
        report['results'] = []
        report['missing_results'] = [session['plan'][0]['segment_id']] if report['trace'] else []
        report['not_started_segments'] = [] if report['trace'] else [session['plan'][0]['segment_id']]
        report['error'] = dict(code=code,at_step=report['last_confirmed_step'],
                              message=(str(error)[:512]+'; pending input/response retained in transport sidecar'))
        report['outcome'] = dict(status='fault',reason=code)
        if transport and transport[-1]['response'] is None:
            transport[-1].update(rejected_response=controller.last_response_raw,failure_code=code)
    except Exception as error:
        report.update(report_complete=False,results=[],
                      missing_results=[session['plan'][0]['segment_id']] if report['trace'] else [],
                      not_started_segments=[] if report['trace'] else [session['plan'][0]['segment_id']],
                      error=dict(code='RUNNER_EXCEPTION',at_step=report['last_confirmed_step'],message=str(error)[:512]),
                      outcome=dict(status='fault',reason='RUNNER_EXCEPTION'))
    finally:
        final_stop = local_stop(robot)
        if report['stop'] is None:report['stop'] = final_stop
        if not final_stop['confirmed']:
            report['stop'] = final_stop
            report['outcome'] = dict(status='fault',reason='STOP_NOT_CONFIRMED')
            if report['report_complete'] and report['trace']:
                report['trace'][-1]['local_stop'] = final_stop
                if report['results']:
                    report['results'][-1].update(stop_confirmed=False,outcome=deepcopy(report['outcome']))
        controller.close()
    transport_digest = hashlib.sha256(canonical(transport)).hexdigest()
    if report['error'] is not None:
        report['error']['message'] += '; transport_canonical_sha256='+transport_digest
    return dict(report=report,transport=transport,source_scenario=asdict(scenario),
                runtime=dict(single_goal_only=True,worker_process_started=controller.process is not None,
                             scout_physics_executed=robot.advance_calls > 0,
                             worker_alive_after_cleanup=controller.alive,confirmed_advances=robot.advance_calls,
                             transport_canonical_sha256=transport_digest,
                             sensor_samples=robot.sensor_samples,paired_full_mission_poc_executed=False))
