# test_unit.py
import pytest
from OASIS import ElasticPreprints, safe_request

def test_normalize_query():
    ep = ElasticPreprints(provider="psyarxiv")
    assert ep.normalize_query("deepfake and abuse") == "deepfake AND abuse"
    assert ep.normalize_query("x | y & z") == "x OR y AND z"
    assert ep.normalize_query("NOT child") == "NOT child"

def test_safe_request_success(monkeypatch):
    class DummyRes:
        status_code = 200
        def raise_for_status(self): return
        text = "OK"

    def dummy_request(method, url, **kwargs):
        return DummyRes()

    monkeypatch.setattr("httpx.request", dummy_request)
    res = safe_request("GET", "http://test.com")
    assert res.text == "OK"
