# -*- coding: utf-8 -*-
"""任务层：每个任务封装一个业务动作，返回 Result 供调度器决策。"""

from tasks.base import Result, Task
from tasks.battle import BattleTask
from tasks.collect import CollectTask
from tasks.donate import DonateTask
from tasks.launch import LaunchTask
from tasks.reload import ReloadTask
from tasks.train import TrainTask

# 默认执行顺序：先收集，再捐兵，最后训练
ORDER = ['collect', 'donate', 'train']


def build_task(name, args=None, troop=None, donate_troop=None,
               train_count=5, donate_count=3):
    """按名字创建任务；参数优先取显式传入，其次取 args。"""
    if name == 'collect':
        return CollectTask()
    if name == 'donate':
        troop = donate_troop or getattr(args, 'donate_troop', 'donate_troop.png')
        count = donate_count or getattr(args, 'donate_count', 3)
        return DonateTask(troop=troop, count=count)
    if name == 'train':
        apply = not getattr(args, 'no_apply', False)
        return TrainTask(apply=apply)
    if name == 'reload':
        return ReloadTask(restart=getattr(args, 'restart', False))
    if name == 'launch':
        return LaunchTask()
    if name == 'battle':
        return BattleTask(
            min_gold=getattr(args, 'min_gold', 1_000_000),
            min_elixir=getattr(args, 'min_elixir', 500_000),
            min_dark=getattr(args, 'min_dark', 0),
            max_skips=getattr(args, 'max_skips', 8),
            own_battle=getattr(args, 'own_battle', True),
            battles=getattr(args, 'battles', 5),
        )
    raise ValueError(f'未知任务: {name}')


__all__ = ['Result', 'Task', 'BattleTask', 'CollectTask', 'DonateTask',
           'LaunchTask', 'ReloadTask', 'TrainTask', 'ORDER', 'build_task']
