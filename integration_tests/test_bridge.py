from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time
import unittest

from scout.models import load_scenario,Pose
from scout.integration.bridge import ProcessController,ControllerFailure,decode
from scout.integration.digital import DigitalProbeRobot,session_for,observation_for,local_stop
from scout.integration.runner import run_goal
from scout.simulator import CollisionGuardError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_integration_contract import validate_report,parse,ROOT as CONTRACT_ROOT
SCHEMA = parse((CONTRACT_ROOT/'contract-v0.schema.json').read_text(encoding='utf-8'))
SOURCES = {k:dict(commit=None,source_sha256=None) for k in ('scout','skillforge')}


def command(mode):return [sys.executable,'-m','integration_tests.worker_fixtures',mode]


def validate(bundle):
    r = bundle['report']
    validate_report(r,SCHEMA,active_trial_id=r['trial_id'],active_epoch=r['epoch'])


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(ROOT/'scout/scenarios/normal.json')

    def run_fake(self,mode,**kwargs):
        result = run_goal(self.scenario,command(mode),ROOT,SOURCES,execution='contract_example',**kwargs)
        validate(result)
        self.assertFalse(result['runtime']['worker_alive_after_cleanup'])
        self.assertTrue(result['report']['stop']['confirmed'])
        return result

    def test_invalid_responses_never_advance_and_stop(self):
        for mode in ('epoch','version','ttl','nan','bool','overspeed','oversized','duplicate'):
            with self.subTest(mode=mode):
                b = self.run_fake(mode)
                self.assertEqual(b['report']['outcome']['reason'],'INVALID_COMMAND')
                self.assertEqual(b['runtime']['confirmed_advances'],0)
                self.assertFalse(b['report']['report_complete'])

    def test_eof_and_nonzero_exit_are_not_success(self):
        for mode in ('eof','exit','exception'):
            with self.subTest(mode=mode):
                b = self.run_fake(mode)
                self.assertEqual(b['report']['outcome']['reason'],'CONTROLLER_EXCEPTION')
                self.assertEqual(b['runtime']['confirmed_advances'],0)

    def test_timeout_and_unterminated_frame_kill_worker(self):
        for mode in ('hang','partial-line'):
            with self.subTest(mode=mode):
                c = ProcessController(command(mode),cwd=ROOT,timeout_s=.1)
                session = session_for(self.scenario,1,'timeout-epoch')
                c.start(session)
                obs = observation_for(DigitalProbeRobot(self.scenario,1).read(),0,session)
                begin = time.monotonic()
                with self.assertRaises(ControllerFailure) as error:c.act(obs)
                self.assertEqual(error.exception.code,'CONTROLLER_TIMEOUT')
                self.assertLess(time.monotonic()-begin,3)
                self.assertFalse(c.alive)
                with self.assertRaises(ControllerFailure):c.act(obs)
                c.close()

    def test_partial_prefix_retains_pending_protocol_input(self):
        b = self.run_fake('later')
        r = b['report']
        self.assertEqual(r['last_confirmed_step'],2)
        self.assertEqual(len(r['trace']),2)
        self.assertEqual(r['missing_results'],['A-1'])
        self.assertEqual(len(b['transport']),3)
        self.assertEqual(b['transport'][-1]['observation']['step'],2)
        self.assertIn('CONTROLLER_EXCEPTION',b['transport'][-1]['rejected_response'])

    def test_runtime_budget_has_terminal_observation_and_no_extra_advance(self):
        b = self.run_fake('zero')
        self.assertEqual(b['report']['outcome']['reason'],'MISSION_TIMEOUT')
        self.assertEqual(b['runtime']['confirmed_advances'],3600)
        self.assertEqual(b['report']['trace'][-1]['observation']['step'],3600)
        self.assertIsNone(b['report']['trace'][-1]['requested'])

    def test_repeated_read_and_stop_do_not_resample_range(self):
        robot = DigitalProbeRobot(self.scenario,1)
        first = robot.read();state = robot.rng.getstate()
        self.assertEqual(robot.read(),first)
        self.assertTrue(local_stop(robot)['confirmed'])
        self.assertEqual(robot.rng.getstate(),state)
        self.assertEqual(robot.sensor_samples,1)

    def test_invalid_profile_rejected_before_spawn(self):
        s = session_for(self.scenario,1,'bad-profile')
        s['profile']['max_v_mps'] = 1
        c = ProcessController(command('zero'),cwd=ROOT)
        with self.assertRaises(ValueError):c.start(s)
        self.assertIsNone(c.process)

    def test_session_is_copied_and_wrong_active_epoch_poisoned(self):
        s = session_for(self.scenario,1,'active')
        c = ProcessController(command('zero'),cwd=ROOT)
        c.start(s)
        s['plan'][0]['x_m'] = 1
        self.assertEqual(c.session['plan'][0]['x_m'],2.4)
        obs = observation_for(DigitalProbeRobot(self.scenario,1).read(),0,c.session)
        obs['epoch'] = 'old'
        with self.assertRaises(ControllerFailure) as error:c.act(obs)
        self.assertEqual(error.exception.code,'INVALID_OBSERVATION')
        self.assertFalse(c.alive)

    def test_strict_wire_json(self):
        for raw in (b'{"x":NaN}',b'{"x":1e999}',b'{"x":1,"x":2}',b'\xff'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):decode(raw)
        with self.assertRaises(ValueError):decode(b'['*40+b'0'+b']'*40)

    @unittest.skipUnless(os.environ.get('SKILLFORGE_ROOT'),'separate pinned SkillForge checkout required')
    def test_public_worker_inspection_uses_canonical_stop_label(self):
        session = session_for(self.scenario,1,'inspection-epoch')
        c = ProcessController([sys.executable,'-m','skillforge.scout_worker'],
                              cwd=os.environ['SKILLFORGE_ROOT'])
        try:
            c.start(session)
            obs = observation_for(DigitalProbeRobot(self.scenario,1).read(),0,session)
            obs['motion_enabled'] = False
            reply = c.act(obs)
            self.assertEqual(reply['limitation'],'inspection-stop')
            self.assertIsNone(reply['raw_action'])
            self.assertEqual(reply['command']['mode'],'stop')
            self.assertEqual(reply['command']['velocity'],dict(v_mps=0,omega_rad_s=0))
            self.assertTrue(reply['local_stop_required'])
        finally:
            c.close()
        self.assertFalse(c.alive)

    @unittest.skipUnless(os.environ.get('SKILLFORGE_ROOT'),'separate pinned SkillForge checkout required')
    def test_unknown_stop_and_invalid_telemetry_are_honest(self):
        class NoStop(DigitalProbeRobot):
            def stop(self):
                if self.time < .05:super().stop()
        class BadTelemetry(DigitalProbeRobot):
            def read(self):
                t = super().read()
                return replace(t,pose=Pose(float('nan'),.6,0)) if self.time >= .05 else t
        for kind,reason in [(NoStop,'STOP_NOT_CONFIRMED'),(BadTelemetry,'INVALID_OBSERVATION')]:
            with self.subTest(kind=kind):
                b = run_goal(self.scenario,[sys.executable,'-m','skillforge.scout_worker'],os.environ['SKILLFORGE_ROOT'],
                             SOURCES,execution='contract_example',robot_type=kind)
                validate(b)
                self.assertEqual(b['report']['outcome']['reason'],reason)
                json.dumps(b,allow_nan=False)

    @unittest.skipUnless(os.environ.get('SKILLFORGE_ROOT'),'separate pinned SkillForge checkout required')
    def test_guard_rejects_one_attempt_without_advancing(self):
        class RejectAdvance(DigitalProbeRobot):
            def advance(self,dt):
                self.collision_guard_activations += 1
                self.stop()
                raise CollisionGuardError('injected atomic guard rejection')
        b = run_goal(self.scenario,[sys.executable,'-m','skillforge.scout_worker'],os.environ['SKILLFORGE_ROOT'],
                     SOURCES,execution='contract_example',robot_type=RejectAdvance)
        validate(b)
        self.assertEqual(b['report']['outcome']['reason'],'FOOTPRINT_GUARD')
        self.assertEqual(b['runtime']['confirmed_advances'],0)
        self.assertIsNone(b['report']['trace'][0]['applied'])

    @unittest.skipUnless(os.environ.get('SKILLFORGE_ROOT'),'separate pinned SkillForge checkout required')
    def test_actual_public_worker_four_physics_cases(self):
        normal = self.scenario
        turn = replace(normal,name='turn',stations=(replace(normal.stations[0],x=.6,y=1.8),*normal.stations[1:]))
        for s,expected in [(normal,'GOAL_REACHED'),(turn,'GOAL_REACHED'),
                           (load_scenario(ROOT/'scout/scenarios/blocked.json'),'PATH_BLOCKED'),
                           (load_scenario(ROOT/'scout/scenarios/sensor-failure.json'),'SENSOR_UNAVAILABLE')]:
            with self.subTest(scenario=s.name):
                b = run_goal(s,[sys.executable,'-m','skillforge.scout_worker'],os.environ['SKILLFORGE_ROOT'],
                             SOURCES,execution='contract_example')
                validate(b)
                self.assertEqual(b['report']['outcome']['reason'],expected)
                self.assertEqual(b['runtime']['confirmed_advances'],b['report']['last_confirmed_step'])
                self.assertFalse(b['runtime']['worker_alive_after_cleanup'])
                if s.name=='turn':
                    self.assertTrue(any(r['limitation']=='controller-normalized' for r in b['report']['trace']))


if __name__=='__main__':unittest.main()
