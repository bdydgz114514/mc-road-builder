# -*- coding: utf-8 -*-
"""
analyze.py -- 整条路全面体检。

对每一列报告：
    路面高度（众数）        应该是 68
    该列 5 格里有几格是圆石   应该 5
    该列有没有非圆石的"杂色"  （地形/泥土混进路面）
    该列下方有没有支撑        （悬空 = 掉下去的风险）
最后按段汇总，指出哪一段需要抬高、哪一段需要削平、哪一段要补格。
"""
import sys

from worldmem import WorldMem
from collections import Counter

AIR = ('空气', '洞穴空气', '虚空空气')
DECK = 68
Z0, Z1 = 270, 274
X_START, X_END = -8232, -7950        # 2026-10 更新：东端已推进到 -7950
BRIDGE = (-7982, -7966)              # 拱桥段：路面高度本来就不是 68，别报异常


def solid(t):
    return t is not None and t not in AIR


def main():
    report = []
    for x0 in range(X_START, X_END + 1, 22):
        x1 = min(x0 + 21, X_END)
        wm = WorldMem.refresh_near((x0 + x1) // 2, (Z0 + Z1) // 2, rx=14,
                                   y_lo=55, y_hi=82)
        for x in range(x0, x1 + 1):
            tops = []
            n_cobble = 0
            n_other = 0
            n_air = 0
            n_float = 0
            for z in range(Z0, Z1 + 1):
                top = None
                for y in range(82, 55, -1):
                    t = wm.block(x, y, z)
                    if solid(t):
                        top = y
                        tops.append(y)
                        break
                t68 = wm.block(x, DECK, z)
                if t68 is not None and '圆石' in str(t68):
                    n_cobble += 1
                elif t68 is None or t68 in AIR:
                    n_air += 1
                else:
                    n_other += 1
                # 悬空检查：deck 位置是圆石但下方是空气
                if t68 is not None and '圆石' in str(t68):
                    below = wm.block(x, DECK - 1, z)
                    if below is None or below in AIR:
                        n_float += 1
            mode = Counter(tops).most_common(1)[0] if tops else (None, 0)
            in_bridge = BRIDGE[0] <= x <= BRIDGE[1]
            report.append({
                'x': x, 'top': mode[0], 'cobble': n_cobble,
                'air': n_air, 'other': n_other, 'float': n_float,
                'bridge': in_bridge,
            })

    # 按段汇总
    print("=== 逐列（每列只打关键异常）===")
    segs = {}
    for r in report:
        seg = (r['x'] // 22) * 22
        segs.setdefault(seg, []).append(r)

    problem = []
    for seg in sorted(segs):
        rows = segs[seg]
        xs = [r['x'] for r in rows]
        # 拱桥段的路面高度本来就不是 68，按"高度异常"报是误报，单独标注
        rows = [r for r in rows if not r.get('bridge')]
        if not rows:
            print("  x %5d..%5d  拱桥段（路面高度随拱形变化，不按 68 校验）" % (xs[0], xs[-1]))
            continue
        bad_top = [r for r in rows if r['top'] is not None and r['top'] != DECK]
        no_road = [r for r in rows if r['cobble'] == 0]
        partial = [r for r in rows if 0 < r['cobble'] < 5]
        other = [r for r in rows if r['other'] > 0]
        floated = [r for r in rows if r['float'] > 0]
        tags = []
        if no_road:
            tags.append('无路面%d列' % len(no_road))
        if partial:
            tags.append('残缺%d列' % len(partial))
        if bad_top:
            hs = Counter(r['top'] for r in bad_top).most_common(3)
            tags.append('高度异常%s' % hs)
        if other:
            tags.append('杂色%d列' % len(other))
        if floated:
            tags.append('悬空%d列' % len(floated))
        print("  x %5d..%5d  %s" % (xs[0], xs[-1], '  '.join(tags) if tags else 'OK'))
        if tags:
            problem.append((xs[0], xs[-1], tags))

    print()
    print("=== 需要处理的段 ===")
    if not problem:
        print("  无（整条路都合格）")
    for x0, x1, tags in problem:
        print("  x %5d..%5d  %s" % (x0, x1, '  '.join(tags)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
