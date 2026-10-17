# -*- coding: utf-8 -*-
"""
shots_daemon.py -- 每 15 秒截一张游戏画面，落到 shots/live/。

为什么要常驻而不是"需要时再截"：
    截图要靠 mc-shot.ps1 找窗口 + CopyFromScreen，单次 1~2 秒；
    如果每次都在关键路径上现截，会把施工节奏拖慢。
    常驻后台按固定节奏落盘，需要时直接读最新帧，零等待。

注意（实测坑）：
    · 窗口被最小化时 `CopyFromScreen` 拿不到游戏画面，会**静默复制上一张**。
      所以每帧都记 sha256，如果连续多帧完全一致 → 记一条 WARN（可能窗口丢了）。
    · 只保留最近 --keep 帧，避免撑爆硬盘。
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SHOT_PS1 = os.path.join(HERE, 'mc-shot.ps1')
RAW = os.path.join(HERE, 'mc-window.png')
LIVE = os.path.join(HERE, 'shots', 'live')


def say(*a):
    print('[%s] [live] %s' % (time.strftime('%H:%M:%S'), ' '.join(str(x) for x in a)), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', type=float, default=15.0)
    ap.add_argument('--keep', type=int, default=120)
    args = ap.parse_args()

    os.makedirs(LIVE, exist_ok=True)
    last_hash = None
    same = 0
    n = 0
    say('开始，每 %.0fs 一帧，保留 %d 帧' % (args.interval, args.keep))
    while True:
        t0 = time.time()
        try:
            subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                            '-File', SHOT_PS1], capture_output=True, timeout=60)
            if os.path.exists(RAW):
                data = open(RAW, 'rb').read()
                h = hashlib.sha256(data).hexdigest()
                if h == last_hash:
                    same += 1
                    if same in (3, 10, 30):
                        say('WARN 连续 %d 帧完全一样（窗口可能又被最小化）' % same)
                else:
                    same = 0
                last_hash = h
                out = os.path.join(LIVE, time.strftime('%H%M%S') + '.png')
                with open(out, 'wb') as f:
                    f.write(data)
                n += 1
        except Exception as e:
            say('截图失败：%s' % e)

        # 只留最近 keep 帧
        try:
            files = sorted(os.listdir(LIVE))
            if len(files) > args.keep:
                for f in files[:-args.keep]:
                    os.remove(os.path.join(LIVE, f))
        except Exception:
            pass

        time.sleep(max(0.5, args.interval - (time.time() - t0)))


if __name__ == '__main__':
    sys.exit(main())
