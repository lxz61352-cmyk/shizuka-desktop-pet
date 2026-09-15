"""Offline side-pose motion and gravity inspector; no API or user data."""
import argparse,math,sys,time,tkinter as tk
from tkinter import ttk
from pathlib import Path
from PIL import Image,ImageTk,ImageDraw,ImageFont
ROOT=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from character_packs import discover_packs,load_pack
from layered_renderer import LayeredRenderer
from pet_motion import MotionController
from pet_ground import GroundMotion
from pet_triggers import ActionTriggers

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("pack",nargs="?",default=str(ROOT/"characters/shizuka-side-motion"))
    parser.add_argument("--seconds",type=int,default=0)
    args=parser.parse_args()
    packs=[p for p in discover_packs(ROOT/"characters")[0] if p.renderer=="layered"]
    selected=load_pack(args.pack)
    root=tk.Tk()
    root.title(selected.name + " · 动作预览")
    root.configure(bg="#f3f5fa");root.resizable(False,False)
    stage=tk.Label(root,bg="#f3f5fa",bd=0,cursor="hand2")
    stage.grid(row=0,column=0,padx=14,pady=14)
    panel=tk.Frame(root,bg="#f3f5fa")
    panel.grid(row=0,column=1,padx=(0,22),pady=25,sticky="n")
    ttk.Label(panel,text="角色局部动作",font=("Microsoft YaHei UI",16,"bold")).pack(anchor="w",pady=(0,14))
    choice=ttk.Combobox(panel,state="readonly",width=27,values=[p.name for p in packs])
    choice.set(selected.name);choice.pack(fill="x")
    animated=tk.BooleanVar(value=True);speaking=tk.BooleanVar();blink=tk.BooleanVar()
    state=tk.StringVar(value="待机")
    controller=MotionController(selected.manifest.get('interaction_physics'));ground=GroundMotion()
    triggers=ActionTriggers(time.monotonic())
    renderer=LayeredRenderer(selected)
    with Image.open(selected.portrait) as source:
        hit_art=source.convert("RGBA")
    height=360;stage_w=490;stage_h=580;floor=548
    offset=[0.0,0.0];press=None;demo_started=None;touch=None;last_click=None
    try:
        import ctypes
        double_seconds=max(.25,ctypes.windll.user32.GetDoubleClickTime()/1000)
    except (AttributeError,OSError):
        double_seconds=.5
    started=time.monotonic()
    try:
        font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",12)
    except OSError:
        font=ImageFont.load_default(size=12)
    def floor_top():
        neutral=renderer.frame(height,animated=False)
        foot=neutral.getchannel("A").point(lambda a:255 if a>=128 else 0).getbbox()[3]
        return floor-foot
    def reset_position():
        offset[:]=[(stage_w-round(renderer.canvas_size[0]*height/renderer.canvas_size[1]))/2,floor_top()]
    reset_position()
    def change(_event=None):
        nonlocal renderer,selected,demo_started,press,touch,last_click,triggers,hit_art
        selected=packs[choice.current()];renderer=LayeredRenderer(selected)
        root.title(selected.name + " · 动作预览")
        with Image.open(selected.portrait) as source:
            hit_art=source.convert("RGBA")
        controller.reset();ground.cancel();demo_started=None;press=None;touch=None;last_click=None
        triggers=ActionTriggers(time.monotonic())
        reset_position()
    choice.bind("<<ComboboxSelected>>",change)
    tk.Label(panel,text="右键按住头部提起，以鼠标抓取点为支点。",bg="#f3f5fa",fg="#526071").pack(anchor="w",pady=(14,8))
    for label,var in (("启用动作与眨眼",animated),("说话嘴型",speaking),("保持闭眼",blink)):
        ttk.Checkbutton(panel,text=label,variable=var).pack(anchor="w",pady=5)
    def action(name,gesture=False):
        now=time.monotonic()
        if triggers.allow(name,now,manual=not gesture,gesture=gesture,
                active=controller.action is not None,blocked=controller.dragging or ground.active):
            animated.set(True);controller.trigger(name,now)
            return True
        return False
    actions=tk.Frame(panel,bg="#f3f5fa");actions.pack(fill="x",pady=12)
    for i,(key,label) in enumerate((("pat","摸摸头"),("sleep","打盹 · zzz"),("happy","小跳 · 两次"))):
        ttk.Button(actions,text=label,command=lambda k=key:action(k)).grid(row=i//2,column=i%2,padx=3,pady=4,sticky="ew")
    def drop(now):
        controller.release(now,falling=True)
        ground.start(offset[1],floor_top(),now,gravity=height*6)
    def demo():
        nonlocal demo_started
        animated.set(True);controller.reset();ground.cancel();reset_position()
        offset[1]-=180
        demo_started=time.monotonic()
        controller.begin_drag((0,0),(.5,.2),demo_started)
    ttk.Button(panel,text="演示：提起保持 → 下落着地",command=demo).pack(fill="x",pady=5)
    tk.Label(panel,textvariable=state,bg="#f3f5fa",fg="#245d88",font=("Microsoft YaHei UI",11)).pack(anchor="w",pady=14)
    tk.Label(panel,text="在人物上操作（与正式版一致）：\n左键按住头顶来回轻抚 → 摸头\n右键按住头部拖动 → 提起，绕抓取点摇晃\n双击身体 → 连跳两次（冷却 5 秒）\n\n正式桌宠还会自动触发：\n电脑空闲 1 分钟 → 打盹\n隐藏满 30 秒再叫出 → 跳两下\n聊天、拖动、下落期间暂停。",bg="#f3f5fa",fg="#637083",justify="left").pack(anchor="w",pady=8)
    tk.Label(panel,text="离线预览，不调用 AI 或读取记忆。",bg="#f3f5fa",fg="#637083").pack(anchor="w",pady=12)
    def down(event):
        nonlocal press,demo_started,touch,last_click
        if not region(event,"head_pickup")[1]:
            press=None
            return
        touch=None;last_click=None
        press=(event.x_root,event.y_root,event.x,event.y,*offset)
        demo_started=None;ground.cancel();controller.falling=False
    def move(event):
        if not press:return
        dx,dy=event.x_root-press[0],event.y_root-press[1]
        if not controller.dragging and max(abs(dx),abs(dy))>4:
            grab=((press[2]-press[4])/(renderer.canvas_size[0]*height/renderer.canvas_size[1]),
                  (press[3]-press[5])/height)
            scale=height/hit_art.height
            box=tuple(v*scale for v in hit_art.getchannel("A").point(lambda a:255 if a>=128 else 0).getbbox())
            limits=renderer.pickup_limits(box,(round(hit_art.width*scale),height),grab)
            controller.begin_drag((press[0]/height,press[1]/height),
                grab,time.monotonic(),angle_limits=limits)
        if controller.dragging:
            offset[:]=[press[4]+dx,press[5]+dy]
            controller.drag_to((event.x_root/height,event.y_root/height),time.monotonic())
    def up(_event):
        nonlocal press
        if controller.dragging:drop(time.monotonic())
        press=None
    def region(event,region_name="head_pat"):
        scale=height/renderer.canvas_size[1]
        x,y=(event.x-offset[0])/scale,(event.y-offset[1])/scale
        box=selected.manifest.get("interaction_regions",{}).get(region_name,
            [renderer.canvas_size[0]*.33,renderer.canvas_size[1]*.1,renderer.canvas_size[0]*.68,renderer.canvas_size[1]*.28])
        visible=0<=x<hit_art.width and 0<=y<hit_art.height and hit_art.getpixel((int(x),int(y)))[3]>=128
        return x/renderer.canvas_size[1],visible and box[0]<=x<box[2] and box[1]<=y<box[3],visible and y>=selected.manifest.get("body_hinge",.55)*renderer.canvas_size[1]
    def touch_down(event):
        nonlocal touch
        if press is not None or ground.active:return
        x,head,body=region(event)
        touch=dict(point=(event.x,event.y),head=head,body=body,moved=False,origin_x=x)
        triggers.clear_stroke();triggers.stroke(x,time.monotonic(),head)
    def touch_move(event):
        nonlocal last_click
        if touch is None:return
        if max(abs(event.x-touch["point"][0]),abs(event.y-touch["point"][1]))>4:
            touch["moved"]=True;last_click=None
        x,head,_=region(event)
        if controller.petting:
            controller.pet_to(x)
            return
        if controller.action is None and triggers.stroke(x,time.monotonic(),head and touch["head"],pressed=True):
            if action("pat",gesture=True):
                controller.begin_pet(touch["origin_x"],time.monotonic());controller.pet_to(x)
    def touch_up(event):
        nonlocal touch,last_click
        if touch is None:return
        now=time.monotonic()
        controller.end_pet(now)
        if not touch["moved"] and touch["body"]:
            if (last_click and now-last_click[0]<=double_seconds
                    and abs(event.x-last_click[1])+abs(event.y-last_click[2])<=10):
                action("happy",gesture=True);last_click=None
            else:last_click=(now,event.x,event.y)
        else:last_click=None
        touch=None;triggers.clear_stroke()
    stage.bind("<ButtonPress-1>",touch_down);stage.bind("<B1-Motion>",touch_move);stage.bind("<ButtonRelease-1>",touch_up)
    stage.bind("<ButtonPress-3>",down);stage.bind("<B3-Motion>",move);stage.bind("<ButtonRelease-3>",up)
    names={"idle":"待机","dragging":"持续提起 · 撇嘴","falling":"下落","landing":"着地缓冲",
        "pat":"摸摸头","happy":"连跳两次","sleep":"打盹 · zzz"}
    phases={"start":"进入","loop":"持续","end":"收尾"}
    def tick():
        nonlocal demo_started
        now=time.monotonic()
        if demo_started is not None:
            age=now-demo_started
            if age<3.2:controller.drag_to((.18*math.sin(age*6) if age<1.7 else 0,0),now)
            else:drop(now);demo_started=None
        if ground.active:
            step=ground.step(now);offset[1]=step.y
            if step.impact:controller.land(now)
        gaze=((root.winfo_pointerx()-stage.winfo_rootx()-stage_w/2)/600,
              (root.winfo_pointery()-stage.winfo_rooty()-180)/600)
        pose=controller.step(now,gaze,animated.get())
        frame=renderer.frame(height,now-started,speaking=speaking.get(),animated=animated.get(),
            eye_open=0 if blink.get() else None,pose=pose)
        bg=Image.new("RGB",(stage_w,stage_h),"#f3f5fa")
        draw=ImageDraw.Draw(bg)
        draw.rectangle((0,floor,stage_w,stage_h),fill="#dce5f3")
        draw.line((0,floor,stage_w,floor),fill="#8aa3c5",width=2)
        draw.text((15,floor+10),"任务栏上沿（预览）",font=font,fill="#536b8d")
        bg.paste(frame.convert("RGB"),(round(offset[0]),round(offset[1])),
            mask=frame.getchannel("A"))
        stage._image=ImageTk.PhotoImage(bg);stage.configure(image=stage._image)
        state.set(names.get(pose.state,pose.state)+" · "+phases[pose.phase])
        root.after(max(10,40-int((time.monotonic()-now)*1000)),tick)
    tick()
    if args.seconds:root.after(args.seconds*1000,root.destroy)
    root.mainloop()
if __name__=="__main__":main()
