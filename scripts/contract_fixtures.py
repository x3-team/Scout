"""Deterministic FORMAT fixtures for draft.3, never measured experiments."""
from copy import deepcopy
import hashlib
import json
from check_integration_contract import ROOT, VERSION, digest

TRIAL, EPOCH = 'format-trial-1', 'format-epoch-1'


def velocity(v=0, w=0):
    return {'v_mps':v,'omega_rad_s':w}


def identity(kind):
    return {'schema_version':VERSION,'trial_id':TRIAL,'epoch':EPOCH,'type':kind}


def stop(confirmed=True):
    return {'attempted':True,'confirmed':confirmed,
            'telemetry':velocity() if confirmed else None}


def row(step, sid='A-1', target='A', phase='navigate', x=.6, v=0, previous_v=0):
    active = phase == 'navigate'
    advance = phase in ('navigate','inspection')
    obs = {**identity('observation'),'segment_id':sid,'target_id':target,
           'step':step,'time_s':step*.05,'sampled_at_s':step*.05,
           'pose':{'x_m':x,'y_m':.6,'yaw_rad':0},'velocity':velocity(previous_v),
           'motion_enabled':active,'sensor_status':'valid','front_body_clearance_m':1}
    command = {**identity('command'),'segment_id':sid,'target_id':target,'step':step,
               'expires_after_step':step+1,'mode':'drive' if v else 'stop','velocity':velocity(v)} if advance else None
    return {'observation':obs,'phase':phase,'raw_action':velocity(v) if active else None,
            'requested':command,'rejected_response':None,'applied':velocity(v) if advance else None,
            'limitation':{'navigate':'none','inspection':'inspection-stop','terminal':'safety-stop',
                          'interrupted':'interrupted'}[phase],
            'advance':advance,'guard_activated':False,'controller_fault':None,
            'local_stop':None if active else stop()}


def result(report, sid, a, b, status, reason):
    p = next(p for p in report['plan'] if p['segment_id'] == sid)
    trace = report['trace']
    import math
    distance = sum(math.hypot(trace[i+1]['observation']['pose']['x_m']-trace[i]['observation']['pose']['x_m'],
                              trace[i+1]['observation']['pose']['y_m']-trace[i]['observation']['pose']['y_m'])
                   for i in range(a,b))
    return {**identity('result'),'segment_id':sid,'target_id':p['target_id'],'start_step':a,
            'end_step':b,'scope':'segment','outcome':{'status':status,'reason':reason},
            'stop_confirmed':trace[b]['local_stop']['confirmed'],
            'metrics':{'steps':b-a,'duration_s':(b-a)*.05,'distance_m':distance,
                       'collision_guard_activations':sum(t['guard_activated'] for t in trace[a:b+1])}}


def refresh(report):
    """Keep scenario declaration coherent when a fixture deliberately changes it."""
    s, m = report['session'],report['manifest']
    s['plan'] = deepcopy(report['plan'])
    m['scene'].update(world=deepcopy(s['world']),start_pose=deepcopy(s['start_pose']),plan=deepcopy(report['plan']))
    m['scene_sha256'] = digest(m['scene'])
    return report


def empty():
    profile = dict(dt_s=.05,max_steps=3600,max_v_mps=.15,max_omega_rad_s=.8,
                   stop_clearance_m=.22,sensor_range_m=1.,arrival_tolerance_m=.025,controller_timeout_s=1.)
    session = {**identity('session'),'profile_id':'digital_known_map','frame':'lab_x_right_y_up_yaw_ccw',
               'profile':profile,'seed':1,'controller':{'id':'goal_seeker','version':1},
               'world':{'width_m':3,'height_m':2.4,'radius_m':.14,'obstacles':[]},
               'start_pose':{'x_m':.6,'y_m':.6,'yaw_rad':0},'plan':[],
               'provenance':{'pose':'ideal_simulation','map':'ideal_static_map',
                             'range':'synthetic_body_clearance','computer_vision_executed':False}}
    manifest = {'trial_id':TRIAL,'epoch':EPOCH,'wire_revision':VERSION,
                'wire_schema_sha256':hashlib.sha256((ROOT/'contract-v0.schema.json').read_bytes()).hexdigest(),
                'sources':{'scout':{'commit':'547a343a462169461be3a5e33ea6766f83b5b988','source_sha256':None},
                           'skillforge':{'commit':'0fc2e8d96c6669782945e42bc78357d0aa4609ed','source_sha256':None}},
                'scene':{'world':{},'start_pose':{},'plan':[],
                         'sensor_noise_m':.002,'sensor_failure_at_s':None},
                'scene_sha256':'0'*64,'seed':{'value':1,'derivation':'identity-u64-v1'},
                'profile':deepcopy(profile),'normalization':'si-lab-yaw-clamp-v1',
                'environment':{'python':None,'os':None}}
    return {**identity('experiment_report'),'execution':'contract_example','session':session,
            'manifest':manifest,'plan':[],'trace':[],'results':[], 'not_started_segments':[],
            'missing_results':[],'report_complete':True,'last_confirmed_step':0,
            'outcome':{'status':'fault','reason':'SENSOR_UNAVAILABLE'},'stop':stop(),'error':None}


def base_report():
    r = empty()
    r['plan'] = [{'segment_id':'A-1','target_id':'A','x_m':.61,'y_m':.6},
                 {'segment_id':'B-1','target_id':'B','x_m':2.4,'y_m':.6}]
    r['trace'] = [row(0,v=.1),row(1,x=.605,v=.1,previous_v=.1),
                  row(2,phase='inspection',x=.61,previous_v=.1),
                  row(3,'B-1','B',phase='terminal',x=.61)]
    r['trace'][-1]['observation'].update(sensor_status='unavailable',front_body_clearance_m=None)
    r['manifest']['scene']['sensor_failure_at_s'] = .15
    r['last_confirmed_step'] = 3
    r['results'] = [result(r,'A-1',0,2,'completed','GOAL_REACHED'),
                    result(r,'B-1',3,3,'fault','SENSOR_UNAVAILABLE')]
    return refresh(r)


def long_report(start=0, end=3600, timeout=True):
    r = empty()
    r['plan'] = [{'segment_id':'B-1','target_id':'B','x_m':.6 if not timeout else 2.4,'y_m':.6}]
    if start:
        r['plan'].insert(0,{'segment_id':'A-1','target_id':'A','x_m':.6,'y_m':.6})
    r['trace'] = [row(i,'A-1' if i<start else 'B-1','A' if i<start else 'B',
                      'terminal' if i==end else ('inspection' if start and i==start-1 else 'navigate'))
                  for i in range(end+1)]
    r['last_confirmed_step'] = end
    status, reason = ('timeout','MISSION_TIMEOUT') if timeout else ('completed','GOAL_REACHED')
    r['outcome'] = {'status':status,'reason':reason}
    r['results'] = ([result(r,'A-1',0,start-1,'completed','GOAL_REACHED')] if start else [])
    r['results'].append(result(r,'B-1',start,end,status,reason))
    return refresh(r)


def partial_report(missing_observation=False):
    r = base_report()
    r['trace'] = r['trace'][:1] if missing_observation else [r['trace'][0],row(1,phase='interrupted',x=.605,previous_v=.1)]
    code = 'INVALID_OBSERVATION' if missing_observation else 'CONTROLLER_EXCEPTION'
    if not missing_observation:
        r['trace'][-1]['controller_fault'] = code
    r.update(results=[],not_started_segments=['B-1'],missing_results=['A-1'],report_complete=False,
             last_confirmed_step=1,outcome={'status':'fault','reason':code},
             error={'code':code,'at_step':1,'message':'Format fixture: injected failure, not an executed controller.'})
    return r


def examples():
    r = base_report()
    success = deepcopy(r)
    success['plan'][1]['x_m'] = .61
    success['trace'][-1]['observation'].update(sensor_status='valid',front_body_clearance_m=1)
    success['results'][-1]['outcome'] = {'status':'completed','reason':'GOAL_REACHED'}
    success['outcome'] = {'status':'completed','reason':'GOAL_REACHED'}
    refresh(success)
    blocked = long_report(end=0)
    blocked['trace'][0]['observation']['front_body_clearance_m'] = .22
    blocked['outcome'] = {'status':'blocked','reason':'PATH_BLOCKED'}
    blocked['results'][0]['outcome'] = deepcopy(blocked['outcome'])
    return {'inspection-then-fault':r,'completed-route':success,'blocked':blocked,
            'partial-controller-exception':partial_report(),
            'partial-missing-observation':partial_report(True),
            'late-short-segment':long_report(280,300,False),
            'full-budget-terminal':long_report()}


if __name__ == '__main__':
    # Long generated cases are recipes in code, not thousands of invented
    # measurements in source control. The three base reports remain readable.
    data = examples()
    literal = {k:v for k,v in data.items() if k not in ('late-short-segment','full-budget-terminal')}
    (ROOT/'contract-v0.examples.json').write_text(json.dumps({
        'notice':'FORMAT FIXTURES ONLY. No adapter, PoC or measured experiment executed.',
        'literal_reports':literal,
        'generated_reports':{'late-short-segment':{'start_step':280,'end_step':300},
                             'full-budget-terminal':{'start_step':0,'end_step':3600}}},
        ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
