# -*- coding: utf-8 -*-
"""自动战斗（常规战）。

流程:
    主页 -> 战斗 -> 搜索对手 -> 进攻! -> 读对手战利品
    -> 不达标点“下一个”继续搜；达标点“自动战斗”
    -> 等战斗结束，点“回营”，回主页

“自动战斗”每天有次数限制，这里会在 data/battle_state.json 里按天记录使用次数。
"""

import json
import os
import random
import time
from datetime import date

import cv2
import numpy as np

import config
from actions.common import ensure_home
from tasks.base import Result, Task
from vision.ocr import read_counter, read_number, read_percent, read_resources
from vision.scene import Scene
from vision.template import exists, match

# 对手战利品所在位置（1920x1080 参考坐标）
LOOT_ROIS = {
    'gold': (90, 136, 252, 173),
    'elixir': (90, 196, 252, 233),
    'dark': (90, 259, 252, 296),
}

# 结算画面“您得到了”三个数字（1920x1080 参考坐标）
RESULT_LOOT_ROIS = {
    'gold': (700, 470, 1030, 525),
    'elixir': (700, 545, 1030, 598),
    'dark': (700, 618, 1030, 670),
}

# 结算画面“摧毁率”百分比数字（1920x1080 参考坐标）
RESULT_DESTRUCTION_ROI = (913, 148, 1012, 202)

ONE = dict(min_scale=1.0, max_scale=1.0, steps=1)
STATE_FILE = os.path.join('data', 'battle_state.json')
HISTORY_FILE = os.path.join('data', 'battle_history.json')
POLICY_FILE = os.path.join('data', 'battle_policy.json')
# 学习：攒够这么多场才按平均摧毁率调整一次，单次只动 1 发
LEARN_WINDOW = 5
MIN_AD_LIGHTNING = 2
MAX_AD_LIGHTNING = 5

# 兵种/英雄/法术栏图标中心（参考分辨率 1920x1080，按实战截图量取）
SLOT_CENTERS = [184, 349, 504, 669, 838, 1005, 1164, 1334, 1503]
SLOT_Y = 975
# 当前常用配兵：0 气球、1 飞龙、2 援军、3-5 英雄、6 雷电、7 冰冻、8 活动法术
BALLOON_SLOT = 0
DRAGON_SLOT = 1
CC_SLOT = 2
HERO_SLOTS = (3, 4, 5)
LIGHTNING_SLOT = 6
OTHER_SPELL_SLOTS = (7, 8)

# 兜底投放点：确保都在战场内（底部 UI 从 y≈878 开始，不能越过）
DEPLOY_POINTS = [(80, 320), (80, 500), (80, 680), (1840, 320), (1840, 500),
                 (1840, 680), (300, 215), (1620, 215)]
HERO_POINTS = [(700, 878), (1200, 878), (960, 884)]
# 核心区域（雷电与剩余法术落点，集中在中心建筑群）
CORE_POINTS = [(950, 560), (1000, 600), (910, 600), (1010, 540)]
# 每个防空火箭需要几发雷电（按常见 12/13 本估算，可改）
LIGHTNING_PER_AD = 3
# 防空火箭模板：不同等级外观不同，这里按等级各放一份，缺失的自动跳过
AIR_DEFENSE_TEMPLATES = ('air_defense_3.png', 'air_defense.png',
                         'air_defense_12.png', 'air_defense_11.png',
                         'air_defense_2.png')
# 进入对手阵型后有 30 秒“开战倒计时”，这期间放兵/法术都不生效
PREP_COUNTDOWN = 34
# 游戏内镜头缩放会变化，用多尺度搜索
AD_SCALES = (0.75, 0.85, 0.95, 1.05, 1.2)
# 法术没放出去时，往上/左右错开再试（避免点到兵种栏或界面按钮）
SPELL_SHIFTS = ((0, 0), (0, -35), (0, -70), (-35, 0), (35, 0))


def _count_roi(center):
    """某一格数量标签的 ROI（1920x1080 参考坐标），center 是格子中心 x。"""
    return (center - 50, 890, center + 95, 934)


def _outward(point, step):
    """把点沿“远离村庄中心”的方向挪 step 像素，绕开红线。"""
    dx, dy = point[0] - 960, point[1] - 540
    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
    return (min(max(int(point[0] + dx / length * step), 20), 1900),
            min(max(int(point[1] + dy / length * step), 70), 866))


class BattleTask(Task):
    name = 'battle'
    priority = 60

    def __init__(self, min_gold=1_000_000, min_elixir=500_000,
                 min_dark=0, max_skips=8, own_battle=True, battles=5):
        self.min_gold = min_gold
        self.min_elixir = min_elixir
        self.min_dark = min_dark
        self.max_skips = max_skips
        self.own_battle = own_battle
        self.battles = max(1, int(battles))
        self.result_loot = None
        self.deploy_points = list(DEPLOY_POINTS)
        self.deploy_lines = []
        self.good_line = None
        self.slots = list(SLOT_CENTERS)
        self.lightning_slot = LIGHTNING_SLOT
        self.spell_slots = list(OTHER_SPELL_SLOTS)
        self.policy = self._load_policy()
        self.lightning_per_ad = self.policy['lightning_per_ad']
        self.destruction = None
        self.last_side = None

    # ------------------------------------------------------------ 主流程
    def run(self, robot):
        """连续开战：一场打完回主页就继续下一场，直到打满场数或中途卡住。"""
        for index in range(self.battles):
            if robot.stopped():
                print('  已停止')
                return Result.SKIP
            print(f'  === 第 {index + 1}/{self.battles} 场 ===')
            result = self._battle_once(robot)
            if result is not Result.SUCCESS:
                return result
            if index + 1 < self.battles:
                time.sleep(3)
        return Result.SUCCESS

    def _battle_once(self, robot):
        self.destruction = None
        self.last_side = None
        if not ensure_home(robot):
            print('  当前不在主页，无法开战')
            return Result.SKIP

        if not robot.tap_template('home_attack.png'):
            return Result.RETRY
        if not self._wait_tap(robot, 'battle_search.png'):
            print('  没有进入“选择对手”界面')
            return Result.RETRY
        if not self._wait_tap(robot, 'battle_attack.png', timeout=30):
            print('  搜索结束但没找到“进攻”按钮')
            return Result.RETRY

        for attempt in range(self.max_skips + 1):
            preview = self._wait_prep(robot)
            if preview is None:
                print('  没有进入备战界面（可能倒计时结束），稍后重试')
                return Result.RETRY

            loot = self._read_loot(robot)
            print(f'  对手战利品: 金币 {loot["gold"]}  圣水 {loot["elixir"]}  '
                  f'黑油 {loot["dark"]}')
            if self._meets(loot):
                auto = match(robot.image(refresh=True), 'battle_autofight.png',
                             threshold=0.9, **ONE)
                if auto:
                    print('  达到阈值，点游戏内“自动战斗”')
                    before = read_resources(robot.shot())
                    robot.tap(*auto.center)
                    self._record_use()
                    result = self._wait_battle_end(robot)
                    self._record_battle(loot, before,
                                        read_resources(robot.shot()), result,
                                        method='game')
                    return result
                if self.own_battle:
                    print('  达到阈值，直接放兵（不等倒计时）')
                    return self._own_attack(robot, loot)
                print('  “自动战斗”不可用（次数用完了），结束本次备战')
                robot.tap_template('battle_end.png', threshold=0.9, **ONE)
                time.sleep(3)
                return Result.SKIP

            print(f'  低于阈值，点“下一个”（{attempt + 1}/{self.max_skips}）')
            if not robot.tap_template('battle_next.png', threshold=0.9, **ONE):
                return Result.RETRY
            time.sleep(2)

        print('  搜索次数已用完，结束本次备战')
        robot.tap_template('battle_end.png', threshold=0.9, **ONE)
        time.sleep(3)
        return Result.SKIP

    # ------------------------------------------------------------ 步骤
    @staticmethod
    def _wait_tap(robot, name, timeout=20, threshold=0.9):
        """等按钮出现再点：搜索/加载有快有慢，固定等待容易漏点。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = match(robot.image(refresh=True), name,
                          threshold=threshold, **ONE)
            if found:
                print(f'    命中 {name} @{found.center} 置信度 {found.score:.2f}')
                robot.tap(*found.center)
                return True
            time.sleep(1.0)
        return False

    @staticmethod
    def _wait_prep(robot, timeout=45):
        """等到备战界面出现（“下一个”或“自动战斗”任一可见）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            image = robot.image(refresh=True)
            for name in ('battle_next.png', 'battle_autofight.png'):
                found = match(image, name, threshold=0.9, **ONE)
                if found:
                    return found
            time.sleep(1.2)
        return None

    @staticmethod
    def _read_loot(robot, retries=2):
        """读对手战利品；某一项没读出来就重截一次。"""
        loot = {}
        for attempt in range(retries + 1):
            image = robot.image(refresh=True)
            loot = {name: read_number(image, roi)
                    for name, roi in LOOT_ROIS.items()}
            if all(value is not None for value in loot.values()):
                break
            time.sleep(0.6)
        return loot

    # ------------------------------------------------------------ 自带放兵
    @staticmethod
    def _count_at(image, center):
        """同一标签试几个高度，取出现次数最多的读数，减少 x11 被读成 8 这类错误。"""
        values = []
        for dy in (-6, 0, 6):
            value = read_counter(image, (center - 50, 890 + dy,
                                         center + 95, 934 + dy))
            if value is not None:
                values.append(value)
        if not values:
            return None
        return max(set(values), key=values.count)

    @staticmethod
    def _detect_slots(image):
        """按底部栏的亮块切出每个格子中心；兵种/英雄数量变化时也能对准。

        最后一格是空位（很暗），直接剔除，返回的就是实际有东西的格子。
        """
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        value = hsv[:, :, 2]
        profile = value[905:1025, :].mean(axis=0)
        bright = profile >= 45
        runs, start = [], None
        for x, ok in enumerate(bright):
            if ok and start is None:
                start = x
            elif not ok and start is not None:
                if 100 <= x - start <= 190 and x > 150:
                    runs.append((start, x))
                start = None
        centers = []
        for start, end in runs:
            center = (start + end) // 2
            inside = value[930:1000, center - 40:center + 40]
            if inside.size and inside.mean() < 100:   # 空格子，跳过
                continue
            centers.append(center)
        return centers

    def _slot_center(self, index):
        """第 index 格的中心 x；越界时退回默认表。"""
        if 0 <= index < len(self.slots):
            return self.slots[index]
        return SLOT_CENTERS[min(max(index, 0), len(SLOT_CENTERS) - 1)]

    def _read_bar(self, image):
        """读兵种栏每个格子的数量（xN），读不到为 None。"""
        return {index: self._count_at(image, center)
                for index, center in enumerate(self.slots)}

    @staticmethod
    def _fast_tap(robot, point, pause=0.07):
        """快速连点，不带 robot.tap 那种 0.3~0.8 秒的等待。"""
        if robot.dry_run:
            print(f'    [dry-run] tap {point}')
        else:
            robot.adb.tap(int(point[0]), int(point[1]))
        time.sleep(pause)

    def _deploy_slot(self, robot, slot, count):
        """选中兵种后连续点放；某条边放不出去（红线/海水/屏幕外）就换下一条边。"""
        robot.tap(self._slot_center(slot), SLOT_Y)
        target = min(max(count, 1), 40)
        remaining = self._count_at(robot.shot(), self._slot_center(slot))
        if remaining is None:
            remaining = target
        lines = self.deploy_lines or [self.deploy_points or DEPLOY_POINTS]
        for points in lines:
            if remaining <= 0:
                break
            for i in range(min(remaining, 40)):
                if robot.stopped():
                    return max(remaining, 0)
                self._fast_tap(robot, points[i % len(points)])
            left = self._count_at(robot.shot(), self._slot_center(slot))
            if left is None:
                continue
            if left >= remaining:
                print(f'    这条边放不出去（还剩 {left}），换下一条边')
            else:
                self.good_line = points
            remaining = left
        if remaining:
            print(f'    还有 {remaining} 个没放出去')
        return max(remaining, 0)

    def _cast_spell(self, robot, slot, point):
        """点一发法术并校验数量确实减少，没减少就错位重试。"""
        roi = _count_roi(self._slot_center(slot))
        before = read_counter(robot.shot(), roi)
        if before is None:
            # 读不到数量就没法确认法术是否放出去，不能当成成功
            return False
        for dx, dy in SPELL_SHIFTS:
            # 每发都要重新点一次法术格：放完一发游戏会自动取消选中
            robot.tap(self._slot_center(slot), SLOT_Y)
            time.sleep(0.2)
            target = (min(max(point[0] + dx, 20), 1900),
                      min(max(point[1] + dy, 70), 866))
            self._fast_tap(robot, target, pause=0.5)
            time.sleep(0.3)
            left = read_counter(robot.shot(), roi)
            if left is not None and left < before:
                return True
        return False

    def _find_air_defenses(self, robot, limit=6, threshold=0.62):
        """多模板、多尺度找防空火箭；模板缺失时跳过。

        不同等级外观不一样，镜头缩放也会变，所以逐个模板在多个尺度上匹配。
        结果会标到 data/aa_debug.png，方便人工核对识别是否准确。
        """
        image = robot.image(refresh=True)
        blurred = cv2.GaussianBlur(image, (0, 0), 1.0)
        hits = []
        for name in AIR_DEFENSE_TEMPLATES:
            path = os.path.join(config.TEMPLATE_DIR, name)
            template = cv2.imread(path) if os.path.isfile(path) else None
            if template is None:
                continue
            for scale in AD_SCALES:
                resized = (template if scale == 1.0 else
                           cv2.resize(template, None, fx=scale, fy=scale,
                                      interpolation=cv2.INTER_AREA))
                if (resized.shape[0] >= image.shape[0] or
                        resized.shape[1] >= image.shape[1]):
                    continue
                scores = cv2.matchTemplate(
                    blurred, cv2.GaussianBlur(resized, (0, 0), 1.0),
                    cv2.TM_CCOEFF_NORMED)
                ys, xs = np.where(scores >= threshold)
                for y, x in zip(ys, xs):
                    hits.append((float(scores[y, x]),
                                 (int(x + resized.shape[1] / 2),
                                  int(y + resized.shape[0] / 2))))
        hits.sort(key=lambda item: item[0], reverse=True)
        picked = []
        for _, center in hits:
            if all(abs(center[0] - p[0]) + abs(center[1] - p[1]) > 110
                   for p in picked):
                picked.append(center)
            if len(picked) >= limit:
                break

        os.makedirs('data', exist_ok=True)
        marked = image.copy()
        for x, y in picked:
            cv2.circle(marked, (x, y), 45, (0, 0, 255), 3)
        cv2.imwrite(os.path.join('data', 'aa_debug.png'), marked)
        return picked

    def _cast_lightning(self, robot, count, ads=None):
        """先把雷电砸向防空火箭（有模板时），剩下的砸核心，逐发校验。"""
        left = read_counter(robot.shot(),
                            _count_roi(self._slot_center(self.lightning_slot)))
        left = min(max(count, 1), 12) if left is None else left
        targets = [ad for ad in (ads or []) for _ in range(self.lightning_per_ad)]
        targets += [CORE_POINTS[i % len(CORE_POINTS)] for i in range(12)]
        fails = 0
        for point in targets:
            if left <= 0 or fails >= 3 or robot.stopped():
                break
            if self._cast_spell(robot, LIGHTNING_SLOT, point):
                left -= 1
                fails = 0
            else:
                fails += 1
        if fails >= 3:
            print('  连续几发法术都没放出去，可能战斗已结束或界面被挡')
        print(f'  雷电剩余 {max(left, 0)} 发')

    def _find_spell_slots(self, image):
        """按图标外观认出法术格（不靠第几格），返回 {法术: 格子序号}。"""
        found = {}
        for key, name in (('lightning', 'spell_lightning.png'),
                          ('freeze', 'spell_freeze.png'),
                          ('event', 'spell_event.png')):
            if not exists(name):
                continue
            hit = match(image, name, roi=(0, 880, 1920, 1080),
                        threshold=0.8, **ONE)
            if hit:
                center = hit.center[0]
                found[key] = min(range(len(self.slots)),
                                 key=lambda i: abs(self.slots[i] - center))
        return found

    def _plan_deploy_line(self, image, limit=12):
        """沿“草地最多的边”生成一排投放点（模仿回放：贴边成排下兵）。"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        grass = cv2.inRange(hsv, (30, 40, 40), (90, 255, 255))

        def grassy(x, y):
            patch = grass[y - 15:y + 15, x - 15:x + 15]
            return patch.size > 0 and patch.mean() > 150

        def best_column(xs, ys):
            """从最外侧开始找第一条草地够多的竖列（越靠外越安全）。"""
            for x in xs:
                valid = [(x, y) for y in ys if grassy(x, y)]
                if len(valid) >= 4:
                    return valid
            return []

        rows = range(240, 820, 55)
        bands = {
            'left': best_column((45, 80, 115), rows),
            'right': best_column((1875, 1840, 1805), rows),
            'bottom': [(x, 850) for x in range(300, 1620, 110)
                       if grassy(x, 850)],
            'top': [(x, 190) for x in range(300, 1620, 110)
                    if grassy(x, 190)],
        }
        lines = []
        for name in self._side_order():
            valid = bands.get(name) or []
            if len(valid) >= 4:
                lines.append((name, valid[:limit]))
        if not lines:
            lines = [('fallback', list(DEPLOY_POINTS))]
        # 一条边放不出去（海水/红线）就依次换下一条
        self.deploy_lines = [points for _, points in lines]
        name, points = lines[0]
        return points, name

    def _own_attack(self, robot, loot=None):
        """自带放兵：找草地投放线 → 雷电开道 → 飞龙 → 气球 → 英雄 → 援军 → 法术。"""
        before = read_resources(robot.shot())
        os.makedirs('data', exist_ok=True)

        # 倒计时阶段点击一律无效，先等真正开打，否则会把“没放出去”误判成被红线挡住
        print(f'  等待开战倒计时 {PREP_COUNTDOWN}s（倒计时内放兵/法术不生效）')
        for _ in range(PREP_COUNTDOWN):
            if robot.stopped():
                print('  已停止')
                return Result.SKIP
            time.sleep(1)

        image = robot.shot()
        slots = self._detect_slots(image)
        self.slots = slots if len(slots) >= 9 else list(SLOT_CENTERS)
        # 先按位置兜底，再按法术图标外观精确校正（配兵顺序变了也不会认错）
        self.lightning_slot = max(len(self.slots) - 3, 0)
        self.spell_slots = list(range(len(self.slots) - 2, len(self.slots)))
        spells = self._find_spell_slots(image)
        if 'lightning' in spells:
            self.lightning_slot = spells['lightning']
            print(f'  雷电法术：第 {self.lightning_slot + 1} 格（按图标识别）')
        others = [index for key, index in spells.items() if key != 'lightning']
        if others:
            self.spell_slots = others
        self.deploy_points, side = self._plan_deploy_line(image)
        self.last_side = side
        print(f'  投放方向 {side}，共 {len(self.deploy_points)} 个点'
              f'（雷电 {self.lightning_per_ad} 发/防空）')
        marked = image.copy()
        for x, y in self.deploy_points:
            cv2.circle(marked, (x, y), 14, (0, 0, 255), 3)
        cv2.imwrite(os.path.join('data', 'deploy_plan.png'), marked)
        counts = self._read_bar(image)

        dragon = counts.get(DRAGON_SLOT) or 8
        balloon = counts.get(BALLOON_SLOT) or 12
        cc = counts.get(CC_SLOT) or 9
        lightning = counts.get(self.lightning_slot) or 8
        print(f'  兵力：飞龙 x{dragon}  气球 x{balloon}  '
              f'援军 x{counts.get(CC_SLOT)}  雷电 x{lightning}')

        print('  雷电开道（把雷电用完）')
        ads = self._find_air_defenses(robot)
        if ads:
            print(f'  发现 {len(ads)} 个防空火箭')
        self._cast_lightning(robot, lightning, ads)

        print(f'  放飞龙 x{dragon}')
        self._deploy_slot(robot, DRAGON_SLOT, dragon)

        print(f'  放气球 x{balloon}')
        self._deploy_slot(robot, BALLOON_SLOT, balloon)

        if robot.stopped():
            print('  已停止')
            return Result.SKIP
        print('  放英雄（主力进场后）')
        time.sleep(4)
        hero_points = (self.good_line or
                       (self.deploy_lines[0] if self.deploy_lines
                        else DEPLOY_POINTS))[:4]
        hero_slots = list(range(3, len(self.slots) - 3)) or list(HERO_SLOTS)
        for slot, point in zip(hero_slots, hero_points):
            robot.tap(self._slot_center(slot), SLOT_Y)
            for shift in (0, 35):
                robot.tap(*_outward(point, shift))
                time.sleep(0.35)

        print(f'  放援军 x{cc}')
        self._deploy_slot(robot, CC_SLOT, cc)

        # 复查栏位：还剩多少就补放多少
        left = self._read_bar(robot.shot())
        cv2.imwrite(os.path.join('data', 'deploy_after.png'), robot.image())
        for slot, name in ((DRAGON_SLOT, '飞龙'), (BALLOON_SLOT, '气球'),
                           (CC_SLOT, '援军')):
            remain = left.get(slot)
            if remain:
                print(f'  {name} 还剩 x{remain}，补放')
                self._deploy_slot(robot, slot, remain)

        time.sleep(3)
        print('  剩余法术丢核心')
        for slot in self.spell_slots:
            left = read_counter(robot.shot(),
                                _count_roi(self._slot_center(slot))) or 0
            for i in range(min(left, 4)):
                self._cast_spell(robot, slot,
                                 CORE_POINTS[i % len(CORE_POINTS)])

        result = self._wait_battle_end(robot)
        after = read_resources(robot.shot())
        self._record_battle(loot, before, after, result)
        return result

    def _meets(self, loot):
        for name, need in (('gold', self.min_gold),
                           ('elixir', self.min_elixir),
                           ('dark', self.min_dark)):
            if need and (loot.get(name) is None or loot[name] < need):
                return False
        return True

    def _wait_battle_end(self, robot, timeout=330):
        """等战斗结束，点“回营”，再等回到主页。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if robot.stopped():
                print('  已停止')
                return Result.SKIP
            image = robot.shot()
            returned = match(image, 'battle_return.png', threshold=0.9, **ONE)
            if returned:
                # 存一张结算截图，并直接读“您得到了”的实际收益
                os.makedirs('data', exist_ok=True)
                cv2.imwrite(os.path.join('data', 'last_result.png'), image)
                self.result_loot = {name: read_number(image, roi)
                                    for name, roi in RESULT_LOOT_ROIS.items()}
                self.destruction = read_percent(image, RESULT_DESTRUCTION_ROI)
                print(f'  本场获得: {self.result_loot}')
                if self.destruction is not None:
                    print(f'  摧毁率: {self.destruction}%')
                print('  战斗结束，点“回营”')
                robot.tap(*returned.center)
                time.sleep(4)
                return Result.SUCCESS if ensure_home(robot) else Result.RETRY
            scene, _ = robot.scene()
            if scene == Scene.HOME:
                print('  已回到主页')
                return Result.SUCCESS
            time.sleep(5)
        print('  等待战斗结束超时')
        return Result.RETRY

    # ------------------------------------------------------------ 战绩记忆
    def _record_battle(self, loot, before, after, result, method='own'):
        """把每场战斗的对手资源、实际收益记下来，供后续优化参考。"""
        def diff(key):
            old, new = before.get(key), after.get(key)
            if old is None or new is None:
                return None
            return new - old

        gained = {}
        for key in ('gold', 'elixir', 'dark'):
            value = (self.result_loot or {}).get(key)
            gained[key] = value if value is not None else diff(key)

        record = {
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'method': method,
            'loot': loot,
            'gained': gained,
            'destruction': self.destruction,
            'side': self.last_side if method == 'own' else None,
            'lightning_per_ad': self.lightning_per_ad,
            'result': result.value,
        }
        history = []
        if os.path.isfile(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as fp:
                    history = json.load(fp)
            except (OSError, ValueError):
                history = []
        history.append(record)
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, 'w', encoding='utf-8') as fp:
            json.dump(history, fp, ensure_ascii=False, indent=2)

        gained = record['gained']
        print(f"  本场收益: 金币 {gained['gold']}  圣水 {gained['elixir']}  "
              f"黑油 {gained['dark']}（累计 {len(history)} 场）")
        self._learn(self.destruction, record['side'], method)

    # ------------------------------------------------------------ 策略学习
    @staticmethod
    def _load_policy():
        policy = {'lightning_per_ad': LIGHTNING_PER_AD, 'total_battles': 0,
                  'recent_destruction': [], 'side_stats': {}}
        if os.path.isfile(POLICY_FILE):
            try:
                with open(POLICY_FILE, 'r', encoding='utf-8') as fp:
                    saved = json.load(fp)
                if isinstance(saved, dict):
                    policy.update(saved)
            except (OSError, ValueError):
                pass
        return policy

    def _save_policy(self):
        os.makedirs(os.path.dirname(POLICY_FILE), exist_ok=True)
        with open(POLICY_FILE, 'w', encoding='utf-8') as fp:
            json.dump(self.policy, fp, ensure_ascii=False, indent=2)

    def _side_order(self):
        """按历史平均摧毁率给投放方向排序，偶尔随机探索其他方向。"""
        sides = ['left', 'right', 'bottom', 'top']
        stats = self.policy.get('side_stats') or {}

        def average(side):
            count, total = (stats.get(side) or [0, 0])[:2]
            return total / count if count else -1.0

        order = sorted(sides, key=average, reverse=True)
        if random.random() < 0.15:
            random.shuffle(order)
        return order

    def _learn(self, destruction, side, method='own'):
        """用每场摧毁率慢慢调整打法：样本够才动，单次只改 1 发。"""
        policy = self.policy
        policy['total_battles'] = policy.get('total_battles', 0) + 1
        if destruction is not None and method == 'own':
            recent = policy.setdefault('recent_destruction', [])
            recent.append(int(destruction))
            del recent[:-20]
            if side and side != 'fallback':
                stat = policy.setdefault('side_stats', {}).setdefault(side, [0, 0])
                stat[0] += 1
                stat[1] += int(destruction)

            old = policy['lightning_per_ad']
            if len(recent) >= LEARN_WINDOW:
                avg = sum(recent[-LEARN_WINDOW:]) / LEARN_WINDOW
                new = old
                if avg < 55 and old < MAX_AD_LIGHTNING:
                    new = old + 1
                elif avg > 85 and old > MIN_AD_LIGHTNING:
                    new = old - 1
                if new != old:
                    policy['lightning_per_ad'] = new
                    policy['recent_destruction'] = []
                    self.lightning_per_ad = new
                    print(f'  学习：近 {LEARN_WINDOW} 场平均摧毁 {avg:.0f}%，'
                          f'每个防空的雷电 {old} -> {new} 发')
        self._save_policy()
        print(f'  累计 {policy["total_battles"]} 场，'
              f'当前策略：雷电 {self.lightning_per_ad} 发/防空')

    # ------------------------------------------------------------ 次数记录
    @staticmethod
    def _record_use():
        today = date.today().isoformat()
        state = {}
        if os.path.isfile(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as fp:
                    state = json.load(fp)
            except (OSError, ValueError):
                state = {}
        if state.get('date') != today:
            state = {'date': today, 'auto_uses': 0}
        state['auto_uses'] = state.get('auto_uses', 0) + 1
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w', encoding='utf-8') as fp:
            json.dump(state, fp, ensure_ascii=False, indent=2)
        print(f"  今日自动战斗使用次数: {state['auto_uses']}")
