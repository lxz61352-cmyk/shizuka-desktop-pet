"""Layer compositor and lightweight interactions; no Cubism runtime is claimed."""
import math
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageFont
from pet_motion import Pose
from dataclasses import replace
from local_mesh import LocalMesh


class LayeredRenderer:
    PATCH_ROLES = {"blink_overlay","talk_overlay","eye_left_closed","eye_right_closed","lift_eye","lift_mouth","fall_mouth"}
    # 随眨眼/口型/表情显隐的图层（其余视为基础层，可缓存）
    DYNAMIC_ROLES = {"mouth_open","mouth_closed","blink_overlay","talk_overlay",
                     "eye_left_closed","eye_right_closed","eye_left","eye_right",
                     "lift_eye","lift_mouth","fall_mouth"}

    def __init__(self, pack):
        self.pack = pack
        self.canvas_size = tuple(pack.manifest["canvas_size"])
        self.mesh = LocalMesh(self.canvas_size,pack.manifest["rig"]) if pack.manifest.get("rig") else None
        self.layers = []
        self.roles = {layer.get("role",layer["id"]) for layer in pack.manifest["layers"]}
        for spec in pack.manifest["layers"]:
            with Image.open(pack.asset(spec["image"])) as source:
                patch = spec.get("role") in self.PATCH_ROLES and spec.get("source_box")
                if not patch and (source.mode != "RGBA" or source.getchannel("A").getextrema()[0] != 0):
                    raise ValueError(f"Layer needs genuine RGBA transparency: {spec['id']}")
                rgba = source.convert("RGBA")
                box = spec.get("source_box") or rgba.getchannel("A").point(lambda a:255 if a>=128 else 0).getbbox()
                if not box:
                    raise ValueError(f"Empty layer: {spec['id']}")
                self.layers.append((spec,rgba.crop(tuple(box))))
        self._height = None
        self._scaled = []
        self._dyn_scaled = []
        self._cache = {}
        self._base_cache = {}
        self._split_ok = False
        self._fonts = {}
        self._figure_bbox = None

    def _resize(self,height):
        if self._height == height:
            return
        self._height=height
        self.scale=height/self.canvas_size[1]
        self.size=(round(self.canvas_size[0]*self.scale),height)
        self._scaled=[]
        self._cache={}
        self._base_cache={}
        for spec,img in self.layers:
            x,y,w,h=spec["box"]
            tw,th=max(1,round(w)),max(1,round(h))
            polygon=spec.get("mask_polygon")
            if (tw,th)==img.size and not polygon:
                fitted=img          # 同尺寸且无需蒙版：直接用原图，省一次 LANCZOS
            else:
                fitted=img.resize((tw,th),Image.Resampling.LANCZOS)
                if polygon:
                    mask=Image.new("L",fitted.size)
                    ImageDraw.Draw(mask).polygon(polygon,fill=255)
                    mask=mask.filter(ImageFilter.GaussianBlur(spec.get("mask_feather",0)))
                    fitted.putalpha(ImageChops.multiply(fitted.getchannel("A"),mask))
            self._scaled.append((spec,fitted,round(x),round(y)))
        # 动态补丁单独缩放到显示尺寸（位置也按比例缩放），供「基础组 + 补丁」快路径使用
        self._dyn_scaled=[]
        for spec,img,x,y in self._scaled:
            if spec.get("role",spec["id"]) not in self.DYNAMIC_ROLES:
                continue
            sw=max(1,round(img.width*self.scale)); sh=max(1,round(img.height*self.scale))
            simg=img if (sw,sh)==img.size else img.resize((sw,sh),Image.Resampling.LANCZOS)
            self._dyn_scaled.append((spec,simg,round(x*self.scale),round(y*self.scale)))
        # 动态层（随眨眼/口型/表情显隐）是否全部排在静态层之后 → 可走「缓存基础组 + 每帧只叠补丁」快路径
        first_dyn=len(self._scaled); last_static=-1
        for i,(spec,_,_,_) in enumerate(self._scaled):
            if spec.get("role",spec["id"]) in self.DYNAMIC_ROLES:
                first_dyn=min(first_dyn,i)
            else:
                last_static=max(last_static,i)
        self._split_ok=first_dyn>last_static

    def _role_visible(self,role,closed,mouth,lifted,falling):
        """某个角色在当前状态下是否显示（与旧 _groups 的过滤条件等价）。"""
        if role=="mouth_open" and not mouth: return False
        if role=="mouth_closed" and mouth: return False
        if role=="blink_overlay" and not closed: return False
        if role=="talk_overlay" and not mouth: return False
        if role in ("eye_left_closed","eye_right_closed") and not closed: return False
        if role in ("eye_left","eye_right") and closed and role+"_closed" in self.roles: return False
        if role in ("lift_eye","lift_mouth") and not lifted: return False
        if role=="fall_mouth" and not falling: return False
        if role in ("talk_overlay","mouth_open","mouth_closed") and (
                (lifted and "lift_mouth" in self.roles) or (falling and "fall_mouth" in self.roles)):
            return False
        return True

    def _composite(self,spec,img,x,y,groups,canvas):
        role=spec.get("role",spec["id"])
        gname=spec.get("group","body")
        group=groups.get(gname)
        if group is None:
            group=groups[gname]=Image.new("RGBA",canvas)
        alpha=group.getchannel("A") if role in self.PATCH_ROLES else None
        group.alpha_composite(img,(x,y))
        if alpha is not None:
            group.putalpha(alpha)

    def _base_groups(self,expression):
        """不随眨眼/口型/表情变化的基础组（按高度+expression 缓存，说话/眨眼时不用重建整组）。"""
        if expression in self._base_cache:
            return self._base_cache[expression]
        groups={}
        for spec,img,x,y in self._scaled:
            if spec.get("role",spec["id"]) in self.DYNAMIC_ROLES:
                continue
            self._composite(spec,img,x,y,groups,self.canvas_size)
        groups={name:img.resize(self.size,Image.Resampling.LANCZOS) for name,img in groups.items()}
        self._base_cache[expression]=groups
        return groups

    def _groups(self,closed,mouth,expression):
        lifted=expression=="lifted"
        falling=expression=="falling"
        key=(closed,mouth,expression)
        if key in self._cache:
            groups,fbox=self._cache[key]
            self._figure_bbox=fbox
            return groups
        if self._split_ok:
            # 复制已缩放好的基础组，再把本状态要显示的动态小图块（已按比例缩放）叠上去
            groups={name:img.copy() for name,img in self._base_groups(expression).items()}
            for spec,img,x,y in self._dyn_scaled:
                role=spec.get("role",spec["id"])
                if self._role_visible(role,closed,mouth,lifted,falling):
                    self._composite(spec,img,x,y,groups,self.size)
        else:
            # 兜底：动态层与静态层交错的包走原路径（原始坐标合成后整组缩放）
            groups={}
            for spec,img,x,y in self._scaled:
                role=spec.get("role",spec["id"])
                if self._role_visible(role,closed,mouth,lifted,falling):
                    self._composite(spec,img,x,y,groups,self.canvas_size)
            groups={name:img.resize(self.size,Image.Resampling.LANCZOS) for name,img in groups.items()}
        fbox=None
        if "figure" in groups:
            fbox=groups["figure"].getchannel("A").point(lambda a:255 if a>=128 else 0).getbbox()
        self._cache[key]=(groups,fbox)
        self._figure_bbox=fbox
        return groups

    @staticmethod
    def _move(img,angle=0.0,dx=0.0,dy=0.0,anchor=(0.5,0.4)):
        if abs(angle)+abs(dx)+abs(dy)<1e-8:
            return img
        return img.rotate(angle,Image.Resampling.BILINEAR,
                          center=(img.width*anchor[0],img.height*anchor[1]),translate=(dx,dy))

    @staticmethod
    def _stretch_body(img,stretch,hinge):
        if abs(stretch-1)<1e-5:
            return img
        # Only the region below the neck stretches; head pixels are never scaled.
        w,h=img.size
        join=round(h*hinge)
        bounds=img.getchannel("A").point(lambda a:255 if a>=128 else 0).getbbox()
        if bounds and bounds[3]>join:
            stretch=min(stretch,(h-2-join)/(bounds[3]-join))
        lower_h=h-join
        if lower_h<=1:
            return img
        # 只变换下半身（源裁剪到下半区），避免整图 MESH 变换
        src_bottom=(h-join)/stretch
        out=img.crop((0,join,w,h)).transform((w,lower_h),Image.Transform.MESH,
            [((0,0,w,lower_h),(0,0,0,src_bottom,w,src_bottom,w,0))],Image.Resampling.BILINEAR)
        result=img.copy()
        result.paste(out,(0,join))
        return result

    @classmethod
    def _bound_sway(cls,box,size,angle,dy,anchor):
        """Bound the swing within the existing transparent window, without scaling."""
        if not box:
            return angle,dy
        w,h=size
        cx,cy=w*anchor[0],h*anchor[1]
        def extents(degrees):
            radians=math.radians(degrees)
            c,s=math.cos(radians),math.sin(radians)
            points=[(cx+c*(x-cx)+s*(y-cy),cy-s*(x-cx)+c*(y-cy))
                    for x in (box[0],box[2]) for y in (box[1],box[3])]
            return min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points)
        def fits(degrees):
            left,top,right,bottom=extents(degrees)
            return left>=2 and right<=w-2 and bottom-top<=h-4
        if not fits(angle):
            low,high=0.0,1.0
            for _ in range(12):
                mid=(low+high)/2
                if fits(angle*mid):low=mid
                else:high=mid
            angle*=low
        left,top,right,bottom=extents(angle)
        dy=max(2-top,min(h-2-bottom,dy))
        return angle,dy

    @classmethod
    def _safe_move(cls,img,angle,dy,anchor):
        if abs(angle)+abs(dy)<1e-8:
            return img            # 无位移直接返回，省一次全图 getbbox
        box=img.getchannel("A").point(lambda a:255 if a>=128 else 0).getbbox()
        if not box:
            return img
        angle,dy=cls._bound_sway(box,img.size,angle,dy,anchor)
        return cls._move(img,angle,dy=dy,anchor=anchor)

    def _sleep_effect(self, pose, color_key):
        effect=Image.new("RGBA",self.size)
        if pose.sleep_fx <= 0:
            return effect
        draw=ImageDraw.Draw(effect)
        anchor=self.pack.manifest.get("sleep_effect_anchor",[self.canvas_size[0]*.74,self.canvas_size[1]*.28])
        for i in range(3):
            age=(pose.sleep_time-i*.65)%2.4
            if pose.sleep_time < i*.65:
                continue
            fade=min(1,age/.3,(2.4-age)/.55)*pose.sleep_fx
            size=max(9,round(self.size[1]*(.037+i*.005)))
            if size not in self._fonts:
                self._fonts[size]=ImageFont.load_default(size=size)
            x=anchor[0]*self.scale+age*self.size[1]*.032
            y=anchor[1]*self.scale-age*self.size[1]*.06
            draw.text((round(x),round(y)),"z" if i==0 else "Z",font=self._fonts[size],
                      fill=(103,123,171,round(245*fade)),
                      stroke_width=max(1,round(self.scale)),stroke_fill=(245,248,255,round(220*fade)))
        if color_key:
            # Windows color-key windows have binary alpha. Dither only the small
            # effect patch to retain fading, without changing the character pixels.
            alpha=effect.getchannel("A")
            box=alpha.getbbox()
            if box:
                patch=alpha.crop(box)
                levels=((0,8,2,10),(12,4,14,6),(3,11,1,9),(15,7,13,5))
                values=patch.tobytes()
                patch.putdata([255 if a>(levels[(i//patch.width)%4][i%4]+.5)*16 else 0
                               for i,a in enumerate(values)])
                alpha.paste(patch,box[:2])
                effect.putalpha(alpha)
        return effect

    def frame(self,height,seconds=0.0,gaze=(0.0,0.0),speaking=False,
              animated=True,eye_open=None,mouth_open=None,color_key=False,pose=None):
        self._resize(max(1,int(height)))
        pose=(pose or Pose(gaze=gaze)) if animated else Pose()
        t=seconds if animated else 0.0
        gx,gy=(max(-1,min(1,n)) for n in pose.gaze)
        blink=min(1.0,abs(t%4.3-3.75)/0.10)
        eye=eye_open if eye_open is not None else pose.eye_open
        eye=(blink if animated else 1.0) if eye is None else eye
        mouth=mouth_open if mouth_open is not None else pose.mouth_open
        mouth=(speaking and animated and math.sin(t*14)>-0.2) if mouth is None else mouth
        lifted=pose.expression=="lifted"
        if lifted or pose.expression=="falling":
            eye=1.0
            mouth=False
        groups=self._groups(eye<0.5,bool(mouth),pose.expression)
        h=self.size[1]
        breath=math.sin(t*1.6)*0.0012*h if animated else 0.0
        head_angle=gx*0.55+pose.head_angle
        names={spec.get("group","body") for spec,_,_,_ in self._scaled}
        has_body="body" in names
        has_head="head" in names
        has_figure="figure" in names
        hinge=self.pack.manifest.get("body_hinge",0.50 if has_figure else 0.42)
        pose_m=replace(pose,head_angle=head_angle,
            head_dx=pose.head_dx+gx*.0015,head_dy=pose.head_dy+gy*.0008)
        # 折叠路径：侧身包全部图层都在 figure 组，把「拉伸 + 整图摆动」并进 mesh 的
        # 一次变换，省掉 _stretch_body / _safe_move 两次整图重采样（约省 15ms）。
        if animated and self.mesh and has_figure and not has_body and not has_head:
            angle=pose.angle
            ty=pose.dy*h          # 呼吸由 mesh 的 chest 处理，这里不再叠加整图呼吸平移
            stretch=pose.body_stretch
            box=self._figure_bbox
            if box and stretch!=1.0:
                join=round(h*hinge)
                if box[3]>join:
                    stretch=min(stretch,(h-2-join)/(box[3]-join))
            angle,ty=self._bound_sway(box,self.size,angle,ty,pose.anchor)
            result=self.mesh.deform(groups["figure"],pose_m,t,
                fold={"stretch":stretch,"hinge":hinge,"angle":angle,"translate":ty,"anchor":pose.anchor})
        else:
            result=Image.new("RGBA",self.size)
            if has_body:
                result.alpha_composite(groups["body"])
            if has_head:
                # Front and back hair stay in the same head transform: no doubled contour.
                result.alpha_composite(self._move(groups["head"],head_angle,
                    gx*0.0015*h+pose.head_dx*h,gy*0.0008*h+pose.head_dy*h,anchor=(0.5,0.40)))
            if has_figure:
                if self.mesh:
                    figure=self.mesh.deform(groups["figure"],pose_m,t)
                    breath=0
                else:
                    figure=self._move(groups["figure"],head_angle*0.4,pose.head_dx*h*0.5,
                                      pose.head_dy*h*0.5,anchor=(0.5,0.50))
                result.alpha_composite(figure)
            result=self._stretch_body(result,pose.body_stretch,hinge)
            if animated:
                result=self._safe_move(result,pose.angle,pose.dy*h-breath,pose.anchor)
        if animated and pose.sleep_fx>0:
            result.alpha_composite(self._sleep_effect(pose,color_key))
        if color_key:
            rgb=Image.new("RGB",result.size,(0,0,1))
            rgb.paste(result.convert("RGB"),mask=result.getchannel("A").point(lambda a:255 if a>=128 else 0))
            return rgb
        return result
