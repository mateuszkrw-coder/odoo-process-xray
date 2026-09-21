"""Choosing between the two APIs, without a real Odoo."""
import pytest
import requests

from xray import odoo_api
from xray.odoo_api import OdooClient, OdooError


class FakeResponse:
    def __init__(self, status, headers=None, payload=None, text=""):
        self.status_code, self.headers, self._payload, self.text = status, headers or {}, payload, text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Stands in for requests.Session inside the JSON-2 transport."""

    def __init__(self, response):
        self.headers, self.response, self.calls = {}, response, []

    def post(self, url, json=None, timeout=None, allow_redirects=None):
        self.calls.append((url, json, allow_redirects))
        return self.response


class FakeProxy:
    """Stands in for xmlrpc.client.ServerProxy."""

    last = None

    def __init__(self, url, allow_none=None):
        self.url = url
        FakeProxy.last = self

    def authenticate(self, db, login, key, context):
        return 7 if login == "admin" else False

    def version(self):
        return {"server_version": "18.0"}

    def execute_kw(self, db, uid, key, model, method, args, kwargs):
        FakeProxy.call = (db, uid, model, method, args, kwargs)
        return [{"id": 1, "name": "S00001"}]


@pytest.fixture
def fake_xmlrpc(monkeypatch):
    monkeypatch.setattr(odoo_api.xmlrpc.client, "ServerProxy", FakeProxy)


def json2_session(monkeypatch, response):
    session = FakeSession(response)
    monkeypatch.setattr(requests, "Session", lambda: session)
    return session


def test_uses_json2_when_available(monkeypatch, fake_xmlrpc):
    json2_session(monkeypatch, FakeResponse(200, {"Content-Type": "application/json"}, {"uid": 2}))
    client = OdooClient("https://demo.odoo.com/", "key", "db", log=lambda *_: None)
    assert client.transport.name == "JSON-2"


def test_falls_back_to_xmlrpc_on_older_odoo(monkeypatch, fake_xmlrpc):
    # Odoo 18 redirects the JSON-2 path to the login page
    json2_session(monkeypatch, FakeResponse(303, {"Content-Type": "text/html"}, None, "Redirecting..."))
    lines = []
    client = OdooClient("https://demo.odoo.com", "key", "db", login="admin", log=lines.append)
    assert client.transport.name == "XML-RPC"
    assert "XML-RPC" in lines[0] and "18.0" in lines[0]

    records = client.search_read("sale.order", [("id", "=", 1)], ["name"])
    db, uid, model, method, args, kwargs = FakeProxy.call
    assert (db, uid, model, method, args) == ("db", 7, "sale.order", "search_read", [])
    assert kwargs["domain"] == [("id", "=", 1)] and kwargs["fields"] == ["name"]
    assert records == [{"id": 1, "name": "S00001"}]


def test_older_odoo_without_a_login_says_so(monkeypatch, fake_xmlrpc):
    json2_session(monkeypatch, FakeResponse(404, {"Content-Type": "text/html"}))
    with pytest.raises(OdooError, match="--login"):
        OdooClient("https://demo.odoo.com", "key", "db", log=lambda *_: None)


def test_a_refused_key_is_not_mistaken_for_an_old_odoo(monkeypatch, fake_xmlrpc):
    json2_session(monkeypatch, FakeResponse(401, {"Content-Type": "application/json"}, {"message": "Invalid apikey"}))
    with pytest.raises(OdooError, match="refused"):
        OdooClient("https://demo.odoo.com", "key", "db", login="admin", log=lambda *_: None)
