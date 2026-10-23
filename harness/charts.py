"""Draw the results as SVG charts (no plotting library, so the output is plain text and diffs cleanly).

    python -m harness.charts            # writes docs/charts/*.svg from runs/*.jsonl

A summary row (a radar of pass rate by task type, the total cost per model, and invalid and unsafe calls per run) and
a grid with a bar chart per task (the prompt as the title, a bar per model: % of runs passed). Both read the rows
`harness.report.aggregate` returns.
"""
import argparse
import math
import textwrap
from collections import defaultdict
from html import escape
from pathlib import Path

from harness.tasks import DESCRIPTIONS, TASKS, display_order, tier_name

CHARTS_DIR = Path("docs/charts")

# Okabe-Ito, distinguishable with common colour vision deficiencies; a model keeps its colour across charts.
# The colours go to the models in MODEL_ORDER: qwen grey, deepseek-chat pink, deepseek-v4-pro vermillion, Haiku blue, Sonnet
# green, Opus orange, gpt-4.1 sky blue, gpt-6-sol yellow. A model not in the list takes the next colour, after those.
PALETTE = ["#4D4D4D", "#CC79A7", "#D55E00", "#0072B2", "#009E73", "#E69F00", "#56B4E9", "#F0E442"]
# The order of the models in every chart: local first, then the cheap and open ones, then Claude, then OpenAI.
MODEL_ORDER = ["qwen3:8b", "deepseek-chat", "deepseek-v4-pro", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5",
               "gpt-4.1", "gpt-6-sol"]
INK, MUTED, GRID, PAPER = "#1f2328", "#656d76", "#d0d7de", "#ffffff"
FONT = "font-family=\"-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif\""
WIDTH = 720
CELL_W, CELL_WRAP = 380, 46  # one task's chart in the overview grid: width, and title width in characters
WIDE_CELL_W = 575  # with two charts to a row, each is wider, so the whole grid stays about as wide as three narrow ones


def model_order(models) -> list[str]:
    """The models in the order the charts show them: MODEL_ORDER first, any other model after, by name."""
    return sorted(set(models), key=lambda m: (MODEL_ORDER.index(m) if m in MODEL_ORDER else len(MODEL_ORDER), m))


def colours(models: list[str]) -> dict[str, str]:
    return {m: PALETTE[i % len(PALETTE)] for i, m in enumerate(model_order(models))}


def text(x, y, s, size=13, fill=INK, anchor="start", weight="normal", rotate=None) -> str:
    turn = f' transform="rotate({rotate} {x:.1f} {y:.1f})"' if rotate else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"{turn} {FONT}>{escape(s)}</text>'


def svg(width: int, height: int, body: list[str], title: str) -> str:
    # An opaque background, so the chart reads the same on a light or dark page.
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title, quote=True)}">',
        f"<title>{escape(title)}</title>",
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>',
        *body,
        "</svg>",
    ])


def legend(models: list[str], colour: dict[str, str], x: float, y: float, width: float) -> tuple[list[str], float]:
    """Legend entries wrapped to `width`; returns the shapes and the y below the last row."""
    out, cx = [], x
    for m in models:
        w = 28 + 7.2 * len(m)
        if cx + w > x + width and cx > x:
            cx, y = x, y + 20
        out += [f'<rect x="{cx:.1f}" y="{y - 10}" width="12" height="12" rx="2" fill="{colour[m]}"/>', text(cx + 18, y, m, 12)]
        cx += w
    return out, y + 20


CHAR_W = 5.7  # width of a character at font-size 10, about


def split_name(name: str) -> list[str]:
    """A model name as one line, or two broken after the hyphen that leaves the shorter longest line."""
    cuts = [i + 1 for i, c in enumerate(name) if c in "-:" and 0 < i < len(name) - 1]
    if not cuts:
        return [name]
    best = min(cuts, key=lambda i: max(i, len(name) - i))
    return [name[:best], name[best:]]


def label_mode(models: list[str], slot: float) -> str:
    """How to write the model names under a plot with `slot` pixels per model: 'one' line, 'two' lines, or 'rotated'."""
    fits = lambda lines: all(len(line) * CHAR_W <= slot - 3 for line in lines)
    if all(fits([m]) for m in models):
        return "one"
    if all(fits(split_name(m)) for m in models):
        return "two"
    return "rotated"


def model_labels(body: list[str], models: list[str], centres: list[float], y: float, mode: str, slot: float = 0) -> tuple[float, float]:
    """Write the model names under a plot, starting at y. Returns the y for the run counts and the y of the bottom edge.

    Rotated names hang down and to the left from the axis; their run counts go straight under it. With two lines, only
    the names that do not fit on one are broken.
    """
    if mode == "rotated":
        for m, cx in zip(models, centres):
            body.append(text(cx + 3, y + 16, m, 10, INK, "end", rotate=-50))
        return y, y + 16 + 0.77 * CHAR_W * max((len(m) for m in models), default=0) + 6
    lines = 2 if mode == "two" else 1
    for m, cx in zip(models, centres):
        broken = mode == "two" and len(m) * CHAR_W > slot - 3
        for k, line in enumerate(split_name(m) if broken else [m]):
            body.append(text(cx, y + 11 * k, line, 10, INK, "middle"))
    return y + 11 * (lines - 1) + 12, y + 11 * (lines - 1) + 21


def task_body(task_id: str, rows: list[dict], models: list[str], colour: dict[str, str],
              cell_w: int = CELL_W) -> tuple[list[str], int, int]:
    """The shapes of one task's bars (% passed per model), with the cell's width and height.

    A model with no runs gets no bar. Every cell reserves three title lines, so the plots line up across a row.
    """
    by_model = {r["model"]: r for r in rows}
    wrap = round(CELL_WRAP * cell_w / CELL_W)  # characters of title that fit the cell
    n_title = 3 if cell_w < 500 else 2         # lines reserved for the title, so the plots line up across a row
    title_lines = textwrap.wrap(TASKS[task_id].prompt, wrap)
    if len(title_lines) > n_title:  # cut at the reserved lines, and say so
        title_lines = [*title_lines[:n_title - 1], textwrap.shorten(" ".join(title_lines[n_title - 1:]), wrap - 1, placeholder="…")]
    body = [text(14, 22 + 16 * i, line, 12, weight="bold") for i, line in enumerate(title_lines)]
    # One or two sentences on what the task asks and what makes it pass, under the title.
    n_desc = 3 if cell_w < 500 else 2
    desc = textwrap.wrap(DESCRIPTIONS.get(task_id, ""), round((cell_w - 28) / 5.3))
    if len(desc) > n_desc:
        desc = [*desc[:n_desc - 1], textwrap.shorten(" ".join(desc[n_desc - 1:]), round((cell_w - 28) / 5.3) - 1, placeholder="…")]
    first = 22 + 16 * len(title_lines) + 2       # straight under the title, however many lines it has
    body += [text(14, first + 14 * k, line, 10.5, MUTED) for k, line in enumerate(desc)]
    top = 22 + 16 * n_title + 14 * n_desc + 14     # the plot starts at the same height in every cell
    body.append(text(14, top, task_id, 9, MUTED))  # prompts can start alike (the M31 tasks), so name the task too
    plot_l, plot_r, plot_h, plot_t = 38, cell_w - 14, 100, top + 24
    for pct in (0, 25, 50, 75, 100):
        y = plot_t + plot_h * (1 - pct / 100)
        body += [f'<line x1="{plot_l}" y1="{y:.1f}" x2="{plot_r}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>',
                 text(plot_l - 6, y + 3, f"{pct}%", 9, MUTED, "end")]
    slot = (plot_r - plot_l) / max(len(models), 1)
    bar_w = min(44, slot * 0.6)
    centres = [plot_l + slot * (i + 0.5) for i in range(len(models))]
    count_y, bottom = model_labels(body, models, centres, plot_t + plot_h + 13, label_mode(models, slot), slot)
    for m, cx in zip(models, centres):
        r = by_model.get(m)
        if r is None:
            body.append(text(cx, plot_t + plot_h - 6, "not run", 10, MUTED, "middle"))
        else:
            h = plot_h * r["pass_rate"]
            y = plot_t + plot_h - h
            if h:
                body.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="2" fill="{colour[m]}"/>')
            body.append(text(cx, y - 4, f"{r['pass_rate']:.0%}", 11, INK, "middle", "bold"))
            body.append(text(cx, count_y, f"n={r['runs']}", 9, MUTED, "middle"))
    return body, cell_w, int(bottom + 13)


def grid(title: str, panels: list[tuple[list[str], int, int]], models: list[str], colour: dict[str, str],
         label: str, columns: int = 3, show_legend: bool = True) -> str:
    """Panels (shapes, width, height) in a grid with a title and the model legend. Every cell is as big as the biggest panel."""
    pad, gap = 12, 10
    cell_w, cell_h = max(w for _, w, _ in panels), max(h for _, _, h in panels)
    inner_w = columns * cell_w + (columns - 1) * gap
    body = [text(pad + 2, 26, title, 15, weight="bold")]
    if show_legend:
        shapes, y = legend(models, colour, pad + 2, 48, inner_w)
        body += shapes
    else:
        y = 40
    top = y - 2
    for i, (cell, w, h) in enumerate(panels):
        x, cy = pad + (i % columns) * (cell_w + gap), top + (i // columns) * (cell_h + gap)
        # The box fills the whole cell, so panels of different heights in one row still line up.
        body += [f'<svg x="{x}" y="{cy}" width="{cell_w}" height="{cell_h}" viewBox="0 0 {cell_w} {cell_h}">',
                 f'<rect width="{cell_w}" height="{cell_h}" fill="{PAPER}" stroke="{GRID}"/>', *cell, "</svg>"]
    rows_n = -(-len(panels) // columns)
    return svg(inner_w + 2 * pad, int(top + rows_n * (cell_h + gap) + pad), body, label)


def overview_chart(rows: list[dict], models: list[str], colour: dict[str, str], columns: int = 2) -> str | None:
    """Every task's bars in one grid, `columns` to a row, in `display_order`. None when no task has runs."""
    cell_w = WIDE_CELL_W if columns == 2 else CELL_W
    panels = [task_body(t, rs, models, colour, cell_w) for t in display_order() if (rs := [r for r in rows if r["task"] == t])]
    if not panels:
        return None
    return grid("Pass rate by task", panels, models, colour, "Pass rate by task, one chart per task", columns)


def tier_scores(rows: list[dict]) -> dict[str, dict[int, tuple[int, int]]]:
    """Per model and tier, (passes, runs) pooled over every run of every task in that tier."""
    out: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows:
        out[r["model"]][r["tier"]][0] += r["passes"]
        out[r["model"]][r["tier"]][1] += r["runs"]
    return {m: {t: tuple(v) for t, v in tiers.items()} for m, tiers in out.items()}


PANEL_H = 300


def radar_panel(rows: list[dict], models: list[str], colour: dict[str, str], title: str = "Pass rate by task type",
                height: int = PANEL_H, cy: float = 172) -> tuple[list[str], int, int] | None:
    """Pass rate by task type, a polygon per model. None when fewer than three types have runs (no polygon to draw).

    A model with no runs of a type gets no polygon, only a dot for each type it has: a missing type read as 0% would
    look like a failure.
    """
    scores = tier_scores(rows)
    tiers = sorted({t for s in scores.values() for t in s})
    if len(tiers) < 3:
        return None
    cx, radius = CELL_W / 2, 76
    body = [text(14, 22, title, 13, weight="bold")]
    if len(models) == 1:  # one plot per model: the title is its name, in its colour
        body = [f'<rect x="14" y="12" width="12" height="12" rx="2" fill="{colour[models[0]]}"/>', text(32, 22, title, 13, weight="bold")]

    def point(i: int, frac: float) -> tuple[float, float]:
        a = -math.pi / 2 + 2 * math.pi * i / len(tiers)
        return cx + radius * frac * math.cos(a), cy + radius * frac * math.sin(a)

    for pct in (25, 50, 75, 100):
        ring = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(i, pct / 100) for i in range(len(tiers))))
        body.append(f'<polygon points="{ring}" fill="none" stroke="{GRID}" stroke-width="1"/>')
        body.append(text(cx + 3, cy - radius * pct / 100 - 2, f"{pct}%", 9, MUTED))
    for i, t in enumerate(tiers):
        x, y = point(i, 1)
        lx, ly = point(i, 1.22)
        side = "end" if x < cx - 8 else "start" if x > cx + 8 else "middle"  # a label beside the polygon, not across it
        if side != "middle":
            lx = x + (6 if side == "start" else -6)
        body.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        body.append(text(lx, ly + 4, tier_name(t).capitalize(), 11, INK, side))
    incomplete = []
    for m in models:
        s = scores.get(m, {})
        if not all(t in s for t in tiers):
            incomplete.append(m)
            body += [f'<circle cx="{point(i, s[t][0] / s[t][1])[0]:.1f}" cy="{point(i, s[t][0] / s[t][1])[1]:.1f}" r="3" fill="{colour[m]}"/>'
                     for i, t in enumerate(tiers) if t in s]
            continue
        pts = [point(i, s[t][0] / s[t][1]) for i, t in enumerate(tiers)]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        body.append(f'<polygon points="{poly}" fill="{colour[m]}" fill-opacity="0.15" stroke="{colour[m]}" stroke-width="2"/>')
        body += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{colour[m]}"/>' for x, y in pts]
    if incomplete:
        missing = [tier_name(t).capitalize() for t in tiers if t not in scores.get(incomplete[0], {})]
        note = (f"No polygon: not run on {', '.join(missing)} yet." if len(models) == 1
                else f"No polygon for {', '.join(incomplete)}: not run on every type yet.")
        body.append(text(14, height - 12, note, 9, MUTED))
    return body, CELL_W, height


def nice_max(value: float) -> float:
    """The next 1, 2, 4, 8 or 10 times a power of ten at or above value. The axis has four steps, so these give round
    ticks (a top of 2.5 would put one at 0.625)."""
    if value <= 0:
        return 1
    scale = 10 ** math.floor(math.log10(value))
    return next(m * scale for m in (1, 2, 4, 8, 10) if m * scale >= value)


def axis(body: list[str], plot_l: float, plot_r: float, plot_t: float, plot_h: float, top: float, fmt) -> None:
    for i in range(5):
        y = plot_t + plot_h * (1 - i / 4)
        body += [f'<line x1="{plot_l}" y1="{y:.1f}" x2="{plot_r}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>',
                 text(plot_l - 6, y + 3, fmt(top * i / 4), 9, MUTED, "end")]


def money(x: float) -> str:
    return f"${x:,.2f}" if x >= 0.1 or x == 0 else f"${x:.3f}"


def cost_panel(rows: list[dict], models: list[str], colour: dict[str, str], cell_w: int = CELL_W) -> tuple[list[str], int, int]:
    """Total cost of every run per model, across all tasks. A model with an unpriced run gets 'n/a', not a partial sum."""
    total, runs, priced, estimated = defaultdict(float), defaultdict(int), defaultdict(lambda: True), defaultdict(bool)
    for r in rows:
        runs[r["model"]] += r["runs"]
        if r["cost"] is None:
            priced[r["model"]] = False
        else:
            total[r["model"]] += r["cost"] * r["runs"]
        estimated[r["model"]] |= r["cost_estimated"]
    shown = {m: total[m] for m in models if m in runs and priced[m]}
    top = nice_max(max(shown.values(), default=0))
    body = [text(14, 22, "Total cost of all runs", 13, weight="bold")]
    plot_l, plot_r, plot_h, plot_t = 46, cell_w - 14, 170, 52
    axis(body, plot_l, plot_r, plot_t, plot_h, top, lambda v: f"${v:g}")
    slot = (plot_r - plot_l) / max(len(models), 1)
    bar_w = min(44, slot * 0.6)
    centres = [plot_l + slot * (i + 0.5) for i in range(len(models))]
    mode = label_mode(models, slot)
    count_y, bottom = model_labels(body, models, centres, plot_t + plot_h + 14, mode, slot)
    for m, cx in zip(models, centres):
        if m not in runs:
            body.append(text(cx, plot_t + plot_h - 6, "not run", 10, MUTED, "middle"))
            continue
        body.append(text(cx, count_y, f"n={runs[m]}" if mode == "rotated" else f"{runs[m]} runs", 9, MUTED, "middle"))
        if m not in shown:
            body.append(text(cx, plot_t + plot_h - 6, "no price", 10, MUTED, "middle"))
            continue
        h = plot_h * shown[m] / top
        y = plot_t + plot_h - h
        if h >= 0.5:
            body.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="2" fill="{colour[m]}"/>')
        body.append(text(cx, y - 4, ("~" if estimated[m] else "") + money(shown[m]), 11, INK, "middle", "bold"))
    height = max(PANEL_H, int(bottom + 30))
    body.append(text(14, height - 12, "List prices, cached input at the cached rate. ~ = estimated price.", 9, MUTED))
    return body, cell_w, height


def calls_panel(rows: list[dict], models: list[str], colour: dict[str, str], cell_w: int = CELL_W) -> tuple[list[str], int, int]:
    """Invalid and unsafe tool calls per run, by model: two bars each (dark: invalid, light: unsafe)."""
    runs, invalid, unsafe = defaultdict(int), defaultdict(float), defaultdict(float)
    for r in rows:
        runs[r["model"]] += r["runs"]
        invalid[r["model"]] += r["invalid_calls"] * r["runs"]  # the row holds a per-run mean
        unsafe[r["model"]] += r["unsafe_calls"]  # the row holds a total
    per_run = {m: (invalid[m] / runs[m], unsafe[m] / runs[m]) for m in models if m in runs}
    top = nice_max(max((v for pair in per_run.values() for v in pair), default=0))
    body = [text(14, 22, "Invalid and unsafe calls per run", 13, weight="bold")]
    # Key: the dark bar is the model's colour, the light bar the same colour faded.
    body += [f'<rect x="14" y="30" width="10" height="10" fill="{MUTED}"/>', text(28, 39, "invalid", 10, MUTED),
             f'<rect x="76" y="30" width="10" height="10" fill="{MUTED}" fill-opacity="0.35"/>', text(90, 39, "unsafe", 10, MUTED)]
    plot_l, plot_r, plot_h, plot_t = 46, cell_w - 14, 160, 62
    axis(body, plot_l, plot_r, plot_t, plot_h, top, lambda v: f"{v:g}")
    slot = (plot_r - plot_l) / max(len(models), 1)
    bar_w = min(26, slot * 0.34)
    centres = [plot_l + slot * (i + 0.5) for i in range(len(models))]
    mode = label_mode(models, slot)
    count_y, bottom = model_labels(body, models, centres, plot_t + plot_h + 14, mode, slot)
    for m, cx in zip(models, centres):
        if m not in per_run:
            body.append(text(cx, plot_t + plot_h - 6, "not run", 10, MUTED, "middle"))
            continue
        body.append(text(cx, count_y, f"n={runs[m]}" if mode == "rotated" else f"{runs[m]} runs", 9, MUTED, "middle"))
        for j, (value, opacity) in enumerate(zip(per_run[m], (1, 0.35))):
            x = cx - bar_w - 1 + j * (bar_w + 2)
            h = plot_h * value / top
            if h >= 0.5:
                body.append(f'<rect x="{x:.1f}" y="{plot_t + plot_h - h:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="2" fill="{colour[m]}" fill-opacity="{opacity}"/>')
            body.append(text(x + bar_w / 2, plot_t + plot_h - h - 4, f"{value:.1f}", 10, INK, "middle", "bold"))
    height = max(PANEL_H, int(bottom + 30))
    body.append(text(14, height - 12, "Unsafe: a state-changing call the task did not ask for.", 9, MUTED))
    return body, cell_w, height


def radar_chart(rows: list[dict], models: list[str], colour: dict[str, str], columns: int = 3) -> str | None:
    """Pass rate by task type, one plot per model, `columns` to a row. None when fewer than three types have runs."""
    panels = [p for m in models if (p := radar_panel(rows, [m], colour, title=m, height=270, cy=158))]
    if not panels:
        return None
    return grid("Pass rate by task type", panels, models, colour, "Pass rate by task type, one plot per model", columns, show_legend=False)


def summary_chart(rows: list[dict], models: list[str], colour: dict[str, str]) -> str | None:
    """Total cost, and invalid and unsafe calls per run, as two panels. None when there are no rows."""
    if not rows:
        return None
    panels = [cost_panel(rows, models, colour, WIDE_CELL_W), calls_panel(rows, models, colour, WIDE_CELL_W)]
    return grid("Cost, and invalid and unsafe calls", panels, models, colour, "Total cost, and invalid and unsafe calls per run", 2)


def write_charts(rows: list[dict], out_dir: Path = CHARTS_DIR) -> dict[str, str]:
    """Write the charts the rows support into out_dir; returns {key: file name} (keys: 'radar', 'summary' and 'overview').

    Charts that are no longer drawn are removed, so the folder matches the results.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    models = model_order(r["model"] for r in rows)
    colour = colours(models)
    charts = {"radar": radar_chart(rows, models, colour), "summary": summary_chart(rows, models, colour),
              "overview": overview_chart(rows, models, colour)}
    drawn = {key: f"{key}.svg" for key, chart in charts.items() if chart}
    for key, name in drawn.items():
        (out_dir / name).write_text(charts[key] + "\n")
    for old in out_dir.glob("*.svg"):
        if old.name not in drawn.values():
            old.unlink()
    return drawn


def main():
    from harness.report import RUNS_DIR, aggregate, load_runs
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    ap.add_argument("--out-dir", type=Path, default=CHARTS_DIR)
    ap.add_argument("--schema", choices=("flat", "published"), default="flat")
    args = ap.parse_args()
    runs, _, _ = load_runs(args.runs_dir, args.schema)
    drawn = write_charts(aggregate(runs), args.out_dir)
    print(f"wrote {len(drawn)} chart(s) to {args.out_dir} from {len(runs)} runs")


if __name__ == "__main__":
    main()
