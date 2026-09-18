"""charts.py -- Human-looking chart rendering for J.A.R.V.I.S. documents.

Renders pie / bar / histogram / line charts to PNG bytes so they can be
embedded directly into Word (.docx) and PowerPoint (.pptx) documents, giving
generated files a professional, human-made appearance.

Uses matplotlib (Agg, no GUI) when it is installed; otherwise falls back to a
pure-Pillow renderer so charts still work offline. Callers just use:
    png_bytes, width_in, height_in = render_chart(spec)
"""

import io

CHART_TYPES = ("pie", "bar", "histogram", "line")

PROFESSIONAL_COLORS = [
    (0x2E, 0x86, 0xAB),  # steel blue
    (0xF2, 0x9B, 0x38),  # amber
    (0x6B, 0x8E, 0x23),  # olive
    (0xD9, 0x50, 0x4B),  # brick red
    (0x85, 0x54, 0xA6),  # purple
    (0x50, 0xB4, 0x48),  # green
    (0xE6, 0x7E, 0x22),  # orange
    (0x34, 0x49, 0x5E),  # navy
]


def _numberize(value):
    try:
        f = float(value)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def _chart_series(spec: dict) -> tuple:
    """Normalise labels + values from a chart spec.

    Accepts: {"labels": [...], "values": [...]},
             {"data": {label: value}},
             {"data": [[label, value], ...]},
             {"data": [v1, v2, ...]}.
    Returns (labels, values) where values are numbers and labels are strings.
    """
    labels = [str(x).strip() for x in (spec.get("labels") or []) if str(x).strip()]
    values = spec.get("values")
    if values is None:
        values = spec.get("data") or []

    if isinstance(values, dict):
        labels = [str(k) for k in values.keys()]
        values = list(values.values())

    if isinstance(values, list) and values and isinstance(values[0], (list, tuple)):
        pairs = [[str(p[0]), p[1]] for p in values if len(p) >= 2]
        labels = [p[0] for p in pairs]
        values = [_numberize(p[1]) for p in pairs]
    else:
        values = [_numberize(v) for v in values]

    values = [v for v in values if v is not None]
    if labels and len(labels) != len(values):
        labels = labels[:len(values)]
    return labels, values


def _chart_title(spec: dict) -> str:
    return str(spec.get("title", "") or "").strip()


# ── Matplotlib renderer (primary) ───────────────────────────────────────────

def _render_matplotlib(spec: dict) -> tuple:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ctype = str(spec.get("type", "bar")).lower()
    title = _chart_title(spec)
    width = float(spec.get("width", 6.6))
    height = float(spec.get("height", 4.2))
    labels, values = _chart_series(spec)

    fig, ax = plt.subplots(figsize=(width, height), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    if ctype == "pie":
        if not values:
            raise ValueError("Pie chart needs at least one value")
        colors = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in PROFESSIONAL_COLORS]
        wedges, txts, autotexts = ax.pie(
            values,
            labels=labels if labels and len(labels) == len(values) else None,
            autopct=lambda pct: f"{pct:.1f}%" if pct >= 3 else "",
            startangle=90,
            counterclock=False,
            colors=colors[:len(values)],
            pctdistance=0.82,
            wedgeprops={"edgecolor": "white", "linewidth": 1.4},
        )
        if autotexts:
            for at in autotexts:
                at.set_color("#222222")
                at.set_fontsize(9)
        ax.axis("equal")
    elif ctype == "histogram":
        raw = [_numberize(x) for x in (spec.get("data") or values) if _numberize(x) is not None]
        if not raw:
            raise ValueError("Histogram needs numeric data")
        bins = spec.get("bins", 10)
        ax.hist(raw, bins=bins, color="#2E86AB", edgecolor="white", linewidth=1.0, alpha=0.9)
        ax.set_ylabel("Frequency")
        ax.grid(axis="y", linestyle=":", alpha=0.35)
    elif ctype == "line":
        if not values:
            raise ValueError("Line chart needs at least one value")
        xs = list(range(len(values)))
        ax.plot(xs, values, marker="o", linewidth=2.2, color="#2E86AB", markerfacecolor="white",
                markeredgewidth=1.6, markersize=6)
        ax.fill_between(xs, values, color="#2E86AB", alpha=0.08)
        if labels and len(labels) == len(values):
            ax.set_xticks(xs)
            ax.set_xticklabels(labels, rotation=30 if len(labels) > 6 else 0, ha="right", fontsize=8)
        ax.grid(axis="y", linestyle=":", alpha=0.35)
    else:  # bar
        if not values:
            raise ValueError("Bar chart needs at least one value")
        ids = labels if labels and len(labels) == len(values) else [str(i + 1) for i in range(len(values))]
        colors = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in PROFESSIONAL_COLORS]
        bars = ax.bar(ids, values, color=colors[:len(values)], edgecolor="white", linewidth=1.2)
        ax.set_xticks(range(len(ids)))
        ax.set_xticklabels(ids, rotation=30 if len(ids) > 6 else 0, ha="right", fontsize=8)
        for rect, val in zip(bars, values):
            ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height(),
                    f"{val:g}", ha="center", va="bottom", fontsize=7.5, color="#333333")
        ax.grid(axis="y", linestyle=":", alpha=0.35)

    for spine in ax.spines.values():
        spine.set_color("#cccccc")
    if title:
        ax.set_title(title, fontsize=13, color="#1a1a1a", pad=12, loc="center")

    buf = io.BytesIO()
    try:
        fig.tight_layout()
    except Exception:
        pass
    fig.savefig(buf, format="png", facecolor="white", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read(), width, height


# ── Pure-Pillow fallback renderer (offline) ─────────────────────────────────

def _draw_text(draw, xy, text, font=None, fill=(40, 40, 40)):
    draw.text(xy, text, fill=fill, font=font)


def _render_pil_fallback(spec: dict) -> tuple:
    from PIL import Image, ImageDraw, ImageFont

    ctype = str(spec.get("type", "bar")).lower()
    title = _chart_title(spec)
    width_in = float(spec.get("width", 6.6))
    height_in = float(spec.get("height", 4.2))
    width = int(width_in * 120)
    height = int(height_in * 120)
    labels, values = _chart_series(spec)

    try:
        font = ImageFont.load_default()
        title_font = font
    except Exception:
        font = title_font = None

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    colors = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in PROFESSIONAL_COLORS]

    if ctype == "pie":
        if not values:
            raise ValueError("Pie chart needs at least one value")
        total = sum(values)
        cx, cy, r = width // 2, height // 2 + 10, min(width, height) // 2 - 40
        start = 90
        for i, v in enumerate(values):
            ang = 360 * v / total
            draw.pieslice((cx - r, cy - r, cx + r, cy + r), start=start, end=start - ang,
                          fill=colors[i % len(colors)])
            if labels and i < len(labels):
                mid = (start + (start - ang)) / 2
                import math
                lx = cx + r * 0.62 * math.cos(math.radians(-mid))
                ly = cy + r * 0.62 * math.sin(math.radians(-mid))
                _draw_text(draw, (lx - 2, ly - 6), labels[i][:12], fill=(20, 20, 20))
            start -= ang
    else:
        margin = 46
        gw = width - margin - 14
        gh = height - margin - 18
        maxv = max(values) if values else 1
        if ctype == "histogram":
            raw = [_numberize(x) for x in (spec.get("data") or values) if _numberize(x) is not None]
            bins = spec.get("bins", 10)
            if raw:
                lo, hi = min(raw), max(raw)
                step = max((hi - lo) / bins, 1e-9)
                hist = [0] * bins
                for x in raw:
                    idx = min(int((x - lo) / step) if hi > lo else 0, bins - 1)
                    hist[idx] += 1
                maxv = max(hist) or 1
                values = hist
                labels = [f"{lo + step * i:.0f}-{lo + step * (i + 1):.0f}" for i in range(bins)]
        n = len(values) or 1
        bw = gw / n * 0.72
        for i, v in enumerate(values):
            bh = gh * (v / maxv)
            x0 = margin + i * (gw / n)
            y0 = height - margin - bh
            draw.rectangle((x0, y0, x0 + bw, height - margin), fill=colors[i % len(colors)])
        draw.line((margin, height - margin, margin + gw, height - margin), fill=(90, 90, 90), width=2)
        draw.line((margin, height - margin, margin, height - margin - gh), fill=(90, 90, 90), width=2)

    if title:
        _draw_text(draw, (max(margin, 8), 6), title, fill=(20, 20, 20))

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out.read(), width_in, height_in


# ── Public API ──────────────────────────────────────────────────────────────

def render_chart(spec: dict) -> tuple:
    """Render a chart spec to (png_bytes, width_inches, height_inches).

    spec keys: type (pie|bar|histogram|line), title, labels, values|data,
    bins (histogram), width, height.
    Raises ValueError for unsupported/invalid specs.
    """
    ctype = str(spec.get("type", "bar")).lower()
    if ctype not in CHART_TYPES:
        raise ValueError(f"Unsupported chart type: {ctype}. Use {', '.join(CHART_TYPES)}.")
    try:
        return _render_matplotlib(spec)
    except ValueError:
        raise
    except ImportError:
        return _render_pil_fallback(spec)
    except Exception:
        return _render_pil_fallback(spec)


def chart_image_from_spec(spec: dict) -> bytes:
    """Convenience wrapper returning only the PNG bytes."""
    return render_chart(spec)[0]