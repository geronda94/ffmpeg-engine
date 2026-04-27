from engine.actions.base import BaseActionBuilder
from engine.schema import Action
from engine.actions.utils import expr
import logging
import re

logger = logging.getLogger(__name__)

class MiscBuilder(BaseActionBuilder):
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30, duration: float = 0) -> str:
        t = a.type
        if t == "blur":
            s = a.sigma or 5
            return self.simple(in_label, f"boxblur={s}:{s}", out_label)
        if t == "custom":
            return self.simple(in_label, a.filter or "copy", out_label)
        return self.simple(in_label, "copy", out_label)

class RegionBlurBuilder(BaseActionBuilder):
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30, duration: float = 0) -> str:
        w = a.w or 900
        h = a.h or 250
        x_raw = expr(a.x or "(W-w)/2")
        y_raw = expr(a.y or "(H-h)/2")
        sigma = a.sigma or 40
        # radius здесь используется как ширина растушевки (feathering)
        feather = a.radius or 50 

        # Мапинг переменных для фильтра crop (iw/ih - вход, ow/oh - выход)
        crop_map = {"W": "iw", "H": "ih", "w": "ow", "h": "oh"}
        x_crop = x_raw
        y_crop = y_raw
        for k, v in crop_map.items():
            x_crop = re.sub(rf"\b{k}\b", v, x_crop)
            y_crop = re.sub(rf"\b{k}\b", v, y_crop)

        # Поддержка синхронизации появления (enable)
        enable_str = ""
        if a.start is not None and a.end is not None:
            enable_str = f":enable='between(t,{a.start},{a.end})'"
        elif a.start is not None:
            enable_str = f":enable='gte(t,{a.start})'"
        elif a.end is not None:
            enable_str = f":enable='lte(t,{a.end})'"

        l_main = f"{out_label}_main"
        l_crop = f"{out_label}_crop"
        l_blur = f"{out_label}_blur"
        l_mask = f"{out_label}_mask"
        l_feathered = f"{out_label}_feath"

        chain = []

        # 1. Подготовка: Разделяем поток и вырезаем кусок для размытия
        chain.append(f"[{in_label}]split[{l_main}][{l_crop}]")
        
        # 2. Основное размытие
        chain.append(f"[{l_crop}]crop={w}:{h}:{x_crop}:{y_crop},boxblur={sigma}:{sigma}[{l_blur}]")

        # 3. Генерация Feathered-маски (Градиент через размытие прямоугольника)
        inner_x = feather
        inner_y = feather
        inner_w = f"{w}-2*{feather}"
        inner_h = f"{h}-2*{feather}"
        
        mask_pipe = (
            f"color=c=black:s={w}x{h}:r={fps},format=gray,"
            f"drawbox=x={inner_x}:y={inner_y}:w={inner_w}:h={inner_h}:color=white:t=fill,"
            f"boxblur={feather}:{feather}"
        )
        chain.append(f"{mask_pipe}[{l_mask}]")

        # 4. Сборка: Альфа-слияние размытия с маской и наложение на оригинал
        chain.append(f"[{l_blur}][{l_mask}]alphamerge[{l_feathered}]")
        chain.append(f"[{l_main}][{l_feathered}]overlay={x_raw}:{y_raw}{enable_str}[{out_label}]")

        return ";".join(chain)
