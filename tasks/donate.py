# -*- coding: utf-8 -*-
"""捐兵：主页 -> 部落聊天面板 -> 找增援请求 -> 连点兵种。

注：donate_request.png（增援请求）和 donate_troop.png（兵种）需要按新版 UI 采集。
"""

import time

from actions.common import ensure_home
from actions.gestures import swipe_down
from tasks.base import Result, Task
from vision.template import exists

REQUEST_TEMPLATE = 'donate_request.png'


class DonateTask(Task):
    name = 'donate'
    priority = 30

    def __init__(self, troop='donate_troop.png', count=3):
        self.troop = troop
        self.count = count

    def run(self, robot):
        if not exists(REQUEST_TEMPLATE) or not exists(self.troop):
            print('  缺少增援请求/兵种模板，暂不捐兵')
            return Result.SKIP
        if not ensure_home(robot):
            print('  当前不在主页，无法捐兵')
            return Result.SKIP

        # 新版 UI：左侧“部落”图标直接打开聊天面板
        if not robot.tap_template('home_clan.png'):
            return Result.RETRY
        time.sleep(1)

        if not robot.tap_template(REQUEST_TEMPLATE):
            swipe_down(robot)
            if not robot.tap_template(REQUEST_TEMPLATE):
                print('  没有找到捐兵请求')
                return Result.SKIP

        if not robot.tap_template(self.troop, click_count=self.count):
            return Result.FAILED
        print(f'  已捐出 {self.count} 个兵')
        return Result.SUCCESS
