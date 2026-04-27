from engine.actions.base import BaseActionBuilder
from engine.schema import Action

class GeometryBuilder(BaseActionBuilder):
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30, duration: float = 0, **kwargs) -> str:
        t = a.type
        if t == "scale_and_crop":
            return self.simple(in_label, f"scale={a.w}:{a.h}:force_original_aspect_ratio=increase,crop={a.w}:{a.h}", out_label)
        if t == "scale":
            return self.simple(in_label, f"scale={a.w}:{a.h}", out_label)
        if t == "scale_contain":
            return self.simple(in_label, f"scale={a.w}:{a.h}:force_original_aspect_ratio=decrease", out_label)
        if t == "setsar":
            return self.simple(in_label, "setsar=1", out_label)
        return self.simple(in_label, "copy", out_label)
