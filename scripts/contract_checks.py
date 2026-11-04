"""Behavioral acceptance fixtures of the proposed wire revision, offline only."""
from copy import deepcopy
import hashlib
import json
from check_integration_contract import (ROOT, VERSION, FAULTS, OUTCOMES, validate_report,
                                       parse, require, schema_supported, terminal_reason)
from contract_fixtures import TRIAL, EPOCH, examples, refresh, result, stop, velocity, row


def set_path(value, path, replacement):
    keys = path.split('.')
    for key in keys[:-1]:
        value = value[int(key)] if isinstance(value,list) else value[key]
    key = int(keys[-1]) if isinstance(value,list) else keys[-1]
    value[key] = replacement


def run_checks():
    schema_raw = (ROOT/'contract-v0.schema.json').read_bytes()
    schema = parse(schema_raw.decode('utf-8'))
    schema_supported(schema)
    reports = examples()
    fixtures = parse((ROOT/'contract-v0.examples.json').read_text(encoding='utf-8'),16*1024*1024)
    for name,r in fixtures['literal_reports'].items():
        require(r == reports[name], 'committed example drift: '+name)
    positives = list(reports.items())
    base = reports['inspection-then-fault']
    # Check every complete fault path, preserving its real/unknown stop evidence.
    for code in ('SENSOR_UNAVAILABLE','STALE_SENSOR','LOCALIZATION_UNAVAILABLE',
                 'CONTROLLER_TIMEOUT','CONTROLLER_EXCEPTION','INVALID_COMMAND','FOOTPRINT_GUARD','STOP_NOT_CONFIRMED'):
        r = deepcopy(reports['blocked'])
        t = r['trace'][0]
        t['observation']['front_body_clearance_m'] = 1
        if code == 'SENSOR_UNAVAILABLE':
            t['observation'].update(sensor_status='unavailable',front_body_clearance_m=None)
        elif code == 'STALE_SENSOR':
            t['observation']['sampled_at_s'] = .01
        elif code == 'LOCALIZATION_UNAVAILABLE':
            t['observation']['pose'] = None
        elif code in ('CONTROLLER_TIMEOUT','CONTROLLER_EXCEPTION','INVALID_COMMAND'):
            t['controller_fault'] = code
            if code == 'INVALID_COMMAND':
                t['rejected_response'] = '{"v_mps":NaN}'
        elif code == 'FOOTPRINT_GUARD':
            attempt = row(0,'B-1','B',v=.1)
            t.update(raw_action=attempt['raw_action'],requested=attempt['requested'],guard_activated=True)
            t['observation']['motion_enabled'] = True
        else:
            t['local_stop'] = stop(False)
            r['stop'] = stop(False)
        r['results'][0].update(outcome={'status':'fault','reason':code},stop_confirmed=t['local_stop']['confirmed'])
        r['results'][0]['metrics']['collision_guard_activations'] = int(t['guard_activated'])
        r['outcome'] = {'status':'fault','reason':code}
        positives.append(('fault-'+code,r))
    # The measured-profile positive exists ONLY as an in-memory format test.
    # It is not saved as a measured report or evidence of an executed robot run.
    measured = deepcopy(base)
    measured['execution'] = 'digital_simulation'
    for source in measured['manifest']['sources'].values():
        source['source_sha256'] = '1'*64
    measured['manifest']['environment'] = {'python':'fixture-3.12','os':'fixture-linux'}
    positives.append(('measured-format-completeness-only',measured))
    normalized = deepcopy(base)
    normalized['trace'][0]['raw_action']['v_mps'] = 1
    normalized['trace'][0]['requested']['velocity']['v_mps'] = .15
    normalized['trace'][0]['applied']['v_mps'] = .15
    normalized['trace'][1]['observation']['velocity']['v_mps'] = .15
    normalized['trace'][0]['limitation'] = 'controller-normalized'
    positives.append(('raw-normalization-recorded',normalized))
    before_observation = deepcopy(reports['partial-missing-observation'])
    before_observation.update(trace=[],last_confirmed_step=0,missing_results=[],not_started_segments=['A-1','B-1'])
    before_observation['error']['at_step'] = 0
    positives.append(('partial-before-first-observation',before_observation))
    unknown_stop = deepcopy(reports['partial-controller-exception'])
    unknown_stop['stop'] = stop(False)
    unknown_stop['trace'][-1]['local_stop'] = stop(False)
    unknown_stop['outcome']['reason'] = 'STOP_NOT_CONFIRMED'
    positives.append(('partial-unconfirmed-stop',unknown_stop))
    runner_error = deepcopy(reports['partial-missing-observation'])
    runner_error['error']['code'] = 'RUNNER_EXCEPTION'
    runner_error['outcome']['reason'] = 'RUNNER_EXCEPTION'
    positives.append(('partial-runner-exception',runner_error))
    guard_stop = deepcopy(next(r for n,r in positives if n == 'fault-FOOTPRINT_GUARD'))
    guard_stop['stop'] = stop(False)
    guard_stop['trace'][0]['local_stop'] = stop(False)
    guard_stop['results'][0].update(outcome={'status':'fault','reason':'STOP_NOT_CONFIRMED'},stop_confirmed=False)
    guard_stop['outcome'] = {'status':'fault','reason':'STOP_NOT_CONFIRMED'}
    positives.append(('unconfirmed-stop-outranks-guard',guard_stop))
    # A sensor fault at the budget limit must outrank the timeout.
    budget_fault = deepcopy(reports['full-budget-terminal'])
    budget_fault['trace'][-1]['observation'].update(sensor_status='unavailable',front_body_clearance_m=None)
    budget_fault['outcome'] = {'status':'fault','reason':'SENSOR_UNAVAILABLE'}
    budget_fault['results'][0]['outcome'] = deepcopy(budget_fault['outcome'])
    positives.append(('sensor-fault-outranks-budget',budget_fault))
    for name,r in positives:
        try:
            validate_report(r,schema,active_trial_id=TRIAL,active_epoch=EPOCH)
        except Exception as error:
            raise AssertionError('positive rejected: '+name) from error
    negatives = []
    def mutation(name,path,value,source=base):
        r = deepcopy(source)
        set_path(r,path,value)
        negatives.append((name,r,TRIAL,EPOCH))
    for name,path,value in [
        ('unknown-version','session.schema_version','future'),
        ('old-draft-version','session.schema_version','scout-skillforge/0.1-draft.2'),
        ('wrong-frame','session.frame','image_y_down'),
        ('different-trial','trace.0.observation.trial_id','other'),
        ('old-observation-epoch','trace.0.observation.epoch','old'),
        ('old-command-epoch','trace.0.requested.epoch','old'),
        ('wrong-command-target','trace.0.requested.target_id','B'),
        ('wrong-command-segment','trace.0.requested.segment_id','B-1'),
        ('late-command','trace.0.requested.step',1),
        ('wrong-TTL','trace.0.requested.expires_after_step',2),
        ('result-target-replay','results.0.target_id','B'),
        ('result-epoch-replay','results.0.epoch','old'),
        ('result-trial-replay','results.0.trial_id','other'),
        ('result-segment-replay','results.0.segment_id','B-1'),
        ('duplicate-step','trace.1.observation.step',0),
        ('skipped-step','trace.1.observation.step',2),
        ('wrong-clock','trace.1.observation.time_s',.051),
        ('future-sensor-drive','trace.0.observation.sampled_at_s',.01),
        ('missing-sensor-drive','trace.0.observation.front_body_clearance_m',None),
        ('blocked-drive','trace.0.observation.front_body_clearance_m',.22),
        ('bool-speed','trace.0.requested.velocity.v_mps',True),
        ('reverse-wire-command','trace.0.requested.velocity.v_mps',-.01),
        ('overspeed-wire-command','trace.0.requested.velocity.v_mps',.151),
        ('overturn-wire-command','trace.0.requested.velocity.omega_rad_s',.801),
        ('wrong-command-mode','trace.0.requested.mode','stop'),
        ('applied-not-requested','trace.0.applied.v_mps',.12),
        ('unrecorded-normalization','trace.0.raw_action.v_mps',1),
        ('wrong-normalization-reason','trace.0.limitation','controller-normalized'),
        ('missing-raw-action','trace.0.raw_action',None),
        ('inspection-controller-call','trace.2.raw_action',velocity()),
        ('inspection-movement','trace.2.applied.v_mps',.1),
        ('inspection-enabled','trace.2.observation.motion_enabled',True),
        ('no-inspection-stop','trace.2.local_stop',None),
        ('false-inspection-stop','trace.2.local_stop.confirmed',False),
        ('advance-after-fault','trace.3.advance',True),
        ('new-command-after-fault','trace.3.requested',base['trace'][0]['requested']),
        ('invented-applied-after-fault','trace.3.applied',velocity()),
        ('safety-stop-not-attempted','stop.attempted',False),
        ('stop-without-telemetry','stop.telemetry',None),
        ('nonzero-confirmed-stop','stop.telemetry.v_mps',.1),
        ('wrong-last-confirmed-boundary','last_confirmed_step',2),
        ('metric-time-mismatch','results.0.metrics.duration_s',.11),
        ('impossible-distance','results.0.metrics.distance_m',1),
        ('guard-count-fabricated','results.0.metrics.collision_guard_activations',1),
        ('unearned-success','results.1.outcome',{'status':'completed','reason':'GOAL_REACHED'}),
        ('wrong-end-interval','results.0.end_step',3),
        ('wrong-start-interval','results.1.start_step',0),
        ('fake-observation-velocity','trace.2.observation.velocity.v_mps',0),
        ('pose-teleport','trace.1.observation.pose.x_m',.7),
        ('heading-teleport','trace.1.observation.pose.yaw_rad',1),
        ('outside-footprint','trace.1.observation.pose.x_m',.1),
        ('partial-claim-of-complete','report_complete',False),
        ('false-measurement-label','execution','digital_simulation'),
        ('complete-report-error-hidden','error',{'code':'RUNNER_EXCEPTION','at_step':3,'message':'fixture'}),
        ('scene-digest-mismatch','manifest.scene_sha256','f'*64),
        ('wire-digest-mismatch','manifest.wire_schema_sha256','f'*64),
        ('wrong-manifest-epoch','manifest.epoch','old'),
        ('wrong-manifest-seed','manifest.seed.value',2),
        ('session-plan-target-mismatch','session.plan.0.x_m',2.4),
        ('bad-normalization-version','manifest.normalization','unknown'),
        ('bad-seed-derivation','manifest.seed.derivation','random'),
        ('fake-not-started','not_started_segments',['B-1']),
        ('missing-result-erased','results',[]),
    ]:
        mutation(name,path,value)
    for key in ('trial_id','epoch','wire_revision','wire_schema_sha256','sources','scene','scene_sha256',
                'seed','profile','normalization','environment'):
        r = deepcopy(measured);del r['manifest'][key]
        negatives.append(('missing-manifest-'+key,r,TRIAL,EPOCH))
    for product in ('scout','skillforge'):
        for key in ('commit','source_sha256'):
            mutation('incomplete-'+product+'-'+key,'manifest.sources.'+product+'.'+key,None,measured)
            mutation('malformed-'+product+'-'+key,'manifest.sources.'+product+'.'+key,'invalid',measured)
    for key in ('python','os'):
        mutation('missing-environment-'+key,'manifest.environment.'+key,None,measured)
    for status,reasons in OUTCOMES.items():
        for reason in ('GOAL_REACHED','PATH_BLOCKED','MISSION_TIMEOUT',*FAULTS):
            if reason not in reasons:
                mutation('C1-'+status+'/'+reason,'results.0.outcome',{'status':status,'reason':reason})
    mutation('unknown-fault-code','results.1.outcome.reason','UNKNOWN')
    mutation('global-steps-as-segment-count','results.1.metrics.steps',300,reports['late-short-segment'])
    mutation('terminal3600-command','trace.3600.requested',base['trace'][0]['requested'],reports['full-budget-terminal'])
    mutation('terminal3600-advance','trace.3600.advance',True,reports['full-budget-terminal'])
    mutation('terminal3600-clock','trace.3600.observation.time_s',179.95,reports['full-budget-terminal'])
    extra = deepcopy(reports['full-budget-terminal']);extra['trace'].append(row(3601,'B-1','B','terminal'))
    negatives.append(('record3601',extra,TRIAL,EPOCH))
    mutation('premature-timeout','outcome',{'status':'timeout','reason':'MISSION_TIMEOUT'},reports['completed-route'])
    premature = deepcopy(reports['late-short-segment'])
    premature['outcome'] = {'status':'timeout','reason':'MISSION_TIMEOUT'}
    premature['results'][-1]['outcome'] = deepcopy(premature['outcome'])
    negatives.append(('self-consistent-premature-timeout',premature,TRIAL,EPOCH))
    for name,path,value in [
        ('partial-missing-error','error',None),
        ('partial-fabricated-completion','report_complete',True),
        ('partial-erase-missing','missing_results',[]),
        ('partial-fake-boundary','last_confirmed_step',2),
        ('partial-unknown-observation-invented','trace.1.observation.pose.x_m',2),
        ('partial-success','outcome',{'status':'completed','reason':'GOAL_REACHED'}),
        ('partial-wrong-error-step','error.at_step',0),
    ]:
        mutation(name,path,value,reports['partial-controller-exception'])
    mutation('partial-stop-fault-masked','outcome.reason','CONTROLLER_EXCEPTION',unknown_stop)
    fake_stop_error = deepcopy(reports['partial-controller-exception'])
    fake_stop_error['error']['code'] = 'STOP_NOT_CONFIRMED'
    fake_stop_error['outcome']['reason'] = 'STOP_NOT_CONFIRMED'
    negatives.append(('false-unconfirmed-stop-with-confirmed-telemetry',fake_stop_error,TRIAL,EPOCH))
    mutation('budget-fault-masked-as-timeout','outcome',{'status':'timeout','reason':'MISSION_TIMEOUT'},budget_fault)
    masked = deepcopy(budget_fault)
    masked['outcome'] = {'status':'timeout','reason':'MISSION_TIMEOUT'}
    masked['results'][-1]['outcome'] = deepcopy(masked['outcome'])
    negatives.append(('self-consistent-budget-fault-masked',masked,TRIAL,EPOCH))
    for value in (float('nan'),float('inf'),-float('inf')):
        mutation('native-nonfinite-'+str(value),'trace.0.raw_action.v_mps',value)
    r = deepcopy(base);r['trace'][0]['requested']['extra'] = 1
    negatives.append(('unknown-wire-field',r,TRIAL,EPOCH))
    negatives.append(('whole-report-replayed-old-active-epoch',deepcopy(base),TRIAL,'new-active-epoch'))
    negatives.append(('whole-report-replayed-other-active-trial',deepcopy(base),'other-trial',EPOCH))
    rejected = []
    for name,r,trial,epoch in negatives:
        try:
            validate_report(r,schema,active_trial_id=trial,active_epoch=epoch)
        except ValueError:
            rejected.append(name)
            continue
        raise AssertionError('negative accepted: '+name)
    strict = ['{"a":1,"a":2}','{"v":NaN}','{"v":Infinity}','{"v":1e999}',
              '['*40+'0'+']'*40]
    for raw in strict:
        try:parse(raw)
        except ValueError:continue
        raise AssertionError('strict JSON accepted: '+raw)
    return {'kind':'canonical-contract-fixture-check','schema_version':VERSION,
            'schema_sha256':hashlib.sha256(schema_raw).hexdigest(),
            'examples_sha256':hashlib.sha256((ROOT/'contract-v0.examples.json').read_bytes()).hexdigest(),
            'checker_dependencies':{name:hashlib.sha256((ROOT.parents[1]/name).read_bytes()).hexdigest()
                                    for name in ('scripts/check_integration_contract.py',
                                      'scripts/contract_schema.py','scripts/contract_fixtures.py',
                                      'scripts/contract_checks.py','scripts/check_contract_clock.py')},
            'scout_base_ref':'547a343a462169461be3a5e33ea6766f83b5b988',
            'skillforge_proposal_ref':'0fc2e8d96c6669782945e42bc78357d0aa4609ed',
            'positive_cases':[name for name,_ in positives], 'positive_count':len(positives),
            'negative_cases_rejected':rejected,'negative_count':len(rejected),'strict_json_count':len(strict),
            'legal_advance_steps_checked':3600,'terminal_observation_step':3600,
            'contract_accepted':False,'pending':'SkillForge explicit ref/digest review and repin',
            'runtime_adapter_executed':False,'poc_executed':False,
            'notice':'All cases are format fixtures, including the measured-profile completeness test. '
                     'No measured report or execution is claimed.'}
