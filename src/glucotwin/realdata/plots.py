"""Minimal dependency-free SVG plots for the real-data report."""

from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd

COLORS = {"actual": "#1f2937", "persistence": "#9ca3af", "ridge": "#2563eb", "hgb": "#d97706"}


def _scale(v, lo, hi, a, b):
    return a + (np.asarray(v, float) - lo) / ((hi - lo) or 1.0) * (b - a)


def trajectory_svg(title: str, actual: pd.DataFrame, preds: dict[str, pd.DataFrame], width=900, height=320) -> str:
    """actual: columns timestamp, glucose (recorded readings). preds[name]: columns target_time, pred."""
    left, right, top, bottom = 50, 150, 30, 40
    t0 = actual["timestamp"].min()
    def minutes(s):
        return (pd.to_datetime(s) - t0).dt.total_seconds().to_numpy() / 60
    xs = [minutes(actual["timestamp"])] + [minutes(p["target_time"]) for p in preds.values()]
    ys = [actual["glucose"].to_numpy()] + [p["pred"].to_numpy() for p in preds.values()]
    xmax = max(float(x.max()) for x in xs if len(x))
    ylo = min(40.0, min(float(np.nanmin(y)) for y in ys if len(y)))
    yhi = max(250.0, max(float(np.nanmax(y)) for y in ys if len(y)))
    X = lambda v: _scale(v, 0, xmax, left, width - right)  # noqa: E731
    Y = lambda v: _scale(v, ylo, yhi, height - bottom, top)  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" '
           f'font-size="11"><rect width="100%" height="100%" fill="white"/>',
           f'<text x="{left}" y="18" font-size="13">{escape(title)}</text>']
    for g in (70, 180):
        out.append(f'<line x1="{left}" x2="{width - right}" y1="{Y(g):.1f}" y2="{Y(g):.1f}" stroke="#ef4444" '
                   f'stroke-dasharray="4 3" stroke-width="0.8"/><text x="{left - 30}" y="{Y(g) + 4:.1f}">{g}</text>')
    for h in range(0, int(xmax) + 1, 360):
        out.append(f'<text x="{X(h):.1f}" y="{height - 22}" text-anchor="middle">{h // 60} h</text>')

    def poly(x, y, color, w, dots=False):
        segs, cur = [], []
        for xi, yi in zip(x, y, strict=True):
            if np.isfinite(yi):
                cur.append(f"{X(xi):.1f},{Y(yi):.1f}")
            elif cur:
                segs.append(cur)
                cur = []
        if cur:
            segs.append(cur)
        if dots:
            return "".join(f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="1.3" fill="{color}"/>'
                           for s in segs for p in s)
        return "".join(f'<polyline points="{" ".join(s)}" fill="none" stroke="{color}" stroke-width="{w}"/>'
                       for s in segs)

    # recorded readings as dots + line only between consecutive readings <= 20 min apart (no visual interpolation)
    a = actual.sort_values("timestamp")
    am = minutes(a["timestamp"])
    ag = a["glucose"].to_numpy(float)
    breaks = np.flatnonzero(np.diff(am) > 20) + 1
    for xs_run, ys_run in zip(np.split(am, breaks), np.split(ag, breaks), strict=True):
        if len(xs_run) > 1:
            out.append(poly(xs_run, ys_run, COLORS["actual"], 1.2))
    out.append(poly(am, ag, COLORS["actual"], 1, dots=True))
    for name, p in preds.items():
        p = p.sort_values("target_time")
        out.append(poly(minutes(p["target_time"]), p["pred"].to_numpy(float), COLORS.get(name, "#10b981"), 1, dots=True))
    for i, name in enumerate(["actual", *preds]):
        y = top + 14 * i
        out.append(f'<rect x="{width - right + 10}" y="{y}" width="10" height="10" fill="{COLORS.get(name, "#10b981")}"/>'
                   f'<text x="{width - right + 25}" y="{y + 9}">{escape("recorded CGM" if name == "actual" else name)}</text>')
    out.append(f'<text x="{left}" y="{height - 6}" fill="#6b7280">mg/dL; dots at the time each prediction targets; '
               'dashed lines 70 and 180 mg/dL</text></svg>')
    return "".join(out)


def bars_svg(title: str, rows: list[dict], width=760, height=320, names: dict | None = None, subtitle: str = "",
             y_label: str = "RMSE (mg/dL)") -> str:
    """rows: {label, model, value, lo, hi}; grouped bars from 0 with 95% CI whiskers and a labelled y-axis."""
    names = names or {}
    left, top, bottom = 60, 46, 56
    labels = list(dict.fromkeys(r["label"] for r in rows))
    models = list(dict.fromkeys(r["model"] for r in rows))
    vmax = max(r["hi"] for r in rows) * 1.1
    gw = (width - left - 20) / len(labels)
    bw = gw * 0.8 / len(models)
    Y = lambda v: _scale(v, 0, vmax, height - bottom, top)  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" '
           f'font-size="11"><rect width="100%" height="100%" fill="white"/>',
           f'<text x="{left}" y="18" font-size="13">{escape(title)}</text>',
           f'<text x="{left}" y="34" font-size="10" fill="#374151">{escape(subtitle)}</text>',
           f'<line x1="{left}" x2="{left}" y1="{top}" y2="{height - bottom}" stroke="#6b7280"/>',
           f'<line x1="{left}" x2="{width - 20}" y1="{height - bottom}" y2="{height - bottom}" stroke="#6b7280"/>',
           f'<text x="14" y="{(top + height - bottom) / 2:.0f}" font-size="10" text-anchor="middle" '
           f'transform="rotate(-90 14 {(top + height - bottom) / 2:.0f})">{escape(y_label)}</text>']
    step = 10 if vmax <= 80 else 20
    for tv in range(0, int(vmax) + 1, step):
        out.append(f'<line x1="{left - 4}" x2="{left}" y1="{Y(tv):.1f}" y2="{Y(tv):.1f}" stroke="#6b7280"/>'
                   f'<text x="{left - 6}" y="{Y(tv) + 3:.1f}" text-anchor="end" font-size="9">{tv}</text>')
    for r in rows:
        i, j = labels.index(r["label"]), models.index(r["model"])
        x = left + i * gw + gw * 0.1 + j * bw
        c = COLORS.get(r["model"], "#10b981")
        out.append(f'<rect x="{x:.1f}" y="{Y(r["value"]):.1f}" width="{bw * 0.9:.1f}" '
                   f'height="{Y(0) - Y(r["value"]):.1f}" fill="{c}"/>')
        cx = x + bw * 0.45
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{Y(r["lo"]):.1f}" y2="{Y(r["hi"]):.1f}" stroke="black"/>')
        out.append(f'<text x="{cx:.1f}" y="{Y(r["hi"]) - 3:.1f}" text-anchor="middle" font-size="9">'
                   f'{r["value"]:.1f}</text>')
    for i, lab in enumerate(labels):
        out.append(f'<text x="{left + i * gw + gw / 2:.1f}" y="{height - bottom + 15}" text-anchor="middle">'
                   f'{escape(lab)}</text>')
    for j, m in enumerate(models):
        lx = left + j * (width - left - 20) / len(models)  # legend spacing scales with the canvas width
        out.append(f'<rect x="{lx:.0f}" y="{height - 20}" width="10" height="10" fill="{COLORS.get(m, "#10b981")}"/>'
                   f'<text x="{lx + 14:.0f}" y="{height - 11}">{escape(names.get(m, m))}</text>')
    out.append("</svg>")
    return "".join(out)
