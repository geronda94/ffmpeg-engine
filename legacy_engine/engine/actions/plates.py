from engine.actions.base import BaseActionBuilder
from engine.schema import Action
from engine.actions.utils import expr
import logging

logger = logging.getLogger(__name__)

class PlateBuilder(BaseActionBuilder):
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30) -> str:
        w = a.w or 900
        h = a.h or 250
        x_ovl = expr(a.x or "(W-w)/2")
        y_ovl = expr(a.y or "(H-h)/2")
        box_color = a.boxcolor or "black@0.5"
        plate_out = f"{out_label}_plate"
        
        ops = [f"color=c={box_color}:s={w}x{h}:r={fps},format=rgba"]
        if a.border_width:
            b_color = a.border_color or "white@0.5"
            ops.append(f"drawbox=x=0:y=0:w={w}:h={h}:color={b_color}:t={a.border_width}")
        
        plate_chain = ",".join(ops)
        return f"{plate_chain}[{plate_out}];[{in_label}][{plate_out}]overlay={x_ovl}:{y_ovl}[{out_label}]"
