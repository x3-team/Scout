"""Scout-only digital telemetry and local stop, using the existing physics."""
from dataclasses import replace
import math
from .bridge import VERSION, finite
from ..simulator import SimRobot, CollisionGuardError, wrap_angle


class DigitalProbeRobot(SimRobot):
    """Same Scout physics; one noise sample per boundary, including stop re-reads."""
    def __init__(self,scenario,seed):
        super().__init__(scenario,seed)
        self._sample_time = None
        self._sample = None
        self.sensor_samples = self.advance_calls = 0

    def read(self):
        if self._sample_time != self.time:
            self._sample = super().read()
            self._sample_time = self.time
            self.sensor_samples += 1
        return replace(self._sample,pose=self.pose,linear_speed_mps=self.linear,angular_speed_rps=self.angular)

    def advance(self,dt):
        super().advance(dt)
        self.advance_calls += 1


def session_for(scenario,seed,epoch):
    plan = [dict(segment_id=s.id+'-1',target_id=s.id,x_m=s.x,y_m=s.y) for s in scenario.stations]
    plan.append(dict(segment_id='HOME-1',target_id='HOME',x_m=scenario.start.x,y_m=scenario.start.y))
    return dict(schema_version=VERSION,type='session',trial_id='adapter-smoke',epoch=epoch,
                profile_id='digital_known_map',frame='lab_x_right_y_up_yaw_ccw',seed=seed,
                profile=dict(dt_s=.05,max_steps=3600,max_v_mps=.15,max_omega_rad_s=.8,
                             stop_clearance_m=.22,sensor_range_m=1.,arrival_tolerance_m=.025,controller_timeout_s=1.),
                controller={'id':'goal_seeker','version':1},
                world=dict(width_m=scenario.width,height_m=scenario.height,radius_m=scenario.robot.radius_m,
                           obstacles=[dict(x_min=b.x,y_min=b.y,x_max=b.x+b.width,y_max=b.y+b.height) for b in scenario.obstacles]),
                start_pose=dict(x_m=scenario.start.x,y_m=scenario.start.y,yaw_rad=wrap_angle(scenario.start.heading)),
                plan=plan,provenance=dict(pose='ideal_simulation',map='ideal_static_map',
                                          range='synthetic_body_clearance',computer_vision_executed=False))


def observation_for(telemetry,step,session):
    target = session['plan'][0]
    return dict(schema_version=VERSION,type='observation',trial_id=session['trial_id'],epoch=session['epoch'],
                segment_id=target['segment_id'],target_id=target['target_id'],step=step,time_s=step*.05,
                pose=dict(x_m=telemetry.pose.x,y_m=telemetry.pose.y,yaw_rad=telemetry.pose.heading),
                velocity=dict(v_mps=telemetry.linear_speed_mps,omega_rad_s=telemetry.angular_speed_rps),
                motion_enabled=True,sensor_status='unavailable' if telemetry.front_clearance_m is None else 'valid',
                front_body_clearance_m=telemetry.front_clearance_m,sampled_at_s=telemetry.sampled_at_s)


def local_stop(robot):
    evidence = {'attempted':True,'confirmed':False,'telemetry':None}
    try:
        robot.stop()
        t = robot.read()
        if finite(t.linear_speed_mps) and finite(t.angular_speed_rps):
            evidence['telemetry'] = dict(v_mps=t.linear_speed_mps,omega_rad_s=t.angular_speed_rps)
            evidence['confirmed'] = t.linear_speed_mps == 0 and t.angular_speed_rps == 0
    except Exception:
        pass
    return evidence

