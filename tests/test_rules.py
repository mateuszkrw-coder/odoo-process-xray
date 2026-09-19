from datetime import datetime, timezone

from conftest import make_rows, to_frame
from xray.analyze import build_cases
from xray.eventlog import (
    CREDIT_NOTE, DELIVERY_RESCHEDULED, GOODS_SHIPPED, INVOICE_POSTED, ORDER_CANCELLED, ORDER_CHANGED,
    ORDER_CONFIRMED, PAYMENT_RECEIVED, QUOTE_CREATED, working_days,
)
from xray.rules import RULES

AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)
RULE = {r.key: r for r in RULES}


def case(steps):
    return build_cases(to_frame(make_rows("S1", steps)), AS_OF, "Europe/Brussels")[0]


def hits(key, steps):
    c = case(steps)
    rule = RULE[key]
    return rule.applies_to(c) and rule.check(c)


def test_changed_after_confirmation():
    assert hits("changed_after_confirmation", [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1), (ORDER_CHANGED, 2)])
    assert not hits("changed_after_confirmation", [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1)])


def test_invoiced_before_shipping():
    assert hits("invoiced_before_shipping",
                [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1), (INVOICE_POSTED, 2), (GOODS_SHIPPED, 5)])
    assert not hits("invoiced_before_shipping",
                    [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1), (GOODS_SHIPPED, 2), (INVOICE_POSTED, 5)])


def test_rescheduled_repeatedly():
    base = [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1)]
    assert hits("rescheduled_repeatedly", base + [(DELIVERY_RESCHEDULED, 2), (DELIVERY_RESCHEDULED, 30)])
    assert not hits("rescheduled_repeatedly", base + [(DELIVERY_RESCHEDULED, 2)])


def test_slow_shipping_ignores_weekends():
    # Confirmed Friday 9:00, shipped Monday 9:00: 3 calendar days but 1 working day.
    friday = 4 * 24
    assert not hits("slow_shipping", [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, friday), (GOODS_SHIPPED, friday + 72)])
    # Confirmed Monday, shipped Friday: 4 working days.
    assert hits("slow_shipping", [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1), (GOODS_SHIPPED, 1 + 96)])


def test_paid_late_uses_due_date():
    steps = [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1), (INVOICE_POSTED, 2, "2026-01-10")]
    assert hits("paid_late", steps + [(PAYMENT_RECEIVED, 24 * 30)])      # 4 Feb: 25 days late
    assert not hits("paid_late", steps + [(PAYMENT_RECEIVED, 24 * 10)])  # 15 Jan: 5 days late


def test_overdue_unpaid():
    assert hits("overdue_unpaid", [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1), (INVOICE_POSTED, 2, "2026-02-01")])
    assert not hits("overdue_unpaid", [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1), (INVOICE_POSTED, 2, "2026-12-01")])


def test_cancelled_and_credit_note():
    assert hits("cancelled_after_confirmation", [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1), (ORDER_CANCELLED, 5)])
    assert not hits("cancelled_after_confirmation", [(QUOTE_CREATED, 0), (ORDER_CANCELLED, 5)])  # lost quote
    assert hits("needed_credit_note", [(QUOTE_CREATED, 0), (ORDER_CONFIRMED, 1), (INVOICE_POSTED, 2), (CREDIT_NOTE, 9)])


def test_working_days():
    friday = datetime(2026, 1, 9, 9, 0, tzinfo=timezone.utc)
    monday = datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc)
    assert abs(working_days(friday, monday, "UTC") - 1.0) < 1e-9
    assert abs(working_days(monday, friday.replace(day=16), "UTC") - 4.0) < 1e-9
