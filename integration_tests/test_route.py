from dataclasses import replace
import math
import os
from pathlib import Path
import sys
import unittest

from scout.models import Pose,load_scenario
from scout.simulator import integrate
from scout.integration.runner import run_route
from scout.integration.baseline import run_baseline
from scout.integration.digital import DigitalProbeRobot
from test_bridge import ROOT,SOURCES,validate,command


class RouteTests(unittest.TestCase):
    def test_near_zero_turn_does_not_exceed_commanded_chord(self):
        pose = Pose(1.17070118630936,1.7973492255107808,3.136947898595304)
        for angular in (0,1e-12,-1e-12,4.1207173673285524e-8,-4.1207173673285524e-8,.8):
            with self.subTest(angular=angular):
                end = integrate(pose,.15,angular,.05)
                self.assertLessEqual(math.hypot(end.x-pose.x,end.y-pose.y),.0075+1e-14)
                half = angular*.05/2
                expected = .0075*(math.sin(half)/half if half else 1)
                self.assertAlmostEqual(end.x-pose.x,expected*math.cos(pose.heading+half),places=14)
                self.assertAlmostEqual(end.y-pose.y,expected*math.sin(pose.heading+half),places=14)

    def test_partial_after_completed_segment_preserves_results_and_budget(self):
        b = run_route(load_scenario(ROOT/'scout/scenarios/normal.json'),command('later-segment'),ROOT,
                      SOURCES,execution='contract_example')
        validate(b)
        r = b['report']
        self.assertFalse(r['report_complete'])
        self.assertEqual(r['outcome']['reason'],'CONTROLLER_EXCEPTION')
        self.assertEqual([x['target_id'] for x in r['results']],['A'])
        self.assertEqual(r['missing_results'],['B-1'])
        self.assertEqual(r['not_started_segments'],['C-1','HOME-1'])
        self.assertEqual(r['last_confirmed_step'],r['results'][0]['end_step']+3)
        self.assertEqual(b['transport'][-1]['observation']['segment_id'],'B-1')
        self.assertFalse(b['runtime']['worker_alive_after_cleanup'])

    def test_full_route_timeout_has_one_global_budget(self):
        b = run_route(load_scenario(ROOT/'scout/scenarios/normal.json'),command('zero'),ROOT,
                      SOURCES,execution='contract_example')
        validate(b)
        self.assertEqual(b['report']['last_confirmed_step'],3600)
        self.assertEqual(b['report']['outcome']['reason'],'MISSION_TIMEOUT')
        self.assertEqual(b['report']['not_started_segments'],['B-1','C-1','HOME-1'])

    def test_baseline_is_existing_mission_and_full_command_audit(self):
        b = run_baseline(load_scenario(ROOT/'scout/scenarios/deviations.json'),SOURCES)
        self.assertIsNone(b['error'])
        self.assertEqual(b['report']['visited_stations'],['A','B','C'])
        self.assertTrue(b['report']['returned_home'])
        self.assertEqual(sum(a['kind']=='advance' for a in b['audit']),b['report']['metrics']['control_steps'])
        self.assertEqual(sum(i['result']=='CHANGED' for i in b['report']['inspections']),2)
        self.assertTrue(all(i['synthetic'] for i in b['report']['inspections']))

    @unittest.skipUnless(os.environ.get('SKILLFORGE_ROOT'),'separate pinned SkillForge checkout required')
    def test_real_worker_full_route_and_late_sensor_fault(self):
        scenario = load_scenario(ROOT/'scout/scenarios/deviations.json')
        for s in (scenario,replace(scenario,sensor_failure_at_s=14.)):
            with self.subTest(failure=s.sensor_failure_at_s):
                b = run_route(s,[sys.executable,'-m','skillforge.scout_worker'],os.environ['SKILLFORGE_ROOT'],
                              SOURCES,execution='contract_example')
                validate(b)
                r = b['report']
                self.assertEqual(r['last_confirmed_step'],b['runtime']['confirmed_advances'])
                self.assertTrue(r['stop']['confirmed'])
                self.assertFalse(b['runtime']['worker_alive_after_cleanup'])
                if s.sensor_failure_at_s is None:
                    self.assertEqual([i['station_id'] for i in b['inspections']],['A','B','C'])
                    self.assertEqual([i['result'] for i in b['inspections']],['UNCHANGED','CHANGED','CHANGED'])
                    self.assertTrue(all(i['synthetic'] for i in b['inspections']))
                    self.assertEqual([x['target_id'] for x in r['results']],['A','B','C','HOME'])
                    for a,c in zip(r['results'],r['results'][1:]):
                        self.assertEqual(c['start_step'],a['end_step']+1)
                    self.assertTrue(b['runtime']['full_route_completed'])
                else:
                    self.assertEqual(r['outcome']['reason'],'SENSOR_UNAVAILABLE')
                    self.assertEqual([x['target_id'] for x in r['results']],['A','B'])
                    self.assertEqual(r['not_started_segments'],['C-1','HOME-1'])

    @unittest.skipUnless(os.environ.get('SKILLFORGE_ROOT'),'separate pinned SkillForge checkout required')
    def test_unconfirmed_inspection_stop_never_inspects_or_changes_target(self):
        class NoStop(DigitalProbeRobot):
            def stop(self):
                if self.time < .05:super().stop()
        class MustNotInspect:
            def inspect(self,station):raise AssertionError('inspection requires confirmed stop')
        b = run_route(load_scenario(ROOT/'scout/scenarios/normal.json'),
                      [sys.executable,'-m','skillforge.scout_worker'],os.environ['SKILLFORGE_ROOT'],SOURCES,
                      execution='contract_example',robot_type=NoStop,inspector=MustNotInspect())
        validate(b)
        self.assertEqual(b['report']['outcome']['reason'],'STOP_NOT_CONFIRMED')
        self.assertFalse(b['report']['stop']['confirmed'])
        self.assertEqual(b['inspections'],[])
        self.assertEqual(b['report']['not_started_segments'],['B-1','C-1','HOME-1'])
        self.assertTrue(all(t['observation']['target_id']=='A' for t in b['transport']))

    @unittest.skipUnless(os.environ.get('SKILLFORGE_ROOT'),'separate pinned SkillForge checkout required')
    def test_inspection_exception_retains_prefix_and_stops(self):
        class BrokenInspector:
            def inspect(self,station):raise RuntimeError('injected inspection failure')
        b = run_route(load_scenario(ROOT/'scout/scenarios/normal.json'),
                      [sys.executable,'-m','skillforge.scout_worker'],os.environ['SKILLFORGE_ROOT'],SOURCES,
                      execution='contract_example',inspector=BrokenInspector())
        validate(b)
        self.assertEqual(b['report']['outcome']['reason'],'RUNNER_EXCEPTION')
        self.assertEqual(b['report']['missing_results'],['A-1'])
        self.assertTrue(b['report']['stop']['confirmed'])
        self.assertFalse(b['runtime']['worker_alive_after_cleanup'])


if __name__=='__main__':unittest.main()
