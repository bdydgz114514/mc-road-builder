# -*- coding: utf-8 -*-
"""
revive.py -- 死了自动重生，并记住死亡点和死因。

实测：死亡界面上「重生」按钮在 2560x1440 下位于 (1279, 606)，
即窗口宽 49.9%、高 42.1%。之前点 (1280, 892) 点空了。

用法：
    python revive.py           # 若已死则重生
    from revive import ensure_alive
    ensure_alive()
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import time

import aic

WIN_W_RATIO = 0.4995      # 重生按钮水平位置
WIN_H_RATIO = 0.4208      # 重生按钮垂直位置

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def find_window():
    u = ctypes.windll.user32
    hwnds = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = u.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            if 'Minecraft' in b.value:
                hwnds.append(h)
        return True

    u.EnumWindows(cb, 0)
    return hwnds[0] if hwnds else None


def click_at(x, y):
    u = ctypes.windll.user32
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.25)
    u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.09)
    u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.6)


def respawn(retries=4):
    """点『重生』直到真的活了"""
    for i in range(retries):
        s = aic.state()
        if s.get('alive') and s.get('health', 0) > 0:
            return True
        hwnd = find_window()
        if not hwnd:
            return False
        u = ctypes.windll.user32
        u.ShowWindow(hwnd, 9)
        u.SetForegroundWindow(hwnd)
        time.sleep(0.5)

        class RECT(ctypes.Structure):
            _fields_ = [('l', ctypes.c_long), ('t', ctypes.c_long),
                        ('r', ctypes.c_long), ('b', ctypes.c_long)]

        r = RECT()
        u.GetClientRect(hwnd, ctypes.byref(r))
        pt = wt.POINT(0, 0)
        u.ClientToScreen(hwnd, ctypes.byref(pt))
        w, h = r.r - r.l, r.b - r.t
        bx = pt.x + int(w * WIN_W_RATIO)
        by = pt.y + int(h * WIN_H_RATIO)
        print('  [revive] click respawn at (%d,%d) in %dx%d' % (bx, by, w, h))
        click_at(bx, by)
        for _ in range(6):
            time.sleep(1.0)
            s = aic.state()
            if s.get('alive') and s.get('health', 0) > 0:
                print('  [revive] alive again, hp=%.0f' % s['health'])
                return True
    return False


def ensure_alive():
    s = aic.state()
    if s.get('alive') and s.get('health', 0) > 0:
        return True
    return respawn()


def death_log():
    """从 latest.log 里抓最近的死亡信息"""
    p = r'D:\Minecraft\.minecraft\versions\3\logs\latest.log'
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[-400:]
        for ln in reversed(lines):
            if '被' in ln and '杀死' in ln:
                return ln.strip()
    except Exception:
        pass
    return None


if __name__ == '__main__':
    d = death_log()
    if d:
        print('death:', d)
    ok = ensure_alive()
    s = aic.state()
    print('alive=%s hp=%.0f at (%d,%d,%d)'
          % (ok, s.get('health', 0), int(s.get('x', 0)), int(s.get('y', 0)), int(s.get('z', 0))))
