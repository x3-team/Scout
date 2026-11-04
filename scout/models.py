"""Validated scenario data. All geometry uses metres and radians."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    heading: float = 0.0


@dataclass(frozen=True)
class Obstacle:
    id: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class Station:
    id: str
    x: float
    y: float
    deviations: tuple[str, ...] = ()


@dataclass(frozen=True)
class RobotSpec:
    radius_m: float = 0.14
    wheel_radius_m: float = 0.04
    axle_track_m: float = 0.18
    max_speed_mps: float = 0.15
    max_turn_rps: float = 0.8


@dataclass(frozen=True)
class Scenario:
    name: str
    width: float
    height: float
    start: Pose
    stations: tuple[Station, ...]
    obstacles: tuple[Obstacle, ...] = ()
    robot: RobotSpec = RobotSpec()
    dt_s: float = 0.05
    max_duration_s: float = 180.0
    sensor_range_m: float = 1.0
    sensor_noise_m: float = 0.002
    stop_clearance_m: float = 0.22
    arrival_tolerance_m: float = 0.025
    sensor_failure_at_s: float | None = None

    def __post_init__(self):
        def finite_number(value):
            return (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value))

        def positive(value, name):
            if not finite_number(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")

        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("scenario name must be nonempty")
        for name in ("width", "height", "dt_s", "max_duration_s", "sensor_range_m",
                     "stop_clearance_m", "arrival_tolerance_m"):
            positive(getattr(self, name), name)
        for name, value in asdict(self.robot).items():
            positive(value, name)
        if self.dt_s > 0.1:
            raise ValueError("dt_s must not exceed 0.1 s")
        if self.max_duration_s / self.dt_s > 100_000:
            raise ValueError("scenario exceeds 100000 simulation steps")
        if not finite_number(self.sensor_noise_m) or self.sensor_noise_m < 0:
            raise ValueError("sensor_noise_m must be finite and nonnegative")
        if self.sensor_range_m <= self.stop_clearance_m + self.sensor_noise_m:
            raise ValueError("sensor range must exceed stopping threshold and noise")
        if self.stop_clearance_m <= self.robot.max_speed_mps * self.dt_s + self.sensor_noise_m:
            raise ValueError("stopping threshold must cover a simulation step and sensor noise")
        if not 0 < self.arrival_tolerance_m < self.stop_clearance_m:
            raise ValueError("arrival tolerance must be below stopping clearance")
        if self.sensor_failure_at_s is not None:
            if not finite_number(self.sensor_failure_at_s) or self.sensor_failure_at_s < 0:
                raise ValueError("sensor_failure_at_s must be finite and nonnegative")
        if len(self.stations) != 3:
            raise ValueError("SCOUT-01 requires exactly three stations")
        ids = [station.id for station in self.stations]
        if any(not isinstance(i, str) or not i or i == "HOME" for i in ids) or len(set(ids)) != 3:
            raise ValueError("station IDs must be unique, nonempty and different from HOME")
        obstacle_ids = [obstacle.id for obstacle in self.obstacles]
        if (any(not isinstance(i, str) or not i for i in obstacle_ids)
                or len(set(obstacle_ids)) != len(obstacle_ids)):
            raise ValueError("obstacle IDs must be unique and nonempty")
        for obstacle in self.obstacles:
            for name in ("x", "y", "width", "height"):
                if not finite_number(getattr(obstacle, name)):
                    raise ValueError("obstacle geometry must be finite")
            positive(obstacle.width, "obstacle width")
            positive(obstacle.height, "obstacle height")
            if (obstacle.x < 0 or obstacle.y < 0
                    or obstacle.x + obstacle.width > self.width
                    or obstacle.y + obstacle.height > self.height):
                raise ValueError("obstacle must lie inside the arena")
        for point in (self.start, *self.stations):
            if not finite_number(point.x) or not finite_number(point.y):
                raise ValueError("point coordinates must be finite")
            if not self.is_free(point.x, point.y):
                raise ValueError("start and stations need clearance for the full robot footprint")
        if not finite_number(self.start.heading):
            raise ValueError("heading must be finite")
        for station in self.stations:
            if any(not isinstance(d, str) or not d.strip() for d in station.deviations):
                raise ValueError("deviations must be nonempty strings")

    def is_free(self, x: float, y: float) -> bool:
        radius = self.robot.radius_m
        if not (radius < x < self.width - radius and radius < y < self.height - radius):
            return False
        for obstacle in self.obstacles:
            near_x = min(max(x, obstacle.x), obstacle.x + obstacle.width)
            near_y = min(max(y, obstacle.y), obstacle.y + obstacle.height)
            if math.hypot(x - near_x, y - near_y) <= radius:
                return False
        return True

    @property
    def digest(self) -> str:
        data = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_scenario(path: str | Path) -> Scenario:
    """Reject unknown keys and non-finite geometry before a run starts."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("scenario must be a JSON object")
    try:
        data["start"] = Pose(**data["start"])
        stations = []
        for station in data["stations"]:
            station = dict(station)
            deviations = station.get("deviations", [])
            if not isinstance(deviations, list):
                raise ValueError("deviations must be a list")
            station["deviations"] = tuple(deviations)
            stations.append(Station(**station))
        data["stations"] = tuple(stations)
        data["obstacles"] = tuple(Obstacle(**o) for o in data.get("obstacles", []))
        data["robot"] = RobotSpec(**data.get("robot", {}))
        return Scenario(**data)
    except (TypeError, KeyError, AttributeError) as error:
        raise ValueError(f"invalid scenario structure: {error}") from error
