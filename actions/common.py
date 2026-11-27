# -*- coding: utf-8 -*-
"""通用动作：关弹窗、回主页。"""

import time

from vision.scene import Scene

# 新版 UI 用红色 X 关窗口；只放“点了不会误消费”的按钮，
# 不要把“确定”类按钮加进来。
POPUP_TEMPLATES = ['close_x.png']

_POPUP_MATCH = dict(min_scale=1.0, max_scale=1.0, steps=1, threshold=0.9)


def dismiss_popups(robot, rounds=2):
    """反复关掉挡路的弹窗，返回关掉的次数。"""
    closed = 0
    for _ in range(rounds):
        found = False
        for name in POPUP_TEMPLATES:
            hit = robot.find(name, **_POPUP_MATCH)
            if hit:
                print(f'    关闭弹窗 {name} @{hit.center}')
                robot.tap(*hit.center)
                closed += 1
                found = True
                time.sleep(0.3)
                break
        if not found:
            break
    return closed


def ensure_home(robot, tries=3):
    """确保处于村庄主页；卡在“选择对手”界面时按返回键退出。"""
    for _ in range(tries):
        dismiss_popups(robot)
        scene, _ = robot.scene()
        if scene == Scene.HOME:
            return True
        if scene == Scene.BATTLE:
            # 上次流程中断会停在“联机模式”界面，系统返回键可以退回村庄
            print('    当前在“选择对手”界面，按返回键回主页')
            if robot.dry_run:
                print('    [dry-run] back')
            else:
                robot.adb.shell('input', 'keyevent', 4)
            time.sleep(1.5)
    return False
