"""Fixed-route mission: controller decisions use only pose/range observations."""
from dataclasses import asdict
import math
from . import __version__
from .models import Scenario
from .ports import InspectionPort, RobotPort, Telemetry
from .simulator import CollisionGuardError, SimRobot, SyntheticInspector, wrap_angle


def safety_reason(telemetry: Telemetry, now: float, threshold: float, max_age: float):
    sample = telemetry.front_clearance_m
    if (not math.isfinite(telemetry.sampled_at_s)
            or telemetry.sampled_at_s > now + 1e-9
            or now - telemetry.sampled_at_s > max_age):
        return "STALE_SENSOR"
    if sample is None or not math.isfinite(sample) or sample < 0:
        return "SENSOR_UNAVAILABLE"
    if not all(math.isfinite(value) for value in asdict(telemetry.pose).values()):
        return "LOCALIZATION_UNAVAILABLE"
    if sample <= threshold:
        return "PATH_BLOCKED"
    return None


def run_mission(scenario: Scenario, seed: int = 1, *,
                robot: RobotPort | None = None, inspector: InspectionPort | None = None):
    """Bounded simulation-time mission; always stop the platform on exit.

    Hardware requires a separate real-time scheduler and independent watchdog.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    robot = SimRobot(scenario, seed) if robot is None else robot
    inspector = SyntheticInspector() if inspector is None else inspector
    inspections, events, trace = [], [], []
    state = "PRECHECK"
    status, reason = "TIMEOUT", "MISSION_TIMEOUT"
    targets = [(station.id, station.x, station.y) for station in scenario.stations]
    targets.append(("HOME", scenario.start.x, scenario.start.y))
    target_index, distance, min_clearance = 0, 0.0, None
    elapsed, step = 0.0, 0
    previous_pose = scenario.start
    terminal_pose = scenario.start
    visited = []
    step_limit = math.ceil(scenario.max_duration_s / scenario.dt_s)

    def event(kind, **details):
        events.append({"time_s": round(elapsed, 6), "type": kind, **details})

    def snapshot(pose):
        trace.append({"time_s": round(elapsed, 6), "x": round(pose.x, 6),
                      "y": round(pose.y, 6), "heading": round(pose.heading, 6),
                      "state": state})

    event("MISSION_STARTED", scenario=scenario.name)
    try:
        robot.stop()
        for step in range(step_limit + 1):
            elapsed = step * scenario.dt_s
            telemetry = robot.read()
            pose = telemetry.pose
            terminal_pose = pose
            distance += math.hypot(pose.x - previous_pose.x, pose.y - previous_pose.y)
            previous_pose = pose
            if step % 4 == 0:
                snapshot(pose)
            if elapsed >= scenario.max_duration_s:
                break
            failure = safety_reason(telemetry, elapsed, scenario.stop_clearance_m,
                                    max_age=2 * scenario.dt_s)
            if telemetry.front_clearance_m is not None and math.isfinite(telemetry.front_clearance_m):
                min_clearance = (telemetry.front_clearance_m if min_clearance is None else
                                 min(min_clearance, telemetry.front_clearance_m))
            if failure:
                status = "BLOCKED" if failure == "PATH_BLOCKED" else "FAULT"
                reason = failure
                event("SAFETY_STOP", reason=reason, target=targets[target_index][0])
                break
            target_id, x, y = targets[target_index]
            remaining = math.hypot(x - pose.x, y - pose.y)
            if remaining <= scenario.arrival_tolerance_m:
                robot.stop()
                if target_id == "HOME":
                    status, reason, state = "COMPLETED", "ROUTE_FINISHED", "COMPLETED"
                    event("RETURNED_HOME")
                    break
                state = "INSPECT"
                event("STATION_VISITED", station_id=target_id)
                visited.append(target_id)
                observation = inspector.inspect(scenario.stations[target_index])
                if observation.station_id != target_id:
                    raise ValueError("inspection adapter returned the wrong station")
                if not observation.synthetic or observation.evidence_source != "scenario_fixture":
                    raise ValueError("SCOUT-01 runner accepts only explicitly synthetic fixture evidence")
                if observation.result not in ("CHANGED", "UNCHANGED", "INCONCLUSIVE"):
                    raise ValueError("unknown inspection result")
                inspections.append({"time_s": round(elapsed, 6), **asdict(observation)})
                event("INSPECTION_RECORDED", station_id=target_id,
                      result=observation.result, synthetic=observation.synthetic)
                target_index += 1
                robot.advance(scenario.dt_s)
                continue
            heading_error = wrap_angle(math.atan2(y - pose.y, x - pose.x) - pose.heading)
            if abs(heading_error) > 0.06:
                state = "ALIGN"
                robot.command(0.0, max(-robot.spec.max_turn_rps,
                                      min(robot.spec.max_turn_rps, heading_error * 3)))
            else:
                state = "RETURN" if target_id == "HOME" else "NAVIGATE"
                robot.command(min(robot.spec.max_speed_mps, remaining / scenario.dt_s), 0.0)
            robot.advance(scenario.dt_s)
    except CollisionGuardError:
        status, reason = "FAULT", "FOOTPRINT_GUARD"
        event("SAFETY_STOP", reason=reason)
    finally:
        robot.stop()

    final_telemetry = robot.read()
    terminal_pose = final_telemetry.pose
    stopped = (final_telemetry.linear_speed_mps == 0.0
               and final_telemetry.angular_speed_rps == 0.0)
    if not stopped:
        status, reason = "FAULT", "STOP_NOT_CONFIRMED"
    if status != "COMPLETED":
        state = status
    snapshot(terminal_pose)
    event("MISSION_FINISHED", status=status, reason=reason)
    changes = sum(item["result"] == "CHANGED" for item in inspections)
    return {
        "schema_version": "1.0", "scout_version": __version__,
        "scenario": scenario.name, "scenario_sha256": scenario.digest, "seed": seed,
        "execution": "digital_simulation", "clock": "simulation_seconds",
        "evidence": {"source": "scenario_fixture", "synthetic": True,
                     "computer_vision_executed": False,
                     "notice": "Prepared synthetic deviations; not camera or computer vision results."},
        "status": status, "reason": reason, "visited_stations": visited,
        "planned_stations": [station.id for station in scenario.stations],
        "returned_home": status == "COMPLETED", "stopped": stopped,
        "metrics": {"duration_s": round(elapsed, 6), "distance_m": round(distance, 6),
                    "visited_count": len(visited), "changed_station_count": changes,
                    "completion_ratio": round(len(visited) / len(scenario.stations), 6),
                    "min_front_clearance_m": None if min_clearance is None else round(min_clearance, 6),
                    "collision_guard_activations": getattr(robot, "collision_guard_activations", 0),
                    "simulated_contacts": 0, "control_steps": step},
        "final_pose": asdict(terminal_pose), "inspections": inspections,
        "events": events, "trace": trace, "world": asdict(scenario),
        "limitations": ["Ideal simulated pose; no measured odometry or ArUco localization.",
                        "Instant simulated braking; no claim about physical stopping distance.",
                        "Circular footprint and planar static obstacles; no automatic detour.",
                        "Fixture inspection does not measure computer vision accuracy."],
    }
