"""Supervised local controller port exchanging bounded JSON values.

The launched command is trusted local code in its own process. Its return values
are untrusted. No SkillForge internals, controller algorithm or physics is copied.
This port is digital-only; process termination is not a hardware watchdog.
"""
from copy import deepcopy
import json
import math
import subprocess
from pathlib import Path
import hashlib
import queue
import threading

VERSION = 'scout-skillforge/0.1-draft.3'
SCHEMA_SHA256 = '88640878bb3dc2358cd197a6277a497d98e266ec8d7bd4054b1e6429778f1788'
MAX_BYTES = 65536


class ControllerFailure(RuntimeError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def need(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    try:
        return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:
        return False


def _bounded_depth(value,depth=0):
    need(depth <= 32,'JSON nesting exceeds 32')
    if isinstance(value,dict):
        for item in value.values():_bounded_depth(item,depth+1)
    elif isinstance(value,list):
        for item in value:_bounded_depth(item,depth+1)


def _pairs(items):
    result = {}
    for key,value in items:
        need(key not in result,'duplicate JSON key')
        result[key] = value
    return result


def encode(value):
    _bounded_depth(value)
    raw = json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    need(len(raw) <= MAX_BYTES,'JSON message too large')
    return raw


def decode(raw):
    need(len(raw) <= MAX_BYTES,'JSON message too large')
    def constant(value):
        raise ValueError('nonfinite JSON constant: '+value)
    try:
        value = json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=constant)
        encode(value)  # Also reject overflowed exponents such as 1e999.
        return value
    except (RecursionError,UnicodeError) as error:
        raise ValueError('invalid or deeply nested JSON') from error


class ProcessController:
    """One synchronous request at a time, one worker per live epoch.

    Callback requests use a fixed 1s default deadline. Startup has its own bounded
    deadline to allow Windows spawn/import. Timeout invalidates the whole worker;
    it cannot restart automatically or deliver a late command to another step.
    """
    def __init__(self, command, *, cwd=None, timeout_s=1.0, startup_timeout_s=10.0):
        need(isinstance(command,(tuple,list)) and command and all(isinstance(x,str) and x for x in command),'command must be an argv list')
        need(finite(timeout_s) and timeout_s > 0,'invalid callback deadline')
        need(finite(startup_timeout_s) and startup_timeout_s > 0,'invalid startup deadline')
        self.command,self.cwd = tuple(command),cwd
        self.timeout_s,self.startup_timeout_s = timeout_s,startup_timeout_s
        self.process = None
        self.last_response_raw = None
        self.closed = False
        self.session = None
        self.previous_step = -1
        self.failure = None

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None

    def _call(self, request, deadline):
        if self.closed:
            raise ControllerFailure(self.failure or 'CONTROLLER_EXCEPTION','Worker is closed; restart requires a new epoch')
        raw = encode(request)
        self.last_response_raw = None
        completed = queue.Queue(maxsize=1)
        def io():
            try:
                payload,offset = raw+b'\n',0
                while offset < len(payload):
                    size = self.process.stdin.write(payload[offset:])
                    if not size:raise BrokenPipeError('Controller stdin ended')
                    offset += size
                self.process.stdin.flush()
                line = self.process.stdout.readline(MAX_BYTES+2)
                self.last_response_raw = line.decode('utf-8',errors='replace')[:MAX_BYTES]
                if not line:
                    raise EOFError('Controller stdout ended')
                need(len(line) <= MAX_BYTES+1 and line.endswith(b'\n'),'oversized or unterminated response')
                completed.put((True,line[:-1]))
            except Exception as error:
                completed.put((False,error))
        task = threading.Thread(target=io,daemon=True)
        task.start()
        try:
            ok,value = completed.get(timeout=deadline)
        except queue.Empty:
            self.failure = 'CONTROLLER_TIMEOUT'
            self.close()
            task.join(timeout=1)
            raise ControllerFailure('CONTROLLER_TIMEOUT','Controller deadline exceeded') from None
        if not ok:
            self.failure = 'INVALID_COMMAND' if isinstance(value,ValueError) else 'CONTROLLER_EXCEPTION'
            self.close()
            raise ControllerFailure(self.failure,'Controller process or transport failed') from value
        try:
            reply = decode(value)
            need(isinstance(reply,dict),'reply envelope must be an object')
            need(reply.get('protocol') == 'skillforge-scout-worker/1','unsupported worker protocol')
            if 'error' in reply:
                need(reply.get('command') is None and reply.get('local_stop_required') is True,'unsafe error envelope')
                code = {'INVALID_INPUT':'INVALID_OBSERVATION','CONTROLLER_EXCEPTION':'CONTROLLER_EXCEPTION',
                        'INVALID_COMMAND':'INVALID_COMMAND'}.get(reply['error'])
                need(code is not None,'unknown worker error')
                raise ControllerFailure(code,str(reply.get('message',reply['error']))[:512])
            return reply
        except ControllerFailure as error:
            self.failure = error.code
            self.close()
            raise
        except (ValueError,TypeError) as error:
            self.failure = 'INVALID_COMMAND'
            self.close()
            raise ControllerFailure('INVALID_COMMAND',str(error)) from error

    def start(self, session):
        need(self.process is None and not self.closed,'controller session already started or closed')
        schema = Path(__file__).resolve().parents[2]/'docs/integration/contract-v0.schema.json'
        need(hashlib.sha256(schema.read_bytes()).hexdigest() == SCHEMA_SHA256,'canonical schema pin mismatch')
        self.check_session(session)
        # Copy/freeze all identity, profile and target inputs before spawning.
        self.session = decode(encode(session))
        self.process = subprocess.Popen(self.command,cwd=self.cwd,stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,shell=False)
        ready = self._call(self.session,self.startup_timeout_s)
        if ready != {'protocol':'skillforge-scout-worker/1','ready':True,'wire_revision':VERSION}:
            self.close()
            raise ControllerFailure('CONTROLLER_EXCEPTION','Worker did not acknowledge the pinned wire')

    def act(self, observation):
        need(self.session is not None,'controller not started')
        try:
            self.check_observation(observation)
        except (ValueError,TypeError,KeyError) as error:
            self.failure = 'INVALID_OBSERVATION'
            self.close()
            raise ControllerFailure('INVALID_OBSERVATION',str(error)) from error
        reply = self._call(observation,self.timeout_s)
        try:
            self.check_reply(reply,observation)
        except (ValueError,TypeError,KeyError) as error:
            self.failure = 'INVALID_COMMAND'
            self.close()
            raise ControllerFailure('INVALID_COMMAND',str(error)) from error
        self.previous_step = observation['step']
        if reply['reason'] is not None:
            self.close()
        return deepcopy(reply)

    def check_observation(self, obs):
        need(isinstance(obs,dict),'observation must be an object')
        expected = {'schema_version','trial_id','epoch','type','segment_id','target_id','step','time_s',
                    'pose','velocity','motion_enabled','sensor_status','front_body_clearance_m','sampled_at_s'}
        need(set(obs) == expected,'observation fields')
        need(obs['schema_version'] == VERSION and obs['type'] == 'observation','observation version/type')
        need(all(obs[k] == self.session[k] for k in ('trial_id','epoch')),'observation attempt mismatch')
        step = obs['step']
        need(type(step) is int and step == self.previous_step+1 and step <= 3600,'old or out-of-budget observation')
        need(finite(obs['time_s']) and abs(obs['time_s']-step*.05) <= 1e-9,'observation clock')
        need(type(obs['motion_enabled']) is bool,'motion flag')
        target = next((p for p in self.session['plan'] if p['segment_id'] == obs['segment_id']),None)
        need(target is not None and target['target_id'] == obs['target_id'],'unplanned target')
        need(obs['sensor_status'] in ('valid','unavailable'),'sensor status')
        distance = obs['front_body_clearance_m']
        need((distance is None) == (obs['sensor_status'] == 'unavailable'),'sensor status/null mismatch')
        need(distance is None or (finite(distance) and 0 <= distance <= 1),'sensor range')
        need(finite(obs['sampled_at_s']) and 0 <= obs['sampled_at_s'] <= 180.000000001,'sensor timestamp')
        pose = obs['pose']
        if pose is not None:
            need(isinstance(pose,dict) and set(pose) == {'x_m','y_m','yaw_rad'} and all(finite(v) for v in pose.values()),'invalid pose')
            need(-math.pi <= pose['yaw_rad'] < math.pi,'pose angle')
            self.check_point(pose,self.session['world'])
        velocity = obs['velocity']
        self.check_velocity(velocity)
        # Full geometry/sequence/report verification remains in the pinned checker.

    @staticmethod
    def check_point(point, world):
        r,x,y = world['radius_m'],point['x_m'],point['y_m']
        need(finite(x) and finite(y) and r < x < world['width_m']-r and r < y < world['height_m']-r,'invalid footprint point')
        for box in world['obstacles']:
            nx,ny = min(max(x,box['x_min']),box['x_max']),min(max(y,box['y_min']),box['y_max'])
            need(math.hypot(x-nx,y-ny) > r,'footprint intersects obstacle')

    @classmethod
    def check_session(cls, session):
        need(isinstance(session,dict) and set(session) == {'schema_version','trial_id','epoch','type',
             'profile_id','frame','profile','seed','controller','world','start_pose','plan','provenance'},'session fields')
        need(session['schema_version'] == VERSION and session['type'] == 'session','unsupported session')
        need(all(isinstance(session[k],str) and 0 < len(session[k]) <= 64 for k in ('trial_id','epoch')),'attempt identity')
        need(session['profile_id'] == 'digital_known_map' and session['frame'] == 'lab_x_right_y_up_yaw_ccw','unsupported frame/profile')
        expected = dict(dt_s=.05,max_steps=3600,max_v_mps=.15,max_omega_rad_s=.8,
                        stop_clearance_m=.22,sensor_range_m=1.,arrival_tolerance_m=.025,controller_timeout_s=1.)
        p = session['profile']
        need(isinstance(p,dict) and set(p) == set(expected) and all(finite(v) for v in p.values()) and p == expected,'profile mismatch')
        need(type(p['max_steps']) is int,'step budget must be integer')
        need(type(session['seed']) is int and 0 <= session['seed'] < 2**64,'seed')
        c = session['controller']
        need(isinstance(c,dict) and set(c) == {'id','version'} and c['id'] == 'goal_seeker' and type(c['version']) is int and c['version'] == 1,'controller identity')
        provenance = session['provenance']
        need(provenance == {'pose':'ideal_simulation','map':'ideal_static_map',
             'range':'synthetic_body_clearance','computer_vision_executed':False}
             and provenance['computer_vision_executed'] is False,'provenance')
        world = session['world']
        need(isinstance(world,dict) and set(world) == {'width_m','height_m','radius_m','obstacles'},'world fields')
        need(all(finite(world[k]) for k in ('width_m','height_m','radius_m')) and world['radius_m'] == .14
             and .3 <= world['width_m'] <= 10 and .3 <= world['height_m'] <= 10,'world dimensions')
        need(isinstance(world['obstacles'],list) and len(world['obstacles']) <= 32,'obstacle limit')
        for b in world['obstacles']:
            need(isinstance(b,dict) and set(b) == {'x_min','x_max','y_min','y_max'} and all(finite(v) for v in b.values()),'obstacle fields')
            need(0 <= b['x_min'] < b['x_max'] <= world['width_m'] and 0 <= b['y_min'] < b['y_max'] <= world['height_m'],'obstacle geometry')
        start = session['start_pose']
        need(isinstance(start,dict) and set(start) == {'x_m','y_m','yaw_rad'} and all(finite(v) for v in start.values()) and -math.pi <= start['yaw_rad'] < math.pi,'start pose')
        cls.check_point(start,world)
        plan = session['plan']
        need(isinstance(plan,list) and 1 <= len(plan) <= 4,'plan size')
        ids,targets = set(),set()
        for t in plan:
            need(isinstance(t,dict) and set(t) == {'segment_id','target_id','x_m','y_m'},'target fields')
            need(isinstance(t['segment_id'],str) and 0 < len(t['segment_id']) <= 64 and t['segment_id'] not in ids,'segment identity')
            need(t['target_id'] in ('A','B','C','HOME') and t['target_id'] not in targets,'target identity')
            ids.add(t['segment_id']);targets.add(t['target_id'])
            cls.check_point(t,world)

    @staticmethod
    def check_velocity(v):
        need(isinstance(v,dict) and set(v) == {'v_mps','omega_rad_s'},'velocity fields')
        need(all(finite(value) for value in v.values()),'velocity must be finite numbers')
        need(0 <= v['v_mps'] <= .15 and abs(v['omega_rad_s']) <= .8,'velocity outside profile')

    @staticmethod
    def expected_reason(obs):
        if obs['pose'] is None:return 'LOCALIZATION_UNAVAILABLE'
        if obs['sensor_status'] == 'unavailable':return 'SENSOR_UNAVAILABLE'
        if not -1e-9 <= obs['time_s']-obs['sampled_at_s'] <= .1+1e-9:return 'STALE_SENSOR'
        if obs['front_body_clearance_m'] <= .22:return 'PATH_BLOCKED'
        if obs['step'] == 3600:return 'MISSION_TIMEOUT'
        return None

    def check_reply(self, reply, obs):
        need(set(reply) == {'protocol','command','raw_action','limitation','local_stop_required','reason'},'reply fields')
        expected = self.expected_reason(obs)
        need(reply['reason'] == expected,'worker safety reason mismatch')
        if expected is not None:
            need(reply['command'] is None and reply['raw_action'] is None
                 and reply['local_stop_required'] is True and reply['limitation'] == 'safety-stop','unsafe terminal reply')
            return
        command,raw = reply['command'],reply['raw_action']
        need(isinstance(command,dict) and set(command) == {'schema_version','trial_id','epoch','type',
             'segment_id','target_id','step','expires_after_step','mode','velocity'},'command fields')
        need(command['schema_version'] == VERSION and command['type'] == 'command','command version/type')
        need(all(type(command[k]) is type(obs[k]) and command[k] == obs[k]
                 for k in ('trial_id','epoch','segment_id','target_id','step')),'command correlation')
        need(type(command['expires_after_step']) is int and command['expires_after_step'] == obs['step']+1,'command TTL')
        self.check_velocity(command['velocity'])
        v = command['velocity']
        need(command['mode'] == ('stop' if v['v_mps'] == 0 and v['omega_rad_s'] == 0 else 'drive'),'command mode')
        if not obs['motion_enabled']:
            need(raw is None and v == {'v_mps':0,'omega_rad_s':0} and reply['local_stop_required'] is True
                 and reply['limitation'] == 'inspection-stop','unsafe disabled-motion response')
            return
        need(isinstance(raw,dict) and set(raw) == {'v_mps','omega_rad_s'} and all(finite(v) for v in raw.values()),'raw action fields')
        need(v == {'v_mps':min(.15,max(0,raw['v_mps'])),'omega_rad_s':min(.8,max(-.8,raw['omega_rad_s']))},'raw/normalization mismatch')
        need(reply['local_stop_required'] is False,'unexpected stop flag')
        need(reply['limitation'] == ('none' if raw == v else 'controller-normalized'),'normalization label')

    def close(self):
        self.closed = True
        if self.process is not None:
            if self.alive:
                self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
            for stream in (self.process.stdin,self.process.stdout):
                if stream is not None:stream.close()

    def __enter__(self):return self
    def __exit__(self,*unused):self.close()
