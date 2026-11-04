"""Fault-injection JSONL subprocesses for the Scout supervisor, no GoalSeeker."""
import json
import sys
import time


def serve(mode):
    source,destination = sys.stdin.buffer,sys.stdout.buffer
    def emit(value):
        destination.write(json.dumps(value).encode()+b'\n');destination.flush()
    session = json.loads(source.readline())
    emit(dict(protocol='skillforge-scout-worker/1',ready=True,wire_revision=session['schema_version']))
    calls = 0
    after_inspection = None
    for line in source:
        obs = json.loads(line);calls += 1
        if after_inspection is not None:after_inspection += 1
        if mode == 'hang':time.sleep(60)
        if mode == 'partial-line':
            destination.write(b'{');destination.flush();time.sleep(60)
        if mode == 'eof':return
        if mode == 'exit':raise SystemExit(7)
        if mode == 'exception' or mode == 'later' and calls == 3 or mode == 'later-segment' and after_inspection == 3:
            emit(dict(protocol='skillforge-scout-worker/1',error='CONTROLLER_EXCEPTION',command=None,local_stop_required=True));return
        if mode == 'oversized':destination.write(b'x'*70000+b'\n');destination.flush();return
        if mode == 'duplicate':destination.write(b'{"protocol":"skillforge-scout-worker/1","protocol":"bad"}\n');destination.flush();return
        reason = ('LOCALIZATION_UNAVAILABLE' if obs['pose'] is None else
                  'SENSOR_UNAVAILABLE' if obs['sensor_status']=='unavailable' else
                  'PATH_BLOCKED' if obs['front_body_clearance_m'] <= .22 else
                  'MISSION_TIMEOUT' if obs['step']==3600 else None)
        if reason:
            emit(dict(protocol='skillforge-scout-worker/1',reason=reason,command=None,raw_action=None,
                      limitation='safety-stop',local_stop_required=True));return
        if not obs['motion_enabled']:
            command = {k:obs[k] for k in ('schema_version','trial_id','epoch','segment_id','target_id','step')}
            command.update(type='command',expires_after_step=obs['step']+1,mode='stop',velocity=dict(v_mps=0,omega_rad_s=0))
            emit(dict(protocol='skillforge-scout-worker/1',command=command,raw_action=None,reason=None,
                      limitation='inspection-stop',local_stop_required=True))
            after_inspection = 0
            continue
        raw = {'v_mps':0 if mode=='zero' else .1,'omega_rad_s':0}
        command = {k:obs[k] for k in ('schema_version','trial_id','epoch','segment_id','target_id','step')}
        command.update(type='command',expires_after_step=obs['step']+1,mode='drive' if raw['v_mps'] else 'stop',velocity=dict(raw))
        if mode=='epoch':command['epoch']='old'
        if mode=='version':command['schema_version']='future'
        if mode=='ttl':command['expires_after_step']+=1
        if mode=='nan':raw['v_mps']=float('nan')
        if mode=='bool':command['velocity']['v_mps']=True
        if mode=='overspeed':command['velocity']['v_mps']=1
        emit(dict(protocol='skillforge-scout-worker/1',command=command,raw_action=raw,reason=None,
                  limitation='none',local_stop_required=False))


if __name__=='__main__':serve(sys.argv[1])
