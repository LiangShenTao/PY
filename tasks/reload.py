# -*- coding: utf-8 -*-
"""重新加载游戏。

优先处理“重新载入游戏 / 重试”按钮（旧版脚本同样逻辑）；
找不到按钮且开启 restart 时，用 adb 重启客户端并等待回到主页。
"""

import time

from actions.game import find_game_package, launch_game, wait_home
from tasks.base import Result, Task
from vision.template import exists, match

# 模板名 -> 匹配参数（新版是大号文字，按 1:1 匹配；
# 旧模板是小尺寸文字，用宽尺度搜索兼容）
RELOAD_TEMPLATES = (
    ('reload_game.png', dict(threshold=0.85, min_scale=0.95,
                             max_scale=1.05, steps=3)),
    ('chongjin.png', dict(threshold=0.72, min_scale=0.75,
                          max_scale=2.4, steps=12)),
    ('chongjin_1.png', dict(threshold=0.72, min_scale=0.75,
                            max_scale=2.4, steps=12)),
)


class ReloadTask(Task):
    name = 'reload'
    priority = 10

    def __init__(self, restart=False):
        self.restart = restart

    def run(self, robot):
        image = robot.shot()
        for name, options in RELOAD_TEMPLATES:
            if not exists(name):
                continue
            found = match(image, name, **options)
            if found:
                print(f'  发现 {name}，点击重新加载')
                robot.tap(*found.center)
                time.sleep(6)
                return Result.SUCCESS

        print('  当前没有“重新载入游戏/重试”按钮')
        if self.restart:
            return self._restart(robot)
        return Result.SKIP

    def _restart(self, robot):
        package = find_game_package(robot.adb)
        if not package:
            print('  没有找到部落冲突包名，无法重启')
            return Result.FAILED
        print(f'  重启客户端 {package}')
        if robot.dry_run:
            print('    [dry-run] 跳过 force-stop 与启动命令')
            return Result.SKIP
        robot.adb.shell('am', 'force-stop', package)
        time.sleep(2)
        if not launch_game(robot.adb, package):
            print('  找不到启动 Activity，无法重新打开游戏')
            return Result.FAILED
        if wait_home(robot):
            return Result.SUCCESS
        print('  等待超时，游戏可能还在加载')
        return Result.RETRY
