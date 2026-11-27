# -*- coding: utf-8 -*-
"""进入游戏：启动客户端，并等待加载到村庄主页。"""

from actions.game import find_game_package, launch_game, wait_home
from tasks.base import Result, Task
from vision.scene import Scene


class LaunchTask(Task):
    name = 'launch'
    priority = 5

    def run(self, robot):
        scene, _ = robot.scene()
        print(f'  当前界面: {scene.value}')
        if scene == Scene.HOME:
            print('  已经在游戏主页，无需启动')
            return Result.SUCCESS

        package = find_game_package(robot.adb)
        if not package:
            print('  没有找到部落冲突包名，确认游戏已安装在模拟器里')
            return Result.FAILED
        print(f'  启动客户端 {package}')
        if robot.dry_run:
            print('    [dry-run] 跳过启动命令')
            return Result.SUCCESS

        if not launch_game(robot.adb, package):
            print('  找不到启动 Activity，无法打开游戏')
            return Result.FAILED
        if wait_home(robot):
            print('  已进入游戏主页')
            return Result.SUCCESS
        print('  等待超时，游戏可能还在加载')
        return Result.RETRY
