# -*- coding: utf-8 -*-
"""从已知数值的截图里生成资源栏数字模板（0-9）。

用法:
    py -3.13 tools/build_digit_templates.py

每个数字会按多个亮度阈值各存一份变体（modle/digits/<数字>_<序号>.png），
识别时所有变体一起参与匹配，避免资源条背景忽明忽暗导致掉字。
换 UI 字体后，重新截几张主页图并更新下面的 SAMPLES 即可。
"""

import os

import cv2
import numpy as np

ROWS = [(38, 74), (112, 148), (186, 222), (262, 298)]
X0, X1 = 1520, 1900
THRESHOLDS = [(160, 140), (180, 160), (200, 180), (220, 200),
              (230, 210), (240, 220)]
OUT_DIR = os.path.join('modle', 'digits')
DIGIT_SIZE = 32

# 截图 -> 四行资源的真实数值（金币/圣水/黑油/宝石）
SAMPLES = {
    'screenshots/current.png': ['5825081', '8233355', '129139', '2842'],
    'screenshots/16_back1.png': ['3969718', '3539567', '105070', '2842'],
    'screenshots/after_collect.png': ['5837772', '8249997', '129196', '2842'],
}


def make_mask(image, high, low):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return ((image.min(axis=2) > low) & (gray > high)).astype(np.uint8) * 255


def glyph_boxes(mask, band_shape):
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    min_h = max(8, int(band_shape[0] * 0.5))
    boxes = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if h >= min_h and 2 <= w <= h and area >= 20:
            boxes.append((int(x), int(y), int(w), int(h)))
    boxes.sort(key=lambda b: b[0])
    return boxes


def normalize(crop):
    h, w = crop.shape
    new_w = max(1, int(round(w * DIGIT_SIZE / h)))
    resized = cv2.resize(crop, (new_w, DIGIT_SIZE),
                         interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((DIGIT_SIZE, DIGIT_SIZE), np.uint8)
    x = (DIGIT_SIZE - new_w) // 2
    canvas[:, x:x + new_w] = resized
    return canvas


def main():
    samples = {}
    for path, values in SAMPLES.items():
        image = cv2.imread(path)
        if image is None:
            print(f'跳过（读不到）: {path}')
            continue
        for (y0, y1), text in zip(ROWS, values):
            for high, low in THRESHOLDS:
                band = image[y0:y1, X0:X1]
                mask = make_mask(band, high, low)
                boxes = glyph_boxes(mask, band.shape)
                if len(boxes) > len(text):
                    boxes = boxes[-len(text):]
                if len(boxes) != len(text):
                    continue
                for (x, y, w, h), char in zip(boxes, text):
                    glyph = normalize(mask[y:y + h, x:x + w])
                    key = (char, glyph.tobytes())
                    samples.setdefault(char, {})[key] = glyph

    os.makedirs(OUT_DIR, exist_ok=True)
    for old in os.listdir(OUT_DIR):
        if old.endswith('.png'):
            os.remove(os.path.join(OUT_DIR, old))

    for char, unique in sorted(samples.items()):
        for index, glyph in enumerate(unique.values()):
            name = f'{char}.png' if index == 0 else f'{char}_{index}.png'
            cv2.imwrite(os.path.join(OUT_DIR, name), glyph)
        print(f'数字 {char}: {len(unique)} 个变体')


if __name__ == '__main__':
    main()
