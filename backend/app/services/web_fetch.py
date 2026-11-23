"""v9.2 #168 Fetch a web page for the knowledge base, safely.

The address comes from a customer of Anril, so the server must never be tricked into reading its own network
(a cloud metadata address, the database, a laptop). Rules, all enforced here:
  - http or https only, ports 80 and 443 only, no user:password in the address
  - the name is looked up and EVERY address it gives must be public: no loopback (127/8, ::1), private (10/8,
    172.16/12, 192.168/16, fc00::/7), link-local (169.254/16 which holds the cloud metadata address, fe80::/10),
    unspecified (0.0.0.0, ::), carrier-grade NAT, multicast or reserved ranges
  - the check runs again on the exact address the connection uses (so a name that changes its answer between
    the check and the connection, "DNS rebinding", is refused too), and again for every redirect (max 3)
  - 10 seconds in total, 2 MB at most, text/html only
Scripts, styles and other non-text parts of the page are dropped; what is left is plain text."""
import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 10.0
ALLOWED_PORTS = (80, 443)
MAX_URL_CHARS = 2000


class WebFetchError(Exception):
    """A reason the page could not be read, in words the owner can act on."""


def blocked_ip(raw: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when this address must never be fetched."""
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        for inner in (ip.ipv4_mapped, ip.sixtofour, ip.teredo[1] if ip.teredo else None):
            if inner is not None and blocked_ip(inner):
                return True
    if ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved:
        return True
    return not ip.is_global  # carrier-grade NAT (100.64/10) and anything else that is not on the public internet


def check_url(url: str) -> tuple[str, str, int]:
    """(clean url, host, port) or WebFetchError. Only looks at the text of the address."""
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_CHARS:
        raise WebFetchError("Type a full web address, like https://yourshop.com/about")
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise WebFetchError("That web address doesn't look right.")
    if parts.scheme not in ("http", "https"):
        raise WebFetchError("Only http and https web addresses can be read.")
    host = (parts.hostname or "").strip(".").lower()
    if not host or parts.username or parts.password or re.search(r"[^a-z0-9.:_\-\[\]%]", host):
        raise WebFetchError("That web address doesn't look right.")
    port = port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise WebFetchError("Only normal web addresses (no special port) can be read.")
    return parts._replace(fragment="").geturl(), host, port


async def resolve_public(host: str, port: int) -> list[str]:
    """Every address for this name, all checked. Refuses when ANY is not public."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise WebFetchError("Couldn't find that website. Check the address.")
    ips: list[str] = []
    for info in infos:
        ip = info[4][0].split("%")[0]
        if blocked_ip(ip):
            raise WebFetchError("That address can't be read. Use your public website address.")
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise WebFetchError("Couldn't find that website. Check the address.")
    return ips


class _GuardedBackend(httpcore.AsyncNetworkBackend):
    """Opens the connection to an address it has checked itself, never to whatever the name says later."""

    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        last: Exception | None = None
        for ip in await resolve_public(host, port):
            try:
                return await self._inner.connect_tcp(ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as e:
                last = e
        raise last or WebFetchError("Couldn't connect to that website.")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise WebFetchError("That address can't be read.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class GuardedTransport(httpx.AsyncHTTPTransport):
    """httpx transport whose every connection goes through _GuardedBackend. No proxy from the environment."""

    def __init__(self) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(), max_connections=4, network_backend=_GuardedBackend()
        )


# ---------------------------------------------------------------- html to text

_SKIP = {"script", "style", "noscript", "template", "svg", "head", "iframe", "object", "canvas", "select", "option"}
_BREAK = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header", "footer", "nav", "main",
          "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr", "dt", "dd", "form", "aside"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in _SKIP and tag != "head":
            self._skip += 1
        if tag in _BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP and tag != "head":
            self._skip = max(0, self._skip - 1)
        if tag in _BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, readable text). Scripts, styles and hidden template parts are dropped."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.split("\n")]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip().replace("\x00", "")
    return re.sub(r"\s+", " ", parser.title).strip()[:200], cleaned


# ---------------------------------------------------------------- the fetch

async def _fetch(url: str, transport) -> tuple[str, str]:
    headers = {"User-Agent": "AnrilKnowledgeBot/1.0", "Accept": "text/html,application/xhtml+xml;q=0.9",
               "Accept-Encoding": "identity"}  # no compression, so the 2 MB cap counts what was sent
    async with httpx.AsyncClient(transport=transport or GuardedTransport(), follow_redirects=False,
                                 timeout=httpx.Timeout(TIMEOUT_SECONDS), headers=headers) as client:
        for hop in range(MAX_REDIRECTS + 1):
            url, host, port = check_url(url)
            await resolve_public(host, port)  # each hop is checked before anything is sent
            try:
                async with client.stream("GET", url) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        target = resp.headers.get("location")
                        if not target:
                            raise WebFetchError("That website sent us somewhere we couldn't follow.")
                        url = urljoin(url, target)
                        continue
                    if resp.status_code != 200:
                        raise WebFetchError(f"That website didn't open (error {resp.status_code}).")
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype not in ("text/html", "application/xhtml+xml"):
                        raise WebFetchError("That link is not a web page. Upload files as documents instead.")
                    declared = resp.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > MAX_BYTES:
                        raise WebFetchError("That page is too big to read (over 2 MB).")
                    if resp.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
                        raise WebFetchError("That website sent the page in a form we can't read.")  # asked for none: don't unpack a zip bomb
                    body = bytearray()
                    async for chunk in resp.aiter_raw():  # counted before any unpacking
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise WebFetchError("That page is too big to read (over 2 MB).")
                    charset = resp.charset_encoding or "utf-8"
            except httpx.TimeoutException:
                raise WebFetchError("That website took too long to answer.")
            except httpx.HTTPError:
                raise WebFetchError("Couldn't open that website.")
            try:
                html = bytes(body).decode(charset, errors="replace")
            except LookupError:
                html = bytes(body).decode("utf-8", errors="replace")
            title, text = html_to_text(html)
            return title, text
    raise WebFetchError("That website sent us around in circles (too many redirects).")


async def fetch_page_text(url: str, *, transport=None) -> tuple[str, str, str]:
    """(final-safe address, title, text). Raises WebFetchError with a plain reason."""
    clean, _host, _port = check_url(url)
    try:
        title, text = await asyncio.wait_for(_fetch(clean, transport), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise WebFetchError("That website took too long to answer.")
    if len(text) < 40:
        raise WebFetchError("That page has hardly any readable text (it may need a login or load by script).")
    return clean, title, text
