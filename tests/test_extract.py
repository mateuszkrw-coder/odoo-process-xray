"""The extractor against a fake Odoo that answers like the JSON-2 API does."""
from xray.eventlog import (
    CREDIT_NOTE, DELIVERY_RESCHEDULED, GOODS_SHIPPED, INVOICE_POSTED, ORDER_CHANGED, ORDER_CONFIRMED,
    PAYMENT_RECEIVED, QUOTE_CREATED, QUOTE_SENT,
)
from xray.extract import Extractor

SELECTIONS = {
    ("sale.order", "state"): [("draft", "Quotation"), ("sent", "Quotation Sent"), ("sale", "Sales Order"),
                              ("cancel", "Cancelled")],
    ("stock.picking", "state"): [("assigned", "Ready"), ("done", "Done")],
    ("account.move", "state"): [("draft", "Draft"), ("posted", "Posted")],
    ("account.move", "payment_state"): [("not_paid", "Not Paid"), ("paid", "Paid")],
}
POLISH = {"Quotation Sent": "Oferta wysłana", "Sales Order": "Zamówienie sprzedaży"}

DATA = {
    "res.lang": [{"id": 1, "code": "en_US", "active": True}, {"id": 2, "code": "pl_PL", "active": True}],
    "sale.order": [{
        "id": 1, "name": "S00001", "state": "sale", "create_date": "2026-01-05 09:00:00",
        "create_uid": [2, "Ann"], "date_order": "2026-01-06 10:00:00", "partner_id": [7, "Acme"],
        "user_id": [2, "Ann"], "warehouse_id": [1, "Brussels DC"], "amount_total": 120.0,
        "currency_id": [1, "EUR"], "picking_ids": [10], "invoice_ids": [20],
    }, {
        # migrated order: no chatter history at all
        "id": 2, "name": "S00002", "state": "sale", "create_date": "2026-01-05 11:00:00",
        "create_uid": [2, "Ann"], "date_order": "2026-01-07 10:00:00", "partner_id": [7, "Acme"],
        "user_id": [2, "Ann"], "warehouse_id": [1, "Brussels DC"], "amount_total": 50.0,
        "currency_id": [1, "EUR"], "picking_ids": [11], "invoice_ids": [],
    }],
    "res.partner": [{"id": 7, "country_id": [21, "Belgium"]}],
    "sale.order.line": [{"id": 1, "order_id": [1, "S00001"], "product_id": [5, "Coffee"]},
                        {"id": 2, "order_id": [2, "S00002"], "product_id": [5, "Coffee"]}],
    "stock.picking": [
        {"id": 10, "name": "BRU/OUT/1", "state": "done", "picking_type_code": "outgoing", "date_done": "2026-01-08 10:00:00"},
        {"id": 11, "name": "BRU/OUT/2", "state": "done", "picking_type_code": "outgoing", "date_done": "2026-01-09 10:00:00"},
    ],
    "account.move": [
        {"id": 20, "name": "INV/1", "move_type": "out_invoice", "state": "posted", "invoice_date": "2026-01-09",
         "invoice_date_due": "2026-02-08", "reversed_entry_id": False},
        {"id": 21, "name": "RINV/1", "move_type": "out_refund", "state": "posted", "invoice_date": "2026-01-15",
         "invoice_date_due": "2026-01-15", "reversed_entry_id": [20, "INV/1"]},
    ],
    "ir.model.fields": [
        {"id": 100, "model": "sale.order", "name": "state"}, {"id": 101, "model": "sale.order", "name": "amount_total"},
        {"id": 102, "model": "stock.picking", "name": "state"}, {"id": 103, "model": "stock.picking", "name": "scheduled_date"},
        {"id": 104, "model": "account.move", "name": "state"}, {"id": 105, "model": "account.move", "name": "payment_state"},
    ],
    "mail.message": [
        {"id": 1, "model": "sale.order", "res_id": 1, "date": "2026-01-05 10:00:00", "author_id": [3, "Ann"]},
        {"id": 2, "model": "sale.order", "res_id": 1, "date": "2026-01-06 10:00:00", "author_id": [3, "Ann"]},
        {"id": 3, "model": "sale.order", "res_id": 1, "date": "2026-01-06 15:00:00", "author_id": [3, "Ann"]},
        {"id": 4, "model": "stock.picking", "res_id": 10, "date": "2026-01-07 09:00:00", "author_id": [4, "Marc"]},
        {"id": 5, "model": "stock.picking", "res_id": 10, "date": "2026-01-08 10:00:00", "author_id": [4, "Marc"]},
        {"id": 6, "model": "account.move", "res_id": 20, "date": "2026-01-09 11:00:00", "author_id": [5, "Julie"]},
        {"id": 7, "model": "account.move", "res_id": 21, "date": "2026-01-15 11:00:00", "author_id": [5, "Julie"]},
        {"id": 8, "model": "account.move", "res_id": 20, "date": "2026-02-01 11:00:00", "author_id": [5, "Julie"]},
    ],
    "mail.tracking.value": [
        # the salesperson works in Polish: the chatter stores Polish labels
        {"id": 1, "mail_message_id": [1, ""], "field_id": [100, ""], "old_value_char": "Oferta", "new_value_char": "Oferta wysłana"},
        {"id": 2, "mail_message_id": [2, ""], "field_id": [100, ""], "old_value_char": "Oferta wysłana", "new_value_char": "Zamówienie sprzedaży"},
        {"id": 3, "mail_message_id": [3, ""], "field_id": [101, ""], "old_value_float": 100.0, "new_value_float": 120.0},
        {"id": 4, "mail_message_id": [4, ""], "field_id": [103, ""], "old_value_datetime": "2026-01-07 09:00:00",
         "new_value_datetime": "2026-01-10 09:00:00"},
        {"id": 5, "mail_message_id": [5, ""], "field_id": [102, ""], "old_value_char": "Ready", "new_value_char": "Done"},
        {"id": 6, "mail_message_id": [6, ""], "field_id": [104, ""], "old_value_char": "Draft", "new_value_char": "Posted"},
        {"id": 7, "mail_message_id": [7, ""], "field_id": [104, ""], "old_value_char": "Draft", "new_value_char": "Posted"},
        {"id": 8, "mail_message_id": [8, ""], "field_id": [105, ""], "old_value_char": "Not Paid", "new_value_char": "Paid"},
    ],
}


def _value(record, field):
    value = record.get(field)
    return value[0] if isinstance(value, list) and value and not isinstance(value[0], list) and field != "ids" else value


def _match(record, domain):
    for field, op, target in domain:
        value = _value(record, field)
        if op == "=" and value != target:
            return False
        if op == "in" and value not in target:
            return False
        if op == "!=" and target is False and not value:
            return False
        if op in (">=", "<"):
            continue
    return True


class FakeOdoo:
    def search_read(self, model, domain, fields, **_):
        if model == "mail.message":
            domain = [d for d in domain if d[0] != "tracking_value_ids"]
        return [dict(r) for r in DATA[model] if _match(r, domain)]

    def read_by_ids(self, model, ids, fields):
        return self.search_read(model, [("id", "in", list(ids))], fields)

    def call(self, model, method, **params):
        assert method == "fields_get"
        polish = params["context"]["lang"] == "pl_PL"
        return {field: {"selection": [(v, POLISH.get(l, l) if polish else l) for v, l in SELECTIONS[(model, field)]]}
                for field in params["allfields"] if (model, field) in SELECTIONS}


def test_extract_builds_events():
    rows, stats = Extractor(FakeOdoo(), log=lambda *_: None).run()
    s1 = [(r["activity"], r["timestamp"], r["source"]) for r in rows if r["case_id"] == "S00001"]
    activities = [a for a, _, _ in s1]
    assert sorted(activities) == sorted([QUOTE_CREATED, QUOTE_SENT, ORDER_CONFIRMED, ORDER_CHANGED,
                                         DELIVERY_RESCHEDULED, GOODS_SHIPPED, INVOICE_POSTED, PAYMENT_RECEIVED,
                                         CREDIT_NOTE])
    assert all(source == "history" for _, _, source in s1)
    confirmed = next(t for a, t, _ in s1 if a == ORDER_CONFIRMED)
    assert confirmed == "2026-01-06T10:00:00+00:00"
    invoice = next(r for r in rows if r["activity"] == INVOICE_POSTED)
    assert invoice["due_date"] == "2026-02-08" and invoice["resource"] == "Julie"
    assert next(r for r in rows if r["activity"] == ORDER_CHANGED)["detail"] == "amount 100.00 -> 120.00"


def test_orders_without_history_fall_back_to_document_dates():
    rows, _ = Extractor(FakeOdoo(), log=lambda *_: None).run()
    s2 = {r["activity"]: r for r in rows if r["case_id"] == "S00002"}
    assert s2[ORDER_CONFIRMED]["source"] == "document date"
    assert s2[ORDER_CONFIRMED]["timestamp"] == "2026-01-07T10:00:00+00:00"
    assert s2[GOODS_SHIPPED]["source"] == "document date"
