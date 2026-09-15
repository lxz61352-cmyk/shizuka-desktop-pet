"""Deterministic interaction state and springs, independent of Tk and artwork."""
from dataclasses import dataclass
import math


def clamp(value, lo, hi):
    return max(lo,min(hi,value))


@dataclass
class Spring:
    value: float = 0.0
    velocity: float = 0.0

    def step(self,target,dt,stiffness=105,damping=13):
        count=max(1,math.ceil(dt*120))
        h=dt/count
        for _ in range(count):
            self.velocity += ((target-self.value)*stiffness-self.velocity*damping)*h
            self.value += self.velocity*h
        return self.value


@dataclass(frozen=True)
class Pose:
    gaze: tuple = (0.0,0.0)
    angle: float = 0.0
    dy: float = 0.0  # fraction of canvas height
    body_stretch: float = 1.0
    head_angle: float = 0.0
    head_dx: float = 0.0
    head_dy: float = 0.0
    hair_sway: float = 0.0
    leg_sway: float = 0.0
    breath: float = 0.0
    sleep_fx: float = 0.0
    sleep_time: float = 0.0
    eye_open: float | None = None
    mouth_open: bool | None = None
    expression: str = "neutral"
    anchor: tuple = (0.5,0.18)
    state: str = "idle"
    phase: str = "loop"
    activity_progress: float = 1.0


class MotionController:
    ACTIONS={"pat":2.4,"happy":2.0,"sleep":5.0}

    # ---- 拖动摇摆：驱动阻尼单摆参数（想更晃/更稳就调这里）----
    SWAY_MAX_DEG = 95.0       # 最大摆角（度，放宽很多，别被卡住）
    SWAY_PERIOD = 1.05        # 自然摆动周期（秒，越大越慢悠悠）
    SWAY_DAMP_DRAG = 0.05     # 拖动时的阻尼比（越小越容易荡、反向甩得越高）
    SWAY_DAMP_FREE = 0.075    # 松手后（未下落）的阻尼比
    SWAY_DAMP_FALL = 0.95     # 松手下落时的阻尼比（接近临界，快速停摆）
    SWAY_RETURN_K = 150.0     # 松手下落时"回正弹簧"刚度（越大停得越快）
    SWAY_DRIVE_V = 4.0        # 速度驱动增益（持续拖动时的滞后，越大越明显）
    SWAY_DRIVE_A = 0.8        # 加速度驱动增益（起步/反向的惯性，别太大否则一提就乱晃）

    LANDING_SECONDS = .25
    PREPARE_SECONDS = .35

    def __init__(self,physics=None,recover_frames=None):
        self.physics=physics or {}
        self.recover_frames=tuple(recover_frames or ())
        self.recover_seconds=sum(frame['duration'] for frame in self.recover_frames) if self.recover_frames else .8
        self.reset()

    def reset(self):
        self.dragging=False
        self.grab=(0.5,0.18)
        self.sway_limits=(-self.SWAY_MAX_DEG,self.SWAY_MAX_DEG)
        self.pointer=None
        self.pointer_time=None
        self.last_movement=None
        self.last_time=None
        self.drag_started=-100.0
        self.released=-100.0
        self.landing_started=None
        self.settled_at=None
        self.action=None
        self.action_started=0.0
        self.speed=0.0
        self.accel=0.0
        self.prev_v=0.0
        self.sway=Spring()
        self.lift=Spring()
        self.gaze_x=Spring()
        self.gaze_y=Spring()
        self.hair=Spring()
        self.falling=False
        self.petting=False
        self.pet_controlled=False
        self.pet_origin=0.0
        self.pet_target=0.0
        self.pet_follow=Spring()

    def begin_pet(self,pointer_x,now):
        if self.action!="pat" or self.dragging or self.falling:
            return False
        self.petting=self.pet_controlled=True
        self.pet_origin=pointer_x
        self.pet_target=0.0
        self.pet_follow=Spring()
        self.action_started=now
        return True

    def pet_to(self,pointer_x):
        if self.petting:
            self.pet_target=clamp((pointer_x-self.pet_origin)*18,-3.0,3.0)

    def end_pet(self,now):
        if self.petting:
            self.petting=False
            self.pet_target=0.0
            self.action_started=now-(self.ACTIONS["pat"]-.35)

    def begin_drag(self,pointer,grab,now,angle_limits=None):
        self.landing_started=self.settled_at=None
        self.petting=self.pet_controlled=False
        self.pet_target=0.0
        self.dragging=True
        self.falling=False
        self.pointer=pointer
        self.pointer_time=now
        self.last_movement=now
        self.drag_started=now
        self.grab=tuple(clamp(n,0.0,1.0) for n in grab)
        self.sway_limits=angle_limits or (-self.SWAY_MAX_DEG,self.SWAY_MAX_DEG)
        self.action=None
        self.speed=0.0
        self.accel=0.0
        self.prev_v=0.0
        # Picking up a stationary character must not inject a scripted swing.

    def drag_to(self,pointer,now):
        if not self.dragging:
            return
        dt=max(0.008,now-self.pointer_time)
        # Pointer coordinates are normalized by the displayed character height.
        velocity=clamp((pointer[0]-self.pointer[0])/dt,-12,12)
        if abs(pointer[0]-self.pointer[0])>.001:
            self.last_movement=now
        self.speed += (velocity-self.speed)*(1-math.exp(-dt*18))
        acc=clamp((velocity-self.prev_v)/dt,-25,25)
        self.prev_v=velocity
        self.accel += (acc-self.accel)*(1-math.exp(-dt*12))
        self.pointer,self.pointer_time=pointer,now

    def release(self,now,falling=False):
        if not self.dragging:
            return
        self.dragging=False
        self.falling=falling
        self.released=-100 if falling else now
        self.speed=0.0
        if not falling:
            self.land(now)

    def land(self,now,settled=True):
        self.falling=False
        self.released=now
        self.landing_started=now
        self.settled_at=now if settled else None

    def settle(self,now):
        if self.landing_started is not None and self.settled_at is None:
            self.settled_at=now

    def body_state(self,now):
        if self.dragging:return "dragging"
        if self.falling:return "falling"
        if self.landing_started is not None:
            if self.settled_at is None or now-self.settled_at<self.LANDING_SECONDS:return "landing"
            if now-self.settled_at<self.LANDING_SECONDS+self.PREPARE_SECONDS+self.recover_seconds:return "recover"
        return "idle"

    def recovery_phase(self,now):
        age=now-self.settled_at-self.LANDING_SECONDS
        if age<self.PREPARE_SECONDS:return "prepare"
        age-=self.PREPARE_SECONDS
        for index,frame in enumerate(self.recover_frames):
            age-=frame['duration']
            if age<0:return f"frame-{index}"
        return "tidy"

    def trigger(self,action,now):
        if action not in self.ACTIONS:
            raise ValueError(f"Unknown action: {action}")
        if self.dragging or self.falling:
            return False
        self.landing_started=self.settled_at=None
        self.petting=self.pet_controlled=False
        self.pet_target=0.0
        self.action,self.action_started=action,now
        return True

    def step(self,now,gaze=(0.0,0.0),enabled=True):
        dt=0.0 if self.last_time is None else clamp(now-self.last_time,0,0.1)
        self.last_time=now
        if not enabled:
            # No latent spring kick when animation is enabled again.
            self.sway=Spring();self.lift=Spring();self.speed=0.0
            self.gaze_x=Spring();self.gaze_y=Spring()
            self.hair=Spring()
            self.petting=self.pet_controlled=False
            self.pet_follow=Spring();self.pet_target=0.0
            self.action=None;self.released=-100.0
            self.landing_started=self.settled_at=None
            return Pose()
        gx=self.gaze_x.step(clamp(gaze[0],-1,1),dt,90,19)
        gy=self.gaze_y.step(clamp(gaze[1],-1,1),dt,90,19)
        release_age=now-self.released
        if self.dragging and now-self.pointer_time>0.045:
            self.speed*=math.exp(-dt*12)
            self.accel*=math.exp(-dt*12)
        theta=math.radians(self.sway.value)
        omega=math.radians(self.sway.velocity)
        max_rad=math.radians(self.SWAY_MAX_DEG)
        if self.falling or (not self.dragging and release_age<0.7):
            # 松手下落：临界阻尼强弹簧快速回正，别晃太久
            K=self.SWAY_RETURN_K
            alpha=-(K)*math.sin(theta)-2*math.sqrt(K)*omega
            omega=clamp(omega+alpha*dt,-20.0,20.0)
            omega*=math.exp(-dt*3.0)
        else:
            # 驱动阻尼单摆：θ'' = -ω0²·sinθ - 2ζω0·θ' + drive
            w0=2*math.pi/self.SWAY_PERIOD
            zeta=self.SWAY_DAMP_DRAG if self.dragging else self.SWAY_DAMP_FREE
            if self.dragging and 'drag_still_damping' in self.physics:
                still=now-self.last_movement-self.physics.get('drag_still_delay',.08)
                blend=clamp(still/.16,0,1)
                zeta+=(self.physics['drag_still_damping']-zeta)*blend
            drive=-(self.SWAY_DRIVE_V*self.speed+self.SWAY_DRIVE_A*self.accel) if self.dragging else 0.0
            alpha=-(w0*w0)*math.sin(theta)-2*zeta*w0*omega+drive
            omega=clamp(omega+alpha*dt,-14.0,14.0)
        low,high=(tuple(math.radians(a) for a in self.sway_limits) if self.dragging
                  else (-max_rad,max_rad))
        theta=clamp(theta+omega*dt,low,high)
        if (theta<=low and omega<0) or (theta>=high and omega>0):
            omega=0.0
        self.sway.value=math.degrees(theta)
        self.sway.velocity=math.degrees(omega)
        sway=self.sway.value
        lifted=clamp(self.lift.step(1.0 if self.dragging else 0.0,dt,160,12),-0.35,1.15)
        # Window gravity handles the fall; the landing artwork absorbs impact.
        dy=0.0
        head_angle=head_dx=head_dy=0.0
        eye=mouth=None
        state=self.body_state(now)
        phase="start" if self.dragging and now-self.drag_started<.2 else "end" if state=="landing" else "loop"
        if state=="recover":
            phase=self.recovery_phase(now)
        expression="lifted" if self.dragging else "falling" if self.falling else "neutral"
        sleep_fx=sleep_time=0.0
        leg=0.0
        breath=.3*math.sin(now*1.7)
        pet_follow=self.pet_follow.step(self.pet_target,dt,100,20)
        if self.dragging:
            mouth=False
        if self.action:
            t=now-self.action_started
            length=self.ACTIONS[self.action]
            if self.petting:
                t=min(t,length-.5)
            if t>=length:
                self.action=None
                self.pet_controlled=False
            else:
                fade=clamp(min(t/.3,(length-t)/.35),0,1)
                envelope=fade*fade*(3-2*fade)
                phase="start" if t<.3 else "end" if length-t<.35 else "loop"
                state=self.action
                if self.action=="pat":
                    eye=0.0;mouth=False
                    head_angle=(2.8+.8*math.sin(t*7))*envelope
                    head_dy=.004*envelope
                    breath=0
                    if self.pet_controlled:
                        # Input displacement controls the lean, never face scale.
                        head_angle=(2.4-pet_follow)*envelope
                        head_dx=pet_follow*.0008*envelope
                elif self.action=="happy":
                    # Two separate arcs; the second is a little softer.
                    for start,duration,height in ((.25,.6,.045),(.98,.5,.036)):
                        jump=clamp((t-start)/duration,0,1)
                        dy-=height*4*jump*(1-jump)
                    eye=0.0;mouth=True
                elif self.action=="sleep":
                    fade=min(1,t/0.6,(length-t)/0.6)
                    eye=0.0 if fade>0.4 else None
                    head_angle=5.0*fade
                    head_dy=0.008*fade
                    breath=.6*math.sin(now*1.5)
                    mouth=False
                    sleep_fx=fade
                    sleep_time=t
        hair=self.hair.step(head_angle*.25+sway*.09,dt,48,8)
        squash=.035*math.exp(-release_age*7)*math.sin(release_age*14) if 0<=release_age<.7 else 0
        return Pose(gaze=(gx,gy),angle=sway,dy=dy,body_stretch=1+lifted*0.055,
                    head_angle=head_angle,head_dx=head_dx,head_dy=head_dy,
                    hair_sway=hair,leg_sway=leg,breath=breath-squash*8,
                    sleep_fx=sleep_fx,sleep_time=sleep_time,
                    eye_open=eye,mouth_open=mouth,expression=expression,
                    anchor=self.grab,state=state,phase=phase)
