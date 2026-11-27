# -*- coding: utf-8 -*-
"""游戏客户端控制：找包名、启动、等待进入主页。"""

import time

from vision.scene import Scene


def find_game_package(adb):
    """从已安装应用里找到部落冲突包名（国服/国际服通用）。"""
    out = adb.run('shell', 'pm', 'list', 'packages').stdout.decode('utf-8', 'ignore')
    packages = [line.strip().replace('package:', '') for line in out.splitlines()]
    for pkg in packages:
        if 'clashofclans' in pkg.lower():
            return pkg
    return None


def resolve_activity(adb, package):
    """查包名的启动 Activity，返回 '包名/Activity' 或 None。

    雷电模拟器没有 monkey 命令，只能用 am start 指定组件启动。
    """
    proc = adb.run('shell', 'cmd', 'package', 'resolve-activity',
                   '--brief', package)
    lines = proc.stdout.decode('utf-8', 'ignore').strip().splitlines()
    if lines:
        candidate = lines[-1].strip()
        if '/' in candidate:
            return candidate
    return None


def launch_game(adb, package):
    """把游戏启动/切到前台，成功返回 True。"""
    activity = resolve_activity(adb, package)
    if not activity:
        return False
    adb.shell('am', 'start', '-n', activity)
    return True


def wait_home(robot, timeout=120, interval=5):
    """轮询截图，等待进入村庄主页。返回 True/False。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(interval)
        try:
            scene, _ = robot.scene()
        except Exception as exc:
            print(f'  截图失败: {exc}')
            continue
        print(f'  等待加载… 当前界面: {scene.value}')
        if scene == Scene.HOME:
            return True
    return False
