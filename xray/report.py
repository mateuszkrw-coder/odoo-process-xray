"""Render the analysis as one self-contained HTML page (no external files)."""
from html import escape
from math import log

from . import PROJECT_URL, __version__
from .analyze import DIMENSIONS, WEEKDAYS
from .eventlog import (
    CREDIT_NOTE, DELIVERY_RESCHEDULED, GOODS_SHIPPED, INVOICE_POSTED, INVOICE_RESET, ORDER_CANCELLED,
    ORDER_CHANGED, ORDER_CONFIRMED, PAYMENT_RECEIVED, QUOTE_CREATED, QUOTE_SENT,
)

# "How long" is encoded with 9 steps of one blue ramp (classes w0..w8). The
# actual colours live in the page CSS so light and dark mode each get their
# own steps: darker = longer on a light page, brighter = longer on a dark one.
WAIT_STEPS = 9


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def days(d, short=False):
    if d is None:
        return "–"
    if d < 1:
        return f"{d * 24:.0f} h" if short else f"{d * 24:.0f} hours"
    return f"{d:.1f} d" if short else f"{d:.1f} days"


def pct(x):
    return f"{x:.0%}"


def date(d):
    return f"{d.day} {d:%b %Y}"


def join(names, limit=5):
    names = [escape(str(n)) for n in names]
    if len(names) > limit:
        names = names[:limit] + [f"{len(names) - limit} more"]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def wait_class(value, top, low=None):
    """w0..w8 for a wait. Without `low`: log scale from 0 to `top`, so short waits
    still differ. With `low`: linear from `low` to `top` (for small ranges)."""
    if value is None or top <= 0:
        return "wn"
    if low is not None:
        t = (value - low) / (top - low) if top > low else 0
    else:
        t = log(1 + max(value, 0)) / log(1 + top)
    return f"w{max(0, min(WAIT_STEPS - 1, round(t * (WAIT_STEPS - 1))))}"


def tip(text):
    return f'data-tip="{escape(text, quote=True)}" tabindex="0"'


# --------------------------------------------------------------------------
# Findings: turn rule results and bottlenecks into sentences
# --------------------------------------------------------------------------

GROUP_WORDING = {
    "salesperson": "handled by {}",
    "warehouse": "shipped from {}",
    "customer": "from {}",
    "product": "containing {}",
    "confirmed_on": "confirmed on {}",
}


def findings(results):
    items = []
    for b in results.bottlenecks:
        slow = [s[0] for s in b["slow_days"]]
        slow_median = max(s[1] for s in b["slow_days"])
        items.append({
            "id": f"bottleneck-{len(items)}",
            "kind": "bottleneck",
            "title": f"{b['warehouse']} ships late-week orders days later",
            "headline": f"Orders confirmed on {join(slow)} wait up to {days(slow_median)} (working days) "
                        f"before shipping from {escape(b['warehouse'])}, against {days(b['typical_days'])} "
                        f"on its fastest days.",
            "where": f"{b['orders']} orders were affected over the period.",
            "summary": f"orders confirmed on {join(slow)} take up to {days(slow_median)} to ship "
                       f"instead of {days(b['typical_days'])} ({b['orders']} orders).",
            "why": "The delay is not spread evenly: it depends on the day the order comes in, which points "
                   "to capacity or planning at the end of the week rather than to the products.",
            "fix": "Check staffing and picking capacity at the end of the week. Inventory > Settings > "
                   "<b>Batch, Wave &amp; Cluster Transfers</b> helps a team clear a backlog, and a clear "
                   "same-week cut-off time sets honest expectations.",
            "score": b["orders"] * 3,
            "bottleneck": b,
        })
    for r in results.rules:
        if not r.hits:
            continue
        where = []
        for k, c in enumerate(r.concentration):
            group = GROUP_WORDING[c.dimension].format(join(c.values))
            if k == 0:
                where.append(f"{pct(c.hit_share)} of them are orders {group}, which make up only "
                             f"{pct(c.case_share)} of {r.rule.applies_to_label}: {pct(c.rate)} of those orders "
                             f"are affected, against {pct(r.rate)} on average.")
            else:
                where.append(f"Also concentrated in orders {group} ({pct(c.hit_share)} of the problem, "
                             f"{pct(c.case_share)} of the orders).")
        summary = f"{len(r.hits)} orders ({pct(r.rate)})"
        if r.concentration:
            c = r.concentration[0]
            summary += f", {pct(c.hit_share)} of them {GROUP_WORDING[c.dimension].format(join(c.values, 3))}"
        items.append({
            "id": f"rule-{r.rule.key}",
            "summary": summary + ".",
            "kind": "rule",
            "title": r.rule.title,
            "headline": f"{len(r.hits)} of {r.applicable} {r.rule.applies_to_label} ({pct(r.rate)}).",
            "where": " ".join(where),
            "why": r.rule.why,
            "fix": r.rule.odoo_fix,
            "score": len(r.hits) * (3 if r.concentration else 1),
            "rule": r,
        })
    return sorted(items, key=lambda f: -f["score"])


# --------------------------------------------------------------------------
# Charts (inline SVG)
# --------------------------------------------------------------------------

def bar_path(x, y, w, h, r=4):
    """Horizontal bar, square at the baseline, rounded at the data end."""
    r = min(r, w / 2, h / 2)
    return (f"M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
            f"V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z")


def hbars(rows, reference=None, label="bar chart", width=600, label_w=190):
    """Horizontal bars. rows: dicts with label, value, text, tip, highlight.

    Emphasis form: highlighted rows in the accent colour, the rest grey, and
    every bar carries its value label so colour is never the only channel.
    """
    row_h, value_w = 30, 120
    bar_w = width - label_w - value_w
    top = max([r["value"] for r in rows] + [reference[0] if reference else 0]) or 1
    height = row_h * len(rows) + (26 if reference else 8)
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label, quote=True)}">']
    if reference:
        x = label_w + bar_w * reference[0] / top
        parts.append(f'<line class="ref" x1="{x:.1f}" x2="{x:.1f}" y1="2" y2="{height - 20}"/>'
                     f'<text class="axis" x="{x:.1f}" y="{height - 6}" text-anchor="middle">{escape(reference[1])}</text>')
    for i, r in enumerate(rows):
        y = 6 + i * row_h
        w = max(bar_w * r["value"] / top, 2)
        name = str(r["label"])
        short = escape(name if len(name) <= 26 else name[:25] + "…")
        cls = "bar accent" if r.get("highlight") else "bar muted-bar"
        parts.append(f'<text class="label" x="{label_w - 10}" y="{y + 15}" text-anchor="end">{short}</text>'
                     f'<path class="{cls}" d="{bar_path(label_w, y + 4, w, 16)}" {tip(r["tip"])}/>'
                     f'<text class="value halo" x="{label_w + w + 8:.1f}" y="{y + 16}">{r["text"]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def rule_bars(result, concentration):
    highlight = set(concentration.values)
    rows = result.breakdown[concentration.dimension]
    rows = sorted(rows, key=lambda r: (r[0] not in highlight, -(r[2] / r[1] if r[1] else 0), r[0]))[:7]

    def rate(applicable, hits):
        return hits / applicable if applicable else 0

    return hbars([{
        "label": value,
        "value": rate(applicable, hits),
        "text": f'{pct(rate(applicable, hits))} <tspan class="muted">({hits}/{applicable})</tspan>',
        "tip": f"{value}: {hits} of {applicable} orders affected ({pct(rate(applicable, hits))})",
        "highlight": value in highlight,
    } for value, applicable, hits in rows], reference=(result.rate, f"average {pct(result.rate)}"),
        label=f"Share of orders affected by {DIMENSIONS[concentration.dimension].lower()}")


def weekday_bars(matrix_row, slow_days, typical):
    present = [d for d in WEEKDAYS if d in matrix_row]
    return hbars([{
        "label": d,
        "value": matrix_row[d][0],
        "text": f'{matrix_row[d][0]:.1f} d <tspan class="muted">({matrix_row[d][1]} orders)</tspan>',
        "tip": f"Confirmed on {d}: median {days(matrix_row[d][0])} to ship ({matrix_row[d][1]} orders)",
        "highlight": d in slow_days,
    } for d in present], reference=(typical, f"fastest days: {typical:.1f} d"),
        label="Median working days to ship, by weekday confirmed", label_w=70, width=520)


def step_bars(steps, width=640):
    label_w, value_w, row_h = 170, 160, 40
    bar_w = width - label_w - value_w
    top = max((s.p90_days or 0) for s in steps) or 1
    height = row_h * len(steps) + 34
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Median calendar days per step, with 90th percentile">']
    for i, s in enumerate(steps):
        y = 6 + i * row_h
        parts.append(f'<text class="label" x="{label_w - 10}" y="{y + 17}" text-anchor="end">{escape(s.label)}</text>')
        if s.median_days is None:
            parts.append(f'<text class="value muted" x="{label_w}" y="{y + 17}">no data</text>')
            continue
        w = max(bar_w * s.median_days / top, 2)
        p90 = label_w + bar_w * (s.p90_days or 0) / top
        parts.append(f'<line class="whisker" x1="{label_w + w:.1f}" x2="{p90:.1f}" y1="{y + 12}" y2="{y + 12}"/>'
                     f'<line class="whisker" x1="{p90:.1f}" x2="{p90:.1f}" y1="{y + 6}" y2="{y + 18}"/>'
                     f'<path class="bar accent" d="{bar_path(label_w, y + 4, w, 16)}" '
                     f'{tip(f"{s.label}: median {days(s.median_days)}, 90% within {days(s.p90_days)} ({s.n} orders)")}/>'
                     f'<text class="value" x="{p90 + 8:.1f}" y="{y + 17}">{days(s.median_days)} '
                     f'<tspan class="muted">· 90% ≤ {days(s.p90_days, short=True)}</tspan></text>')
    y = height - 10
    parts.append(f'<rect class="bar accent" x="{label_w}" y="{y - 9}" width="14" height="10" rx="2"/>'
                 f'<text class="axis" x="{label_w + 20}" y="{y}">median</text>'
                 f'<line class="whisker" x1="{label_w + 84}" x2="{label_w + 104}" y1="{y - 4}" y2="{y - 4}"/>'
                 f'<text class="axis" x="{label_w + 110}" y="{y}">90% of orders</text>')
    parts.append("</svg>")
    return "".join(parts)


def heatmap(matrix, bottlenecks):
    slow = {(b["warehouse"], d[0]) for b in bottlenecks for d in b["slow_days"]}
    used_days = [d for d in WEEKDAYS if any(d in row for row in matrix.values())]
    values = [v[0] for row in matrix.values() for v in row.values()]
    low, top = (min(values), max(values)) if values else (0, 1)
    head = "".join(f"<th>{d}</th>" for d in used_days)
    body = []
    for warehouse in sorted(matrix):
        cells = []
        for d in used_days:
            if d not in matrix[warehouse]:
                cells.append('<td class="empty">–</td>')
                continue
            value, n = matrix[warehouse][d]
            mark = " slow" if (warehouse, d) in slow else ""
            cells.append(f'<td class="cell {wait_class(value, top, low)}{mark}" '
                         f'{tip(f"{warehouse}, confirmed on {d}: median {days(value)} to ship ({n} orders)")}>'
                         f'<b>{value:.1f}</b><small>{n} orders</small></td>')
        body.append(f'<tr><th scope="row">{escape(warehouse)}</th>{"".join(cells)}</tr>')
    return (f'<table class="heatmap"><thead><tr><th></th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


# Where each activity sits on the map: the normal flow runs down the left
# column; detours and corrections sit in the right column, next to the step
# they interrupt.
MAIN, SIDE = 0, 1
MAP_POSITIONS = {
    QUOTE_CREATED: (MAIN, 0), QUOTE_SENT: (MAIN, 1), ORDER_CONFIRMED: (MAIN, 2),
    ORDER_CANCELLED: (SIDE, 1.2), ORDER_CHANGED: (SIDE, 2.6), DELIVERY_RESCHEDULED: (SIDE, 3.6),
    GOODS_SHIPPED: (MAIN, 4.4), INVOICE_POSTED: (MAIN, 5.4), INVOICE_RESET: (SIDE, 5.6),
    CREDIT_NOTE: (SIDE, 6.4), PAYMENT_RECEIVED: (MAIN, 7.2),
}


def process_map(results, min_share=0.015):
    """Directly-follows graph. Arrow width = orders, arrow colour = median wait."""
    total = len(results.cases)
    edges = [(a, b, e) for (a, b), e in results.edges.items()
             if a in MAP_POSITIONS and b in MAP_POSITIONS and e["count"] >= max(3, min_share * total)]
    names = {a for a, _, _ in edges} | {b for _, b, _ in edges}
    if not names:
        return "<p>No data.</p>"
    node_w, node_h, row_h = 236, 46, 84
    max_count = max(e["count"] for _, _, e in edges)
    top_wait = max((e["median_days"] or 0) for _, _, e in edges) or 1

    plans = []
    for a, b, e in edges:
        (ca, ra), (cb, rb) = MAP_POSITIONS[a], MAP_POSITIONS[b]
        if a == b:
            kind = "loop"
        elif ca != cb:
            kind = "cross"
        else:
            between = any(MAP_POSITIONS[n][0] == ca and min(ra, rb) < MAP_POSITIONS[n][1] < max(ra, rb)
                          for n in names)
            kind = "straight" if rb > ra and not between else ("arc-left" if ca == MAIN else "arc-right")
        plans.append((a, b, e, kind))

    # Leave room on the left for the arcs that skip or go back along the main column.
    left_arcs = sum(1 for p in plans if p[3] == "arc-left")
    right_arcs = sum(1 for p in plans if p[3] in ("arc-right", "loop"))
    main_x = 20 + (34 + 30 * left_arcs) * 0.75 + 64 if left_arcs else 20
    col_x = (main_x, main_x + node_w + 164)
    pos = {n: (col_x[MAP_POSITIONS[n][0]], 30 + MAP_POSITIONS[n][1] * row_h) for n in names}
    width = col_x[SIDE] + node_w + (34 + 30 * right_arcs) * 0.75 + 76
    height = max(y for _, y in pos.values()) + node_h + 16

    # Give every arrow its own connection point on the node's side.
    usage = {}
    for i, (a, b, e, kind) in enumerate(plans):
        if kind == "straight":
            continue
        if kind == "cross":
            sa, sb = ("R", "L") if MAP_POSITIONS[a][0] == MAIN else ("L", "R")
        else:
            sa = sb = "L" if kind == "arc-left" else "R"
        usage.setdefault((a, sa), []).append((pos[b][1], 0, i, "out"))
        usage.setdefault((b, sb), []).append((pos[a][1], 1, i, "in"))
    ports = {}
    for (node, side), uses in usage.items():
        uses.sort()
        x, y = pos[node]
        for k, (_, _, i, direction) in enumerate(uses):
            ports[(i, direction)] = (x + (node_w if side == "R" else 0), y + node_h * (k + 1) / (len(uses) + 1))

    svg = ['<defs>' + "".join(arrow_marker(f"w{i}") for i in range(WAIT_STEPS)) + arrow_marker("wn") + '</defs>']
    labels = []
    bulges = {"L": 0, "R": 0}
    for i in sorted(range(len(plans)), key=lambda i: -plans[i][2]["count"]):
        a, b, e, kind = plans[i]
        (xa, ya), (xb, yb) = pos[a], pos[b]
        if kind == "straight":
            x = xa + node_w / 2
            d = f"M{x},{ya + node_h} L{x},{yb - 1}"
            lx, ly, anchor = x + 12, (ya + node_h + yb) / 2 + 4, "start"
        else:
            (x1, y1), (x2, y2) = ports[(i, "out")], ports[(i, "in")]
            if kind == "cross":
                dx = (x2 - x1) * 0.5
                d = f"M{x1:.1f},{y1:.1f} C{x1 + dx:.1f},{y1:.1f} {x2 - dx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
                lx, ly, anchor = (x1 + x2) / 2, (y1 + y2) / 2 - 6, "middle"
            elif kind == "loop":
                d = f"M{x1:.1f},{y1:.1f} C{x1 + 40:.1f},{y1 - 22:.1f} {x2 + 40:.1f},{y2 + 22:.1f} {x2:.1f},{y2:.1f}"
                lx, ly, anchor = x1 + 36, (y1 + y2) / 2 + 4, "start"
            else:
                side = "L" if kind == "arc-left" else "R"
                sign = -1 if side == "L" else 1
                bulges[side] += 1
                reach = 34 + 30 * bulges[side]
                d = f"M{x1:.1f},{y1:.1f} C{x1 + sign * reach:.1f},{y1:.1f} {x2 + sign * reach:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
                lx, ly = x1 + sign * reach * 0.75 + sign * 4, (y1 + y2) / 2 + 4
                anchor = "end" if side == "L" else "start"
        cls = wait_class(e["median_days"], top_wait)
        stroke = 1.3 + 7 * (e["count"] / max_count) ** 0.6
        wait = f" · {days(e['median_days'], short=True)}" if e["median_days"] is not None else ""
        desc = f"{a} → {b}: {e['count']} orders" + (f", median wait {days(e['median_days'])}" if wait else "")
        svg.append(f'<g class="edge" {tip(desc)}><path class="hit" d="{d}"/>'
                   f'<path class="flow {cls}" d="{d}" stroke-width="{stroke:.1f}" marker-end="url(#ah-{cls})"/></g>')
        labels.append(f'<text class="edge-label" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">{e["count"]}{wait}</text>')
    for n in sorted(names, key=lambda n: MAP_POSITIONS[n][1]):
        x, y = pos[n]
        count = results.nodes.get(n, 0)
        side = " side" if MAP_POSITIONS[n][0] == SIDE else ""
        svg.append(f'<g class="node{side}" {tip(f"{n}: {count} orders")}>'
                   f'<rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="8"/>'
                   f'<text class="node-title" x="{x + node_w / 2}" y="{y + 20}" text-anchor="middle">{escape(n)}</text>'
                   f'<text class="node-sub" x="{x + node_w / 2}" y="{y + 36}" text-anchor="middle">{count} orders</text></g>')
    titles = (f'<text class="col-title" x="{col_x[MAIN] + node_w / 2}" y="12" text-anchor="middle">Normal flow</text>'
              f'<text class="col-title" x="{col_x[SIDE] + node_w / 2}" y="12" text-anchor="middle">Detours and corrections</text>')
    return (f'<svg class="map" viewBox="0 -4 {width:.0f} {height + 4:.0f}" width="{width:.0f}" role="img" '
            f'aria-label="Process map: how orders move from step to step">{titles}{"".join(svg)}{"".join(labels)}</svg>')


def arrow_marker(cls):
    return (f'<marker id="ah-{cls}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="12" markerHeight="12" '
            f'orient="auto" markerUnits="userSpaceOnUse"><path class="head {cls}" d="M0,0 L10,5 L0,10 Z"/></marker>')


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

def table(headers, rows, numeric=()):
    head = "".join(f'<th class="{"num" if i in numeric else ""}">{escape(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td class="{"num" if i in numeric else ""}">{escape(str(c))}</td>'
                                    for i, c in enumerate(row)) + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table class="data"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def format_summary(text):
    """The model writes a lead sentence, bullets and a closing line: keep that shape."""
    parts, bullets = [], []
    for line in text.splitlines():
        if line.startswith(("- ", "* ", "• ")):
            bullets.append(f"<li>{escape(line[2:].strip())}</li>")
            continue
        if bullets:
            parts.append(f'<ul class="written-points">{"".join(bullets)}</ul>')
            bullets = []
        parts.append(f"<p>{escape(line)}</p>")
    if bullets:
        parts.append(f'<ul class="written-points">{"".join(bullets)}</ul>')
    return "".join(parts)


def finding_card(f, results, number):
    body = [f'<p class="headline">{f["headline"]}</p>']
    if f["where"]:
        body.append(f'<p class="where">{f["where"]}</p>')
    if f["kind"] == "rule" and f["rule"].concentration:
        r, c = f["rule"], f["rule"].concentration[0]
        body.append(f'<figure><figcaption>Share of {escape(r.rule.applies_to_label)} affected, '
                    f'by {escape(DIMENSIONS[c.dimension].lower())}</figcaption>{rule_bars(r, c)}</figure>')
    if f["kind"] == "bottleneck":
        b = f["bottleneck"]
        row = results.weekday_matrix[b["warehouse"]]
        body.append(f'<figure><figcaption>Median working days from confirmation to shipment at '
                    f'{escape(b["warehouse"])}, by the day the order was confirmed</figcaption>'
                    f'{weekday_bars(row, {s[0] for s in b["slow_days"]}, b["typical_days"])}</figure>')
    body.append(f'<div class="advice"><div><h4>Why it matters</h4><p>{f["why"]}</p></div>'
                f'<div><h4>What to do in Odoo</h4><p>{f["fix"]}</p></div></div>')
    if f["kind"] == "rule":
        r = f["rule"]
        rows = [(c.case_id, c["customer"], c["salesperson"], c["warehouse"]) for c in r.hits[:200]]
        body.append(f'<details><summary>Show the {len(r.hits)} orders</summary>'
                    f'{table(["Order", "Customer", "Salesperson", "Warehouse"], rows)}</details>')
    return (f'<article class="finding" id="{f["id"]}"><div class="num-badge">{number}</div>'
            f'<div class="finding-body"><h3>{escape(f["title"])}</h3>{"".join(body)}</div></article>')


def render(results, source_note="", ai_summary=None):
    counts = results.counts
    confirmed = [c for c in results.cases if c.has(ORDER_CONFIRMED)]
    problem_orders = {c.case_id for r in results.rules for c in r.hits}
    items = findings(results)
    key_items = [f for f in items if f["kind"] == "bottleneck" or f["rule"].concentration] or items[:5]
    other_items = [f for f in items if f not in key_items]
    o2c = results.order_to_cash
    start, end = results.period
    history_share = results.sources.get("history", 0) / max(counts["events"], 1)

    tiles = [
        ("Sales orders analysed", f"{counts['quotations']:,}", f"{date(start)} – {date(end)}"),
        ("Quotations confirmed", pct(counts["conversion"]), f"{counts['confirmed']:,} of {counts['quotations']:,}"),
        ("Order to cash (median)", days(o2c.median_days), f"90% within {days(o2c.p90_days)}"),
        ("Orders with at least one problem", pct(len(problem_orders & {c.case_id for c in confirmed}) / max(len(confirmed), 1)),
         f"{len(problem_orders):,} orders, {len(items)} kinds of problem"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="tile-label">{escape(l)}</div>'
                         f'<div class="tile-value">{v}</div><div class="tile-sub">{escape(s)}</div></div>'
                         for l, v, s in tiles)

    summary = "".join(f'<li><a href="#{f["id"]}">{escape(f["title"])}</a>: {f["summary"]}</li>' for f in key_items)
    written = ""
    if ai_summary and ai_summary[0]:
        written = (f'<div class="card written"><h3>Summary</h3>{format_summary(ai_summary[0])}'
                   f'<p class="written-note">{escape(ai_summary[1])}</p></div>')
    cards = "".join(finding_card(f, results, i + 1) for i, f in enumerate(key_items))
    others = table(["Check", "Orders affected", "Share"],
                   [(f["title"], len(f["rule"].hits), pct(f["rule"].rate)) for f in other_items], numeric=(1, 2))
    clean_rules = [r.rule.title for r in results.rules if not r.hits]

    edge_rows = [(a, b, e["count"], days(e["median_days"]))
                 for (a, b), e in sorted(results.edges.items(), key=lambda kv: -kv[1]["count"])]
    variant_rows = "".join(
        f'<tr><td class="num">{n}</td><td class="num">{pct(share)}</td>'
        f'<td><div class="share"><span style="width:{share * 100:.1f}%"></span></div></td>'
        f'<td class="path">{" <span class=arrow>→</span> ".join(escape(a) for a in path)}</td></tr>'
        for path, n, share in results.variants)
    step_rows = [(s.label, s.n, days(s.median_days), days(s.p90_days)) for s in results.steps + [o2c]]

    return PAGE.format(
        title=escape(f"Order-to-cash X-ray · {results.company}" if results.company else "Order-to-cash X-ray"),
        company=escape(results.company or "Your company"),
        period=f"{date(start)} – {date(end)}",
        source_note=escape(source_note),
        tiles=tiles_html,
        summary=summary,
        written=written,
        cards=cards,
        others=others if other_items else "",
        clean=(f"<p class='muted'>No problems found for: {escape('; '.join(clean_rules))}.</p>" if clean_rules else ""),
        process_map=process_map(results),
        edge_table=table(["From", "To", "Orders", "Median wait"], edge_rows, numeric=(2, 3)),
        step_chart=step_bars(results.steps + [o2c]),
        step_table=table(["Step", "Orders", "Median", "90th percentile"], step_rows, numeric=(1, 2, 3)),
        heatmap=heatmap(results.weekday_matrix, results.bottlenecks),
        variant_rows=variant_rows,
        n_variants=counts["variants"],
        events=f"{counts['events']:,}",
        history_note=("All of them come from that change history." if history_share >= 0.9995 else
                      f"{pct(history_share)} of them come from that change history; the rest from the "
                      f"documents' own dates."),
        tz=escape(results.tz),
        as_of=date(results.as_of),
        version=__version__,
        project_url=PROJECT_URL,
    )


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --text: #0b0b0b; --text-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --accent: #2a78d6; --accent-soft: #cde2fb; --gray-bar: #b4b3ab; --node: #ffffff; --node-side: #f4f3ef;
  --w0: #b7d3f6; --w0-ink: #0b0b0b; --w1: #9ec5f4; --w1-ink: #0b0b0b; --w2: #86b6ef; --w2-ink: #0b0b0b; --w3: #6da7ec; --w3-ink: #0b0b0b; --w4: #5598e7; --w4-ink: #0b0b0b; --w5: #2a78d6; --w5-ink: #ffffff; --w6: #1c5cab; --w6-ink: #ffffff; --w7: #104281; --w7-ink: #ffffff; --w8: #0d366b; --w8-ink: #ffffff;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --text: #ffffff; --text-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --accent: #3987e5; --accent-soft: #1c3350; --gray-bar: #5d5c57; --node: #232322; --node-side: #1f1f1e;
    --w0: #184f95; --w0-ink: #ffffff; --w1: #1c5cab; --w1-ink: #ffffff; --w2: #256abf; --w2-ink: #ffffff; --w3: #2a78d6; --w3-ink: #ffffff; --w4: #3987e5; --w4-ink: #0b0b0b; --w5: #5598e7; --w5-ink: #0b0b0b; --w6: #6da7ec; --w6-ink: #0b0b0b; --w7: #9ec5f4; --w7-ink: #0b0b0b; --w8: #cde2fb; --w8-ink: #0b0b0b;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --text: #ffffff; --text-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --accent: #3987e5; --accent-soft: #1c3350; --gray-bar: #5d5c57; --node: #232322; --node-side: #1f1f1e;
  --w0: #184f95; --w0-ink: #ffffff; --w1: #1c5cab; --w1-ink: #ffffff; --w2: #256abf; --w2-ink: #ffffff; --w3: #2a78d6; --w3-ink: #ffffff; --w4: #3987e5; --w4-ink: #0b0b0b; --w5: #5598e7; --w5-ink: #0b0b0b; --w6: #6da7ec; --w6-ink: #0b0b0b; --w7: #9ec5f4; --w7-ink: #0b0b0b; --w8: #cde2fb; --w8-ink: #0b0b0b;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--page); color: var(--text);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 40px 20px 64px; }}
a {{ color: var(--accent); }}
.eyebrow {{ font-size: 13px; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); margin: 0 0 6px; }}
h1 {{ font-size: 30px; line-height: 1.2; margin: 0 0 8px; }}
h2 {{ font-size: 21px; margin: 52px 0 6px; }}
h3 {{ font-size: 18px; margin: 0 0 6px; }}
h4 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin: 0 0 4px; }}
.lede {{ color: var(--text-2); margin: 0 0 4px; max-width: 70ch; }}
.muted {{ color: var(--muted); }}
.section-intro {{ color: var(--text-2); margin: 0 0 18px; max-width: 72ch; }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 28px; }}
.tile {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }}
.tile-label {{ font-size: 13px; color: var(--text-2); }}
.tile-value {{ font-size: 30px; font-weight: 600; margin: 4px 0 2px; }}
.tile-sub {{ font-size: 13px; color: var(--muted); }}
.summary {{ margin: 0; padding-left: 20px; }}
.written {{ margin-top: 28px; }}
.written h3 {{ margin-bottom: 8px; }}
.written p {{ margin: 0 0 10px; font-size: 16px; }}
.written-points {{ margin: 0 0 12px; padding-left: 22px; }}
.written-points li {{ margin: 6px 0; font-size: 15px; }}
.written-note {{ font-size: 13px !important; color: var(--muted); border-top: 1px solid var(--grid); padding-top: 8px; }}
.summary li {{ margin: 6px 0; }}
.finding {{ display: flex; gap: 16px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 22px 22px 16px; margin: 14px 0; }}
.num-badge {{ flex: 0 0 30px; height: 30px; border-radius: 50%; background: var(--accent-soft); color: var(--text);
  font-weight: 600; display: grid; place-items: center; font-size: 14px; }}
.finding-body {{ flex: 1; min-width: 0; }}
.headline {{ font-size: 16px; margin: 0 0 6px; }}
.where {{ color: var(--text-2); margin: 0 0 12px; }}
figure {{ margin: 14px 0; }}
figcaption {{ font-size: 13px; color: var(--muted); margin-bottom: 6px; }}
.advice {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 16px 0 6px; padding-top: 14px;
  border-top: 1px solid var(--grid); }}
.advice p {{ margin: 0; font-size: 14px; color: var(--text-2); }}
details {{ margin: 10px 0 0; }}
summary {{ cursor: pointer; color: var(--accent); font-size: 14px; }}
.chart {{ width: 100%; max-width: 640px; height: auto; display: block; }}
.chart .label, .chart .value {{ font-size: 13px; fill: var(--text); }}
.halo {{ paint-order: stroke; stroke: var(--surface); stroke-width: 4px; stroke-linejoin: round; }}
.chart .axis, .chart .muted {{ font-size: 12px; fill: var(--muted); }}
.bar.accent {{ fill: var(--accent); }}
.bar.muted-bar {{ fill: var(--gray-bar); }}
.chart .ref {{ stroke: var(--text-2); stroke-width: 1; }}
.chart .whisker {{ stroke: var(--muted); stroke-width: 2; stroke-linecap: round; }}
.w0 {{ --c: var(--w0); --ink: var(--w0-ink); }}
.w1 {{ --c: var(--w1); --ink: var(--w1-ink); }}
.w2 {{ --c: var(--w2); --ink: var(--w2-ink); }}
.w3 {{ --c: var(--w3); --ink: var(--w3-ink); }}
.w4 {{ --c: var(--w4); --ink: var(--w4-ink); }}
.w5 {{ --c: var(--w5); --ink: var(--w5-ink); }}
.w6 {{ --c: var(--w6); --ink: var(--w6-ink); }}
.w7 {{ --c: var(--w7); --ink: var(--w7-ink); }}
.w8 {{ --c: var(--w8); --ink: var(--w8-ink); }}
.wn {{ --c: var(--muted); --ink: var(--text); }}
.flow {{ fill: none; stroke: var(--c); stroke-linecap: round; }}
.head {{ fill: var(--c); }}
.map-wrap {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px 0; }}
.map {{ display: block; margin: 0 auto; max-width: none; }}
.node rect {{ fill: var(--node); stroke: var(--axis); stroke-width: 1; }}
.node.side rect {{ fill: var(--node-side); }}
.col-title {{ font-size: 12px; letter-spacing: .04em; text-transform: uppercase; fill: var(--muted); }}
.node-title {{ font-size: 14px; font-weight: 600; fill: var(--text); }}
.node-sub {{ font-size: 12px; fill: var(--muted); }}
.edge-label {{ font-size: 12px; fill: var(--text-2); paint-order: stroke; stroke: var(--surface); stroke-width: 4px; }}
.edge .hit {{ fill: none; stroke: transparent; stroke-width: 16; }}
.edge:hover path:not(.hit), .edge:focus path:not(.hit) {{ opacity: .75; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 18px; align-items: center; font-size: 13px; color: var(--text-2); margin: 10px 0 0; }}
.ramp {{ display: inline-flex; vertical-align: middle; margin: 0 6px; }}
.ramp span {{ width: 18px; height: 10px; background: var(--c); }}
.heatmap {{ border-collapse: separate; border-spacing: 2px; width: 100%; max-width: 760px; }}
.heatmap th {{ font-weight: 500; font-size: 13px; color: var(--text-2); padding: 4px 8px; text-align: center; }}
.heatmap th[scope=row] {{ text-align: right; white-space: nowrap; }}
.heatmap td {{ text-align: center; padding: 10px 6px; border-radius: 4px; background: var(--c); color: var(--ink); }}
.heatmap td b {{ display: block; font-size: 16px; }}
.heatmap td small {{ font-size: 11px; opacity: .85; }}
.heatmap td.slow {{ box-shadow: inset 0 0 0 2px var(--text); }}
.heatmap td.empty {{ color: var(--muted); background: none; }}
.table-wrap {{ overflow-x: auto; }}
table.data {{ border-collapse: collapse; width: 100%; font-size: 14px; margin-top: 8px; }}
table.data th {{ text-align: left; font-weight: 600; color: var(--text-2); border-bottom: 1px solid var(--axis); padding: 6px 10px; }}
table.data td {{ border-bottom: 1px solid var(--grid); padding: 6px 10px; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.variants td {{ vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--grid); font-size: 14px; }}
.variants {{ border-collapse: collapse; width: 100%; }}
.variants .path {{ color: var(--text-2); }}
.variants .arrow {{ color: var(--muted); }}
.share {{ width: 90px; height: 10px; background: var(--grid); border-radius: 3px; margin-top: 6px; }}
.share span {{ display: block; height: 100%; background: var(--accent); border-radius: 3px; }}
.about p, .about li {{ color: var(--text-2); font-size: 14px; }}
footer {{ margin-top: 48px; font-size: 13px; color: var(--muted); }}
#tooltip {{ position: fixed; pointer-events: none; z-index: 10; max-width: 320px; background: var(--text); color: var(--page);
  font-size: 13px; padding: 6px 10px; border-radius: 6px; opacity: 0; transition: opacity .1s; }}
[data-tip]:focus {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
@media (max-width: 640px) {{
  h1 {{ font-size: 24px; }}
  .advice {{ grid-template-columns: 1fr; }}
  .finding {{ padding: 16px; gap: 10px; }}
  .num-badge {{ display: none; }}
}}
</style>
</head>
<body>
<main>
<p class="eyebrow">Odoo Process X-Ray · order-to-cash</p>
<h1>{company}</h1>
<p class="lede">What really happened to every sales order between {period}, reconstructed from Odoo's own
change history. {source_note}</p>

<div class="tiles">{tiles}</div>

{written}

<h2>Key findings</h2>
<p class="section-intro">Problems that are both frequent and concentrated somewhere specific, so there is
something concrete to fix. Click one to jump to its details.</p>
<div class="card"><ol class="summary">{summary}</ol></div>

{cards}

<h2>Other checks</h2>
<p class="section-intro">These rules found problems too, but with no clear pattern behind them.</p>
{others}
{clean}

<h2>The process map</h2>
<p class="section-intro">Every box is a step, every arrow means "this step came right after that one".
Thicker arrows carry more orders, and the colour shows how long orders waited before the next step
(scale below). Numbers read as <i>orders · median wait</i>. Rare paths (under 1.5% of orders) are hidden.</p>
<div class="map-wrap">{process_map}</div>
<div class="legend"><span>Arrow colour = median wait:
<span class="ramp"><span class="w0"></span><span class="w2"></span><span class="w4"></span><span class="w6"></span><span class="w8"></span></span>
short → long</span><span>Arrow width = number of orders</span></div>
<details><summary>Show the map as a table</summary>{edge_table}</details>

<h2>Where the time goes</h2>
<p class="section-intro">Median calendar days for each step, from the first time it happened to the first time
the next one did. The whisker shows how long it takes for 90% of orders.</p>
<div class="card">{step_chart}</div>
<details><summary>Show as a table</summary>{step_table}</details>

<h2>Shipping speed by warehouse and weekday</h2>
<p class="section-intro">Median <b>working days</b> from confirmation to shipment, by the weekday the order was
confirmed. Weekends are excluded, so a Friday order shipped on Monday counts as one day.
Outlined cells were flagged as unusually slow.</p>
<div class="card table-wrap">{heatmap}</div>

<h2>Most common paths</h2>
<p class="section-intro">The {n_variants} different routes orders took, most frequent first (repeated steps
are counted once).</p>
<div class="card table-wrap"><table class="variants"><tbody>{variant_rows}</tbody></table></div>

<h2>About this analysis</h2>
<div class="about">
<ul>
<li><b>Source.</b> {events} events read from Odoo through its JSON-2 API: sales orders, deliveries,
invoices and credit notes, plus their chatter tracking (the status-change lines). {history_note}</li>
<li><b>Method.</b> Plain counting and date arithmetic. Each problem is a short rule written in Python,
and a pattern is only reported when it would be very unlikely by chance.</li>
<li><b>Limits.</b> The data shows <i>what</i> happened, not <i>why</i>: every finding is a question to take
to the people involved. Orders migrated from an older system have no change history.
Weekdays and weekends are computed in {tz}. Overdue status as of {as_of}.</li>
</ul>
</div>

<footer>Generated by <a href="{project_url}">Odoo Process X-Ray</a> v{version}.</footer>
</main>
<div id="tooltip" role="tooltip"></div>
<script>
(function () {{
  var tip = document.getElementById("tooltip");
  function show(el, x, y) {{
    tip.textContent = el.getAttribute("data-tip");
    var w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(x + 14, window.innerWidth - w - 8) + "px";
    tip.style.top = Math.max(y - h - 10, 8) + "px";
    tip.style.opacity = 1;
  }}
  function hide() {{ tip.style.opacity = 0; }}
  document.querySelectorAll("[data-tip]").forEach(function (el) {{
    el.addEventListener("pointermove", function (e) {{ show(el, e.clientX, e.clientY); }});
    el.addEventListener("pointerleave", hide);
    el.addEventListener("focus", function () {{
      var r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top);
    }});
    el.addEventListener("blur", hide);
  }});
}})();
</script>
</body>
</html>
"""
