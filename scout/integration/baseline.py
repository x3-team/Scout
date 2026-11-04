"""Record the existing Scout mission without copying or replacing its decisions."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import platform
from .digital import DigitalProbeRobot
from .provenance import canonical
from ..mission import run_mission


class RecordedRobot(DigitalProbeRobot):
    def __init__(self,scenario,seed):
        super().__init__(scenario,seed)
        self.audit = []

    def read(self):
        telemetry = super().read()
        self.audit.append(dict(kind='read',step=self.advance_calls,telemetry=asdict(telemetry)))
        return telemetry

    def command(self,linear_mps,angular_rps):
        super().command(linear_mps,angular_rps)
        self.audit.append(dict(kind='command',step=self.advance_calls,
                               requested=dict(v_mps=linear_mps,omega_rad_s=angular_rps),
                               applied=dict(v_mps=self.linear,omega_rad_s=self.angular)))

    def advance(self,dt):
        before = asdict(self.pose)
        super().advance(dt)
        self.audit.append(dict(kind='advance',step=self.advance_calls-1,dt_s=dt,
                               before=before,after=asdict(self.pose),
                               applied=dict(v_mps=self.linear,omega_rad_s=self.angular)))

    def stop(self):
        super().stop()
        # Record actual telemetry after stop, using the common cached sample policy.
        telemetry = super().read()
        self.audit.append(dict(kind='stop',step=self.advance_calls,telemetry=asdict(telemetry),
                               confirmed=telemetry.linear_speed_mps==0 and telemetry.angular_speed_rps==0))


def run_baseline(scenario,sources,*,seed=1):
    robot = RecordedRobot(scenario,seed)
    report,error = None,None
    try:
        report = run_mission(scenario,seed,robot=robot)
    except Exception as failure:
        # Failed attempts stay in the comparison denominator with their audit prefix.
        error = dict(type=type(failure).__name__,message=str(failure)[:512])
    finally:
        robot.stop()
    return dict(report=report,error=error,audit=robot.audit,source_scenario=asdict(scenario),
                provenance=dict(controller='existing scout.mission.run_mission',sources=deepcopy(sources),
                                scene_sha256=scenario.digest,seed=seed,
                                environment=dict(python=platform.python_version(),os=platform.platform()),
                                sensor_policy='one synthetic sample per global boundary; stop reads reuse it',
                                report_format='Scout legacy 1.0; not a GoalSeeker wire report',
                                audit_canonical_sha256=hashlib.sha256(canonical(robot.audit)).hexdigest()),
                runtime=dict(confirmed_advances=robot.advance_calls,sensor_samples=robot.sensor_samples,
                             physics_owner='Scout SimRobot',stop_confirmed=robot.audit[-1]['confirmed']))
