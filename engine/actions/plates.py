from engine.actions.base import BaseActionBuilder
from engine.schema import Action
from engine.actions.utils import expr

class PlateBuilder(BaseActionBuilder):
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30) -> str:
        w = a.w or 400
        h = a.h or 100
        x = expr(a.x or "(W-w)/2")
        y = expr(a.y or "(H-h)/2")
        
        l_orig = f"{out_label}_orig"
        l_blur = f"{out_label}_blur"
        l_mask = f"{out_label}_mask"
        l_final_box = f"{out_label}_box"

        chain = [f"[{in_label}]split[ {l_orig} ][ {l_blur} ]"]

        # Эффект стекла
        proc = f"[{l_blur}]crop={w}:{h}:{x}:{y}"
        if a.blur:
            proc += f",boxblur={a.blur}:{a.blur}"
        
        # Наложение цвета
        color = a.boxcolor or "black@0.5"
        proc += f",drawbox=x=0:y=0:w={w}:h={h}:color={color}:t=fill"
        
        # Рамка
        if a.border_width:
            b_color = a.border_color or "white"
            proc += f",drawbox=x=0:y=0:w={w}:h={h}:color={b_color}:t={a.border_width}"
        
        proc += f"[{l_mask}]"
        chain.append(proc)

        # Скругление
        if a.radius:
            r = a.radius
            geq_expr = (
                f"if("
                f" (x<{r} && y<{r} && (pow({r}-x,2)+pow({r}-y,2))>pow({r},2)) || "
                f" (x>{w}-{r} && y<{r} && (pow(x-({w}-{r}),2)+pow({r}-y,2))>pow({r},2)) || "
                f" (x<{r} && y>{h}-{r} && (pow({r}-x,2)+pow(y-({h}-{r}),2))>pow({r},2)) || "
                f" (x>{w}-{r} && y>{h}-{r} && (pow(x-({w}-{r}),2)+pow(y-({h}-{r}),2))>pow({r},2))"
                f", 0, 255)"
            )
            chain.append(f"[{l_mask}]format=rgba,geq=a='{geq_expr}'[{l_final_box}]")
        else:
            chain.append(f"[{l_mask}]copy[{l_final_box}]")

        # Финал
        chain.append(f"[{l_orig}][{l_final_box}]overlay={x}:{y}[{out_label}]")
        
        return ";".join(chain)
