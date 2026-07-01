#!/usr/bin/env python3

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
from datetime import datetime, timezone
from urllib.parse import urlparse


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_PUBLIC_CATEGORY = "linear"
DEFAULT_PUBLIC_INTERVALS = ("5", "15", "240")
INTERVAL_MINUTES = {
    "5": 5,
    "5m": 5,
    "15": 15,
    "15m": 15,
    "240": 240,
    "4h": 240,
    "4H": 240,
}
CANONICAL_INTERVALS = {
    "5": "5m",
    "5m": "5m",
    "15": "15m",
    "15m": "15m",
    "240": "4H",
    "4h": "4H",
    "4H": "4H",
}


class WebSocketError(Exception):
    pass


class SimpleWebSocketClient:
    def __init__(self, url, timeout=10.0):
        self.url = url
        self.timeout = timeout
        self.sock = None
        self.buffer = b""

    def connect(self):
        try:
            parsed = urlparse(self.url)
            if parsed.scheme not in {"ws", "wss"}:
                raise WebSocketError(f"unsupported websocket scheme: {parsed.scheme}")
            host = parsed.hostname
            if not host:
                raise WebSocketError("websocket URL is missing a host")
            port = parsed.port or (443 if parsed.scheme == "wss" else 80)
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"

            raw_sock = socket.create_connection((host, port), timeout=self.timeout)
            if parsed.scheme == "wss":
                context = ssl.create_default_context()
                self.sock = context.wrap_socket(raw_sock, server_hostname=host)
            else:
                self.sock = raw_sock
            self.sock.settimeout(self.timeout)

            key = base64.b64encode(os.urandom(16)).decode("ascii")
            host_header = host if port in {80, 443} else f"{host}:{port}"
            request_lines = [
                f"GET {path} HTTP/1.1",
                f"Host: {host_header}",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {key}",
                "Sec-WebSocket-Version: 13",
                "User-Agent: trading-paper-api/1.0",
                "\r\n",
            ]
            self.sock.sendall("\r\n".join(request_lines).encode("utf-8"))

            response = self._recv_until(b"\r\n\r\n")
            headers_raw, _, remainder = response.partition(b"\r\n\r\n")
            self.buffer = remainder
            lines = headers_raw.decode("utf-8", errors="replace").split("\r\n")
            if not lines or " 101 " not in lines[0]:
                raise WebSocketError(f"websocket handshake failed: {lines[0] if lines else 'empty response'}")

            headers = {}
            for line in lines[1:]:
                if ":" not in line:
                    continue
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()

            expected = base64.b64encode(
                hashlib.sha1(f"{key}{WS_GUID}".encode("utf-8")).digest()
            ).decode("ascii")
            if headers.get("sec-websocket-accept") != expected:
                raise WebSocketError("websocket handshake returned an unexpected Sec-WebSocket-Accept header")
        except WebSocketError:
            self.close()
            raise
        except (OSError, ssl.SSLError) as exc:
            self.close()
            raise WebSocketError(f"websocket connect failed: {exc}") from exc

    def close(self):
        if self.sock is None:
            return
        try:
            self.send_close()
        except Exception:
            pass
        try:
            self.sock.close()
        finally:
            self.sock = None
            self.buffer = b""

    def _recv_until(self, marker):
        while marker not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WebSocketError("websocket connection closed during handshake")
            self.buffer += chunk
        return self.buffer

    def _recv_exact(self, size, timeout=None):
        if self.sock is None:
            raise WebSocketError("websocket is not connected")
        if timeout is not None:
            self.sock.settimeout(timeout)
        while len(self.buffer) < size:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WebSocketError("websocket connection closed")
            self.buffer += chunk
        data = self.buffer[:size]
        self.buffer = self.buffer[size:]
        return data

    def _send_frame(self, opcode, payload=b""):
        if self.sock is None:
            raise WebSocketError("websocket is not connected")
        payload = payload or b""
        first_byte = 0x80 | (opcode & 0x0F)
        mask_key = os.urandom(4)
        length = len(payload)
        if length < 126:
            header = bytes([first_byte, 0x80 | length])
        elif length < (1 << 16):
            header = bytes([first_byte, 0x80 | 126]) + struct.pack("!H", length)
        else:
            header = bytes([first_byte, 0x80 | 127]) + struct.pack("!Q", length)
        masked = bytes(payload[i] ^ mask_key[i % 4] for i in range(length))
        self.sock.sendall(header + mask_key + masked)

    def send_json(self, payload):
        self._send_frame(0x1, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def send_close(self):
        self._send_frame(0x8, b"")

    def _recv_frame(self, timeout=None):
        header = self._recv_exact(2, timeout=timeout)
        first_byte, second_byte = header[0], header[1]
        fin = bool(first_byte & 0x80)
        opcode = first_byte & 0x0F
        masked = bool(second_byte & 0x80)
        length = second_byte & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask_key = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(payload[i] ^ mask_key[i % 4] for i in range(length))
        return {
            "fin": fin,
            "opcode": opcode,
            "payload": payload,
        }

    def recv_json(self, timeout=None):
        try:
            chunks = []
            text_started = False
            while True:
                frame = self._recv_frame(timeout=timeout)
                opcode = frame["opcode"]
                payload = frame["payload"]

                if opcode == 0x8:
                    raise WebSocketError("websocket close frame received")
                if opcode == 0x9:
                    self._send_frame(0xA, payload)
                    return None
                if opcode == 0xA:
                    return None
                if opcode == 0x1:
                    text_started = True
                    chunks.append(payload)
                    if frame["fin"]:
                        break
                    continue
                if opcode == 0x0 and text_started:
                    chunks.append(payload)
                    if frame["fin"]:
                        break
                    continue
                raise WebSocketError(f"unsupported websocket opcode: {opcode}")

            raw = b"".join(chunks).decode("utf-8")
            return json.loads(raw)
        except socket.timeout:
            raise
        except WebSocketError:
            self.close()
            raise
        except (OSError, ssl.SSLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.close()
            raise WebSocketError(f"websocket receive failed: {exc}") from exc


def utc_from_ms(value):
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(microsecond=0).isoformat()


def interval_minutes(value):
    key = str(value or "").strip()
    if key not in INTERVAL_MINUTES:
        raise ValueError(f"unsupported interval {value!r}")
    return INTERVAL_MINUTES[key]


def canonical_interval(value):
    key = str(value or "").strip()
    return CANONICAL_INTERVALS.get(key, key)


def closed_bar_reference_ms(start_ms, interval):
    return int(start_ms) + interval_minutes(interval) * 60 * 1000


def build_public_ws_url(market_base_url="", category=DEFAULT_PUBLIC_CATEGORY):
    explicit = os.environ.get("BYBIT_PUBLIC_WS_URL", "").strip()
    if explicit:
        return explicit

    parsed = urlparse((market_base_url or "").strip() or "https://api.bybit.com")
    host = parsed.netloc or "api.bybit.com"
    if host.startswith("api."):
        host = "stream." + host[len("api.") :]
    elif host.startswith("api-"):
        host = "stream-" + host[len("api-") :]
    elif not host.startswith("stream"):
        host = "stream.bybit.com"
    return f"wss://{host}/v5/public/{category}"


def build_public_kline_topics(symbols, intervals=DEFAULT_PUBLIC_INTERVALS):
    topics = []
    for interval in intervals:
        normalized_interval = str(interval).strip()
        for symbol in symbols:
            normalized_symbol = str(symbol or "").strip().upper()
            if normalized_symbol:
                topics.append(f"kline.{normalized_interval}.{normalized_symbol}")
    return topics


def build_subscribe_message(topics):
    return {
        "req_id": f"sub-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "op": "subscribe",
        "args": list(topics or []),
    }


def _message_items(message):
    if not isinstance(message, dict):
        return []
    data = message.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _build_closed_kline_event(snapshot, *, start_ms=None, end_ms=None, source="confirmed_close"):
    interval_token = snapshot["interval_token"]
    event_start_ms = int(snapshot["start_ms"] if start_ms is None else start_ms)
    reference_ms = closed_bar_reference_ms(event_start_ms, interval_token)
    event_end_ms = reference_ms - 1 if end_ms is None else int(end_ms)
    return {
        "topic": snapshot.get("topic") or f"kline.{interval_token}.{snapshot['symbol']}",
        "symbol": snapshot["symbol"],
        "interval": snapshot["interval"],
        "interval_token": interval_token,
        "start_ms": event_start_ms,
        "end_ms": event_end_ms,
        "reference_ms": reference_ms,
        "reference_at": utc_from_ms(reference_ms),
        "event_key": f"{snapshot['symbol']}:{interval_token}:{event_start_ms}",
        "type": "closed_candle",
        "source": source,
    }


def normalize_kline_snapshots(message):
    if not isinstance(message, dict):
        return []

    topic = str(message.get("topic") or "").strip()
    items = _message_items(message)
    snapshots = []

    for item in items:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol") or "").strip().upper()
        interval = str(item.get("interval") or "").strip()
        if topic.startswith("kline."):
            parts = topic.split(".")
            if len(parts) >= 3:
                if not interval:
                    interval = parts[1]
                symbol = symbol or parts[2].strip().upper()
        if not symbol or not interval:
            continue

        start_ms = item.get("start")
        end_ms = item.get("end")
        try:
            start_ms = int(start_ms)
        except (TypeError, ValueError):
            continue
        if end_ms not in (None, ""):
            try:
                end_ms = int(end_ms)
            except (TypeError, ValueError):
                end_ms = None

        reference_ms = closed_bar_reference_ms(start_ms, interval)
        if end_ms is None:
            end_ms = reference_ms - 1

        snapshots.append(
            {
                "topic": topic or f"kline.{interval}.{symbol}",
                "symbol": symbol,
                "interval": canonical_interval(interval),
                "interval_token": interval,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "reference_ms": reference_ms,
                "reference_at": utc_from_ms(reference_ms),
                "confirm": item.get("confirm") is True,
            }
        )
    return snapshots


def normalize_closed_kline_events(message):
    return [
        _build_closed_kline_event(snapshot)
        for snapshot in normalize_kline_snapshots(message)
        if snapshot.get("confirm") is True
    ]


class KlineRolloverDetector:
    def __init__(self, *, bootstrap_previous=True):
        self.bootstrap_previous = bool(bootstrap_previous)
        self.latest_by_stream = {}
        self.emitted_event_keys = set()

    def _append_once(self, events, event):
        event_key = str(event.get("event_key") or "").strip()
        if not event_key or event_key in self.emitted_event_keys:
            return
        self.emitted_event_keys.add(event_key)
        events.append(event)

    def events_from_message(self, message):
        events = []
        for event in normalize_closed_kline_events(message):
            self._append_once(events, event)

        for snapshot in normalize_kline_snapshots(message):
            stream_key = (snapshot["symbol"], snapshot["interval_token"])
            previous = self.latest_by_stream.get(stream_key)
            if previous is None:
                if self.bootstrap_previous:
                    interval_ms = interval_minutes(snapshot["interval_token"]) * 60 * 1000
                    previous_start_ms = int(snapshot["start_ms"]) - interval_ms
                    if previous_start_ms >= 0:
                        self._append_once(
                            events,
                            _build_closed_kline_event(
                                snapshot,
                                start_ms=previous_start_ms,
                                end_ms=int(snapshot["start_ms"]) - 1,
                                source="rollover_bootstrap",
                            ),
                        )
                self.latest_by_stream[stream_key] = snapshot
                continue

            if int(snapshot["start_ms"]) > int(previous["start_ms"]):
                self._append_once(
                    events,
                    _build_closed_kline_event(previous, source="rollover"),
                )
                self.latest_by_stream[stream_key] = snapshot
            elif int(snapshot["start_ms"]) == int(previous["start_ms"]):
                self.latest_by_stream[stream_key] = snapshot

        return events


class PublicKlineEventService:
    def __init__(
        self,
        *,
        market_base_url="https://api.bybit.com",
        category=DEFAULT_PUBLIC_CATEGORY,
        symbols=None,
        intervals=DEFAULT_PUBLIC_INTERVALS,
        timeout=10.0,
    ):
        self.market_base_url = market_base_url
        self.category = category
        self.symbols = [str(item).upper() for item in (symbols or []) if str(item or "").strip()]
        self.intervals = [str(item).strip() for item in (intervals or DEFAULT_PUBLIC_INTERVALS)]
        self.timeout = float(timeout)
        self.url = build_public_ws_url(market_base_url=self.market_base_url, category=self.category)
        self.client = SimpleWebSocketClient(self.url, timeout=self.timeout)
        self.topics = build_public_kline_topics(self.symbols, self.intervals)
        self.rollover_detector = KlineRolloverDetector(bootstrap_previous=True)

    def connect(self):
        self.client.connect()
        if self.topics:
            self.client.send_json(build_subscribe_message(self.topics))

    def close(self):
        self.client.close()

    def recv_closed_events(self, timeout=None):
        try:
            message = self.client.recv_json(timeout=timeout)
        except socket.timeout:
            return []
        if message is None:
            return []
        return self.rollover_detector.events_from_message(message)
