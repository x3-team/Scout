"""Hardware-independent contracts; no simulation world in controller inputs."""
from dataclasses import dataclass
from typing import Protocol
from .models import Pose, RobotSpec, Station


@dataclass(frozen=True)
class Telemetry:
    pose: Pose
    front_clearance_m: float | None
    sampled_at_s: float
    linear_speed_mps: float
    angular_speed_rps: float


@dataclass(frozen=True)
class Inspection:
    station_id: str
    result: str
    deviations: tuple[str, ...]
    evidence_source: str
    synthetic: bool


class RobotPort(Protocol):
    spec: RobotSpec

    def read(self) -> Telemetry: ...
    def command(self, linear_mps: float, angular_rps: float) -> None: ...
    def advance(self, dt_s: float) -> None: ...
    def stop(self) -> None: ...


class InspectionPort(Protocol):
    def inspect(self, station: Station) -> Inspection: ...
