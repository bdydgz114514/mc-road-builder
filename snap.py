# -*- coding: utf-8 -*-
"""
snap.py -- 自动截图。出问题自己拍，不再问用户"你看到什么了"。

用法：
    from snap import snap
    snap('gate-failed-x-8092')        # 命名截图，存到 shots/

文件名带时间戳，同一原因多次触发也不会互相覆盖。
只在 Windows + 有游戏窗口时工作；截不到就返回 None，不抛异常（不能因为截图失败而中断任务）。
"""
import os
import subprocess
import time

SHOT_PS1 = r'D:\mc-road-builder\mc-shot.ps1'
RAW = r'D:\mc-road-builder\mc-window.png'
SHOT_DIR = r'D:\mc-road-builder\shots'


def snap(tag='snap'):
    """截一张，返回保存路径（失败返回 None）。"""
    try:
        os.makedirs(SHOT_DIR, exist_ok=True)
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', SHOT_PS1],
            capture_output=True, timeout=60)
        if not os.path.exists(RAW):
            return None
        safe = ''.join(c if (c.isalnum() or c in '-_') else '_' for c in str(tag))[:48]
        out = os.path.join(SHOT_DIR, '%s_%s.png' % (time.strftime('%H%M%S'), safe))
        with open(RAW, 'rb') as f:
            data = f.read()
        with open(out, 'wb') as f:
            f.write(data)
        print('  [snap] %s' % out)
        return out
    except Exception as e:
        print('  [snap failed] %s' % e)
        return None


if __name__ == '__main__':
    import sys
    print(snap(sys.argv[1] if len(sys.argv) > 1 else 'manual'))
