"""In-process guard: block every non-loopback socket connection and DNS lookup.

Scope: this covers the Python engine process only. It says nothing about what the
Ollama installation does on its own; the Wi-Fi-off demo is the separate check.
"""
import ipaddress
import socket


class BlockedConnection(OSError):
    pass


_orig = {}


def is_loopback(host):
    if isinstance(host, bytes):
        host = host.decode()
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check(sock, addr):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and not is_loopback(addr[0]):
        raise BlockedConnection(f"blocked non-loopback connection to {addr[0]}")


def install():
    if _orig:
        return
    _orig["connect"], _orig["connect_ex"] = socket.socket.connect, socket.socket.connect_ex
    _orig["getaddrinfo"] = socket.getaddrinfo

    def connect(self, addr):
        _check(self, addr)
        return _orig["connect"](self, addr)

    def connect_ex(self, addr):
        _check(self, addr)
        return _orig["connect_ex"](self, addr)

    def getaddrinfo(host, *a, **k):
        if host is not None and not is_loopback(host):
            raise BlockedConnection(f"blocked DNS lookup for {host}")
        return _orig["getaddrinfo"](host, *a, **k)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    socket.getaddrinfo = getaddrinfo


def uninstall():
    if _orig:
        socket.socket.connect = _orig["connect"]
        socket.socket.connect_ex = _orig["connect_ex"]
        socket.getaddrinfo = _orig["getaddrinfo"]
        _orig.clear()
