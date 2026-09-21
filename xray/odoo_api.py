"""Talking to Odoo, whichever version it is.

Odoo 19 introduced the JSON-2 API and deprecated the old XML-RPC one. Most
companies still run 17 or 18, so the client tries JSON-2 first and falls back
to XML-RPC, which needs a login name next to the key. Everything above this
module works the same either way.
"""
import xmlrpc.client

import requests

from . import __version__

USER_AGENT = f"odoo-process-xray/{__version__}"


class OdooError(Exception):
    pass


class Json2Transport:
    """Odoo 19+: POST {url}/json/2/{model}/{method} with a bearer API key."""

    name = "JSON-2"

    def __init__(self, url, api_key, database=None, timeout=120):
        self.url, self.timeout = url, timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
        })
        if database:
            self.session.headers["X-Odoo-Database"] = database

    def available(self):
        """Older Odoo answers this path with a redirect to the login page."""
        try:
            response = self.session.post(f"{self.url}/json/2/res.users/context_get", json={},
                                         timeout=30, allow_redirects=False)
        except requests.RequestException as e:
            raise OdooError(f"cannot reach {self.url}: {e}")
        if response.status_code in (401, 403):
            raise OdooError(f"the API key was refused ({response.status_code}): {response.text[:200]}")
        return response.status_code == 200 and "json" in response.headers.get("Content-Type", "")

    def call(self, model, method, **params):
        response = self.session.post(f"{self.url}/json/2/{model}/{method}", json=params,
                                     timeout=self.timeout, allow_redirects=False)
        if response.status_code != 200:
            try:
                message = response.json().get("message", response.text)
            except ValueError:
                message = response.text
            raise OdooError(f"{model}.{method} failed ({response.status_code}): {message}")
        return response.json()


class XmlRpcTransport:
    """Odoo 18 and older: /xmlrpc/2, with the API key used as the password."""

    name = "XML-RPC"

    def __init__(self, url, api_key, database, login, timeout=120):
        if not database or not login:
            raise OdooError("Odoo 18 and older need --db and --login (the user name the key belongs to).")
        self.url, self.database, self.key, self.login = url, database, api_key, login
        self.common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
        self.models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
        self.uid = None

    def available(self):
        try:
            self.uid = self.common.authenticate(self.database, self.login, self.key, {})
        except Exception as e:
            raise OdooError(f"cannot reach {self.url} over XML-RPC: {e}")
        if not self.uid:
            raise OdooError(f"Odoo refused the login '{self.login}' with that API key.")
        return True

    def server_version(self):
        try:
            return self.common.version().get("server_version", "")
        except Exception:
            return ""

    def call(self, model, method, **params):
        try:
            # Odoo takes every argument by name, and pops `context` itself.
            return self.models.execute_kw(self.database, self.uid, self.key, model, method, [], params)
        except xmlrpc.client.Fault as fault:
            raise OdooError(f"{model}.{method} failed: {fault.faultString.strip().splitlines()[-1]}")
        except Exception as e:
            raise OdooError(f"{model}.{method} failed: {e}")


class OdooClient:
    def __init__(self, url, api_key, database=None, login=None, timeout=120, log=print):
        self.url = url.rstrip("/")
        json2 = Json2Transport(self.url, api_key, database, timeout)
        if json2.available():
            self.transport = json2
        else:
            xmlrpc_transport = XmlRpcTransport(self.url, api_key, database, login, timeout)
            xmlrpc_transport.available()
            self.transport = xmlrpc_transport
            log(f"Odoo {xmlrpc_transport.server_version()} has no JSON-2 API; using XML-RPC.")

    def call(self, model, method, **params):
        return self.transport.call(model, method, **params)

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
