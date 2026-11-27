# -*- coding: utf-8 -*-
"""资源栏数字识别。

不用第三方 OCR：游戏内数字字体固定，直接用 modle/digits/0~9.png
做字符模板匹配，速度快且没有额外依赖。
"""

import os
from functools import lru_cache

import cv2
import numpy as np

import config

DIGIT_DIR = os.path.join(config.TEMPLATE_DIR, 'digits')
DIGIT_SIZE = 32

# 资源栏 ROI（参考分辨率 1920x1080 下的像素坐标）
ROW_ROIS = {
    'gold': (1520, 38, 1900, 74),
    'elixir': (1520, 112, 1900, 148),
    'dark': (1520, 186, 1900, 222),
    'gems': (1520, 262, 1900, 298),
}


@lru_cache(maxsize=1)
def _templates():
    """加载 modle/digits 下所有数字模板变体，文件名首字符即数字。"""
    templates = []
    if not os.path.isdir(DIGIT_DIR):
        return templates
    for name in sorted(os.listdir(DIGIT_DIR)):
        if not name.endswith('.png') or not name[0].isdigit():
            continue
        image = cv2.imread(os.path.join(DIGIT_DIR, name),
                           cv2.IMREAD_GRAYSCALE)
        if image is not None:
            templates.append((name[0], image))
    return templates


def available():
    return {t[0] for t in _templates()} >= set('0123456789')


def _glyph_boxes(mask, band_shape):
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    min_h = max(8, int(band_shape[0] * 0.5))
    boxes = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        # 数字宽度不会超过高度；“+”号、图标会被过滤掉
        if h >= min_h and 2 <= w <= h and area >= 20:
            boxes.append((int(x), int(y), int(w), int(h)))
    boxes.sort(key=lambda b: b[0])
    return boxes


def _normalize(crop):
    h, w = crop.shape
    new_w = max(1, int(round(w * DIGIT_SIZE / h)))
    resized = cv2.resize(crop, (new_w, DIGIT_SIZE),
                         interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((DIGIT_SIZE, DIGIT_SIZE), np.uint8)
    x = (DIGIT_SIZE - new_w) // 2
    canvas[:, x:x + new_w] = resized
    return canvas


def _classify(glyph, templates, min_score, min_margin):
    """返回 (字符, 分数)；置信度不够时返回 (None, 分数)。"""
    # 同一数字有多个模板变体，取每个数字的最高分再比较
    best_by_digit = {}
    for digit, template in templates:
        score = float(cv2.matchTemplate(glyph, template,
                                        cv2.TM_CCOEFF_NORMED)[0][0])
        if score > best_by_digit.get(digit, -1.0):
            best_by_digit[digit] = score
    ranked = sorted(best_by_digit.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return None, -1.0
    best, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else -1.0
    if best_score < min_score or best_score - second_score < min_margin:
        return None, best_score
    return best, best_score


def _scale_roi(roi, shape):
    sx = shape[1] / config.REF_SIZE[0]
    sy = shape[0] / config.REF_SIZE[1]
    x0, y0, x1, y1 = roi
    return int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy)


# 资源条背景明暗差别很大，按多组阈值各试一遍，取置信度最高的读数
THRESHOLDS = ((220, 200), (230, 210), (240, 220), (210, 190),
              (200, 180), (180, 160), (160, 140))


def read_number(image, roi, min_score=0.80, min_margin=0.08):
    """读 ROI 里的数字，失败返回 None。"""
    templates = _templates()
    if not templates:
        return None
    x0, y0, x1, y1 = _scale_roi(roi, image.shape)
    band = image[y0:y1, x0:x1]
    if band.size == 0:
        return None

    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    low_channel = band.min(axis=2)
    best_value, best_conf = None, -1.0
    for high, low in THRESHOLDS:
        mask = ((low_channel > low) & (gray > high)).astype(np.uint8) * 255
        boxes = _glyph_boxes(mask, band.shape)
        if not 1 <= len(boxes) <= 9:
            continue

        chars = []
        scores = []
        for x, y, w, h in boxes:
            glyph = _normalize(mask[y:y + h, x:x + w])
            char, score = _classify(glyph, templates, min_score, min_margin)
            if char is None:
                break
            chars.append(char)
            scores.append(score)
        else:
            value = int(''.join(chars))
            confidence = sum(scores) / len(scores)
            if confidence > best_conf:
                best_value, best_conf = value, confidence
    return best_value


def read_counter(image, roi, min_score=0.8, min_margin=0.08):
    """读兵种栏上 “x16” 这类数量标签，忽略前面的 x。失败返回 None。"""
    templates = _templates()
    if not templates:
        return None
    x0, y0, x1, y1 = _scale_roi(roi, image.shape)
    band = image[y0:y1, x0:x1]
    if band.size == 0:
        return None

    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    low_channel = band.min(axis=2)
    best_value, best_conf = None, -1.0
    for high, low in THRESHOLDS:
        mask = ((low_channel > low) & (gray > high)).astype(np.uint8) * 255
        boxes = _glyph_boxes(mask, band.shape)
        # 跳过开头的 “x”（宽高接近），剩下的才是数字
        if boxes and boxes[0][2] >= boxes[0][3] * 0.7:
            boxes = boxes[1:]
        if not 1 <= len(boxes) <= 3:
            continue
        chars, scores = [], []
        for x, y, w, h in boxes:
            glyph = _normalize(mask[y:y + h, x:x + w])
            char, score = _classify(glyph, templates, min_score, min_margin)
            if char is None:
                break
            chars.append(char)
            scores.append(score)
        else:
            value = int(''.join(chars))
            confidence = sum(scores) / len(scores)
            if confidence > best_conf:
                best_value, best_conf = value, confidence
    return best_value


def read_percent(image, roi):
    """读结算界面“摧毁率”那种绿色百分比数字，失败返回 None。"""
    templates = _templates()
    if not templates:
        return None
    x0, y0, x1, y1 = _scale_roi(roi, image.shape)
    band = image[y0:y1, x0:x1]
    if band.size == 0:
        return None

    blue, green, red = cv2.split(band)
    mask = ((green > 140) &
            (green.astype(int) - np.maximum(red, blue) > 35))
    mask = mask.astype(np.uint8) * 255
    boxes = _glyph_boxes(mask, band.shape)
    if not 1 <= len(boxes) <= 4:
        return None
    chars = []
    for x, y, w, h in boxes:
        glyph = _normalize(mask[y:y + h, x:x + w])
        char, _ = _classify(glyph, templates, 0.78, 0.06)
        if char is None:
            break  # 后面的“%”符号识别不出来，直接结束
        chars.append(char)
    if not chars:
        return None
    return int(''.join(chars))


def read_resources(image):
    """读右上角金币/圣水/黑油/宝石，读不到的项为 None。"""
    return {name: read_number(image, roi) for name, roi in ROW_ROIS.items()}


def format_resources(resources):
    def fmt(value):
        return '未知' if value is None else f'{value:,}'

    return (f"金币 {fmt(resources.get('gold'))}  "
            f"圣水 {fmt(resources.get('elixir'))}  "
            f"黑油 {fmt(resources.get('dark'))}  "
            f"宝石 {fmt(resources.get('gems'))}")
