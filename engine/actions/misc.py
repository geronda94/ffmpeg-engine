from engine.actions.base import BaseActionBuilder
from engine.schema import Action

class MiscBuilder(BaseActionBuilder):
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30) -> str:
        t = a.type
        if t == "blur":
            s = a.sigma or 5
            return self.simple(in_label, f"boxblur={s}:{s}", out_label)
        if t == "custom":
            return self.simple(in_label, a.filter or "copy", out_label)
        return self.simple(in_label, "copy", out_label)
