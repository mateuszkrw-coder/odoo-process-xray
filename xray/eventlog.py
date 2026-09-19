"""The event log: one row per thing that happened to a sales order.

This is the standard input format for process mining (case / activity /
timestamp), so the CSV also opens directly in Disco, Celonis, ProM or PM4Py.
"""
import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Activities, in the order they normally happen.
QUOTE_CREATED = "Quotation created"
QUOTE_SENT = "Quotation sent"
ORDER_CONFIRMED = "Order confirmed"
ORDER_CHANGED = "Order changed after confirmation"
ORDER_CANCELLED = "Order cancelled"
DELIVERY_RESCHEDULED = "Delivery rescheduled"
GOODS_SHIPPED = "Goods shipped"
INVOICE_POSTED = "Invoice posted"
INVOICE_RESET = "Invoice reset to draft"
CREDIT_NOTE = "Credit note posted"
PAYMENT_RECEIVED = "Payment received"

ACTIVITY_ORDER = [
    QUOTE_CREATED, QUOTE_SENT, ORDER_CONFIRMED, ORDER_CHANGED, DELIVERY_RESCHEDULED,
    GOODS_SHIPPED, INVOICE_POSTED, INVOICE_RESET, CREDIT_NOTE, PAYMENT_RECEIVED, ORDER_CANCELLED,
]

CASE_COLUMNS = ["customer", "customer_country", "salesperson", "warehouse", "order_amount", "currency", "products"]
COLUMNS = ["case_id", "activity", "timestamp", "resource", "document", "detail", "source", "due_date"] + CASE_COLUMNS


def write_csv(rows, path):
    rows = sorted(rows, key=lambda r: (r["case_id"], r["timestamp"], ACTIVITY_ORDER.index(r["activity"])))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def working_days(start, end, tz="UTC"):
    """Days from start to end, not counting Saturdays and Sundays (in local time)."""
    zone = ZoneInfo(tz)
    start, end = start.astimezone(zone), end.astimezone(zone)
    seconds = (end - start).total_seconds()
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        next_day = day + timedelta(days=1)
        if day.weekday() >= 5:
            overlap = (min(end, next_day) - max(start, day)).total_seconds()
            seconds -= max(overlap, 0)
        day = next_day
    return seconds / 86400


@dataclass
class Event:
    activity: str
    timestamp: datetime
    resource: str = ""
    document: str = ""
    detail: str = ""


@dataclass
class Case:
    """Everything that happened to one sales order, in time order.

    The helper methods exist so business rules read like plain English:
        case.has(GOODS_SHIPPED)
        case.happened_before(INVOICE_POSTED, GOODS_SHIPPED)
        case.days_between(ORDER_CONFIRMED, GOODS_SHIPPED)
    """
    case_id: str
    events: list
    attributes: dict = field(default_factory=dict)
    due_date: datetime | None = None
    as_of: datetime | None = None  # when the data was extracted ("today")
    tz: str = "UTC"                  # local time zone, for weekdays and weekends

    def has(self, activity):
        return any(e.activity == activity for e in self.events)

    def count(self, activity):
        return sum(1 for e in self.events if e.activity == activity)

    def first(self, activity):
        return next((e.timestamp for e in self.events if e.activity == activity), None)

    def last(self, activity):
        return next((e.timestamp for e in reversed(self.events) if e.activity == activity), None)

    def happened_before(self, a, b):
        """True if the first `a` happened before the first `b` (both must exist)."""
        ta, tb = self.first(a), self.first(b)
        return ta is not None and tb is not None and ta < tb

    def days_between(self, a, b):
        """Days from the first `a` to the first `b`, or None if either is missing."""
        ta, tb = self.first(a), self.first(b)
        if ta is None or tb is None:
            return None
        return (tb - ta).total_seconds() / 86400

    def working_days_between(self, a, b):
        """Like days_between, but weekends don't count."""
        ta, tb = self.first(a), self.first(b)
        if ta is None or tb is None:
            return None
        return working_days(ta, tb, self.tz)

    @property
    def activities(self):
        return [e.activity for e in self.events]

    def __getitem__(self, attribute):
        return self.attributes.get(attribute, "")
