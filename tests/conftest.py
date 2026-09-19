import random
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from xray.eventlog import (
    GOODS_SHIPPED, INVOICE_POSTED, ORDER_CHANGED, ORDER_CONFIRMED, PAYMENT_RECEIVED, QUOTE_CREATED,
)

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)  # a Monday


def make_rows(case_id, steps, **attributes):
    """steps: list of (activity, hours after T0[, due_date])."""
    base = {"customer": "Acme", "customer_country": "Belgium", "salesperson": "Ann", "warehouse": "BRU",
            "order_amount": "100.00", "currency": "EUR", "products": "Coffee"}
    base.update(attributes)
    rows = []
    for step in steps:
        activity, hours = step[0], step[1]
        due = step[2] if len(step) > 2 else ""
        rows.append(dict(base, case_id=case_id, activity=activity,
                         timestamp=(T0 + timedelta(hours=hours)).isoformat(),
                         resource="", document=case_id, detail="", source="history", due_date=due))
    return rows


def to_frame(rows):
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df


@pytest.fixture
def synthetic_log():
    """200 orders; salesperson 'Tom' changes most of his orders after confirmation."""
    rng = random.Random(1)
    rows = []
    for i in range(200):
        seller = ["Ann", "Bob", "Cid", "Tom"][i % 4]
        steps = [(QUOTE_CREATED, i), (ORDER_CONFIRMED, i + 20)]
        changed = rng.random() < (0.7 if seller == "Tom" else 0.03)
        if changed:
            steps.append((ORDER_CHANGED, i + 22))
        steps += [(GOODS_SHIPPED, i + 30), (INVOICE_POSTED, i + 40, "2026-03-01"), (PAYMENT_RECEIVED, i + 600)]
        rows += make_rows(f"S{i:05d}", steps, salesperson=seller)
    return to_frame(rows)
