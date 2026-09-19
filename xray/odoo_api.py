"""Minimal client for Odoo's JSON-2 API (Odoo 19+).

    POST {url}/json/2/{model}/{method}
    Authorization: bearer {api_key}

The older XML-RPC / JSON-RPC endpoints are deprecated since Odoo 19, so this
tool only speaks JSON-2.
"""
import requests

from . import __version__


class OdooError(Exception):
    pass


class OdooClient:
    def __init__(self, url, api_key, database=None, timeout=120):
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"odoo-process-xray/{__version__}",
        })
        if database:
            self.session.headers["X-Odoo-Database"] = database
        self.timeout = timeout

    def call(self, model, method, **params):
        response = self.session.post(f"{self.url}/json/2/{model}/{method}", json=params, timeout=self.timeout)
        if response.status_code != 200:
            try:
                message = response.json().get("message", response.text)
            except ValueError:
                message = response.text
            raise OdooError(f"{model}.{method} failed ({response.status_code}): {message}")
        return response.json()

    def search_read(self, model, domain, fields, order="id", page_size=2000, context=None):
        """Read every matching record, page by page."""
        records, offset = [], 0
        while True:
            params = {"domain": domain, "fields": fields, "order": order, "limit": page_size, "offset": offset}
            if context:
                params["context"] = context
            page = self.call(model, "search_read", **params)
            records += page
            if len(page) < page_size:
                return records
            offset += page_size

    def read_by_ids(self, model, ids, fields, chunk=1000):
        """search_read on a (possibly long) list of ids, in chunks."""
        ids = sorted(set(ids))
        records = []
        for start in range(0, len(ids), chunk):
            records += self.search_read(model, [("id", "in", ids[start:start + chunk])], fields)
        return records
