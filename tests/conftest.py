"""The whole suite runs with outbound network access blocked.

TrazoPDF promises that documents never leave the computer (see PRIVACY.md). Any test that
tries to reach a non-loopback address fails, so a regression that adds a network call is caught.
"""
import ipaddress
import socket

import pytest

_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", ""}


def _is_loopback(host):
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host)
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def connect(self, address, *args, **kwargs):
        if isinstance(address, tuple) and not _is_loopback(address[0]):
            raise AssertionError(f"Blocked network connection to {address[0]!r}")
        return real_connect(self, address, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            raise AssertionError(f"Blocked name lookup for {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
