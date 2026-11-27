# -*- coding: utf-8 -*-
"""ADB 设备层。

相比旧实现的两点改进：
1. 用 `adb exec-out screencap -p` 一次性拿到 PNG 字节，省掉“设备端写文件 + pull”；
2. 用参数列表调用而不是拼 shell 字符串，路径带空格也不会出错。
"""

import os
import subprocess

import config


class AdbError(RuntimeError):
    """ADB 不可用或命令执行失败。"""


class Adb:
    def __init__(self, path=None, serial=None):
        self.path = path or config.adb_path
        self.serial = config.device_name if serial is None else serial
        # 配置的路径不存在时，退回环境变量里的 adb
        if not os.path.isfile(self.path):
            self.path = 'adb'

    # ------------------------------------------------------------ 基础
    def _cmd(self, *args):
        cmd = [self.path]
        if self.serial:
            cmd += ['-s', self.serial]
        return cmd + [str(a) for a in args]

    def run(self, *args, timeout=20):
        cmd = self._cmd(*args)
        try:
            return subprocess.run(cmd, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            raise AdbError(
                f"找不到 adb 可执行文件: {cmd[0]}\n"
                "请把 config.py 里的 adb_path 改成实际路径，或把 adb 加入 PATH。"
            )
        except subprocess.TimeoutExpired:
            raise AdbError(f"adb 命令超时({timeout}s): {' '.join(cmd)}")

    def shell(self, *args):
        return self.run('shell', *args)

    # ------------------------------------------------------------ 设备
    def devices(self):
        out = self.run('devices').stdout.decode('utf-8', 'ignore')
        return [line.split('\t')[0] for line in out.splitlines()[1:] if '\tdevice' in line]

    def is_connected(self):
        try:
            devices = self.devices()
        except AdbError:
            return False
        return self.serial in devices if self.serial else bool(devices)

    # ------------------------------------------------------------ 截图
    def screencap(self, path=None):
        path = path or config.SCREENSHOT
        proc = self.run('exec-out', 'screencap', '-p')
        if proc.returncode == 0 and proc.stdout:
            tmp = path + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(proc.stdout)
            os.replace(tmp, path)
        else:
            # 极老的 adb 不支持 exec-out 时兜底
            self.shell('screencap', '-p', '/sdcard/screen.png')
            self.run('pull', '/sdcard/screen.png', path)
        return path

    # ------------------------------------------------------------ 输入
    def tap(self, x, y):
        self.shell('input', 'tap', int(x), int(y))

    def swipe(self, x1, y1, x2, y2, duration=config.SWIPE_DURATION):
        self.shell('input', 'swipe', int(x1), int(y1), int(x2), int(y2), int(duration))

    def sendevent(self, device, etype, code, value):
        self.shell('sendevent', device, etype, code, value)
