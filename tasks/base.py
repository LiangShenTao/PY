# -*- coding: utf-8 -*-
"""任务基类与执行结果。"""

from enum import Enum


class Result(str, Enum):
    SUCCESS = 'success'   # 做成了
    RETRY = 'retry'       # 中途失败，可以重试
    FAILED = 'failed'     # 失败了，本轮放弃
    SKIP = 'skip'         # 不适用（例如不在主页、没有可做的事）


class Task:
    name = 'task'
    priority = 100        # 数字越小越先执行

    def run(self, robot) -> Result:
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name}>"
