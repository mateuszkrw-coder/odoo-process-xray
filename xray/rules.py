"""Business rules: what counts as a problem in order-to-cash.

This is the analyst's part of the tool. Each rule is a short function that
looks at ONE order (a Case) and answers True ("this order has the problem") or
False. The report runs every rule on every order, counts the hits and looks
for where they concentrate (a salesperson, a warehouse, a customer, a
product, a weekday...).

To add a rule, copy one below and change it. You can use:

    case.has(ACTIVITY)                  did it happen at all?
    case.count(ACTIVITY)                how many times?
    case.first(ACTIVITY)                when did it first happen? (datetime or None)
    case.happened_before(A, B)          did A happen before B?
    case.days_between(A, B)             days from A to B (or None)
    case.working_days_between(A, B)     same, without weekends
    case.due_date, case.as_of           invoice due date, and "today"
    case["salesperson"], case["warehouse"], case["customer"], ...

`applies_to` decides which orders the rule is about (the denominator of the
percentage). By default: every confirmed order.
"""
from dataclasses import dataclass
from typing import Callable

from .eventlog import (
    CREDIT_NOTE, DELIVERY_RESCHEDULED, GOODS_SHIPPED, INVOICE_POSTED, ORDER_CANCELLED, ORDER_CHANGED,
    ORDER_CONFIRMED, PAYMENT_RECEIVED, Case,
)


@dataclass
class Rule:
    key: str
    title: str
    check: Callable[[Case], bool]
    applies_to: Callable[[Case], bool]
    applies_to_label: str
    why: str
    odoo_fix: str


RULES: list[Rule] = []


def confirmed(case):
    return case.has(ORDER_CONFIRMED)


def rule(title, why, odoo_fix, applies_to=confirmed, applies_to_label="confirmed orders"):
    """Register the decorated function as a rule."""
    def register(check):
        RULES.append(Rule(check.__name__, title, check, applies_to, applies_to_label, why, odoo_fix))
        return check
    return register


# --------------------------------------------------------------------------
# Order handling
# --------------------------------------------------------------------------

@rule(
    title="Changed after the customer confirmed",
    why="Every change after confirmation means rework downstream, and a risk that the customer "
        "gets a different price or quantity than what they agreed to.",
    odoo_fix="Sales > Settings > <b>Lock Confirmed Sales</b> makes confirmed orders read-only, so a change "
             "needs a deliberate unlock. Then ask why these orders change: missing information at "
             "quotation time, or price corrections?",
)
def changed_after_confirmation(case):
    return case.has(ORDER_CHANGED)


@rule(
    title="Cancelled after confirmation",
    why="A confirmed order that gets cancelled has already consumed planning and picking effort.",
    odoo_fix="Start recording <b>why</b> orders are cancelled (for example with a custom "
             "'cancellation reason' field) so the pattern becomes visible.",
)
def cancelled_after_confirmation(case):
    return case.happened_before(ORDER_CONFIRMED, ORDER_CANCELLED)


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------

@rule(
    title="Delivery date pushed back twice or more",
    why="Each postponement is a broken promise to the customer, and usually points to a stock or "
        "supplier problem on specific products.",
    odoo_fix="For the products involved, set reordering rules (Inventory > Operations > "
             "<b>Replenishment</b>) and realistic vendor lead times, so promised dates can be kept.",
)
def rescheduled_repeatedly(case):
    return case.count(DELIVERY_RESCHEDULED) >= 2


@rule(
    title="Shipped more than 3 working days after confirmation",
    why="Slow shipping delays the invoice (and therefore the cash) and frustrates customers.",
    odoo_fix="Compare picking capacity by warehouse and weekday. Inventory > Settings > "
             "<b>Batch, Wave &amp; Cluster Transfers</b> helps a team clear a backlog faster.",
    applies_to=lambda case: case.has(GOODS_SHIPPED) and case.has(ORDER_CONFIRMED),
    applies_to_label="shipped orders",
)
def slow_shipping(case):
    return case.working_days_between(ORDER_CONFIRMED, GOODS_SHIPPED) > 3


# --------------------------------------------------------------------------
# Invoicing
# --------------------------------------------------------------------------

@rule(
    title="Invoiced before the goods shipped",
    why="Invoicing what hasn't shipped yet leads to disputes and credit notes whenever the "
        "delivery changes.",
    odoo_fix="Set the <b>Invoicing Policy</b> to 'Delivered quantities' (Sales > Settings, or per "
             "product) so invoices only contain what has actually shipped.",
    applies_to=lambda case: case.has(INVOICE_POSTED) and case.has(GOODS_SHIPPED),
    applies_to_label="invoiced and shipped orders",
)
def invoiced_before_shipping(case):
    return case.happened_before(INVOICE_POSTED, GOODS_SHIPPED)


@rule(
    title="Needed a credit note",
    why="A credit note is an invoice that had to be corrected: extra work for accounting and a "
        "worse experience for the customer.",
    odoo_fix="Fix the cause, not the symptom: check whether these orders were invoiced before "
             "shipping or changed after confirmation.",
    applies_to=lambda case: case.has(INVOICE_POSTED),
    applies_to_label="invoiced orders",
)
def needed_credit_note(case):
    return case.has(CREDIT_NOTE)


# --------------------------------------------------------------------------
# Payment
# --------------------------------------------------------------------------

@rule(
    title="Paid more than two weeks after the due date",
    why="Late payment costs working capital. It is usually concentrated on a few customers.",
    odoo_fix="Enable Accounting > Settings > <b>Sales Credit Limit</b> for these customers, send "
             "payment reminders before the due date (follow-up reports in Odoo Enterprise), and "
             "consider shorter payment terms.",
    applies_to=lambda case: case.has(PAYMENT_RECEIVED) and case.due_date is not None,
    applies_to_label="paid orders",
)
def paid_late(case):
    days_late = (case.first(PAYMENT_RECEIVED).date() - case.due_date.date()).days
    return days_late > 14


@rule(
    title="Overdue and still unpaid",
    why="Open overdue invoices are revenue you have earned but not collected.",
    odoo_fix="Chase these invoices now. The order numbers are listed in the table view.",
    applies_to=lambda case: case.has(INVOICE_POSTED) and case.due_date is not None,
    applies_to_label="invoiced orders",
)
def overdue_unpaid(case):
    return not case.has(PAYMENT_RECEIVED) and case.as_of.date() > case.due_date.date()
