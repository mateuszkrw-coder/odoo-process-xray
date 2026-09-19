"""From an event log to findings: timings, paths, bottlenecks, rule hits.

Everything here is plain counting and date arithmetic with pandas. No AI and
no guessing: the same event log always gives the same numbers.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import comb, exp, lgamma, log
from statistics import median
from zoneinfo import ZoneInfo

import pandas as pd

from .eventlog import (
    ACTIVITY_ORDER, GOODS_SHIPPED, INVOICE_POSTED, ORDER_CANCELLED, ORDER_CONFIRMED, PAYMENT_RECEIVED,
    QUOTE_CREATED, Case, Event,
)
from .rules import RULES

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DIMENSIONS = {
    "salesperson": "Salesperson",
    "warehouse": "Warehouse",
    "customer": "Customer",
    "product": "Product",
    "confirmed_on": "Day confirmed",
}
STEPS = [
    ("Quote to order", QUOTE_CREATED, ORDER_CONFIRMED),
    ("Order to shipment", ORDER_CONFIRMED, GOODS_SHIPPED),
    ("Shipment to invoice", GOODS_SHIPPED, INVOICE_POSTED),
    ("Invoice to payment", INVOICE_POSTED, PAYMENT_RECEIVED),
]
START, END = "Start", "End"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_event_log(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df


def build_cases(df, as_of, tz):
    zone = ZoneInfo(tz)
    cases = []
    for case_id, rows in df.sort_values("timestamp", kind="stable").groupby("case_id", sort=True):
        first = rows.iloc[0]
        events = [Event(r.activity, r.timestamp.to_pydatetime(), r.resource, r.document, r.detail)
                  for r in rows.itertuples()]
        dues = [d for d in rows["due_date"] if d]
        attributes = {col: first[col] for col in ("customer", "customer_country", "salesperson",
                                                   "warehouse", "currency")}
        attributes["order_amount"] = float(first["order_amount"] or 0)
        attributes["products"] = [p for p in first["products"].split("; ") if p]
        case = Case(case_id, events, attributes,
                    due_date=datetime.fromisoformat(dues[0]).replace(tzinfo=timezone.utc) if dues else None,
                    as_of=as_of, tz=tz)
        confirmed = case.first(ORDER_CONFIRMED)
        case.attributes["confirmed_on"] = WEEKDAYS[confirmed.astimezone(zone).weekday()] if confirmed else ""
        cases.append(case)
    return cases


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

@dataclass
class StepTiming:
    label: str
    start: str
    end: str
    n: int
    median_days: float | None
    p90_days: float | None


@dataclass
class Concentration:
    """A small group (one salesperson, a few customers...) where a rule hits unusually often."""
    dimension: str
    values: list
    hit_share: float    # share of all hits that fall in the group
    case_share: float   # share of all orders that fall in the group
    rate: float         # how often the rule hits inside the group
    cases: set          # ids of the group's orders

    @property
    def label(self):
        return DIMENSIONS[self.dimension]


@dataclass
class RuleResult:
    rule: object
    applicable: int
    hits: list
    breakdown: dict                      # dimension -> [(value, applicable, hits)]
    concentration: list = field(default_factory=list)

    @property
    def rate(self):
        return len(self.hits) / self.applicable if self.applicable else 0.0


@dataclass
class Results:
    company: str
    as_of: datetime
    tz: str
    period: tuple
    cases: list
    counts: dict
    steps: list
    order_to_cash: StepTiming
    nodes: dict
    edges: dict
    variants: list
    weekday_matrix: dict
    bottlenecks: list
    rules: list
    sources: dict
    currency: str


def _days(delta):
    return delta.total_seconds() / 86400


def _quantile(values, q):
    if not values:
        return None
    return float(pd.Series(values).quantile(q))


def step_timing(cases, label, start, end):
    values = [d for c in cases if (d := c.days_between(start, end)) is not None and d >= 0]
    return StepTiming(label, start, end, len(values), _quantile(values, 0.5), _quantile(values, 0.9))


def process_map(cases):
    """Directly-follows graph: how often activity B comes right after activity A."""
    nodes = Counter()
    edges = defaultdict(list)
    for case in cases:
        seen = set()
        previous, previous_time = START, None
        for event in case.events:
            if event.activity not in seen:
                nodes[event.activity] += 1
                seen.add(event.activity)
            wait = _days(event.timestamp - previous_time) if previous_time else None
            edges[(previous, event.activity)].append(wait)
            previous, previous_time = event.activity, event.timestamp
        edges[(previous, END)].append(None)
    summary = {}
    for pair, waits in edges.items():
        timed = [w for w in waits if w is not None]
        summary[pair] = {"count": len(waits), "median_days": median(timed) if timed else None}
    return dict(nodes), summary


def variants(cases, top=8):
    """Distinct paths through the process (repeats of the same step collapsed)."""
    paths = Counter()
    for case in cases:
        path = []
        for activity in case.activities:
            if not path or path[-1] != activity:
                path.append(activity)
        paths[tuple(path)] += 1
    total = len(cases)
    return [(path, n, n / total) for path, n in paths.most_common(top)], len(paths)


def weekday_matrix(cases):
    """Median working days from confirmation to shipment, per warehouse and weekday confirmed."""
    cells = defaultdict(list)
    for case in cases:
        days = case.working_days_between(ORDER_CONFIRMED, GOODS_SHIPPED)
        if days is not None and days >= 0:
            cells[(case["warehouse"], case["confirmed_on"])].append(days)
    matrix = defaultdict(dict)
    for (warehouse, weekday), values in cells.items():
        matrix[warehouse][weekday] = (median(values), len(values))
    return dict(matrix)


def find_bottlenecks(matrix, min_orders=8, min_ratio=1.75, min_days=1.5):
    """Weekdays whose orders wait much longer than that warehouse's normal days."""
    found = []
    for warehouse, days in matrix.items():
        usable = {d: v for d, v in days.items() if v[1] >= min_orders}
        if len(usable) < 3:
            continue
        typical = median(sorted(v[0] for v in usable.values())[:3])  # the three fastest days
        slow = [(d, v[0], v[1]) for d, v in usable.items()
                if v[0] >= min_days and typical > 0 and v[0] / typical >= min_ratio]
        if slow:
            slow.sort(key=lambda s: WEEKDAYS.index(s[0]))
            found.append({"warehouse": warehouse, "typical_days": typical, "slow_days": slow,
                          "orders": sum(s[2] for s in slow)})
    return sorted(found, key=lambda b: -b["orders"])


def _values(case, dimension):
    if dimension == "product":
        return case["products"] or [""]
    return [case[dimension]]


def chance(hits, orders, rate):
    """Probability of seeing at least `hits` problems in `orders` orders by pure
    chance, if every order had the average `rate` (binomial tail)."""
    if rate <= 0:
        return 0.0 if hits else 1.0
    if rate >= 1:
        return 1.0
    total = 0.0
    for k in range(hits, orders + 1):
        total += exp(lgamma(orders + 1) - lgamma(k + 1) - lgamma(orders - k + 1)
                     + k * log(rate) + (orders - k) * log(1 - rate))
    return min(total, 1.0)


def evaluate_rule(rule, cases, min_hits=3, min_lift=1.75, max_chance=1e-3):
    """Run one rule on every order, then look for where the hits concentrate.

    A concentration is a small group of values (one salesperson, a few
    customers, one product...) whose orders hit the rule at least `min_lift`
    times more often than average and together explain a large share of all
    hits. It is only reported if it is very unlikely to be chance: if the
    group's orders behaved like all other orders, seeing that many hits must
    have a probability below `max_chance` (divided by the number of groups of
    that size we could have picked). Small numbers don't produce stories.
    """
    applicable = [c for c in cases if rule.applies_to(c)]
    hits = [c for c in applicable if rule.check(c)]
    hit_ids = {c.case_id for c in hits}
    overall = len(hits) / len(applicable) if applicable else 0
    breakdown, candidates = {}, []
    for dimension in DIMENSIONS:
        counts = defaultdict(lambda: [0, 0])
        for case in applicable:
            for value in _values(case, dimension):
                counts[value][0] += 1
        for case in hits:
            for value in _values(case, dimension):
                counts[value][1] += 1
        rows = sorted(((v, a, h) for v, (a, h) in counts.items() if v), key=lambda r: (-r[2], -r[1], r[0]))
        breakdown[dimension] = rows
        members = [v for v, a, h in rows if h >= min_hits and h / a >= min_lift * overall][:5]
        if not members:
            continue
        group = {c.case_id for c in applicable if any(v in members for v in _values(c, dimension))}
        group_hits = len(group & hit_ids)
        hit_share, case_share = group_hits / len(hits), len(group) / len(applicable)
        # Compare with the orders outside the group: how likely is this many
        # hits if the group behaved like everyone else?
        rest = len(applicable) - len(group)
        rest_rate = max(len(hits) - group_hits, 0.5) / rest if rest else overall
        possible_groups = comb(len(rows), len(members))
        if (group_hits >= 5 and hit_share >= 0.4 and hit_share / case_share >= 1.5
                and chance(group_hits, len(group), rest_rate) < max_chance / possible_groups):
            candidates.append(Concentration(dimension, members, hit_share, case_share, group_hits / len(group), group))

    # Keep the strongest; drop groups that only restate one already kept
    # (e.g. "Warsaw's salespeople" when "Warsaw warehouse" is already there),
    # or whose hits are mostly explained by it.
    candidates.sort(key=lambda c: (-(c.hit_share / c.case_share) * c.hit_share, len(c.values)))
    kept = []
    for c in candidates:
        c_hits = c.cases & hit_ids
        redundant = False
        for k in kept:
            overlap = len(c.cases & k.cases)
            similar = overlap / len(c.cases | k.cases) >= 0.8
            nested = overlap / len(c.cases) >= 0.9 and c.rate < 2 * k.rate
            explained = len(c_hits & k.cases) / len(c_hits) >= 0.8
            redundant = redundant or similar or nested or explained
        if not redundant:
            kept.append(c)
    return RuleResult(rule, len(applicable), hits, breakdown, kept[:3])


def analyze(df, company="", as_of=None, tz="Europe/Brussels"):
    as_of = as_of or df["timestamp"].max().to_pydatetime()
    cases = build_cases(df, as_of, tz)

    def n(pred):
        return sum(1 for c in cases if pred(c))

    counts = {
        "quotations": len(cases),
        "confirmed": n(lambda c: c.has(ORDER_CONFIRMED)),
        "lost": n(lambda c: not c.has(ORDER_CONFIRMED)),
        "cancelled_after_confirmation": n(lambda c: c.happened_before(ORDER_CONFIRMED, ORDER_CANCELLED)),
        "shipped": n(lambda c: c.has(GOODS_SHIPPED)),
        "invoiced": n(lambda c: c.has(INVOICE_POSTED)),
        "paid": n(lambda c: c.has(PAYMENT_RECEIVED)),
        "events": len(df),
    }
    counts["conversion"] = counts["confirmed"] / counts["quotations"] if counts["quotations"] else 0

    nodes, edges = process_map(cases)
    top_variants, n_variants = variants(cases)
    matrix = weekday_matrix(cases)
    currencies = Counter(c["currency"] for c in cases)

    return Results(
        company=company,
        as_of=as_of,
        tz=tz,
        period=(df["timestamp"].min().to_pydatetime(), df["timestamp"].max().to_pydatetime()),
        cases=cases,
        counts=counts | {"variants": n_variants},
        steps=[step_timing(cases, *s) for s in STEPS],
        order_to_cash=step_timing(cases, "Order to cash", ORDER_CONFIRMED, PAYMENT_RECEIVED),
        nodes=nodes,
        edges=edges,
        variants=top_variants,
        weekday_matrix=matrix,
        bottlenecks=find_bottlenecks(matrix),
        rules=[evaluate_rule(r, cases) for r in RULES],
        sources=dict(Counter(df["source"])),
        currency=currencies.most_common(1)[0][0] if currencies else "",
    )


def activity_rank(activity):
    if activity == START:
        return -1
    if activity == END:
        return len(ACTIVITY_ORDER)
    return ACTIVITY_ORDER.index(activity) if activity in ACTIVITY_ORDER else len(ACTIVITY_ORDER) - 1
