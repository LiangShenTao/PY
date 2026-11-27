# -*- coding: utf-8 -*-
"""模板匹配：多尺度查找 + ROI 支持，返回的坐标已经换算回整张截图。"""

import os
from dataclasses import dataclass

import cv2
import numpy as np

import config


@dataclass
class Match:
    x: int
    y: int
    w: int
    h: int
    score: float
    scale: float

    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2


def roi_pixels(roi, shape):
    """把 ROI 统一成像素 (x, y, w, h)。

    ROI 可以写成像素 (200, 300, 100, 80)，
    也可以写成 0~1 的比例 (0.0, 0.12, 0.2, 0.1)（推荐，能适配不同分辨率）。
    """
    if not roi:
        return None
    h_img, w_img = shape[:2]
    x, y, w, h = roi
    if all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in roi):
        return (int(x * w_img), int(y * h_img), int(w * w_img), int(h * h_img))
    return (int(x), int(y), int(w), int(h))


def load_template(name):
    path = name if os.path.isabs(name) else os.path.join(config.TEMPLATE_DIR, name)
    image = cv2.imread(path)
    if image is None:
        raise FileNotFoundError(f"模板不存在或无法读取: {path}")
    return image


def exists(name):
    """模板文件是否存在（用于任务在模板未采集时安全跳过）。"""
    path = name if os.path.isabs(name) else os.path.join(config.TEMPLATE_DIR, name)
    return os.path.isfile(path)


def _scale_list(min_scale, max_scale, steps):
    if min_scale == max_scale or steps <= 1:
        return [float(min_scale)]
    return [float(s) for s in np.linspace(min_scale, max_scale, steps)]


def _search_region(image, roi):
    """按 ROI 裁剪搜索区域，返回 (search, offset_x, offset_y)。"""
    search = image
    offset_x = offset_y = 0
    box = roi_pixels(roi, image.shape)
    if box:
        x, y, w, h = box
        search = image[y:y + h, x:x + w]
        offset_x, offset_y = x, y
    return search, offset_x, offset_y


def match(image, template_name, roi=None, threshold=None, min_scale=None,
          max_scale=None, steps=None):
    """在大图中查找模板，返回 Match 或 None。"""
    threshold = config.THRESHOLD if threshold is None else threshold
    min_scale = config.MIN_SCALE if min_scale is None else min_scale
    max_scale = config.MAX_SCALE if max_scale is None else max_scale
    steps = config.STEPS if steps is None else steps

    template = load_template(template_name)

    search, offset_x, offset_y = _search_region(image, roi)
    if search.size == 0:
        return None

    search = cv2.GaussianBlur(search, (3, 3), 0)
    template = cv2.GaussianBlur(template, (3, 3), 0)
    tpl_h, tpl_w = template.shape[:2]
    search_h, search_w = search.shape[:2]

    best = None
    best_score = -1.0
    for scale in _scale_list(min_scale, max_scale, steps):
        w = int(round(tpl_w * scale))
        h = int(round(tpl_h * scale))
        if w < 2 or h < 2 or w > search_w or h > search_h:
            continue
        resized = cv2.resize(template, (w, h), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        if score > best_score:
            best_score = score
            best = Match(loc[0] + offset_x, loc[1] + offset_y, w, h, score, scale)

    if best is None or best.score < threshold:
        return None
    return best


def match_all(image, template_name, roi=None, threshold=None, min_scale=None,
              max_scale=None, steps=None, max_results=20, min_distance=40):
    """查找模板的所有实例（按分数排序 + 距离去重）。"""
    threshold = config.THRESHOLD if threshold is None else threshold
    min_scale = config.MIN_SCALE if min_scale is None else min_scale
    max_scale = config.MAX_SCALE if max_scale is None else max_scale
    steps = config.STEPS if steps is None else steps

    template = load_template(template_name)
    search, offset_x, offset_y = _search_region(image, roi)
    if search.size == 0:
        return []

    search = cv2.GaussianBlur(search, (3, 3), 0)
    template = cv2.GaussianBlur(template, (3, 3), 0)
    tpl_h, tpl_w = template.shape[:2]
    search_h, search_w = search.shape[:2]

    candidates = []
    for scale in _scale_list(min_scale, max_scale, steps):
        w = int(round(tpl_w * scale))
        h = int(round(tpl_h * scale))
        if w < 2 or h < 2 or w > search_w or h > search_h:
            continue
        resized = cv2.resize(template, (w, h), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= threshold)
        for x, y in zip(xs, ys):
            candidates.append(
                Match(int(x) + offset_x, int(y) + offset_y, w, h,
                      float(result[y, x]), scale))

    candidates.sort(key=lambda m: m.score, reverse=True)
    picked = []
    for cand in candidates:
        cx, cy = cand.center
        if all((cx - p.center[0]) ** 2 + (cy - p.center[1]) ** 2
               >= min_distance ** 2 for p in picked):
            picked.append(cand)
            if len(picked) >= max_results:
                break
    return picked
