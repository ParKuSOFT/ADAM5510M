# -*- coding: utf-8 -*-
"""Экспорт рисунка плоттера в SVG."""


def write_svg(path, plotter):
    spm = float(plotter.spm)
    w, h = plotter.width, plotter.height
    with plotter.lock:
        segs = list(plotter.segments)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" '
           'viewBox="0 0 %g %g">' % (w, h, w, h),
           '<rect width="%g" height="%g" fill="white" stroke="#999" stroke-width="0.5"/>' % (w, h),
           '<g stroke="black" stroke-width="0.4" stroke-linecap="round" fill="none">']
    # объединяем подряд идущие параллельные отрезки
    runs = []
    for x0, y0, x1, y1 in segs:
        if runs:
            a0, b0, a1, b1 = runs[-1]
            if (a1, b1) == (x0, y0) and (a1 - a0) * (y1 - y0) == (b1 - b0) * (x1 - x0) \
                    and (a1 - a0) * (x1 - x0) + (b1 - b0) * (y1 - y0) > 0:
                runs[-1] = (a0, b0, x1, y1)
                continue
        runs.append((x0, y0, x1, y1))
    for x0, y0, x1, y1 in runs:
        out.append('<line x1="%.3f" y1="%.3f" x2="%.3f" y2="%.3f"/>' % (
            x0 / spm, h - y0 / spm, x1 / spm, h - y1 / spm))
    out.append("</g></svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
