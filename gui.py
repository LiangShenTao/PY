# -*- coding: utf-8 -*-
"""Tkinter 控制面板：设置参数、开始/停止任务、查看实时日志。

运行:
    py -3.13 gui.py
"""

import contextlib
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from types import SimpleNamespace

import config
from actions.view import normalize_view
from device.adb import Adb
from robot import Robot
from tasks import ORDER, build_task
from vision.ocr import format_resources, read_resources
from vision.scene import detect as detect_scene

TASKS = [
    ('进入游戏', 'launch'),
    ('视角归位', 'view'),
    ('界面识别', 'scene'),
    ('收资源', 'collect'),
    ('捐兵', 'donate'),
    ('训练部队', 'train'),
    ('自动战斗', 'battle'),
    ('重新加载游戏', 'reload'),
    ('全部（收资源→捐兵→训练）', 'all'),
]
TASK_KEYS = dict(TASKS)


class _QueueWriter:
    """把 print 输出转发到日志队列，工作线程不直接碰 Tk 控件。"""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(('log', text))

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title('部落冲突自动化助手')
        root.geometry('860x640')
        root.minsize(720, 520)

        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None

        self._build_settings()
        self._build_controls()
        self._build_log()

        self.root.after(100, self._drain_log)

    # ------------------------------------------------------------ UI
    def _build_settings(self):
        box = ttk.LabelFrame(self.root, text='运行设置', padding=10)
        box.pack(fill='x', padx=10, pady=(10, 4))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text='ADB 路径').grid(row=0, column=0, sticky='w', padx=(0, 8), pady=3)
        self.adb_path = tk.StringVar(value=config.adb_path)
        ttk.Entry(box, textvariable=self.adb_path).grid(
            row=0, column=1, columnspan=2, sticky='we', pady=3)

        ttk.Label(box, text='设备名').grid(row=1, column=0, sticky='w', padx=(0, 8), pady=3)
        self.device_name = tk.StringVar(value=config.device_name)
        ttk.Entry(box, textvariable=self.device_name, width=20).grid(
            row=1, column=1, sticky='w', pady=3)
        ttk.Label(box, text='（adb devices 里看到的序列号）',
                  foreground='#888').grid(row=1, column=2, sticky='w', padx=6)

        ttk.Label(box, text='任务').grid(row=2, column=0, sticky='w', padx=(0, 8), pady=3)
        self.task = tk.StringVar(value=TASKS[0][0])
        ttk.Combobox(box, textvariable=self.task, state='readonly',
                     values=[name for name, _ in TASKS]).grid(
            row=2, column=1, sticky='w', pady=3)

        opts = ttk.Frame(box)
        opts.grid(row=3, column=1, columnspan=2, sticky='w', pady=3)

        self.loop = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text='循环执行', variable=self.loop).pack(side='left')

        ttk.Label(opts, text='间隔(秒)').pack(side='left', padx=(12, 4))
        self.interval = tk.StringVar(value='10')
        ttk.Entry(opts, textvariable=self.interval, width=6).pack(side='left')

        self.apply = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text='训练时一键应用配兵', variable=self.apply).pack(
            side='left', padx=12)

        self.dry_run = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text='模拟运行（不实际点击）', variable=self.dry_run).pack(
            side='left')

        extra = ttk.Frame(box)
        extra.grid(row=4, column=1, columnspan=2, sticky='w', pady=3)
        ttk.Label(extra, text='捐兵次数').pack(side='left')
        self.donate_count = tk.StringVar(value='3')
        tk.Spinbox(extra, from_=1, to=10, width=5,
                   textvariable=self.donate_count).pack(side='left', padx=(4, 12))
        ttk.Label(extra, text='捐兵需要 modle/donate_request.png 与 donate_troop.png 模板',
                  foreground='#888').pack(side='left')

        reload_box = ttk.Frame(box)
        reload_box.grid(row=5, column=1, columnspan=2, sticky='w', pady=3)
        self.restart = tk.BooleanVar(value=False)
        ttk.Checkbutton(reload_box, text='重新加载时找不到按钮就重启客户端',
                        variable=self.restart).pack(side='left')
        ttk.Label(reload_box, text='（强制关闭并重新打开游戏）',
                  foreground='#888').pack(side='left', padx=6)

        view_box = ttk.Frame(box)
        view_box.grid(row=6, column=1, columnspan=2, sticky='w', pady=3)
        self.auto_view = tk.BooleanVar(value=True)
        ttk.Checkbutton(view_box, text='开始任务前自动把视角缩到最大',
                        variable=self.auto_view).pack(side='left')

        battle_box = ttk.Frame(box)
        battle_box.grid(row=7, column=1, columnspan=2, sticky='w', pady=3)
        ttk.Label(battle_box, text='自动战斗阈值  金币≥').pack(side='left')
        self.min_gold = tk.StringVar(value='1000000')
        tk.Entry(battle_box, textvariable=self.min_gold, width=9).pack(side='left', padx=(2, 8))
        ttk.Label(battle_box, text='圣水≥').pack(side='left')
        self.min_elixir = tk.StringVar(value='500000')
        tk.Entry(battle_box, textvariable=self.min_elixir, width=8).pack(side='left', padx=(2, 8))
        ttk.Label(battle_box, text='黑油≥').pack(side='left')
        self.min_dark = tk.StringVar(value='0')
        tk.Entry(battle_box, textvariable=self.min_dark, width=6).pack(side='left', padx=(2, 8))
        ttk.Label(battle_box, text='最多搜索').pack(side='left')
        self.max_skips = tk.StringVar(value='8')
        tk.Entry(battle_box, textvariable=self.max_skips, width=3).pack(side='left', padx=(2, 2))
        ttk.Label(battle_box, text='次').pack(side='left')
        ttk.Label(battle_box, text='连续打').pack(side='left', padx=(8, 0))
        self.battles = tk.StringVar(value='5')
        tk.Entry(battle_box, textvariable=self.battles, width=3).pack(side='left', padx=(2, 2))
        ttk.Label(battle_box, text='场').pack(side='left')
        self.own_battle = tk.BooleanVar(value=True)
        ttk.Checkbutton(battle_box, text='游戏自动战斗不可用时自己放兵',
                        variable=self.own_battle).pack(side='left', padx=(10, 0))

    def _build_controls(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill='x', padx=10, pady=4)

        self.btn_start = ttk.Button(bar, text='开始', command=self.on_start)
        self.btn_start.pack(side='left')
        self.btn_stop = ttk.Button(bar, text='停止', command=self.on_stop,
                                   state='disabled')
        self.btn_stop.pack(side='left', padx=6)
        ttk.Button(bar, text='识别当前界面',
                   command=self.on_identify).pack(side='left', padx=6)
        ttk.Button(bar, text='读取资源',
                   command=self.on_resources).pack(side='left', padx=6)
        ttk.Button(bar, text='清空日志',
                   command=self.clear_log).pack(side='left', padx=6)

        self.status = tk.StringVar(value='就绪')
        ttk.Label(bar, textvariable=self.status,
                  foreground='#0a7').pack(side='right')

    def _build_log(self):
        self.log_text = scrolledtext.ScrolledText(
            self.root, wrap='word', font=('Consolas', 10), state='disabled')
        self.log_text.pack(fill='both', expand=True, padx=10, pady=(4, 10))

    # ------------------------------------------------------------ 日志
    def _append(self, text):
        self.log_text.config(state='normal')
        self.log_text.insert('end', text)
        self.log_text.see('end')
        self.log_text.config(state='disabled')

    def _drain_log(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == 'log':
                    self._append(payload)
                elif kind == 'status':
                    self.status.set(payload)
                elif kind == 'done':
                    self.btn_start.config(state='normal')
                    self.btn_stop.config(state='disabled')
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)

    def clear_log(self):
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')

    # ------------------------------------------------------------ 设备
    def _robot(self):
        return Robot(adb=Adb(path=self.adb_path.get().strip(),
                             serial=self.device_name.get().strip()))

    def _report_scene(self, robot):
        image = robot.shot()
        scene, hits = detect_scene(image)
        print(f'当前界面: {scene.value}')
        for name, found in hits.items():
            print(f'  锚点 {name}: 中心 {found.center} 置信度 {found.score:.2f}')
        print(f'  资源: {format_resources(read_resources(image))}')
        self.log_queue.put(('status', f'当前界面: {scene.value}'))

    def on_identify(self):
        if self.worker and self.worker.is_alive():
            self._append('任务运行中，先停止再识别\n')
            return
        threading.Thread(target=self._identify, daemon=True).start()

    def _identify(self):
        try:
            with contextlib.redirect_stdout(_QueueWriter(self.log_queue)):
                print('正在截图识别…')
                robot = self._robot()
                if not robot.adb.is_connected():
                    print('没有检测到设备，请确认模拟器已启动、USB 调试已打开')
                    return
                self._report_scene(robot)
        except Exception as exc:
            self._append(f'出错: {exc}\n')

    def on_resources(self):
        if self.worker and self.worker.is_alive():
            self._append('任务运行中，先停止再读取\n')
            return

        def read():
            try:
                with contextlib.redirect_stdout(_QueueWriter(self.log_queue)):
                    print('正在读取资源…')
                    robot = self._robot()
                    if not robot.adb.is_connected():
                        print('没有检测到设备，请确认模拟器已启动、USB 调试已打开')
                        return
                    print(format_resources(read_resources(robot.shot())))
            except Exception as exc:
                self._append(f'出错: {exc}\n')

        threading.Thread(target=read, daemon=True).start()

    # ------------------------------------------------------------ 运行
    def on_start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            interval = float(self.interval.get())
            donate_count = int(self.donate_count.get())
            min_gold = int(self.min_gold.get())
            min_elixir = int(self.min_elixir.get())
            min_dark = int(self.min_dark.get())
            max_skips = int(self.max_skips.get())
            battles = int(self.battles.get())
        except ValueError:
            self._append('参数格式不对：间隔/捐兵次数/战斗阈值都需要填数字\n')
            return
        if interval < 1:
            self._append('间隔至少 1 秒\n')
            return

        args = SimpleNamespace(donate_troop='donate_troop.png',
                               donate_count=donate_count,
                               no_apply=not self.apply.get(),
                               restart=self.restart.get(),
                               min_gold=min_gold,
                               min_elixir=min_elixir,
                               min_dark=min_dark,
                               max_skips=max_skips,
                               battles=battles,
                               own_battle=self.own_battle.get())
        config_kw = dict(
            task_key=TASK_KEYS[self.task.get()],
            args=args,
            interval=interval,
            loop=self.loop.get(),
            adb_path=self.adb_path.get().strip(),
            device=self.device_name.get().strip(),
            dry_run=self.dry_run.get(),
            auto_view=self.auto_view.get(),
        )

        self.stop_event.clear()
        self.btn_start.config(state='disabled')
        self.btn_stop.config(state='normal')
        self.status.set('运行中…')
        self.worker = threading.Thread(target=self._run, kwargs=config_kw,
                                       daemon=True)
        self.worker.start()

    def on_stop(self):
        self.stop_event.set()
        self._append('已请求停止：当前动作结束后生效\n')
        self.status.set('正在停止…')

    def _run(self, task_key, args, interval, loop, adb_path, device, dry_run,
             auto_view):
        try:
            with contextlib.redirect_stdout(_QueueWriter(self.log_queue)):
                print(f'=== 连接设备 {device} ===')
                robot = Robot(adb=Adb(path=adb_path, serial=device),
                              dry_run=dry_run)
                robot.stop_event = self.stop_event
                if not robot.adb.is_connected():
                    print('没有检测到设备，请确认模拟器已启动、USB 调试已打开')
                    return
                print('设备已连接')

                if task_key == 'scene':
                    self._report_scene(robot)
                    return

                if task_key == 'view':
                    normalize_view(robot)
                    return

                if auto_view and task_key in ('collect', 'donate', 'train', 'all'):
                    normalize_view(robot)

                names = ORDER if task_key == 'all' else [task_key]
                round_no = 0
                while not self.stop_event.is_set():
                    round_no += 1
                    print(f'--- 第 {round_no} 轮 ---')
                    self._run_round(robot, names, args)
                    if not loop:
                        break
                    print(f'等待 {interval:.1f} 秒（点停止可中断）')
                    if self.stop_event.wait(interval):
                        break
                print('已停止' if self.stop_event.is_set() else '完成')
        except Exception as exc:
            self._append(f'运行出错: {exc}\n')
        finally:
            self.log_queue.put(('done', None))
            self.log_queue.put(('status', '就绪'))

    def _run_round(self, robot, names, args):
        """按顺序跑任务，任意一个成功就结束本轮。"""
        for name in names:
            if self.stop_event.is_set():
                return
            task = build_task(name, args)
            print(f'[{task.name}] 开始')
            try:
                result = task.run(robot)
            except Exception as exc:
                print(f'[{task.name}] 异常: {exc}')
                continue
            print(f'[{task.name}] -> {result.value}')
            if result.name == 'SUCCESS':
                return


def main():
    try:  # Windows 高分屏下避免界面发虚
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
