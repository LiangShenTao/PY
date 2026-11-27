# -*- coding: utf-8 -*-
"""滑动手势。坐标定义在 config.py 里，按参考分辨率等比缩放。"""

import time

import config


def _swipe(robot, points, duration):
    x1, y1, x2, y2 = points
    robot.swipe((x1, y1), (x2, y2), duration)


def swipe_up(robot, duration=config.SWIPE_DURATION):
    _swipe(robot, config.SWIPE_UP, duration)


def swipe_down(robot, duration=config.SWIPE_DURATION):
    _swipe(robot, config.SWIPE_DOWN, duration)


def swipe_left(robot, duration=config.SWIPE_DURATION):
    _swipe(robot, config.SWIPE_LEFT, duration)


def swipe_right(robot, duration=config.SWIPE_DURATION):
    _swipe(robot, config.SWIPE_RIGHT, duration)


def multi_touch_zoom(robot, start1, end1, start2, end2, steps=10,
                     duration=200, device=None):
    """双指捏合缩放（需要 root，直接写输入设备）。

    缩小：两个手指向中心收拢；放大：两个手指向外张开。
    """
    device = device or config.TOUCH_DEVICE
    adb = robot.adb
    sx1, sy1 = robot._scale_point(*start1)
    ex1, ey1 = robot._scale_point(*end1)
    sx2, sy2 = robot._scale_point(*start2)
    ex2, ey2 = robot._scale_point(*end2)

    def send(etype, code, value):
        adb.sendevent(device, etype, code, value)

    # 两指按下
    send(3, 57, 0)          # ABS_MT_TRACKING_ID
    send(3, 53, sx1)        # ABS_MT_POSITION_X
    send(3, 54, sy1)        # ABS_MT_POSITION_Y
    send(0, 0, 0)
    send(3, 57, 1)
    send(3, 53, sx2)
    send(3, 54, sy2)
    send(0, 0, 0)

    # 两指移动
    for step in range(steps):
        ratio = step / steps
        send(3, 53, int(sx1 + (ex1 - sx1) * ratio))
        send(3, 54, int(sy1 + (ey1 - sy1) * ratio))
        send(3, 57, 0)
        send(0, 0, 0)
        send(3, 53, int(sx2 + (ex2 - sx2) * ratio))
        send(3, 54, int(sy2 + (ey2 - sy2) * ratio))
        send(3, 57, 1)
        send(0, 0, 0)
        time.sleep(duration / 1000 / steps)

    # 两指抬起
    send(3, 57, -1)
    send(0, 0, 0)
    send(3, 57, -1)
    send(0, 0, 0)


def pinch_in(robot, duration=500):
    """缩小画面。"""
    multi_touch_zoom(robot,
                     start1=(300, 800), end1=(500, 500),
                     start2=(700, 800), end2=(500, 500),
                     duration=duration)


def pinch_out(robot, duration=500):
    """放大画面。"""
    multi_touch_zoom(robot,
                     start1=(500, 500), end1=(300, 800),
                     start2=(500, 500), end2=(700, 800),
                     duration=duration)
