"""Local inverse mesh: rigid head, blended neck, delayed hair and anchored limbs."""
import math
from PIL import Image

def smooth(value):
    value=max(0.0,min(1.0,value))
    return value*value*(3-2*value)

class LocalMesh:
    def __init__(self,canvas,rig):
        self.canvas=canvas
        self.rig=rig
        self._grids={}
        self.rows=16          # 网格纵向行数（越大越精细、越慢）
    def deform(self,image,pose,seconds=0,fold=None):
        w,h=image.size
        sx,sy=w/self.canvas[0],h/self.canvas[1]
        rig=self.rig
        pivot=rig["head_pivot"]
        full,still=rig["head_band"]
        a=math.radians(pose.head_angle)
        c,s=math.cos(a),math.sin(a)
        hair=pose.hair_sway
        chest=pose.breath
        leg=pose.leg_sway
        mesh_active=abs(a)+abs(pose.head_dx)+abs(pose.head_dy)+abs(hair)+abs(chest)+abs(leg)>1e-9
        # fold: 把整图摆动(绕 anchor 旋转+平移)与下半身拉伸并进这一次 mesh 变换，
        # 省掉 _safe_move/_stretch_body 两次整图重采样。forward 顺序是 mesh→拉伸→摆动，
        # 所以逆映射要先撤摆动、再撤拉伸、最后才是 mesh 本体。
        if fold is not None:
            f_stretch=fold["stretch"]; f_hinge=fold["hinge"]
            f_angle=fold["angle"]; f_ty=fold["translate"]; f_anchor=fold["anchor"]
            fcx,fcy=w*f_anchor[0],h*f_anchor[1]
            fa=math.radians(f_angle); fca,fsa=math.cos(fa),math.sin(fa)
            f_join=h*f_hinge
            f_active=abs(f_angle)+abs(f_ty)+abs(f_stretch-1)>1e-8
        else:
            f_active=False
        if not mesh_active and not f_active:return image
        # Source vertices are shared by neighbouring quads. No cutout gap can open.
        def source(dx,dy):
            if f_active:
                px=dx-fcx; py=dy-f_ty-fcy
                ox=fcx+fca*px-fsa*py
                oy=fcy+fsa*px+fca*py
                if f_stretch!=1.0 and oy>f_join:
                    oy=f_join+(oy-f_join)/f_stretch
                x,y=ox/sx,oy/sy
            else:
                x,y=dx/sx,dy/sy
            weight=1-smooth((y-full)/(still-full))
            # Inverse rigid rotation of the head about its neck pivot.
            tx=x-pose.head_dx*self.canvas[1]
            ty=y-pose.head_dy*self.canvas[1]
            rx=pivot[0]+c*(tx-pivot[0])-s*(ty-pivot[1])
            ry=pivot[1]+s*(tx-pivot[0])+c*(ty-pivot[1])
            ux=x+(rx-x)*weight
            uy=y+(ry-y)*weight
            for x0,y0,x1,y1,sign in rig["hair_regions"]:
                if x0<x<x1 and y0<y<y1:
                    edge=math.sin(math.pi*(x-x0)/(x1-x0))**2
                    tip=smooth((y-y0)/(y1-y0))
                    # Feather the last edge into the neck/background.
                    fade=1-smooth((y-(y1-25))/25)
                    ux-=hair*sign*edge*tip*fade*8
            bx,by,bw,bh=rig["chest_region"]
            if abs(x-bx)<bw and abs(y-by)<bh:
                weight=(1-((x-bx)/bw)**2)**2*(1-((y-by)/bh)**2)**2
                uy-=chest*2.5*weight
            for lx,ly,lw,lh,sign in rig["leg_regions"]:
                if abs(x-lx)<lw and ly<y<ly+lh:
                    weight=(1-((x-lx)/lw)**2)**2*math.sin(math.pi*(y-ly)/lh)**2
                    ux-=leg*sign*weight*8
            return ux*sx,uy*sy
        size=(w,h)
        rows=self.rows
        if h>480:
            rows=max(10,round(self.rows*480.0/h))   # 大尺寸适当降网格密度，控制每帧开销
        gkey=(size,rows)
        if gkey not in self._grids:
            step=max(7,round(h/rows))
            xs=list(range(0,w,step))+[w]
            ys=list(range(0,h,step))+[h]
            self._grids[gkey]=(xs,ys)
        xs,ys=self._grids[gkey]
        points={(x,y):source(x,y) for y in ys for x in xs}
        mesh=[]
        for j in range(len(ys)-1):
            for i in range(len(xs)-1):
                x0,x1=xs[i:i+2];y0,y1=ys[j:j+2]
                quad=(*points[x0,y0],*points[x0,y1],*points[x1,y1],*points[x1,y0])
                mesh.append(((x0,y0,x1,y1),quad))
        result=image.transform(size,Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
        # Ensure unmoving legs/body retain the exact original samples, including AA.
        # （折叠模式下整图都在动，这个静态回贴不再成立，跳过）
        if not f_active and abs(chest)+abs(leg)<1e-9:
            y_still=min(h,math.ceil(still*sy)+1)
            result.paste(image.crop((0,y_still,w,h)),(0,y_still))
        return result
