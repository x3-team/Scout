"""Differential-drive kinematics, conservative sensing and swept collision guard."""
import math
import random
from .models import Pose, Scenario, Station
from .ports import Inspection, Telemetry


def wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def integrate(pose: Pose, linear: float, angular: float, dt: float) -> Pose:
    heading = pose.heading + angular * dt
    # Exact arc in midpoint/sinc form: subtracting nearly equal sin/cos values
    # and multiplying by v/omega loses precision as omega approaches zero.
    half_turn = angular * dt / 2
    chord = linear * dt * (math.sin(half_turn) / half_turn if half_turn else 1.0)
    x = pose.x + chord * math.cos(pose.heading + half_turn)
    y = pose.y + chord * math.sin(pose.heading + half_turn)
    return Pose(x, y, wrap_angle(heading))


def ray_box(x, y, dx, dy, left, bottom, right, top):
    """Distance to an axis-aligned box along a unit ray, or infinity."""
    enter, leave = -math.inf, math.inf
    for position, direction, low, high in ((x, dx, left, right), (y, dy, bottom, top)):
        if abs(direction) < 1e-12:
            if position < low or position > high:
                return math.inf
        else:
            a, b = (low - position) / direction, (high - position) / direction
            enter, leave = max(enter, min(a, b)), min(leave, max(a, b))
    if leave < max(enter, 0):
        return math.inf
    return max(0.0, enter)


class CollisionGuardError(RuntimeError):
    """A proposed simulation movement would intersect the robot footprint."""


class SimRobot:
    def __init__(self, scenario: Scenario, seed: int):
        self.scenario = scenario
        self.spec = scenario.robot
        self.pose = scenario.start
        self.time = 0.0
        self.linear = self.angular = 0.0
        self.left_wheel_rps = self.right_wheel_rps = 0.0
        self.distance = 0.0
        self.collision_guard_activations = 0
        self.rng = random.Random(seed)

    def clearance(self):
        s, p, r = self.scenario, self.pose, self.spec.radius_m
        dx, dy = math.cos(p.heading), math.sin(p.heading)
        distances = [s.sensor_range_m]
        for position, direction, low, high in ((p.x, dx, r, s.width - r),
                                               (p.y, dy, r, s.height - r)):
            if direction > 1e-12:
                distances.append((high - position) / direction)
            elif direction < -1e-12:
                distances.append((low - position) / direction)
        for obstacle in s.obstacles:
            distances.append(ray_box(p.x, p.y, dx, dy, obstacle.x - r, obstacle.y - r,
                                     obstacle.x + obstacle.width + r,
                                     obstacle.y + obstacle.height + r))
        return max(0.0, min(distances))

    def read(self):
        failure = self.scenario.sensor_failure_at_s
        distance = None
        if failure is None or self.time < failure:
            noise = self.rng.uniform(-self.scenario.sensor_noise_m, self.scenario.sensor_noise_m)
            distance = max(0.0, min(self.scenario.sensor_range_m, self.clearance() + noise))
        return Telemetry(self.pose, distance, self.time, self.linear, self.angular)

    def command(self, linear_mps, angular_rps):
        if not math.isfinite(linear_mps) or not math.isfinite(angular_rps):
            self.stop()
            raise ValueError("motor command must be finite")
        self.linear = max(0.0, min(self.spec.max_speed_mps, linear_mps))
        self.angular = max(-self.spec.max_turn_rps, min(self.spec.max_turn_rps, angular_rps))
        half_track = self.spec.axle_track_m / 2
        self.left_wheel_rps = (self.linear - self.angular * half_track) / self.spec.wheel_radius_m
        self.right_wheel_rps = (self.linear + self.angular * half_track) / self.spec.wheel_radius_m

    def advance(self, dt_s):
        if not math.isfinite(dt_s) or dt_s <= 0:
            self.stop()
            raise ValueError("time step must be finite and positive")
        steps = max(1, math.ceil(abs(self.linear) * dt_s / 0.005),
                    math.ceil(abs(self.angular) * dt_s / 0.025))
        proposed = self.pose
        for _ in range(steps):
            previous = proposed
            proposed = integrate(previous, self.linear, self.angular, dt_s / steps)
            # Arc/chord deviation inflates the swept box: no skipping thin obstacles.
            margin = (abs(self.linear / self.angular)
                      * (1 - math.cos(abs(self.angular * dt_s / steps) / 2))
                      if abs(self.angular) > 1e-10 else 0.0)
            if not self._sweep_clear(previous, proposed, margin):
                self.collision_guard_activations += 1
                self.stop()
                raise CollisionGuardError("movement rejected by simulated footprint guard")
        self.distance += abs(self.linear) * dt_s
        self.pose = proposed
        self.time += dt_s

    def _sweep_clear(self, previous, proposed, margin):
        s, radius = self.scenario, self.spec.radius_m + margin
        if not all(radius < p.x < s.width - radius and radius < p.y < s.height - radius
                   for p in (previous, proposed)):
            return False
        dx, dy = proposed.x - previous.x, proposed.y - previous.y
        length = math.hypot(dx, dy)
        if length < 1e-12:
            return s.is_free(proposed.x, proposed.y)
        for obstacle in s.obstacles:
            entry = ray_box(previous.x, previous.y, dx / length, dy / length,
                            obstacle.x - radius, obstacle.y - radius,
                            obstacle.x + obstacle.width + radius,
                            obstacle.y + obstacle.height + radius)
            if entry <= length:
                return False
        return True

    def stop(self):
        self.linear = self.angular = 0.0
        self.left_wheel_rps = self.right_wheel_rps = 0.0


class SyntheticInspector:
    def inspect(self, station: Station):
        return Inspection(station.id, "CHANGED" if station.deviations else "UNCHANGED",
                          station.deviations, "scenario_fixture", True)
