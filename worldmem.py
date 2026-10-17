# -*- coding: utf-8 -*-
"""
worldmem.py -- 直接读 blockmap.bin（内存为主的第一块）。

和 /dump 的差别：
    /dump      游戏 → JSON 文本 → HTTP → Python 解析    (几十万方块时几秒)
    blockmap   游戏 → 二进制写 mmap → Python mmap 读    (毫秒)

用法：
    from worldmem import WorldMem
    w = WorldMem.refresh(-8160, 60, 266, -8120, 80, 278)   # 让游戏写一次
    t = w.block(-8140, 67, 272)                            # 单格查询，O(1)
    drops = w.drop_below(-8140, 67, 272)                   # 往下几格实地

写入是游戏主线程做的，读侧靠 seq 前后一致判断有没有被撕裂。
"""
import os
import struct
import time

import aic

PATH = r'D:\mc-road-builder\blockmap.bin'
MAGIC = 0x504D4C42          # "BLMP"
HEADER = 48
AIR = ('空气', '洞穴空气', '虚空空气')


class WorldMem:
    def __init__(self):
        self.blocks = {}
        self.palette = []
        self.box = (0, 0, 0, 0, 0, 0)
        self.seq = 0
        self.read_ms = 0.0

    # ---------- 写入（让游戏导出） ----------
    @staticmethod
    def export(x0, y0, z0, x1, y1, z1, timeout=60):
        r = aic.get('/blockmap?x0=%d&y0=%d&z0=%d&x1=%d&y1=%d&z1=%d'
                    % (x0, y0, z0, x1, y1, z1), t=timeout)
        return str(r.get('result', ''))

    # ---------- 读取 ----------
    def load(self):
        t0 = time.time()
        with open(PATH, 'rb') as f:
            size = os.path.getsize(PATH)
            data = f.read(size)
        magic, ver, seq, count = struct.unpack_from('<4i', data, 0)
        if magic != MAGIC:
            raise ValueError('bad magic 0x%08X (expected 0x%08X)' % (magic, MAGIC))
        x0, y0, z0, x1, y1, z1 = struct.unpack_from('<6i', data, 16)
        pal_count = struct.unpack_from('<i', data, 40)[0]

        pos = HEADER
        names = []
        for _ in range(pal_count):
            ln = struct.unpack_from('<i', data, pos)[0]
            pos += 4
            names.append(data[pos:pos + ln].decode('utf-8'))
            pos += ln

        blocks = {}
        for _ in range(count):
            dx, dy, dz, pi = struct.unpack_from('<hbhHx', data, pos)   # 8 bytes incl. pad
            pos += 8
            blocks[(x0 + dx, y0 + dy, z0 + dz)] = names[pi]

        if self.seq and seq <= self.seq:
            raise RuntimeError('stale blockmap: seq %d -> %d (export likely timed out)'
                               % (self.seq, seq))
        self.blocks = blocks
        self.palette = names
        self.box = (x0, y0, z0, x1, y1, z1)
        self.seq = seq
        self.read_ms = (time.time() - t0) * 1000.0
        return self

    @classmethod
    def refresh_near(cls, cx, cz, rx=12, y_lo=None, y_hi=None, timeout=60, retries=2):
        """以 (cx, cz) 为中心的 box —— 不要掺玩家坐标。

        掺了玩家坐标会让 box 横跨几百格，/blockmap 超时后读到旧文件，
        于是每一次回读都"成功"（unify 的 placed=40 假数据就是这么来的）。

        ⚠️ 并且**必须校验盒子本身**：`refresh_near` 每次都是新实例，实例的
        `self.seq` 是 0，load() 里的 seq 递增检查在这个路径上形同虚设 ——
        `/blockmap` 一旦超时，读到的是上一次请求写的旧文件（盒子完全不同），
        此时 `in_box()` 全 false → `block()` 返回 None，看上去像"一片空气"。
        实测就是这样把 x=-8300 附近读成"从 y=61 到 74 全是空气"的。
        """
        if y_lo is None:
            y_lo = 40
        if y_hi is None:
            y_hi = 90
        want = (cx - rx, y_lo, cz - rx, cx + rx, y_hi, cz + rx)
        last = None
        for _ in range(max(1, retries + 1)):
            res = cls.export(*want, timeout=timeout)
            if not res.startswith('ok'):
                last = 'export failed: %s' % res
                continue
            w = cls().load()
            if tuple(w.box) == want:
                return w
            last = 'box mismatch: want %s got %s' % (want, tuple(w.box))
        raise RuntimeError('refresh_near(%d,%d,rx=%d): %s' % (cx, cz, rx, last))

    @classmethod
    def refresh(cls, x0, y0, z0, x1, y1, z1, timeout=60):
        res = cls.export(x0, y0, z0, x1, y1, z1, timeout=timeout)
        if not res.startswith('ok'):
            raise RuntimeError('export failed: %s' % res)
        w = cls().load()
        if tuple(w.box) != (x0, y0, z0, x1, y1, z1):
            raise RuntimeError('box mismatch: want %s got %s'
                               % ((x0, y0, z0, x1, y1, z1), tuple(w.box)))
        return w

    # ---------- 查询 ----------
    def in_box(self, x, y, z):
        x0, y0, z0, x1, y1, z1 = self.box
        return x0 <= x <= x1 and y0 <= y <= y1 and z0 <= z <= z1

    def loaded(self, x, y, z):
        # 这一格的数据到底读没读到（区分空气和没读）
        if (x, y, z) in self.blocks:
            return True
        return self.in_box(x, y, z)

    def block(self, x, y, z):
        # box 范围内查不到 -> 空气；box 范围外 -> None(未加载)
        t = self.blocks.get((x, y, z))
        if t is not None:
            return t
        if self.in_box(x, y, z):
            return '空气'
        return None

    def is_air(self, x, y, z):
        t = self.block(x, y, z)
        return t is None or t in AIR

    def is_solid(self, x, y, z):
        t = self.block(x, y, z)
        return t is not None and t not in AIR

    def drop_below(self, x, y, z, maximum=24):
        # 往下几格踩到实地；看不到底（真的没读）返回 None
        for d in range(1, maximum + 1):
            if not self.loaded(x, y - d, z):
                return None
            t = self.block(x, y - d, z)
            if t is not None and t not in AIR:
                return d - 1
        return None

    def column(self, x, z, y_top, depth):
        return [(y, self.block(x, y, z)) for y in range(y_top, y_top - depth - 1, -1)]

    def stats(self):
        return {
            'blocks': len(self.blocks),
            'palette': len(self.palette),
            'box': self.box,
            'seq': self.seq,
            'read_ms': round(self.read_ms, 1),
        }


if __name__ == '__main__':
    s = aic.state()
    px, py, pz = int(s['x']), int(s['y']), int(s['z'])
    print('player (%d,%d,%d)' % (px, py, pz))

    t0 = time.time()
    w = WorldMem.refresh(px - 40, 50, pz - 12, px + 40, 90, pz + 12)
    total_ms = (time.time() - t0) * 1000.0

    print()
    print('=== WorldMem ===')
    for k, v in w.stats().items():
        print('  %-8s %s' % (k, v))
    print('  总耗时   %.1f ms  (含 HTTP 往返)' % total_ms)
    print('  纯读取   %.1f ms' % w.read_ms)
    print('  -> µs/块  %.2f' % (w.read_ms * 1000.0 / max(1, len(w.blocks))))

    print()
    print('=== 单格查询（应该是 O(1)） ===')
    for (x, y, z) in [(px, py - 1, pz), (px, py, pz), (px + 2, py, pz), (px, py + 3, pz)]:
        print('  (%d,%d,%d) = %s  drop=%s' % (x, y, z, w.block(x, y, z), w.drop_below(x, y, z)))
