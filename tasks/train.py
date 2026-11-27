# -*- coding: utf-8 -*-
"""训练部队（新版 UI）。

新版的军队/训练入口在“战斗”按钮里：
    主页 -> 战斗 -> 编辑军队 -> 配兵助手 -> 一键应用 -> 返回
"""

import time

from actions.common import ensure_home
from tasks.base import Result, Task


class TrainTask(Task):
    name = 'train'
    priority = 40

    def __init__(self, apply=True):
        self.apply = apply

    def run(self, robot):
        if not ensure_home(robot):
            print('  当前不在主页，无法训练')
            return Result.SKIP

        if not robot.tap_template('home_attack.png'):
            return Result.RETRY
        time.sleep(1)

        if not robot.tap_template('battle_edit_army.png'):
            return Result.RETRY
        time.sleep(1)

        if not robot.tap_template('army_quick_fill.png'):
            return Result.FAILED
        time.sleep(1)

        if self.apply:
            if not robot.tap_template('quickfill_apply.png'):
                return Result.FAILED
            print('  已一键应用配兵推荐')
            time.sleep(1)

        # 退回主页
        robot.tap_template('quickfill_back.png')
        time.sleep(1)
        return Result.SUCCESS
