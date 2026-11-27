# -*- coding: utf-8 -*-
"""界面识别：用少量“该界面才有的”锚点模板判断当前界面。

模板均按 1920x1080 采集（横屏新版 UI），识别用 1:1 单尺度匹配。
游戏版本更新后，只需重截 modle/ 里的模板、必要时改 SCENE_ANCHORS。
"""

from enum import Enum

import config
from vision.template import match


class Scene(str, Enum):
    HOME = 'home'                # 村庄主页
    BATTLE = 'battle'            # 战斗菜单
    ARMY = 'army'                # 编辑军队
    QUICKFILL = 'quickfill'      # 配兵推荐
    CLAN_CHAT = 'clan_chat'      # 部落聊天面板
    UNKNOWN = 'unknown'


SCENE_ANCHORS = {
    Scene.QUICKFILL: ['quickfill_apply.png'],
    Scene.BATTLE: ['battle_edit_army.png'],
    Scene.ARMY: ['army_quick_fill.png'],
    Scene.CLAN_CHAT: ['clan_chat_bar.png'],
    Scene.HOME: ['home_attack.png', 'home_clan.png'],
}

# 优先级：被覆盖的界面先判，主页最后（主页元素最多，避免误判）
_SCENE_ORDER = [Scene.QUICKFILL, Scene.BATTLE, Scene.ARMY, Scene.CLAN_CHAT, Scene.HOME]


def detect(image, threshold=None):
    """返回 (Scene, {模板名: Match})，命中即返回。"""
    threshold = config.SCENE_THRESHOLD if threshold is None else threshold
    hits = {}
    for scene in _SCENE_ORDER:
        for name in SCENE_ANCHORS[scene]:
            try:
                found = match(image, name, threshold=threshold,
                              min_scale=1.0, max_scale=1.0, steps=1)
            except FileNotFoundError:
                continue
            if found:
                hits[name] = found
                return scene, hits
    return Scene.UNKNOWN, hits
