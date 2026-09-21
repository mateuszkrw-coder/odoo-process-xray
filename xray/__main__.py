"""Command line.

    # 1. Pull the history out of Odoo (API key in the ODOO_API_KEY variable)
    python -m xray extract --url https://mycompany.odoo.com --db mycompany --out eventlog.csv

    # 2. Analyse it and write the report
    python -m xray report eventlog.csv --out report.html

    # or both at once
    python -m xray run --url ... --db ... --out-dir output/
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .ai import write_summary
from .analyze import analyze, load_event_log
from .eventlog import write_csv
from .extract import Extractor
from .odoo_api import OdooClient, OdooError
from .report import render


def meta_path(csv_path):
    return Path(csv_path).with_suffix(".meta.json")


def cmd_extract(args):
    key = os.environ.get("ODOO_API_KEY")
    if not key:
        sys.exit("Set the ODOO_API_KEY environment variable (Odoo > Preferences > Account Security > New API Key).")
    client = OdooClient(args.url, key, args.db, login=args.login or os.environ.get("ODOO_LOGIN"))
    extractor = Extractor(client)
    rows, stats = extractor.run(since=args.since, until=args.until)
    if not rows:
        sys.exit("No sales orders found.")
    companies = client.call("res.company", "search_read", domain=[], fields=["name"], limit=1, order="id")
    write_csv(rows, args.out)
    meta = {
        "company": args.company or (companies[0]["name"] if companies else ""),
        "url": args.url,
        "database": args.db,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "orders": stats.get("orders", 0),
        "events": len(rows),
        "events_from_history": stats.get("history", 0),
    }
    meta_path(args.out).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} events for {meta['orders']} orders to {args.out}")


def cmd_report(args):
    df = load_event_log(args.eventlog)
    meta = {}
    if meta_path(args.eventlog).exists():
        meta = json.loads(meta_path(args.eventlog).read_text(encoding="utf-8"))
    as_of = None
    if args.as_of:
        as_of = datetime.fromisoformat(args.as_of).replace(tzinfo=timezone.utc)
    elif meta.get("extracted_at"):
        as_of = datetime.fromisoformat(meta["extracted_at"])
    company = args.company or meta.get("company", "")
    results = analyze(df, company=company, as_of=as_of, tz=args.tz)
    note = args.note
    if note is None and meta.get("extracted_at"):
        note = f"Data read from Odoo on {datetime.fromisoformat(meta['extracted_at']):%d %b %Y}."
    ai_summary = None
    if args.ai != "off":
        text, reason = write_summary(results, provider=args.ai, anonymised=not args.ai_send_names)
        ai_summary = (text, reason)
        if not text:
            print(f"No AI summary ({reason}); the report is complete without it.")
    Path(args.out).write_text(render(results, note or "", ai_summary), encoding="utf-8")
    print(f"Wrote {args.out}: {results.counts['quotations']} orders, "
          f"{sum(1 for r in results.rules if r.hits)} kinds of problem found")


def cmd_run(args):
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    args.out = str(out / "eventlog.csv")
    cmd_extract(args)
    args.eventlog, args.out = args.out, str(out / "report.html")
    cmd_report(args)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m xray", description="Process mining for Odoo order-to-cash.")
    sub = parser.add_subparsers(dest="command", required=True)

    def odoo_args(p):
        p.add_argument("--url", required=True, help="Odoo address, e.g. https://mycompany.odoo.com")
        p.add_argument("--db", help="database name (needed when the server hosts several)")
        p.add_argument("--login", help="user name the API key belongs to; only needed on Odoo 18 and "
                                       "older, which use the XML-RPC API (or set ODOO_LOGIN)")
        p.add_argument("--since", help="only orders created on or after this date (YYYY-MM-DD)")
        p.add_argument("--until", help="only orders created before this date (YYYY-MM-DD)")

    def report_args(p):
        p.add_argument("--company", help="company name shown in the report")
        p.add_argument("--tz", default="Europe/Brussels", help="time zone for weekdays (default Europe/Brussels)")
        p.add_argument("--as-of", help="date used as 'today' for overdue invoices (default: extraction date)")
        p.add_argument("--note", help="extra sentence under the report title")
        p.add_argument("--ai", default="off", choices=["off", "auto", "gemini", "groq", "custom"],
                       help="let a language model write the summary paragraph from the computed numbers "
                            "(needs GEMINI_API_KEY, GROQ_API_KEY, or XRAY_AI_URL + XRAY_AI_KEY); "
                            "off by default")
        p.add_argument("--ai-send-names", action="store_true",
                       help="send real names to the model (default: anonymise people and customers)")

    p = sub.add_parser("extract", help="read Odoo and write the event log CSV")
    odoo_args(p)
    p.add_argument("--company", help="company name to store with the data")
    p.add_argument("--out", default="eventlog.csv")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("report", help="analyse an event log CSV and write the HTML report")
    p.add_argument("eventlog")
    report_args(p)
    p.add_argument("--out", default="report.html")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("run", help="extract + report")
    odoo_args(p)
    report_args(p)
    p.add_argument("--out-dir", default="output")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except OdooError as e:
        sys.exit(f"Odoo said no: {e}")


if __name__ == "__main__":
    main()
