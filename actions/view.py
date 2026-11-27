# -*- coding: utf-8 -*-
"""视角控制：双指缩放（sendevent 多点触控）与视角归位。"""

import re
import time

import config
from actions.common import ensure_home

ABS_MT_SLOT = 47
ABS_MT_POSITION_X = 53
ABS_MT_POSITION_Y = 54
ABS_MT_TRACKING_ID = 57
ABS_MT_PRESSURE = 58
BTN_TOUCH = 330
EV_SYN = 0
EV_KEY = 1
EV_ABS = 3


def detect_touch_device(adb):
    """从 getevent -pl 里找支持多点触控的设备路径。"""
    try:
        out = adb.run('shell', 'getevent', '-pl',
                      timeout=15).stdout.decode('utf-8', 'ignore')
    except Exception:
        return config.TOUCH_DEVICE
    for block in re.split(r'add device \d+:', out):
        if 'ABS_MT_POSITION_X' in block and 'ABS_MT_SLOT' in block:
            found = re.search(r'/dev/input/event\d+', block)
            if found:
                return found.group(0)
    return config.TOUCH_DEVICE


def _pinch_script(device, p1, p2, q1, q2, steps=10):
    """生成一段 sendevent 脚本：两根手指从 p1/p2 移到 q1/q2。"""
    events = []

    def send(kind, code, value):
        events.append(f'sendevent {device} {kind} {code} {int(value)}')

    send(EV_KEY, BTN_TOUCH, 1)
    send(EV_ABS, ABS_MT_SLOT, 0)
    send(EV_ABS, ABS_MT_TRACKING_ID, 100)
    send(EV_ABS, ABS_MT_POSITION_X, p1[0])
    send(EV_ABS, ABS_MT_POSITION_Y, p1[1])
    send(EV_ABS, ABS_MT_PRESSURE, 1)
    send(EV_ABS, ABS_MT_SLOT, 1)
    send(EV_ABS, ABS_MT_TRACKING_ID, 101)
    send(EV_ABS, ABS_MT_POSITION_X, p2[0])
    send(EV_ABS, ABS_MT_POSITION_Y, p2[1])
    send(EV_ABS, ABS_MT_PRESSURE, 1)
    send(EV_SYN, 0, 0)

    for i in range(1, steps + 1):
        ratio = i / steps
        x1 = int(p1[0] + (q1[0] - p1[0]) * ratio)
        y1 = int(p1[1] + (q1[1] - p1[1]) * ratio)
        x2 = int(p2[0] + (q2[0] - p2[0]) * ratio)
        y2 = int(p2[1] + (q2[1] - p2[1]) * ratio)
        send(EV_ABS, ABS_MT_SLOT, 0)
        send(EV_ABS, ABS_MT_POSITION_X, x1)
        send(EV_ABS, ABS_MT_POSITION_Y, y1)
        send(EV_ABS, ABS_MT_SLOT, 1)
        send(EV_ABS, ABS_MT_POSITION_X, x2)
        send(EV_ABS, ABS_MT_POSITION_Y, y2)
        send(EV_SYN, 0, 0)

    send(EV_ABS, ABS_MT_SLOT, 0)
    send(EV_ABS, ABS_MT_TRACKING_ID, -1)
    send(EV_ABS, ABS_MT_SLOT, 1)
    send(EV_ABS, ABS_MT_TRACKING_ID, -1)
    send(EV_KEY, BTN_TOUCH, 0)
    send(EV_SYN, 0, 0)
    return '; '.join(events)


def pinch(robot, center=(960, 540), start_gap=400, end_gap=140, steps=10,
          device=None):
    """双指捏合：两根手指水平收拢（end_gap 小于 start_gap 即缩小视角）。"""
    device = device or detect_touch_device(robot.adb)
    cx, cy = center
    p1 = robot._scale_point(cx - start_gap, cy)
    p2 = robot._scale_point(cx + start_gap, cy)
    q1 = robot._scale_point(cx - end_gap, cy)
    q2 = robot._scale_point(cx + end_gap, cy)
    if robot.dry_run:
        print(f'    [dry-run] pinch {start_gap} -> {end_gap}')
        return
    robot.adb.run('shell', _pinch_script(device, p1, p2, q1, q2, steps),
                  timeout=20)


def zoom_out(robot, times=3):
    """连续捏合，把视角缩到最大。"""
    for _ in range(times):
        pinch(robot, start_gap=420, end_gap=100)
        time.sleep(0.8)


def normalize_view(robot, times=3):
    """在主页把视角缩到最大，返回是否成功。"""
    if not ensure_home(robot):
        print('  当前不在主页，无法调整视角')
        return False
    zoom_out(robot, times=times)
    print(f'  视角已缩小（{times} 次双指捏合）')
    return True
