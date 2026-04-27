from abc import ABC, abstractmethod
from engine.schema import Action

class BaseActionBuilder(ABC):
    @abstractmethod
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30, duration: float = 0) -> str:
        """Построить строку (или цепочку) фильтров для данного экшена."""
        pass

    def simple(self, in_label: str, f_str: str, out_label: str) -> str:
        """Вспомогательный метод для простых фильтров."""
        return f"[{in_label}]{f_str}[{out_label}]"
