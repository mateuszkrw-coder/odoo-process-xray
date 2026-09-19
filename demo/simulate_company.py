"""Generate one year of order-to-cash history for a fictional company.

Runs INSIDE Odoo (``odoo shell``), not over the API, because it has to move
Odoo's clock: every action is executed "as of" a planned date, so creation
dates, chatter messages and status-change tracking all carry realistic
historical timestamps.

    odoo shell -d xray --no-http < simulate_company.py

The company is fictional. Its problems are planted on purpose so the analysis
has something real to find (see PLANTED below). The analysis does not know
about them — it has to rediscover them from Odoo's own history.

PLANTED
  1. Warsaw warehouse does not pick on Thu afternoon / Fri: those orders ship
     the following Tuesday or Wednesday.
  2. Salesperson Tom Peeters edits ~40% of his orders after confirmation.
  3. Warsaw invoices ~25% of orders at confirmation, before goods ship;
     a third of those later need a credit note.
  4. The Espresso Machine Pro has supplier problems: its deliveries get
     rescheduled 1-3 times.
  5. Five customers pay 40-110 days after invoicing (terms are 30 days).
"""
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from freezegun import freeze_time

SEED = 42
START = datetime(2025, 9, 1)          # local time, first quotation
END = datetime(2026, 8, 31, 23, 0)    # local time, "today" for the snapshot
N_QUOTES = 560
LOCAL_TZ = ZoneInfo("Europe/Brussels")

rng = random.Random(SEED)

# --------------------------------------------------------------------------
# Time helpers. Plans are built in local time, Odoo stores naive UTC.
# --------------------------------------------------------------------------

def to_utc(local):
    return local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def business(local):
    """Move a local datetime into office hours (Mon-Fri, 08:00-17:30)."""
    while True:
        if local.weekday() >= 5:
            local = (local + timedelta(days=7 - local.weekday())).replace(hour=8, minute=rng.randint(0, 59))
        elif local.hour < 8:
            local = local.replace(hour=8, minute=rng.randint(0, 59))
        elif (local.hour, local.minute) > (17, 30):
            local = (local + timedelta(days=1)).replace(hour=8, minute=rng.randint(0, 59))
        else:
            return local.replace(second=rng.randint(0, 59), microsecond=0)


def after(local, min_days, max_days):
    return business(local + timedelta(days=rng.uniform(min_days, max_days)))


def next_weekday(local, weekday, hour_from=9, hour_to=16):
    days = (weekday - local.weekday()) % 7 or 7
    day = local + timedelta(days=days)
    return day.replace(hour=rng.randint(hour_from, hour_to), minute=rng.randint(0, 59), second=0, microsecond=0)


# --------------------------------------------------------------------------
# Master data
# --------------------------------------------------------------------------

PRODUCTS = [
    # name, price, weight in orders
    ("House Blend Beans 1kg", 16.0, 30),
    ("Espresso Beans Brazil 1kg", 18.0, 25),
    ("Espresso Beans Ethiopia 1kg", 24.0, 15),
    ("Decaf Colombia Beans 1kg", 21.0, 8),
    ("Ground Coffee 250g", 6.0, 12),
    ("Green Tea Sencha 500g", 14.0, 8),
    ("Earl Grey Tea 500g", 12.0, 8),
    ("Chai Latte Mix 1kg", 19.0, 6),
    ("Oat Milk Barista 12x1L", 28.0, 14),
    ("Vanilla Syrup 1L", 9.0, 8),
    ("Paper Cups 12oz x1000", 45.0, 12),
    ("Cup Lids x1000", 25.0, 9),
    ("Descaler Tablets x10", 35.0, 5),
    ("Barista Apron", 22.0, 3),
    ("Coffee Grinder Compact", 650.0, 3),
    ("Espresso Machine Pro", 2400.0, 4),
]
SHORTAGE_PRODUCT = "Espresso Machine Pro"

CUSTOMERS_BE = [
    ("Café Parvis", "Brussels"), ("Koffiebar Meir", "Antwerp"), ("Brasserie du Canal", "Brussels"),
    ("Hotel Lindenhof", "Ghent"), ("Office Hub Leuven", "Leuven"), ("Salon Mosan", "Liège"),
    ("Bakkerij Zuid", "Antwerp"), ("Co-Work Ixelles", "Brussels"), ("Tearoom Duinen", "Ostend"),
    ("Café Sint-Pieters", "Ghent"), ("Hotel Horizon Namur", "Namur"), ("Bistro Flagey Corner", "Brussels"),
    ("Campus Kitchen Louvain", "Louvain-la-Neuve"), ("Lunchbar Kouter", "Ghent"), ("Station Coffee Mechelen", "Mechelen"),
    ("Hotel Atelier Bruges", "Bruges"), ("Kantine Noord", "Antwerp"), ("Espresso Point Wavre", "Wavre"),
    ("Café des Arts Mons", "Mons"), ("Business Park Diegem", "Diegem"),
]
CUSTOMERS_PL = [
    ("Kawiarnia Mokotów", "Warszawa"), ("Hotel Nad Wisłą", "Kraków"), ("Biuro Centrum Wola", "Warszawa"),
    ("Cukiernia Stare Miasto", "Gdańsk"), ("Kawiarnia Rynek", "Wrocław"), ("Hotel Poznań Park", "Poznań"),
    ("Coworking Praga", "Warszawa"), ("Bistro Kazimierz", "Kraków"), ("Kawiarnia Sopot Molo", "Sopot"),
    ("Stołówka Politechnika", "Łódź"), ("Hotel Tatry View", "Zakopane"), ("Piekarnia Żoliborz", "Warszawa"),
    ("Kawiarnia Ogród", "Lublin"), ("Biurowiec Mokotowska", "Warszawa"), ("Café Nowa Huta", "Kraków"),
    ("Restauracja Odra", "Szczecin"),
]
SLOW_PAYERS = {"Hotel Nad Wisłą", "Coworking Praga", "Restauracja Odra", "Brasserie du Canal", "Salon Mosan"}

SALES_BE = ["Sophie Lambert", "Tom Peeters"]
SALES_PL = ["Kasia Nowak", "Piotr Zieliński"]
PRICE_EDITOR = "Tom Peeters"

# --------------------------------------------------------------------------
# Odoo setup
# --------------------------------------------------------------------------

def group_field(Users):
    return "group_ids" if "group_ids" in Users._fields else "groups_id"


def make_user(name, login, group_xmlids):
    Users = env["res.users"]
    user = Users.search([("login", "=", login)])
    if user:
        return user
    groups = [env.ref(x).id for x in group_xmlids]
    return Users.create({
        "name": name,
        "login": login,
        "email": login,
        group_field(Users): [(6, 0, groups)],
    })


def setup():
    company = env.company
    eur = env.ref("base.EUR")
    eur.active = True
    company.write({
        "name": "Beanline Trading (fictional)",
        "currency_id": eur.id,
        "country_id": env.ref("base.be").id,
        "city": "Brussels",
    })
    env["product.pricelist"].search([]).write({"currency_id": eur.id})

    bru = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
    bru.write({"name": "Brussels DC", "code": "BRU"})
    waw = env["stock.warehouse"].search([("code", "=", "WAW")]) or env["stock.warehouse"].create(
        {"name": "Warsaw DC", "code": "WAW", "company_id": company.id})

    term_30 = env.ref("account.account_payment_term_30days")

    products = {}
    for name, price, _ in PRODUCTS:
        product = env["product.product"].create({
            "name": name,
            "type": "consu",
            "is_storable": True,
            "list_price": price,
            "standard_price": round(price * 0.55, 2),
            "invoice_policy": "order",
            "taxes_id": [(6, 0, [])],
        })
        for wh in (bru, waw):
            env["stock.quant"]._update_available_quantity(product, wh.lot_stock_id, 100000)
        products[name] = product

    customers = []
    for (name, city), country in [(c, "be") for c in CUSTOMERS_BE] + [(c, "pl") for c in CUSTOMERS_PL]:
        customers.append(env["res.partner"].create({
            "name": name,
            "is_company": True,
            "city": city,
            "country_id": env.ref(f"base.{country}").id,
            "property_payment_term_id": term_30.id,
        }))

    sales_groups = ["sales_team.group_sale_salesman_all_leads"]
    users = {}
    for name in SALES_BE + SALES_PL:
        users[name] = make_user(name, name.split()[0].lower() + "@beanline.example", sales_groups)
    users["Marc Dubois"] = make_user("Marc Dubois", "marc@beanline.example", ["stock.group_stock_user"] + sales_groups)
    users["Ola Wiśniewska"] = make_user("Ola Wiśniewska", "ola@beanline.example", ["stock.group_stock_user"] + sales_groups)
    for name in ("Julie Martin", "Anna Kowalczyk"):
        users[name] = make_user(name, name.split()[0].lower() + "@beanline.example",
                                ["account.group_account_invoice"] + sales_groups)
    return {"bru": bru, "waw": waw, "products": products, "customers": customers, "users": users}


# --------------------------------------------------------------------------
# Plan: decide, per quotation, what happens and when (local time)
# --------------------------------------------------------------------------

MONTH_WEIGHT = {9: 1.0, 10: 1.1, 11: 1.3, 12: 1.2, 1: 0.8, 2: 0.9, 3: 1.0, 4: 1.0, 5: 1.0, 6: 0.9, 7: 0.7, 8: 0.5}


def random_creation_date():
    days = (END - START).days - 12
    while True:
        day = START + timedelta(days=rng.randrange(days))
        if rng.random() < MONTH_WEIGHT[day.month] / 1.3:
            return business(day.replace(hour=rng.randint(8, 17), minute=rng.randint(0, 59)))


def plan_quote(customer, is_pl):
    salesperson = rng.choice(SALES_PL if is_pl else SALES_BE)
    names = [p[0] for p in PRODUCTS]
    weights = [p[2] for p in PRODUCTS]
    lines = {}
    for _ in range(rng.choice([1, 1, 2, 2, 2, 3, 3, 4])):
        product = rng.choices(names, weights)[0]
        qty = 1 if PRODUCTS[names.index(product)][1] > 500 else rng.choice([2, 4, 5, 6, 10, 12, 20, 24])
        lines[product] = qty

    p = {
        "customer": customer, "is_pl": is_pl, "warehouse": "waw" if is_pl else "bru",
        "salesperson": salesperson,
        "warehouse_user": "Ola Wiśniewska" if is_pl else "Marc Dubois",
        "accountant": "Anna Kowalczyk" if is_pl else "Julie Martin",
        "lines": lines, "steps": [],
    }
    step = lambda when, kind, **kw: p["steps"].append((when, kind, kw))

    created = random_creation_date()
    step(created, "create")
    last = created
    if rng.random() < 0.75:
        last = business(created + timedelta(hours=rng.uniform(0.3, 6)))
        step(last, "send")

    if rng.random() < 0.17:  # quotation never accepted
        cancel_at = after(last, 14, 40)
        if cancel_at < END and rng.random() < 0.7:
            step(cancel_at, "cancel")
        return p

    confirmed = business(last + timedelta(days=rng.lognormvariate(0.3, 0.9)))
    step(confirmed, "confirm")

    if rng.random() < 0.03:  # customer cancels after confirmation
        step(after(confirmed, 0.2, 3), "cancel")
        return p

    # Planted 4: supplier problems on the espresso machine.
    ship_not_before = confirmed
    if SHORTAGE_PRODUCT in lines and rng.random() < 0.85:
        t = confirmed
        for _ in range(rng.choice([1, 2, 2, 3])):
            t = after(t, 1, 3)
            step(t, "reschedule", days=rng.randint(3, 7))
        ship_not_before = after(t, 2, 5)
    elif rng.random() < 0.05:
        t = after(confirmed, 0.3, 1)
        step(t, "reschedule", days=rng.randint(1, 3))
        ship_not_before = after(t, 1, 2)

    # Planted 1: Warsaw doesn't pick Thu afternoon / Fri / weekend.
    local = confirmed
    late_week = local.weekday() == 4 or local.weekday() >= 5 or (local.weekday() == 3 and local.hour >= 12)
    if is_pl and late_week:
        shipped = next_weekday(local, rng.choice([1, 1, 2]))  # next Tue (or Wed)
    else:
        shipped = after(local, 0.2, 1.6)
    shipped = max(shipped, ship_not_before)

    # Planted 2: one salesperson keeps changing confirmed orders.
    change_rate = 0.40 if salesperson == PRICE_EDITOR else 0.05
    if rng.random() < change_rate:
        change_at = business(confirmed + timedelta(hours=rng.uniform(1, 30)))
        if change_at >= shipped:
            change_at = confirmed + (shipped - confirmed) / 2
        step(change_at, "change")

    # Planted 3: Warsaw sometimes invoices at confirmation, before shipping.
    early_invoice = is_pl and rng.random() < 0.25
    if early_invoice:
        invoiced = business(confirmed + timedelta(hours=rng.uniform(1, 5)))
        if invoiced >= shipped:
            invoiced = confirmed + (shipped - confirmed) / 3
    else:
        invoiced = after(shipped, *((0.5, 3.5) if is_pl else (0, 1.2)))
    posted = business(invoiced + timedelta(minutes=rng.uniform(5, 180)))

    step(shipped, "ship")
    step(invoiced, "invoice")
    step(posted, "post")

    if (early_invoice and rng.random() < 0.33) or rng.random() < 0.02:
        refund_at = after(max(shipped, posted), 3, 15)
        step(refund_at, "refund")
        step(business(refund_at + timedelta(minutes=rng.uniform(10, 120))), "post_refund")

    # Planted 5: slow payers. Terms are 30 days.
    if customer.name in SLOW_PAYERS:
        delay = min(max(rng.gauss(68, 14), 40), 110)
    else:
        delay = min(max(rng.gauss(26, 7), 5), 60)
    if rng.random() > 0.03:
        step(business(posted + timedelta(days=delay)), "pay")
    return p


# --------------------------------------------------------------------------
# Execution: replay every step of every order in global time order
# --------------------------------------------------------------------------

def run():
    data = setup()
    env.cr.commit()

    be = [c for c in data["customers"] if c.country_id.code == "BE"]
    pl = [c for c in data["customers"] if c.country_id.code == "PL"]
    plans = []
    for _ in range(N_QUOTES):
        is_pl = rng.random() < 0.45
        plans.append(plan_quote(rng.choice(pl if is_pl else be), is_pl))
    plans.sort(key=lambda p: p["steps"][0][0])  # quotation numbers follow creation order

    steps = [(when, i, kind, kw) for i, p in enumerate(plans) for when, kind, kw in p["steps"] if when <= END]
    steps.sort(key=lambda s: (s[0], s[1]))
    users = data["users"]

    def execute(p, kind, kw):
        seller = users[p["salesperson"]]
        order = p.get("order")
        if kind == "create":
            wh = data[p["warehouse"]]
            p["order"] = env["sale.order"].with_user(seller).create({
                "partner_id": p["customer"].id,
                "user_id": seller.id,
                "warehouse_id": wh.id,
                "order_line": [(0, 0, {"product_id": data["products"][name].id, "product_uom_qty": qty})
                               for name, qty in p["lines"].items()],
            })
        elif kind == "send":
            order.with_user(seller).action_quotation_sent()
        elif kind == "confirm":
            order.with_user(seller).action_confirm()
        elif kind == "cancel":
            order.with_user(seller)._action_cancel()
        elif kind == "change":
            line = order.with_user(seller).order_line[0]
            line.product_uom_qty = line.product_uom_qty + max(1, round(line.product_uom_qty * rng.uniform(0.2, 0.6)))
        elif kind == "reschedule":
            picking = order.picking_ids.filtered(lambda x: x.state not in ("done", "cancel"))[:1]
            picking.with_user(users[p["warehouse_user"]]).scheduled_date = picking.scheduled_date + timedelta(days=kw["days"])
        elif kind == "ship":
            clerk = users[p["warehouse_user"]]
            for picking in order.picking_ids.filtered(lambda x: x.state not in ("done", "cancel")):
                picking = picking.with_user(clerk)
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                picking.move_ids.picked = True
                picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        elif kind == "invoice":
            p["invoice"] = order.with_user(users[p["accountant"]])._create_invoices()
        elif kind == "post":
            p["invoice"].with_user(users[p["accountant"]]).action_post()
        elif kind == "refund":
            invoice = p["invoice"]
            line = order.order_line[0]
            p["refund"] = env["account.move"].with_user(users[p["accountant"]]).create({
                "move_type": "out_refund",
                "partner_id": invoice.partner_id.id,
                "invoice_origin": order.name,
                "reversed_entry_id": invoice.id,
                "ref": f"Correction of {invoice.name}",
                "invoice_line_ids": [(0, 0, {
                    "product_id": line.product_id.id,
                    "quantity": 1,
                    "price_unit": line.price_unit,
                    "sale_line_ids": [(6, 0, line.ids)],
                })],
            })
        elif kind == "post_refund":
            refund = p["refund"].with_user(users[p["accountant"]])
            refund.action_post()
            receivables = (p["invoice"] + refund).line_ids.filtered(
                lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled)
            receivables.reconcile()
        elif kind == "pay":
            invoice = p["invoice"]
            if invoice.payment_state in ("paid", "in_payment") or invoice.state != "posted":
                return
            env["account.payment.register"].with_user(users[p["accountant"]]).with_context(
                active_model="account.move", active_ids=invoice.ids).create({})._create_payments()

    first = to_utc(steps[0][0])
    done = 0
    with freeze_time(first) as clock:
        for when, i, kind, kw in steps:
            p = plans[i]
            if kind != "create" and "order" not in p:
                continue
            t = to_utc(when)
            clock.move_to(t)
            env.cr._now = t
            execute(p, kind, kw)
            # Chatter tracking is written at commit time; flush it now so the
            # messages carry this step's timestamp instead of the next one's.
            env.flush_all()
            env.cr.precommit.run()
            done += 1
            if done % 250 == 0:
                env.cr.commit()
                print(f"  {done}/{len(steps)} steps, simulated date {when:%Y-%m-%d}", flush=True)
        env.cr.commit()
    print(f"Simulated {len(plans)} quotations, {done} steps, "
          f"{START:%Y-%m-%d} -> {END:%Y-%m-%d}", flush=True)


run()
