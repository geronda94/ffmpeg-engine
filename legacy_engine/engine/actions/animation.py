from engine.actions.base import BaseActionBuilder
from engine.schema import Action
from engine.actions.utils import expr

class AnimationBuilder(BaseActionBuilder):
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30, duration: float = 0) -> str:
        t = a.type
        if t == "zoom":
            z_val = a.zoom or 1.1
            z_expr = a.expr or f"min(1+on*{(z_val-1)/(fps*10):.5f},{z_val})"
            w_out = a.w or 1080
            h_out = a.h or 1920
            if a.smooth:
                w_hd, h_hd = w_out * 4, h_out * 4
                f = (f"scale={w_hd}:{h_hd}:flags=bicubic,format=yuv420p,"
                     f"zoompan=z='{z_expr}':s={w_hd}x{h_hd}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:fps={fps},"
                     f"scale={w_out}:{h_out}:flags=bicubic")
            else:
                f = f"zoompan=z='{z_expr}':s={w_out}x{h_out}:x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:fps={fps}"
            return self.simple(in_label, f, out_label)

        if t == "zoom_blur":
            z_val = a.zoom or 1.2
            z_expr = a.expr or f"min(1+on*{(z_val-1)/(fps*10):.5f}, {z_val})"
            b_val = a.blur or 5
            f = f"zoompan=z='{z_expr}':s='iwxih':d=1:fps={fps},boxblur={b_val}:{b_val}"
            return self.simple(in_label, f, out_label)

        if t == "dissolve":
            st = a.start_time or 0
            d = a.duration or 1.0
            f = f"format=rgba,fade=t=in:st={st}:d={d}:alpha=1"
            return self.simple(in_label, f, out_label)

        if t in ("fade_in", "fade_out"):
            dur = a.duration or 1.0
            type_tag = "in" if t == "fade_in" else "out"
            
            # Если это fade_out и старт не задан, вычисляем его от конца потока
            if t == "fade_out" and not a.start_time:
                st = max(0, duration - dur)
            else:
                st = a.start_time or 0
                
            f = f"fade=t={type_tag}:st={st}:d={dur}"
            if a.alpha: 
                f = f"format=rgba,{f}:alpha=1"
            else: 
                f += f":color={a.color or 'black'}"
            return self.simple(in_label, f, out_label)
            
        return self.simple(in_label, "copy", out_label)
