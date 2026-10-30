"""Bounded, anonymous HTTP checks for permanent website redirects."""
from dataclasses import asdict, dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
import ipaddress
import json
import re
import socket
import sqlite3
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

MAX_AGE = 24 * 60 * 60
MAX_HOPS = 10
CACHEABLE_REASONS = frozenset(("permanent", "no_redirect", "temporary_redirect", "loop", "too_many_redirects"))
TIMEOUT = (10, 20)
USER_AGENT = "maproulette-tagfixes/1.0 (+https://github.com/wielandb/maproulette-tagfixes)"


@dataclass
class RedirectResult:
    source: str
    checked_at: float
    target: str = ""
    hops: list = field(default_factory=list)
    reason: str = ""
    title: str = ""

    @property
    def eligible(self):
        return self.reason == "permanent" and bool(self.hops) and self.target != self.source


def parse_url(value):
    """Accept one explicit HTTP(S) URL without repairing OSM tag contents."""
    if not isinstance(value, str) or not value or re.search(r"[\s\x00-\x1f\x7f]", value):
        raise ValueError("Keine einzelne HTTP(S)-URL")
    if re.search(r"[;,]https?://", value, re.I):
        raise ValueError("Mehrere URLs im Tagwert")
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("Keine absolute HTTP(S)-URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL enthält Zugangsdaten")
    # Accessing port also rejects malformed/out-of-range ports.
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError("Ungültiger Port")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host or ".." in host:
            raise ValueError("Ungültiger öffentlicher Hostname")
    return parts


def resolve_location(current, location):
    if not isinstance(location, str) or not location.strip():
        raise ValueError("Location fehlt")
    location = location.strip()
    target = urljoin(current, location)
    # RFC 9110 10.2.2: an absent fragment inherits the original fragment;
    # an explicitly empty '#' clears it. urljoin alone loses this distinction.
    if "#" not in location:
        parts = urlsplit(target)
        target = urlunsplit(parts._replace(fragment=urlsplit(current).fragment))
    parse_url(target)
    return target


def public_host(host, resolver=socket.getaddrinfo):
    host = host.encode("idna").decode("ascii")
    addresses = resolver(host, None, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Host verweist nicht ausschließlich auf öffentliche IP-Adressen")


def retry_after_seconds(value, now):
    if not value:
        return 0.0
    try:
        if value.strip().isdigit():
            return float(value.strip())
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, parsed.timestamp() - now)
    except (ValueError, TypeError, OverflowError):
        return 0.0


class HostLimiter:
    def __init__(self, interval=1.0, *, clock=time.monotonic, sleep=time.sleep):
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self.next_time = {}
        self.lock = threading.Lock()

    def wait(self, host):
        # Recheck after waking: another worker may have received Retry-After
        # while this worker was waiting for its next permitted request.
        while True:
            with self.lock:
                now = self.clock()
                target = max(now, self.next_time.get(host, now))
                if target - now > 60:
                    return False
                if target <= now:
                    self.next_time[host] = now + self.interval
                    return True
            self.sleep(target - now)

    def postpone(self, host, seconds):
        with self.lock:
            self.next_time[host] = max(self.next_time.get(host, 0), self.clock() + seconds)


class RedirectChecker:
    def __init__(self, *, get=None, limiter=None, host_check=public_host, clock=time.time):
        self.get = get
        self.limiter = limiter or HostLimiter()
        self.host_check = host_check
        self.clock = clock
        self.local = threading.local()
        self.lock = threading.Lock()
        self.attempted = 0
        self.http_responses = 0
        self.transport_failures = 0
        self.conclusive = 0

    def _request(self, url):
        if self.get is not None:
            return self.get(url, allow_redirects=False, stream=True, timeout=TIMEOUT)
        if not hasattr(self.local, "session"):
            session = requests.Session()
            # Do not discover credentials from .netrc or inherit an authenticated
            # browser/session when checking arbitrary OSM website values.
            session.trust_env = False
            session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
            self.local.session = session
        return self.local.session.get(url, allow_redirects=False, stream=True, timeout=TIMEOUT)

    def check(self, source):
        result = self._check(source)
        uncertain = (result.reason in ("transport_error", "retry_later", "http_401", "http_403", "http_408", "http_425", "http_429")
                     or result.reason.startswith("http_5"))
        if not uncertain and result.reason != "invalid_url":
            with self.lock:
                self.conclusive += 1
        return result

    def _check(self, source):
        result = RedirectResult(source, self.clock())
        try:
            parse_url(source)
        except (ValueError, UnicodeError):
            result.reason = "invalid_url"
            return result
        with self.lock:
            self.attempted += 1
        if hasattr(self.local, "session"):
            self.local.session.cookies.clear()
        current = source
        seen = set()
        try:
            for hop_number in range(MAX_HOPS + 1):
                parts = parse_url(current)
                host = parts.hostname.encode("idna").decode("ascii").lower()
                network_url = urlunsplit(parts._replace(fragment=""))
                if network_url in seen:
                    result.reason = "loop"
                    return result
                seen.add(network_url)
                self.host_check(host)
                if not self.limiter.wait(host):
                    result.reason = "retry_later"
                    return result
                response = self._request(network_url)
                with self.lock:
                    self.http_responses += 1
                try:
                    status = response.status_code
                    delay = retry_after_seconds(response.headers.get("Retry-After"), self.clock())
                    if delay:
                        self.limiter.postpone(host, delay)
                    if status == 200:
                        result.target = current
                        result.reason = "permanent" if result.hops and current != source else "no_redirect"
                        if result.eligible:
                            # A short title is review context, never proof of identity.
                            data = bytearray()
                            for chunk in response.iter_content(chunk_size=8192):
                                data.extend(chunk[:max(0, 65536 - len(data))])
                                if len(data) >= 65536:
                                    break
                            match = re.search(br"<title[^>]*>(.*?)</title\s*>", data, re.I | re.S)
                            if match:
                                import html
                                try:
                                    title = match[1].decode(response.encoding or "utf-8", errors="replace")
                                except LookupError:
                                    # Unknown server charset labels must not abort a confirmed redirect.
                                    title = match[1].decode("utf-8", errors="replace")
                                result.title = html.unescape(re.sub(r"\s+", " ", title)).strip()[:200]
                        return result
                    if status not in (301, 308):
                        result.reason = "temporary_redirect" if status in (302, 303, 307) else "http_" + str(status)
                        if status in (429, 503) and not delay:
                            self.limiter.postpone(host, 60)
                        return result
                    if hop_number == MAX_HOPS:
                        result.reason = "too_many_redirects"
                        return result
                    target = resolve_location(current, response.headers.get("Location"))
                    if delay:
                        target_host = urlsplit(target).hostname.encode("idna").decode("ascii").lower()
                        self.limiter.postpone(target_host, delay)
                    result.hops.append({"url": current, "status": status, "target": target})
                    current = target
                finally:
                    response.close()
        except (requests.RequestException, OSError) as exc:
            with self.lock:
                self.transport_failures += 1
            result.reason = "transport_error"
        except (ValueError, UnicodeError):
            result.reason = "invalid_redirect"
        return result

    def ensure_network_worked(self):
        if self.attempted and not self.conclusive:
            raise RuntimeError("Kein Website-Abruf lieferte ein eindeutiges Ergebnis; die bisherige Challenge-Datei bleibt erhalten.")


class ResultCache:
    """One exact URL, one result; only conclusive responses survive a run."""
    def __init__(self, path, *, clock=time.time):
        self.clock = clock
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS results (url TEXT PRIMARY KEY, checked REAL, payload TEXT)")

    def get(self, url):
        row = self.connection.execute("SELECT checked, payload FROM results WHERE url = ?", (url,)).fetchone()
        if row is None or not 0 <= self.clock() - row[0] < MAX_AGE:
            return None
        try:
            result = RedirectResult(**json.loads(row[1]))
            return result if result.reason in CACHEABLE_REASONS else None
        except (ValueError, TypeError):
            return None

    def put(self, result):
        # A global network outage must never become cached 'no candidates'.
        if result.reason not in CACHEABLE_REASONS:
            return
        self.connection.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?)",
                                (result.source, result.checked_at, json.dumps(asdict(result), ensure_ascii=False)))
        self.connection.commit()

    def close(self):
        self.connection.close()
