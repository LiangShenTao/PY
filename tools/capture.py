# -*- coding: utf-8 -*-
"""截图 / 离线识别工具。

    python tools/capture.py                     # 截当前屏、保存并识别界面
    python tools/capture.py --name home         # 截图按 home_时间戳.png 命名
    python tools/capture.py --detect shot.png   # 只识别本地图片（不连设备）
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2

import config
from device.adb import Adb
from vision.scene import detect


def report(image):
    scene, hits = detect(image)
    print(f'界面: {scene.value}')
    for name, found in hits.items():
        print(f'  锚点 {name}: 中心 {found.center} 置信度 {found.score:.2f}')


def main():
    parser = argparse.ArgumentParser(description='截图与界面识别工具')
    parser.add_argument('--name', help='截图文件名前缀')
    parser.add_argument('--detect', help='识别指定的本地图片')
    args = parser.parse_args()

    if args.detect:
        image = cv2.imread(args.detect)
        if image is None:
            print(f'读不到图片: {args.detect}')
            return
        report(image)
        return

    os.makedirs(config.SHOT_DIR, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    path = os.path.join(config.SHOT_DIR, f'{args.name or "shot"}_{stamp}.png')
    Adb().screencap(path)
    image = cv2.imread(path)
    print(f'已保存: {path}')
    if image is not None:
        report(image)


if __name__ == '__main__':
    main()
