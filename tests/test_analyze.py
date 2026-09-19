from datetime import datetime, timezone

from xray.analyze import analyze, evaluate_rule, build_cases
from xray.eventlog import GOODS_SHIPPED, ORDER_CHANGED, ORDER_CONFIRMED, QUOTE_CREATED
from xray.report import render
from xray.rules import RULES

from conftest import make_rows, to_frame

AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_finds_the_salesperson_behind_changes(synthetic_log):
    results = analyze(synthetic_log, as_of=AS_OF)
    changed = next(r for r in results.rules if r.rule.key == "changed_after_confirmation")
    assert changed.concentration, "the planted pattern should be found"
    top = changed.concentration[0]
    assert top.dimension == "salesperson" and top.values == ["Tom"]


def test_no_story_without_a_pattern():
    # 2 hits out of 40 orders, spread over two salespeople: nothing to report.
    rows = []
    for i in range(40):
        steps = [(QUOTE_CREATED, i), (ORDER_CONFIRMED, i + 1)]
        if i in (3, 30):
            steps.append((ORDER_CHANGED, i + 2))
        rows += make_rows(f"S{i:03d}", steps, salesperson="Ann" if i < 20 else "Bob")
    cases = build_cases(to_frame(rows), AS_OF, "UTC")
    rule = next(r for r in RULES if r.key == "changed_after_confirmation")
    assert evaluate_rule(rule, cases).concentration == []


def test_process_map_counts(synthetic_log):
    results = analyze(synthetic_log, as_of=AS_OF)
    assert results.nodes[QUOTE_CREATED] == 200
    assert results.edges[(QUOTE_CREATED, ORDER_CONFIRMED)]["count"] == 200
    assert abs(results.edges[(QUOTE_CREATED, ORDER_CONFIRMED)]["median_days"] - 20 / 24) < 1e-9
    changed = results.nodes.get(ORDER_CHANGED, 0)
    assert results.edges[(ORDER_CONFIRMED, GOODS_SHIPPED)]["count"] == 200 - changed


def test_bottleneck_by_weekday():
    rows = []
    for week in range(6):
        for day in range(5):
            confirmed = week * 168 + day * 24 + 1  # Mon..Fri 10:00
            ship_after = 96 if day == 4 else 20     # Friday orders wait until Tuesday
            for k in range(3):
                case_id = f"S{week}{day}{k}"
                rows += make_rows(case_id, [(QUOTE_CREATED, confirmed - 1), (ORDER_CONFIRMED, confirmed),
                                            (GOODS_SHIPPED, confirmed + ship_after)], warehouse="WAW")
    results = analyze(to_frame(rows), as_of=AS_OF, tz="UTC")
    assert [b["warehouse"] for b in results.bottlenecks] == ["WAW"]
    assert [d[0] for d in results.bottlenecks[0]["slow_days"]] == ["Fri"]


def test_report_escapes_data(synthetic_log):
    log = synthetic_log.copy()
    log.loc[log["case_id"] == "S00003", "customer"] = "<script>alert(1)</script>"
    html = render(analyze(log, company="<b>Evil</b> Ltd", as_of=AS_OF))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;b&gt;Evil&lt;/b&gt; Ltd" in html
    assert html.count("<script>") == 1  # only the page's own tooltip script
