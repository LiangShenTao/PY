# -*- coding: utf-8 -*-
"""COC 自动化入口。

常用用法:
    python main.py --task scene                 # 打印当前界面 + 命中的锚点
    python main.py --task view                  # 在主页把视角缩到最大
    python main.py --task collect               # 收资源
    python main.py --task donate                # 捐兵（默认雷龙）
    python main.py --task train                 # 训练部队（默认雷龙）
    python main.py --task reload                # 重新加载游戏（点“重新载入游戏/重试”）
    python main.py --task launch                # 启动游戏并等待进入主页
    python main.py --task battle                # 自动战斗（常规战，按资源阈值筛选）
    python main.py --task all --loop            # 按 收集->捐兵->训练 顺序循环

离线调试（不连设备）:
    python main.py --task all --image screenshots/home.png --dry-run
"""

import argparse
import time

from robot import Robot
from actions.view import normalize_view
from tasks import ORDER, Result, build_task
from vision.ocr import format_resources, read_resources
from vision.scene import detect as detect_scene


def cmd_scene(robot):
    image = robot.shot()
    scene, hits = detect_scene(image)
    print(f"当前界面: {scene.value}")
    for name, found in hits.items():
        print(f"  锚点 {name}: 中心 {found.center} 置信度 {found.score:.2f}")
    print(f"  资源: {format_resources(read_resources(image))}")


def run_once(robot, names, args):
    """按顺序跑任务，任意一个成功就结束本轮。"""
    for name in names:
        task = build_task(name, args)
        print(f"[{task.name}] 开始")
        try:
            result = task.run(robot)
        except Exception as exc:  # 单个任务出错不影响整个循环
            print(f"[{task.name}] 异常: {exc}")
            result = Result.FAILED
        print(f"[{task.name}] -> {result.value}")
        if result == Result.SUCCESS:
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description='部落冲突自动化助手')
    parser.add_argument('--task', default='auto',
                        choices=['auto', 'scene', 'view', 'collect', 'donate',
                                 'train', 'reload', 'launch', 'battle', 'all'],
                        help='要执行的任务，auto/all 表示按默认顺序全部执行')
    parser.add_argument('--loop', action='store_true', help='循环执行')
    parser.add_argument('--interval', type=float, default=10.0, help='循环间隔(秒)')
    parser.add_argument('--image', help='离线模式：用本地图片代替实时截图')
    parser.add_argument('--dry-run', action='store_true', help='只打印操作，不真正点击')
    parser.add_argument('--donate-troop', default='donate_troop.png', help='捐兵兵种模板')
    parser.add_argument('--donate-count', type=int, default=3, help='捐兵次数')
    parser.add_argument('--no-apply', action='store_true',
                        help='训练时不点“一键应用”，只打开配兵推荐')
    parser.add_argument('--restart', action='store_true',
                        help='重新加载时找不到按钮就重启游戏客户端')
    parser.add_argument('--min-gold', type=int, default=1_000_000,
                        help='自动战斗：对手金币下限')
    parser.add_argument('--min-elixir', type=int, default=500_000,
                        help='自动战斗：对手圣水下限')
    parser.add_argument('--min-dark', type=int, default=0,
                        help='自动战斗：对手黑油下限（0=不限）')
    parser.add_argument('--max-skips', type=int, default=8,
                        help='自动战斗：最多点几次“下一个”')
    parser.add_argument('--battles', type=int, default=5,
                        help='自动战斗：一次连续打几场')
    args = parser.parse_args()

    robot = Robot(image_path=args.image, dry_run=args.dry_run)

    if args.task == 'scene':
        cmd_scene(robot)
        return

    if args.task == 'view':
        normalize_view(robot)
        return

    if args.image is None and not robot.adb.is_connected():
        print('没有检测到设备。请确认模拟器已启动、USB 调试已打开，'
              '并在 config.py 里配置 adb_path 与 device_name。')
        return

    names = ORDER if args.task in ('auto', 'all') else [args.task]

    while True:
        run_once(robot, names, args)
        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n已停止')
