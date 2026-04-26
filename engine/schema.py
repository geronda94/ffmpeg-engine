"""Pydantic-модели для валидации JSON-задания монтажа."""
from __future__ import annotations
from typing import Optional, Literal, List
from pydantic import BaseModel


class OutputConfig(BaseModel):
    path: str = "output/result.mp4"
    fps: int = 30
    codec: Literal["auto", "libx264", "h264_qsv", "h264_nvenc", "h264_amf"] = "auto"
    preset: str = "fast"
    crf: int = 23
    duration: Optional[float] = None


class Resource(BaseModel):
    id: str
    source: str
    # lavfi — встроенный генератор FFmpeg (для тестов без файлов)
    type: Literal["video", "audio", "image", "lavfi"]


class Action(BaseModel):
    type: str
    filter: Optional[str] = None
    expr: Optional[str] = None # Для математических выражений (например, зум)
    # scale / scale_and_crop
    w: Optional[int] = None
    h: Optional[int] = None
    # blur
    sigma: Optional[int] = None
    # drawtext
    text: Optional[str] = None
    fontsize: Optional[int] = None
    fontcolor: Optional[str] = None
    fontfile: Optional[str] = None   # переопределить шрифт для этого action
    x: Optional[str] = None
    y: Optional[str] = None
    # zoompan
    zoom: Optional[float] = None
    smooth: bool = True       # Устранение дрожания через апскейл (полезно для фото)
    # fade
    duration: Optional[float] = None
    start_time: Optional[float] = None
    alpha: bool = False       # True для кроссфейда (уводит в прозрачность)
    color: str = "black"      # В какой цвет уводить (если alpha=False)


class Trim(BaseModel):
    start: float = 0.0
    end: Optional[float] = None


class PipelineStep(BaseModel):
    id: str
    input: str  # resource id
    trim: Optional[Trim] = None
    preset: Optional[str] = None  # Ссылка на пресет
    actions: List[Action] = []


class Position(BaseModel):
    x: str = "(W-w)/2"
    y: str = "(H-h)/2"


class Layer(BaseModel):
    source: str  # step id или resource id
    pos: Position = Position()


class ComposeRoot(BaseModel):
    base: str          # id первого (базового) pipeline step
    layers: List[Layer] = []


class AudioConfig(BaseModel):
    source: str        # resource id
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0


class Task(BaseModel):
    version: str = "2.0"
    output: OutputConfig = OutputConfig()
    resources: List[Resource]
    pipeline: List[PipelineStep]
    compose: ComposeRoot
    audio: Optional[AudioConfig] = None
    presets: dict[str, List[Action]] = {} # Новая секция пресетов
