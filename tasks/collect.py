# -*- coding: utf-8 -*-
"""收资源：点击金币 / 圣水 / 黑油上的“收集”气泡。

模板按优先级排列，新版 collect_label.png 到位后会自动优先使用。
气泡是随村庄缩放的，所以用宽尺度搜索；同时过滤掉右上资源栏与底部菜单。
"""

from actions.common import ensure_home
from tasks.base import Result, Task
from vision.template import exists, match_all

# 模板名 -> 匹配阈值
COLLECT_TEMPLATES = {
    'collect_label.png': 0.80,
    'jinbishouji.png': 0.85,
    'shengshuishouji.png': 0.76,
    'heiyoushouji.png': 0.85,
}
COLLECT_MATCH = dict(min_scale=0.75, max_scale=2.5, steps=12)


def _clickable(found, shape):
    """过滤右上资源栏和底部菜单区域里的误匹配。"""
    h, w = shape[:2]
    fx, fy = found.center[0] / w, found.center[1] / h
    if fy > 0.85:
        return False
    if fx > 0.70 and fy < 0.28:
        return False
    return True


class CollectTask(Task):
    name = 'collect'
    priority = 20

    def __init__(self, limit=15):
        self.limit = limit

    def run(self, robot):
        names = [n for n in COLLECT_TEMPLATES if exists(n)]
        if not names:
            print('  缺少收集模板，暂不收集')
            return Result.SKIP
        if not ensure_home(robot):
            print('  当前不在主页，跳过收集')
            return Result.SKIP

        image = robot.shot()
        targets = []
        for name in names:
            found = match_all(image, name,
                              threshold=COLLECT_TEMPLATES[name],
                              max_results=self.limit, min_distance=60,
                              **COLLECT_MATCH)
            found = [m for m in found if _clickable(m, image.shape)]
            print(f'  {name}: 找到 {len(found)} 个气泡')
            targets.extend(found)

        if not targets:
            print('  没有可收集的资源')
            return Result.SKIP

        for found in targets[:self.limit]:
            cx, cy = found.center
            print(f'    点击 ({cx}, {cy}) 置信度 {found.score:.2f}')
            robot.tap(cx, cy)
        print(f'  已点击 {min(len(targets), self.limit)} 个收集气泡')
        return Result.SUCCESS
