from engine.schema import Action

def build_action(a: Action, in_label: str, out_label: str, fps: int = 30, duration: float = 0) -> str:
    from engine.actions.factory import get_builder
    builder = get_builder(a.type)
    return builder.build(a, in_label, out_label, fps, duration=duration)
