from engine.actions.base import BaseActionBuilder
from engine.schema import Action
from engine.actions.utils import resolve_fontfile, sanitize_text, expr

class TextBuilder(BaseActionBuilder):
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30) -> str:
        text = sanitize_text(a.text or "")
        fontfile = resolve_fontfile(a.fontfile)
        x_val = expr(a.x or "(w-text_w)/2")
        y_val = expr(a.y or "(h-text_h)/2")
        size = a.fontsize or 60
        color = a.fontcolor or "white"
        
        base = f"drawtext=fontfile='{fontfile}':text='{text}':fontsize={size}:fontcolor={color}:x={x_val}:y={y_val}"
        if a.box:
            base += f":box=1:boxcolor={a.boxcolor}:boxborderw={a.boxborderw}"
            
        return self.simple(in_label, base, out_label)
