from dataclasses import replace
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scout.__main__ import main
from scout.mission import run_mission, safety_reason
from scout.models import Obstacle, Pose, RobotSpec, load_scenario
from scout.ports import Inspection, Telemetry
from scout.report import write_html, write_json
from scout.simulator import CollisionGuardError, SimRobot, integrate, ray_box

SCENARIOS = Path(__file__).resolve().parents[1] / "scout" / "scenarios"


def scenario(name="normal"):
    return load_scenario(SCENARIOS / f"{name}.json")


class MissionTests(unittest.TestCase):
    def test_normal_completes_route_and_returns_home(self):
        s = scenario()
        robot = SimRobot(s, 1)
        result = run_mission(s, robot=robot)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["visited_stations"], ["A", "B", "C"])
        self.assertTrue(result["returned_home"])
        self.assertTrue(result["stopped"])
        self.assertLess(math.hypot(robot.pose.x - s.start.x, robot.pose.y - s.start.y),
                        s.arrival_tolerance_m)
        self.assertTrue(all(s.is_free(p["x"], p["y"]) for p in result["trace"]))
        self.assertEqual(robot.linear, 0)
        self.assertEqual(robot.angular, 0)
        self.assertEqual(result["metrics"]["changed_station_count"], 0)
        self.assertEqual(result["metrics"]["collision_guard_activations"], 0)

    def test_prepared_deviations_are_explicitly_synthetic(self):
        r = run_mission(scenario("deviations"))
        self.assertEqual(r["status"], "COMPLETED")
        self.assertEqual(r["metrics"]["changed_station_count"], 2)
        self.assertFalse(r["evidence"]["computer_vision_executed"])
        self.assertTrue(r["evidence"]["synthetic"])
        self.assertTrue(all(i["synthetic"] and i["evidence_source"] == "scenario_fixture"
                            for i in r["inspections"]))
        self.assertEqual(r["inspections"][1]["deviations"], ("prepared_extra_box",))

    def test_blocked_path_stops_before_contact(self):
        s = scenario("blocked")
        robot = SimRobot(s, 5)
        r = run_mission(s, 5, robot=robot)
        self.assertEqual((r["status"], r["reason"]), ("BLOCKED", "PATH_BLOCKED"))
        self.assertFalse(r["returned_home"])
        self.assertEqual(r["visited_stations"], [])
        self.assertLess(robot.pose.x + s.robot.radius_m, 1.5)
        self.assertTrue(s.is_free(robot.pose.x, robot.pose.y))
        self.assertEqual(robot.linear, 0)
        self.assertEqual(robot.collision_guard_activations, 0)
        self.assertLess(r["metrics"]["duration_s"], s.max_duration_s)

    def test_partial_route_keeps_only_completed_inspections(self):
        s = scenario()
        s = replace(s, obstacles=s.obstacles + (Obstacle("late-block", 2.15, 1.1, .5, .2),))
        r = run_mission(s)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(r["visited_stations"], ["A"])
        self.assertEqual([i["station_id"] for i in r["inspections"]], ["A"])

    def test_sensor_failure_stops_and_reports_fault(self):
        s = scenario("sensor-failure")
        robot = SimRobot(s, 1)
        r = run_mission(s, robot=robot)
        self.assertEqual(r["reason"], "SENSOR_UNAVAILABLE")
        self.assertEqual(r["status"], "FAULT")
        self.assertTrue(r["stopped"])
        self.assertAlmostEqual(r["metrics"]["duration_s"], 2)
        self.assertEqual(robot.linear, 0)

    def test_timeout_is_not_success(self):
        s = replace(scenario(), max_duration_s=.1)
        robot = SimRobot(s, 1)
        r = run_mission(s, robot=robot)
        self.assertEqual(r["reason"], "MISSION_TIMEOUT")
        self.assertFalse(r["returned_home"])
        self.assertEqual(robot.linear, 0)

    def test_footprint_guard_fault_is_reported_when_sensor_misses_obstacle(self):
        class BlindRobot(SimRobot):
            def read(self):
                return replace(super().read(), front_clearance_m=1.0)
        s = scenario("blocked")
        robot = BlindRobot(s, 1)
        r = run_mission(s, robot=robot)
        self.assertEqual((r["status"], r["reason"]), ("FAULT", "FOOTPRINT_GUARD"))
        self.assertEqual(r["metrics"]["collision_guard_activations"], 1)
        self.assertTrue(r["stopped"])
        self.assertTrue(s.is_free(robot.pose.x, robot.pose.y))

    def test_unconfirmed_stop_cannot_report_success(self):
        class StuckRobot(SimRobot):
            def read(self):
                return replace(super().read(), linear_speed_mps=.1)
        s = replace(scenario(), max_duration_s=.1)
        r = run_mission(s, robot=StuckRobot(s, 1))
        self.assertEqual(r["reason"], "STOP_NOT_CONFIRMED")
        self.assertFalse(r["stopped"])

    def test_twenty_seeds_finish_without_guard_activation(self):
        for seed in range(20):
            with self.subTest(seed=seed):
                r = run_mission(scenario(), seed)
                self.assertEqual(r["status"], "COMPLETED")
                self.assertEqual(r["metrics"]["collision_guard_activations"], 0)

    def test_same_scenario_seed_has_byte_identical_json(self):
        for name in ("normal", "deviations", "blocked", "sensor-failure"):
            with self.subTest(scenario=name), tempfile.TemporaryDirectory() as directory:
                a, b = Path(directory) / "a.json", Path(directory) / "b.json"
                write_json(run_mission(scenario(name), 17), a)
                write_json(run_mission(scenario(name), 17), b)
                self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_inspection_exception_still_stops_motors(self):
        class BrokenInspector:
            def inspect(self, station):
                raise RuntimeError("camera adapter failed")
        s = scenario()
        robot = SimRobot(s, 1)
        with self.assertRaises(RuntimeError):
            run_mission(s, robot=robot, inspector=BrokenInspector())
        self.assertEqual((robot.linear, robot.angular), (0, 0))

    def test_real_evidence_cannot_be_mislabelled_by_simulation_runner(self):
        class RealInspector:
            def inspect(self, station):
                return Inspection(station.id, "UNCHANGED", (), "camera", False)
        with self.assertRaisesRegex(ValueError, "synthetic"):
            run_mission(scenario(), inspector=RealInspector())

    def test_seed_must_be_integer(self):
        with self.assertRaises(ValueError):
            run_mission(scenario(), True)


class GeometryAndSafetyTests(unittest.TestCase):
    def test_exact_straight_and_circular_kinematics(self):
        p = integrate(Pose(0, 0), .15, 0, 2)
        self.assertAlmostEqual(p.x, .3)
        self.assertAlmostEqual(p.y, 0)
        p = integrate(Pose(0, 0), .1, .5, math.pi)
        self.assertAlmostEqual(p.x, .2)
        self.assertAlmostEqual(p.y, .2)
        self.assertAlmostEqual(p.heading, math.pi / 2)

    def test_two_wheel_mapping_and_stop(self):
        r = SimRobot(scenario(), 1)
        r.command(.1, .2)
        left, right = r.left_wheel_rps, r.right_wheel_rps
        self.assertAlmostEqual((left + right) * r.spec.wheel_radius_m / 2, .1)
        self.assertAlmostEqual((right - left) * r.spec.wheel_radius_m / r.spec.axle_track_m, .2)
        r.stop()
        self.assertEqual((r.left_wheel_rps, r.right_wheel_rps), (0, 0))

    def test_sensor_accounts_for_robot_body_width(self):
        s = replace(scenario(), obstacles=(Obstacle("off-centre", 1.0, .70, .2, .2),),
                    sensor_noise_m=0)
        r = SimRobot(s, 1)
        self.assertAlmostEqual(r.read().front_clearance_m, 1.0 - .14 - .6)

    def test_sensor_detects_arena_boundary(self):
        s = replace(scenario(), sensor_noise_m=0)
        r = SimRobot(s, 1)
        r.pose = Pose(2.7, .6, 0)
        self.assertAlmostEqual(r.read().front_clearance_m, .16)

    def test_swept_guard_does_not_tunnel_through_thin_obstacle(self):
        s = replace(scenario(), obstacles=(Obstacle("thin", 1.2, .3, .00001, .6),))
        r = SimRobot(s, 1)
        r.command(.15, 0)
        initial = r.pose
        with self.assertRaises(CollisionGuardError):
            r.advance(20)
        self.assertEqual(r.pose, initial)
        self.assertEqual((r.linear, r.angular), (0, 0))

    def test_command_clamps_reverse_and_overspeed(self):
        r = SimRobot(scenario(), 1)
        r.command(100, -100)
        self.assertEqual(r.linear, r.spec.max_speed_mps)
        self.assertEqual(r.angular, -r.spec.max_turn_rps)
        r.command(-1, 0)
        self.assertEqual(r.linear, 0)

    def test_nonfinite_command_and_time_stop_robot(self):
        for command in (float("nan"), float("inf")):
            r = SimRobot(scenario(), 1)
            with self.assertRaises(ValueError):
                r.command(command, 0)
            self.assertEqual(r.linear, 0)
        r = SimRobot(scenario(), 1)
        r.command(.1, 0)
        with self.assertRaises(ValueError):
            r.advance(0)
        self.assertEqual(r.linear, 0)

    def test_stale_future_missing_and_invalid_sensors_fail_closed(self):
        p = Pose(.6, .6)
        self.assertEqual(safety_reason(Telemetry(p, 1, 0, 0, 0), 1, .22, .1), "STALE_SENSOR")
        self.assertEqual(safety_reason(Telemetry(p, 1, 2, 0, 0), 1, .22, .1), "STALE_SENSOR")
        for value in (None, float("nan"), float("inf"), -1):
            self.assertEqual(safety_reason(Telemetry(p, value, 1, 0, 0), 1, .22, .1),
                             "SENSOR_UNAVAILABLE")
        self.assertEqual(safety_reason(Telemetry(p, .22, 1, 0, 0), 1, .22, .1), "PATH_BLOCKED")
        invalid = Pose(float("nan"), .6)
        self.assertEqual(safety_reason(Telemetry(invalid, 1, 1, 0, 0), 1, .22, .1),
                         "LOCALIZATION_UNAVAILABLE")

    def test_ray_misses_parallel_box(self):
        self.assertEqual(ray_box(0, 0, 1, 0, 1, 1, 2, 2), math.inf)


class ScenarioValidationTests(unittest.TestCase):
    def test_reject_invalid_geometry_and_unbounded_work(self):
        s = scenario()
        for change in ({"width": float("nan")}, {"dt_s": 0}, {"dt_s": 1},
                       {"sensor_noise_m": -1}, {"sensor_noise_m": float("nan")},
                       {"sensor_range_m": .1}, {"max_duration_s": 1000000},
                       {"start": Pose(.01, .01)}, {"sensor_failure_at_s": -1},
                       {"robot": RobotSpec(radius_m=-1)}, {"width": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(s, **change)

    def test_reject_duplicate_stations_and_colliding_start(self):
        s = scenario()
        with self.assertRaises(ValueError):
            replace(s, stations=(s.stations[0],) * 3)
        with self.assertRaises(ValueError):
            replace(s, start=Pose(1.2, 1.2))

    def test_reject_malformed_json_structure_and_unknown_keys(self):
        base = json.loads((SCENARIOS / "normal.json").read_text())
        for content in ([], {}, {**base, "surprise": 1}, {**base, "start": []},
                        {**base, "stations": None}):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "scenario.json"
                path.write_text(json.dumps(content))
                with self.assertRaises(ValueError):
                    load_scenario(path)

    def test_digest_tracks_scenario_changes(self):
        self.assertEqual(scenario().digest, scenario().digest)
        self.assertNotEqual(scenario().digest, replace(scenario(), name="different").digest)


class ReportsAndCliTests(unittest.TestCase):
    def test_json_roundtrip_and_html_script_escape(self):
        s = replace(scenario(), name='</script><script>alert("unsafe")</script>')
        r = run_mission(s)
        with tempfile.TemporaryDirectory() as directory:
            json_path, html_path = Path(directory) / "a.json", Path(directory) / "a.html"
            write_json(r, json_path)
            write_html(r, html_path)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["scenario"], s.name)
            html = html_path.read_text(encoding="utf-8")
            self.assertNotIn(s.name, html)
            self.assertIn("\\u003c/script>", html)
            self.assertNotIn("https://", html)
            self.assertEqual(set(p.name for p in Path(directory).iterdir()), {"a.json", "a.html"})

    def test_cli_exit_codes_and_reports(self):
        root = SCENARIOS.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            for name, expected in (("normal", 0), ("deviations", 0), ("blocked", 2),
                                   ("sensor-failure", 2)):
                output = Path(directory) / f"{name}.json"
                process = subprocess.run([sys.executable, "-m", "scout", "--scenario", name,
                                          "--output", str(output)], cwd=root,
                                         capture_output=True, text=True, timeout=20)
                self.assertEqual(process.returncode, expected, process.stderr)
                self.assertTrue(output.is_file())

    def test_cli_refuses_clobbering_scenario_or_outputs(self):
        with self.assertRaises(SystemExit):
            main(["--scenario", str(SCENARIOS / "normal.json"),
                  "--output", str(SCENARIOS / "normal.json")])
        with self.assertRaises(SystemExit):
            main(["--output", "same.json", "--html", "same.json"])

    def test_cli_missing_scenario_does_not_write_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "missing.json"
            self.assertEqual(main(["--scenario", "does-not-exist", "--output", str(output)]), 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
