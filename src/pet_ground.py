"""Gravity and floor contact independent of Tk, screen DPI and artwork."""
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class GroundStep:
    y: float
    impact: bool=False
    settled: bool=False

class GroundMotion:
    def __init__(self):
        self.cancel()
    def cancel(self):
        self.active=False
        self.y=0.0
        self.floor=0.0
        self.velocity=0.0
        self.last=None
        self.bounces=0
    def start(self,y,floor,now,gravity=2200.0):
        self.y=min(float(y),float(floor))
        self.floor=float(floor)
        self.velocity=0.0
        self.gravity=max(200.0,float(gravity))
        self.last=now
        self.bounces=0
        self.active=True
    def step(self,now):
        if not self.active:return GroundStep(self.y,settled=True)
        dt=max(0.0,min(.1,now-self.last))
        self.last=now
        count=max(1,math.ceil(dt*240))
        h=dt/count
        impact=False
        for _ in range(count):
            self.velocity+=self.gravity*h
            self.y+=self.velocity*h
            if self.y>=self.floor:
                self.y=self.floor
                impact=impact or self.bounces==0
                self.bounces+=1
                if self.velocity<80 or self.bounces>=3:
                    self.velocity=0
                    self.active=False
                    break
                self.velocity=-min(self.velocity*.26,220)
        return GroundStep(self.y,impact,not self.active)

def floor_position(workarea,bounds,scale,x):
    """Align the visible sole, not the transparent canvas bottom, to the work area."""
    left,top,right,bottom=workarea
    x0,y0,x1,y1=[n*scale for n in bounds]
    if x1-x0 <= right-left:
        x=max(left-x0,min(x,right-x1))
    else:x=(left+right-x0-x1)/2
    return round(x),round(bottom-y1)
