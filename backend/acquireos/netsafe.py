"""Fetching pages and images the app was pointed at (by you, an import or an AI) without
letting that reach inside the network: only http(s) to public addresses, checked again
on every redirect."""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request


class Blocked(OSError):
    pass


def check(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise Blocked(f"Not a web address: {url[:80]}")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise Blocked(f"{u.hostname} could not be found") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise Blocked(f"{u.hostname} is not a public address")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirects)


def urlopen(req, timeout: float = 6):
    """urllib.request.urlopen for public web addresses only."""
    check(req.full_url if isinstance(req, urllib.request.Request) else str(req))
    return _opener.open(req, timeout=timeout)
