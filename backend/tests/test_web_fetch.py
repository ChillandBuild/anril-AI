"""v9.2 #168 The safe web fetch for the knowledge base: the address rules, redirects, size, type, text."""
import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest

from app.services import web_fetch as wf

PUBLIC = "93.184.216.34"
PAGE = "<html><head><title>Sri Sweets</title><style>p{color:red}</style></head><body><script>alert(1)</script><h1>About us</h1><p>We make fresh sweets every day in Chennai.</p><noscript>no</noscript></body></html>"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Every name resolves to a public address unless a test says otherwise."""
    table = {}

    async def fake_resolve(host, port):
        try:
            import ipaddress
            ipaddress.ip_address(host)
            ips = [host]  # an address typed as a number resolves to itself
        except ValueError:
            ips = table.get(host, [PUBLIC])
        for ip in ips:
            if wf.blocked_ip(ip):
                raise wf.WebFetchError("That address can't be read. Use your public website address.")
        return ips

    monkeypatch.setattr(wf, "resolve_public", fake_resolve)
    return table


def run(coro):
    return asyncio.run(coro)


def fetch(handler, url="https://shop.example/about"):
    return run(wf.fetch_page_text(url, transport=httpx.MockTransport(handler)))


def html(body=PAGE, status=200, ctype="text/html; charset=utf-8", headers=None):
    data = body.encode() if isinstance(body, str) else body
    # a real stream (as on the wire), so aiter_raw works the way it does in production
    return httpx.Response(status, stream=httpx.ByteStream(data), headers={"content-type": ctype, **(headers or {})})


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "127.9.9.9", "10.0.0.5", "172.16.0.1", "172.31.255.254", "192.168.1.10", "169.254.169.254",
    "0.0.0.0", "::1", "fc00::1", "fd12:3456::1", "fe80::1", "::ffff:127.0.0.1", "::ffff:169.254.169.254", "100.64.0.1", "224.0.0.1", "::",
])
def test_private_loopback_link_local_and_metadata_addresses_are_blocked(ip):
    assert wf.blocked_ip(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "2606:4700:4700::1111", "172.32.0.1"])
def test_public_addresses_pass(ip):
    assert wf.blocked_ip(ip) is False


@pytest.mark.parametrize("url", [
    "ftp://example.com/a", "file:///etc/passwd", "javascript:alert(1)", "https://user:pw@example.com/", "https://example.com:8080/",
    "", "   ", "https://", "http://exa mple.com",
])
def test_bad_addresses_are_refused(url):
    with pytest.raises(wf.WebFetchError):
        wf.check_url(url)


def test_bare_domain_gets_https():
    assert wf.check_url("shop.example/about#team")[0] == "https://shop.example/about"


def test_a_page_becomes_plain_text_without_scripts_or_styles():
    url, title, text = fetch(lambda r: html())
    assert url == "https://shop.example/about" and title == "Sri Sweets"
    assert "We make fresh sweets every day in Chennai." in text and "About us" in text
    assert "alert(1)" not in text and "color:red" not in text and "no" not in text.split()


def test_a_name_that_points_at_a_private_address_is_refused(public_dns):
    public_dns["evil.example"] = ["10.0.0.7"]
    with pytest.raises(wf.WebFetchError, match="can't be read"):
        fetch(lambda r: html(), "https://evil.example/")


def test_one_private_answer_among_public_ones_refuses_the_name(public_dns):
    public_dns["mixed.example"] = [PUBLIC, "169.254.169.254"]
    with pytest.raises(wf.WebFetchError):
        fetch(lambda r: html(), "https://mixed.example/")


def test_a_literal_metadata_address_is_refused():
    with pytest.raises(wf.WebFetchError):
        fetch(lambda r: html(), "http://169.254.169.254/latest/meta-data/")


def test_redirect_to_another_public_page_is_followed():
    def handler(r):
        if r.url.path == "/old":
            return httpx.Response(301, headers={"location": "/about"})
        return html()
    assert fetch(handler, "https://shop.example/old")[0] == "https://shop.example/old"  # the address the owner typed


def test_redirect_to_a_private_host_is_refused_even_after_a_public_start(public_dns):
    public_dns["internal.example"] = ["192.168.0.9"]
    seen = []

    def handler(r):
        seen.append(str(r.url))
        return httpx.Response(302, headers={"location": "https://internal.example/admin"})
    with pytest.raises(wf.WebFetchError, match="can't be read"):
        fetch(handler)
    assert seen == ["https://shop.example/about"]  # the private host was never contacted


def test_redirect_to_a_metadata_ip_literal_is_refused():
    with pytest.raises(wf.WebFetchError):
        fetch(lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"}))


def test_more_than_three_redirects_is_refused():
    hits = []

    def handler(r):
        hits.append(1)
        return httpx.Response(302, headers={"location": f"/hop{len(hits)}"})
    with pytest.raises(wf.WebFetchError, match="too many redirects"):
        fetch(handler)
    assert len(hits) == 4  # the first request plus three redirects, then stop


def test_three_redirects_are_allowed():
    def handler(r):
        n = int(r.url.path[4:] or 0) if r.url.path.startswith("/hop") else 0
        return httpx.Response(302, headers={"location": f"/hop{n + 1}"}) if n < 3 else html()
    assert fetch(handler)[2]


def test_a_page_over_2mb_is_refused_even_without_a_length_header():
    big = "<html><body><p>" + "a" * (wf.MAX_BYTES + 10) + "</p></body></html>"
    with pytest.raises(wf.WebFetchError, match="too big"):
        fetch(lambda r: html(big))


def test_a_declared_length_over_2mb_is_refused_up_front():
    with pytest.raises(wf.WebFetchError, match="too big"):
        fetch(lambda r: html(PAGE, headers={"content-length": str(wf.MAX_BYTES + 1)}))


@pytest.mark.parametrize("ctype", ["application/json", "application/pdf", "image/png", "text/plain"])
def test_only_html_is_read(ctype):
    with pytest.raises(wf.WebFetchError, match="not a web page"):
        fetch(lambda r: html(PAGE, ctype=ctype))


def test_error_status_is_explained():
    with pytest.raises(wf.WebFetchError, match="404"):
        fetch(lambda r: httpx.Response(404, content=b"no"))


def test_a_page_with_almost_no_text_is_refused():
    with pytest.raises(wf.WebFetchError, match="hardly any readable text"):
        fetch(lambda r: html("<html><body><script>var a=1</script></body></html>"))


def test_slow_websites_time_out(monkeypatch):
    monkeypatch.setattr(wf, "TIMEOUT_SECONDS", 0.05)

    async def slow(*a, **k):
        await asyncio.sleep(1)
    monkeypatch.setattr(wf, "_fetch", slow)
    with pytest.raises(wf.WebFetchError, match="too long"):
        run(wf.fetch_page_text("https://shop.example/"))


def test_the_connection_itself_is_pinned_to_a_checked_address(monkeypatch):
    """Even if the pre-check passed, the real connection resolves again and refuses a private answer
    (a name that changes its answer between the check and the connect)."""
    async def fake_getaddrinfo(self, host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]
    monkeypatch.undo()  # use the real resolve_public, with a stubbed loop.getaddrinfo
    monkeypatch.setattr(asyncio.get_event_loop_policy().__class__, "_never", None, raising=False)
    import asyncio.base_events as be
    monkeypatch.setattr(be.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    backend = wf._GuardedBackend()
    with pytest.raises(wf.WebFetchError):
        run(backend.connect_tcp("rebind.example", 443))


def test_the_transport_uses_the_guarded_backend():
    t = wf.GuardedTransport()
    assert isinstance(t._pool._network_backend, wf._GuardedBackend)


def test_the_request_asks_for_no_compression():
    seen = {}

    def handler(r):
        seen["enc"] = r.headers.get("accept-encoding")
        return html()
    fetch(handler)
    assert seen["enc"] == "identity"


def test_a_compressed_reply_is_refused_not_unpacked():
    with pytest.raises(wf.WebFetchError, match="form we can't read"):
        fetch(lambda r: html(PAGE, headers={"content-encoding": "gzip"}))
