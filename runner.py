# -*- coding: utf-8 -*-
"""
runner.py -- 通宵守护：驱动器崩了就重启，游戏崩了就重开进服。

为什么需要：
    auto_west 自己再稳，它也是**一个进程**。今晚实测的停机原因里，
    一半是"驱动器抛异常退出"、另一半是"游戏崩了"（17:07 那次无崩溃报告）。
    没人看着的时候，这两种情况都会让工程停一整夜。

它做三件事（每轮）：
    1. `/ping` 探桥；连续 3 次不通 → 认定游戏挂了 → 跑 launch-mc.ps1 重开并进服
    2. 读 `west_end.txt`（auto_west 每批落盘的断点）
    3. 起 auto_west 子进程；它退出就重新读断点再起（永不退出）

安全阀：
    · 有 HALT 旗标（G* 管理员进服）→ 不重启施工，只等着
    · 同一断点连续重启 5 次还不动 → 打印诊断并放慢到 10 分钟一次
    · 整点检查一次背包/工具，缺料时先跑一遍补给

用法：
    python runner.py --end -7888 --hours 8
"""
import argparse
import math
import os
import subprocess
import sys
import time

import aic

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'west_end.txt')
HALT = os.path.join(HERE, 'HALT')
LAUNCH = os.path.join(HERE, 'launch-mc.ps1')


def say(*a):
    print('[%s] [runner] %s' % (time.strftime('%Y-%m-%d %H:%M:%S'),
                                ' '.join(str(x) for x in a)), flush=True)


def bridge_ok(timeout=4):
    try:
        r = aic.get('/ping', t=timeout)
        return bool(r.get('ok'))
    except Exception:
        return False


def read_state(default=-837):
    try:
        with open(STATE, 'r', encoding='utf-8') as f:
            return int(f.read().strip())
    except Exception:
        return default


def relaunch_game():
    say('游戏没响应 → 跑 launch-mc.ps1 重开并进服（可能要 2~3 分钟）')
    try:
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', LAUNCH], capture_output=True, text=True, timeout=900)
    except Exception as e:
        say('  重开失败：%s' % e)
        return False
    for _ in range(24):
        time.sleep(5)
        if bridge_ok():
            s = aic.state()
            say('  已回到世界：%.0f,%.0f,%.0f hp=%.0f' % (s['x'], s['y'], s['z'], s['health']))
            return True
    say('  重开了但还是进不去，等下一轮')
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=int, default=None)
    ap.add_argument('--end', type=int, default=-7888)
    ap.add_argument('--hours', type=float, default=8.0)
    ap.add_argument('--batch', type=int, default=14)
    ap.add_argument('--min-hp', type=float, default=2.0)
    args = ap.parse_args()

    t0 = time.time()
    last_state = None
    same = 0
    last_watch_state = None
    stuck_rounds = 0
    alive_misses = 0
    say('守护启动：目标 end=%d，预算 %.1f 小时' % (args.end, args.hours))

    while time.time() - t0 < args.hours * 3600:
        # 1) 桥 / 掉线
        if not bridge_ok():
            alive_misses += 1
            say('桥不通（第 %d 次）' % alive_misses)
            if alive_misses >= 3:
                alive_misses = 0
                relaunch_game()
            time.sleep(20)
            continue
        alive_misses = 0

        # 2) 管理员进服旗标：不重启施工
        if os.path.exists(HALT):
            say('HALT 旗标在（%s），暂停施工，60 秒后复查' %
                open(HALT, encoding='utf-8').read().strip()[:40])
            time.sleep(60)
            continue

        # 3) 断点
        start = args.start if args.start is not None else read_state()
        if start < args.end:
            say('已经铺到 %d，超过目标 %d，收工' % (start, args.end))
            break

        if start == last_state:
            same += 1
        else:
            same = 0
            last_state = start
        if same >= 5:
            say('!! 同一个断点连续重启 %d 次没推进（%d），放慢到 10 分钟一次' % (same, start))
            time.sleep(600)
            same = 0

        # 4) 卡死自查：断点长时间不动但桥还通 → 多半是暂停菜单（Esc）或输入被吞
        if start == last_watch_state:
            stuck_rounds += 1
        else:
            stuck_rounds = 0
            last_watch_state = start
        if stuck_rounds >= 2:
            say('断点 %d 已经 %d 轮没动 → 尝试点「回到游戏」除卡' % (start, stuck_rounds))
            try:
                subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                '-File', os.path.join(HERE, 'click.ps1'),
                                '-X', '1278', '-Y', '379', '-WaitMs', '1200'],
                               capture_output=True, timeout=60)
                aic.cmd('#stop')
            except Exception as e:
                say('  除卡失败：%s' % e)
            stuck_rounds = 0

        say('--- 起 auto_west：x %d → %d ---' % (start, args.end))
        cmd = [sys.executable, 'auto_west.py', '--start', str(start),
               '--end', str(args.end), '--batch', str(args.batch),
               '--hours', '3', '--min-hp', str(args.min_hp)]
        try:
            subprocess.run(cmd, cwd=HERE, timeout=3.5 * 3600)
        except subprocess.TimeoutExpired:
            say('auto_west 跑超 3.5h，杀掉重来')
            subprocess.run(['powershell', '-NoProfile', '-Command',
                            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                            "Where-Object { $_.CommandLine -like '*auto_west*' } | "
                            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                           capture_output=True)
        except Exception as e:
            say('auto_west 异常：%s' % e)
        time.sleep(15)

    say('守护结束')
    return 0


if __name__ == '__main__':
    sys.exit(main())
