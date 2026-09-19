"""Turn Odoo's own history into an event log.

Odoo already records a timestamped history for every sales order, delivery
and invoice: each status change is logged in the chatter (models
``mail.message`` + ``mail.tracking.value``). Nobody reads it in bulk. This
module does, through the JSON-2 API:

    sale.order      state -> sent / sale / cancel, amount_total changes
    stock.picking   state -> done, scheduled_date postponed
    account.move    state -> posted / back to draft, payment_state -> paid

When a record has no history (typically data migrated from an older system),
the document's own dates are used instead and the event is marked
``source=document date``.

Reading ``mail.tracking.value`` requires an API key of a user with the
Settings / Administration right.
"""
from collections import defaultdict
from datetime import datetime, timezone

from .eventlog import (
    CREDIT_NOTE, DELIVERY_RESCHEDULED, GOODS_SHIPPED, INVOICE_POSTED, INVOICE_RESET, ORDER_CANCELLED,
    ORDER_CHANGED, ORDER_CONFIRMED, PAYMENT_RECEIVED, QUOTE_CREATED, QUOTE_SENT,
)

TRACKED_FIELDS = {
    "sale.order": ["state", "amount_total"],
    "stock.picking": ["state", "scheduled_date"],
    "account.move": ["state", "payment_state"],
}
SELECTION_FIELDS = {"state", "payment_state"}
HISTORY, DOCUMENT = "history", "document date"


def _name(many2one):
    return many2one[1] if many2one else ""


def _parse(odoo_datetime):
    """Odoo returns naive UTC strings: '2025-09-01 13:56:32'."""
    if not odoo_datetime:
        return None
    return datetime.strptime(odoo_datetime[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _chunks(items, size=500):
    items = sorted(set(items))
    for start in range(0, len(items), size):
        yield items[start:start + size]


class Extractor:
    def __init__(self, client, log=print):
        self.client = client
        self.log = log

    # -- reading ----------------------------------------------------------

    def read_orders(self, since=None, until=None):
        domain = []
        if since:
            domain.append(("create_date", ">=", since))
        if until:
            domain.append(("create_date", "<", until))
        return self.client.search_read("sale.order", domain, [
            "name", "state", "create_date", "create_uid", "date_order", "partner_id", "user_id",
            "warehouse_id", "amount_total", "currency_id", "picking_ids", "invoice_ids",
        ])

    def selection_labels(self):
        """Map (model, field, label) -> technical value, for every active language.

        The chatter stores the *label* shown to the user at the time
        ("Sales Order", "Bon de commande", "Zamówienie sprzedaży"...), not the
        technical value, so we need the reverse mapping in each language.
        """
        languages = [lang["code"] for lang in self.client.search_read("res.lang", [("active", "=", True)], ["code"])]
        labels = {}
        for model, fields in TRACKED_FIELDS.items():
            wanted = [f for f in fields if f in SELECTION_FIELDS]
            for lang in languages:
                info = self.client.call(model, "fields_get", allfields=wanted, attributes=["selection"],
                                        context={"lang": lang})
                for field_name, meta in info.items():
                    for value, label in meta.get("selection") or []:
                        labels[(model, field_name, label)] = value
        return labels

    def history(self, model, ids):
        """Return {res_id: [(datetime, author, {field: (old, new)}), ...]} sorted by time."""
        fields = self.client.search_read(
            "ir.model.fields", [("model", "=", model), ("name", "in", TRACKED_FIELDS[model])], ["name"])
        field_names = {f["id"]: f["name"] for f in fields}

        messages = {}
        for chunk in _chunks(ids):
            for m in self.client.search_read(
                    "mail.message",
                    [("model", "=", model), ("res_id", "in", chunk), ("tracking_value_ids", "!=", False)],
                    ["res_id", "date", "author_id"]):
                messages[m["id"]] = (m["res_id"], _parse(m["date"]), _name(m["author_id"]), {})

        for chunk in _chunks(messages):
            for t in self.client.search_read(
                    "mail.tracking.value",
                    [("mail_message_id", "in", chunk), ("field_id", "in", list(field_names))],
                    ["field_id", "mail_message_id", "old_value_char", "new_value_char",
                     "old_value_datetime", "new_value_datetime", "old_value_float", "new_value_float"]):
                name = field_names[t["field_id"][0]]
                if name == "scheduled_date":
                    change = (_parse(t["old_value_datetime"]), _parse(t["new_value_datetime"]))
                elif name == "amount_total":
                    change = (t["old_value_float"], t["new_value_float"])
                else:
                    change = (t["old_value_char"], t["new_value_char"])
                messages[t["mail_message_id"][0]][3][name] = change

        by_record = defaultdict(list)
        for msg_id, (res_id, when, author, changes) in sorted(messages.items(), key=lambda kv: (kv[1][1], kv[0])):
            if changes:
                by_record[res_id].append((when, author, changes))
        return by_record

    # -- building events ----------------------------------------------------

    def run(self, since=None, until=None):
        self.log("Reading sales orders...")
        orders = self.read_orders(since, until)
        if not orders:
            return [], {"orders": 0}
        order_ids = [o["id"] for o in orders]

        self.log(f"  {len(orders)} orders. Reading customers, lines, deliveries and invoices...")
        partners = {p["id"]: p for p in self.client.read_by_ids(
            "res.partner", [o["partner_id"][0] for o in orders], ["country_id"])}
        products = defaultdict(set)
        for chunk in _chunks(order_ids):
            for line in self.client.search_read(
                    "sale.order.line", [("order_id", "in", chunk), ("product_id", "!=", False)],
                    ["order_id", "product_id"]):
                products[line["order_id"][0]].add(_name(line["product_id"]))

        pickings = {p["id"]: p for p in self.client.read_by_ids(
            "stock.picking", [pid for o in orders for pid in o["picking_ids"]],
            ["name", "state", "picking_type_code", "date_done"])}
        invoice_ids = [mid for o in orders for mid in o["invoice_ids"]]
        moves = {m["id"]: m for m in self.client.read_by_ids(
            "account.move", invoice_ids,
            ["name", "move_type", "state", "invoice_date", "invoice_date_due", "reversed_entry_id"])}
        # Credit notes created by hand are not always linked to the order lines;
        # catch them through the invoice they reverse.
        for chunk in _chunks(invoice_ids):
            for m in self.client.search_read(
                    "account.move", [("reversed_entry_id", "in", chunk), ("move_type", "=", "out_refund")],
                    ["name", "move_type", "state", "invoice_date", "invoice_date_due", "reversed_entry_id"]):
                moves.setdefault(m["id"], m)

        self.log("  Reading the change history (chatter tracking)...")
        labels = self.selection_labels()
        so_history = self.history("sale.order", order_ids)
        picking_history = self.history("stock.picking", list(pickings))
        move_history = self.history("account.move", list(moves))

        refunds_of = defaultdict(list)
        for move in moves.values():
            if move["reversed_entry_id"]:
                refunds_of[move["reversed_entry_id"][0]].append(move)

        rows = []
        stats = defaultdict(int)
        for order in orders:
            partner = partners.get(order["partner_id"][0], {})
            case = {
                "case_id": order["name"],
                "customer": _name(order["partner_id"]),
                "customer_country": _name(partner.get("country_id")),
                "salesperson": _name(order["user_id"]),
                "warehouse": _name(order["warehouse_id"]),
                "order_amount": f'{order["amount_total"]:.2f}',
                "currency": _name(order["currency_id"]),
                "products": "; ".join(sorted(products[order["id"]])),
            }

            def add(activity, when, resource="", document="", detail="", source=HISTORY, due_date=""):
                stats[source] += 1
                rows.append(dict(case, activity=activity, timestamp=when.isoformat(), resource=resource,
                                 document=document, detail=detail, source=source, due_date=due_date))

            add(QUOTE_CREATED, _parse(order["create_date"]), _name(order["create_uid"]), order["name"])
            rows_before = len(rows)
            self._order_events(order, so_history.get(order["id"], []), labels, add)
            if order["state"] == "sale" and not any(r["activity"] == ORDER_CONFIRMED for r in rows[rows_before:]):
                add(ORDER_CONFIRMED, _parse(order["date_order"]), document=order["name"], source=DOCUMENT)

            for pid in order["picking_ids"]:
                picking = pickings.get(pid)
                if picking and picking["picking_type_code"] == "outgoing":
                    self._picking_events(picking, picking_history.get(pid, []), labels, add)

            order_moves = {mid: moves[mid] for mid in order["invoice_ids"] if mid in moves}
            for mid in order["invoice_ids"]:
                order_moves.update((r["id"], r) for r in refunds_of[mid])
            for move in order_moves.values():
                self._move_events(move, move_history.get(move["id"], []), labels, add)

        stats["orders"] = len(orders)
        return rows, dict(stats)

    @staticmethod
    def _new_value(labels, model, field, change):
        label = change[1]
        return labels.get((model, field, label), label)

    def _order_events(self, order, history, labels, add):
        confirmed = cancelled = False
        for when, author, changes in history:
            if "state" in changes:
                new = self._new_value(labels, "sale.order", "state", changes["state"])
                if new == "sent":
                    add(QUOTE_SENT, when, author, order["name"])
                elif new == "sale":
                    confirmed = True
                    add(ORDER_CONFIRMED, when, author, order["name"])
                elif new == "cancel":
                    cancelled = True
                    add(ORDER_CANCELLED, when, author, order["name"])
            elif "amount_total" in changes and confirmed and not cancelled:
                old, new = changes["amount_total"]
                add(ORDER_CHANGED, when, author, order["name"], f"amount {old:,.2f} -> {new:,.2f}")

    def _picking_events(self, picking, history, labels, add):
        shipped = False
        for when, author, changes in history:
            if "scheduled_date" in changes and not shipped:
                old, new = changes["scheduled_date"]
                if old and new and new > old:
                    days = (new - old).total_seconds() / 86400
                    add(DELIVERY_RESCHEDULED, when, author, picking["name"], f"+{days:.1f} days")
            if "state" in changes and self._new_value(labels, "stock.picking", "state", changes["state"]) == "done":
                shipped = True
                add(GOODS_SHIPPED, when, author, picking["name"])
        if picking["state"] == "done" and not shipped and picking["date_done"]:
            add(GOODS_SHIPPED, _parse(picking["date_done"]), document=picking["name"], source=DOCUMENT)

    def _move_events(self, move, history, labels, add):
        is_refund = move["move_type"] == "out_refund"
        if move["move_type"] not in ("out_invoice", "out_refund"):
            return
        due = move["invoice_date_due"] or ""
        posted = paid = False
        for when, author, changes in history:
            if "state" in changes:
                new = self._new_value(labels, "account.move", "state", changes["state"])
                if new == "posted":
                    posted = True
                    add(CREDIT_NOTE if is_refund else INVOICE_POSTED, when, author, move["name"],
                        due_date="" if is_refund else due)
                elif new == "draft" and not is_refund:
                    add(INVOICE_RESET, when, author, move["name"])
            if "payment_state" in changes and not is_refund and not paid:
                if self._new_value(labels, "account.move", "payment_state", changes["payment_state"]) in ("paid", "in_payment"):
                    paid = True
                    add(PAYMENT_RECEIVED, when, author, move["name"])
        if move["state"] == "posted" and not posted and move["invoice_date"]:
            when = datetime.strptime(move["invoice_date"], "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
            add(CREDIT_NOTE if is_refund else INVOICE_POSTED, when, document=move["name"], source=DOCUMENT,
                due_date="" if is_refund else due)
