# -*- coding: utf-8 -*-
"""Robot：把“设备层 + 视觉层”组合成任务可以直接使用的上下文。"""

import random
import time

import cv2

import config
from device.adb import Adb
from vision import scene as scene_mod
from vision import template as tpl


class Robot:
    def __init__(self, adb=None, image_path=None, dry_run=False):
        self.adb = adb or Adb()
        self.dry_run = dry_run
        self._image = None
        self._static_image = None
        # 面板“停止”按钮会置位这个事件，长任务要在循环里主动检查
        self.stop_event = None
        if image_path:
            self._static_image = cv2.imread(image_path)
            if self._static_image is None:
                raise FileNotFoundError(f"读不到图片: {image_path}")

    def stopped(self):
        """用户是否点了“停止”。"""
        return self.stop_event is not None and self.stop_event.is_set()

    # ------------------------------------------------------------ 截图
    def shot(self):
        if self._static_image is not None:
            self._image = self._static_image.copy()
            return self._image
        image = cv2.imread(self.adb.screencap())
        if image is None:
            raise RuntimeError("截图读取失败，请检查 adb 是否可用")
        self._image = image
        return image

    def image(self, refresh=True):
        if self._static_image is not None:
            return self._static_image
        if refresh or self._image is None:
            return self.shot()
        return self._image

    # ------------------------------------------------------------ 视觉
    def find(self, name, roi=None, threshold=None, min_scale=None,
             max_scale=None, steps=None):
        return tpl.match(self.image(refresh=True), name, roi=roi,
                         threshold=threshold, min_scale=min_scale,
                         max_scale=max_scale, steps=steps)

    def scene(self):
        return scene_mod.detect(self.image(refresh=True))

    # ------------------------------------------------------------ 输入
    def tap(self, x, y):
        jitter_x = random.randint(-config.TAP_JITTER, config.TAP_JITTER)
        jitter_y = random.randint(-config.TAP_JITTER, config.TAP_JITTER)
        x, y = int(x + jitter_x), int(y + jitter_y)
        if self.dry_run:
            print(f"    [dry-run] tap ({x}, {y})")
        else:
            self.adb.tap(x, y)
        time.sleep(random.uniform(config.MIN_DELAY, config.MAX_DELAY))

    def tap_template(self, name, roi=None, click_count=1, threshold=None,
                     min_scale=None, max_scale=None, steps=None):
        found = self.find(name, roi=roi, threshold=threshold,
                          min_scale=min_scale, max_scale=max_scale, steps=steps)
        if not found:
            print(f"    未找到 {name}")
            return False
        cx, cy = found.center
        print(f"    命中 {name} @({cx}, {cy}) 置信度 {found.score:.2f}")
        for _ in range(click_count):
            self.tap(cx, cy)
            time.sleep(config.TAP_INTERVAL)
        return True

    def swipe(self, start, end, duration=config.SWIPE_DURATION):
        x1, y1 = self._scale_point(*start)
        x2, y2 = self._scale_point(*end)
        if self.dry_run:
            print(f"    [dry-run] swipe ({x1}, {y1}) -> ({x2}, {y2})")
        else:
            self.adb.swipe(x1, y1, x2, y2, duration)
        time.sleep(0.5)

    def _scale_point(self, x, y):
        image = self.image(refresh=False)
        h, w = image.shape[:2]
        ref_w, ref_h = config.REF_SIZE
        return int(x * w / ref_w), int(y * h / ref_h)
