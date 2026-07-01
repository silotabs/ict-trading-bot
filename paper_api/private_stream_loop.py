#!/usr/bin/env python3

import argparse
import base64
import hashlib
import hmac
import json
import os
import socket
import ssl
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_api import (
    BYBIT_API_KEY,
    BYBIT_API_SECRET,
    BYBIT_ENV,
    BYBIT_MARKET_BASE_URL,
    BYBIT_PRIVATE_BASE_URL,
    TradingAPIHandler,
    clean_string,
    derive_execution_lifecycle,
    first_present,
    normalize_bybit_env,
    normalize_instrument,
    proposal_is_supervisable,
    resolve_control_state,
    utc_now_iso,
)


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_PRIVATE_TOPICS = ["order", "execution", "position", "wallet"]


class WebSocketError(Exception):
    pass


class SimpleWebSocketClient:
    def __init__(self, url, timeout=10.0):
        self.url = url
        self.timeout = timeout
        self.sock = None
        self.buffer = b""

    def connect(self):
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Listen to Bybit private websocket topics and reconcile execution state."
    )
    parser.add_argument(
        "--runtime-key",
        default="default",
        help="Runtime key used for persisted private-stream runtime state. Default: default.",
    )
    parser.add_argument(
        "--mainnet",
        action="store_true",
        help="Use the Bybit mainnet private websocket instead of testnet.",
    )
    parser.add_argument(
        "--topics",
        default=",".join(DEFAULT_PRIVATE_TOPICS),
        help="Comma-separated private topics to subscribe to. Default: order,execution,position,wallet.",
    )
    parser.add_argument(
        "--ping-interval-seconds",
        type=int,
        default=20,
        help="Application ping interval in seconds. Default: 20.",
    )
    parser.add_argument(
        "--reconnect-delay-seconds",
        type=int,
        default=5,
        help="Seconds to wait before reconnecting after a stream error. Default: 5.",
    )
    parser.add_argument(
        "--socket-timeout-seconds",
        type=float,
        default=10.0,
        help="Socket timeout in seconds. Default: 10.",
    )
    parser.add_argument(
        "--max-active-time",
        default="",
        help="Optional Bybit max_active_time query value such as 1m or 30s.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=0,
        help="Optional total runtime limit for testing. Zero means run until interrupted.",
    )
    parser.add_argument(
        "--disable-events",
        action="store_true",
        help="Do not persist private-stream events to SQLite.",
    )
    return parser.parse_args()


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_private_ws_url(testnet=True, max_active_time="", environment=None):
    explicit_url = os.environ.get("BYBIT_PRIVATE_WS_URL", "").strip()
    if explicit_url:
        return explicit_url

    env_name = normalize_bybit_env(environment or ("testnet" if testnet else "mainnet"))
    if env_name == "testnet":
        base = "wss://stream-testnet.bybit.com/v5/private"
    elif env_name == "demo":
        base = "wss://stream-demo.bybit.com/v5/private"
    else:
        parsed = urlparse(BYBIT_PRIVATE_BASE_URL or BYBIT_MARKET_BASE_URL)
        host = parsed.netloc or "api.bybit.com"
        if host.startswith("api."):
            host = "stream." + host[len("api.") :]
        elif host.startswith("api-"):
            host = "stream-" + host[len("api-") :]
        else:
            host = "stream.bybit.com"
        base = f"wss://{host}/v5/private"

    max_active_time = clean_string(max_active_time)
    if max_active_time:
        return f"{base}?max_active_time={max_active_time}"
    return base


def build_auth_message():
    expires = int((time.time() + 1) * 1000)
    signature = hmac.new(
        BYBIT_API_SECRET.encode("utf-8"),
        f"GET/realtime{expires}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "req_id": f"auth-{expires}",
        "op": "auth",
        "args": [BYBIT_API_KEY, expires, signature],
    }


def build_subscribe_message(topics):
    req_id = f"sub-{int(time.time() * 1000)}"
    return {
        "req_id": req_id,
        "op": "subscribe",
        "args": topics,
    }


def normalize_topics(raw_value):
    parts = []
    for item in (raw_value or "").split(","):
        cleaned = clean_string(item)
        if cleaned:
            parts.append(cleaned)
    return parts or list(DEFAULT_PRIVATE_TOPICS)


def emit_event(runtime_key, disable_events, event_type, severity, summary, payload, proposal_id=None, symbol=None):
    event = {
        "runtime_key": runtime_key,
        "event_type": event_type,
        "severity": severity,
        "summary": summary,
        "payload": payload if isinstance(payload, dict) else {},
        "proposal_id": proposal_id,
        "symbol": symbol,
        "created_at": utc_now_iso(),
    }
    if not disable_events:
        event["event_id"] = TradingAPIHandler.store.create_private_stream_event(
            runtime_key=runtime_key,
            event_type=event_type,
            severity=severity,
            summary=summary,
            event_payload=event["payload"],
            proposal_id=proposal_id,
            symbol=symbol,
        )
    print(
        f"STREAM {severity.upper()} {event_type} | {proposal_id or '-'} | {symbol or '-'} | {summary}",
        file=sys.stderr if severity in {"warning", "error"} else sys.stdout,
    )
    return event


def load_runtime_state(runtime_key):
    record = TradingAPIHandler.store.get_private_stream_runtime(runtime_key)
    if record is None:
        return {}
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    return state


def persist_runtime(runtime_key, connection_status, topics, state, connected_at=None, last_message_at=None):
    TradingAPIHandler.store.upsert_private_stream_runtime(
        runtime_key=runtime_key,
        connection_status=connection_status,
        subscriptions=list(topics),
        state=state,
        connected_at=connected_at,
        last_message_at=last_message_at,
    )


def active_proposals(limit=250):
    items = []
    for proposal_id in TradingAPIHandler.store.list_order_proposal_ids(limit=limit):
        proposal_record = TradingAPIHandler.store.get_order_proposal(proposal_id)
        if proposal_record is None:
            continue
        execution_state = TradingAPIHandler.store.get_execution_state(proposal_id)
        if proposal_is_supervisable(proposal_record, execution_state):
            items.append(proposal_record)
    return items


def wallet_summary_from_stream(wallet_entry, proposal_record=None):
    wallet_entry = wallet_entry if isinstance(wallet_entry, dict) else {}
    proposal = proposal_record.get("proposal") if isinstance(proposal_record, dict) else {}
    account_context = proposal.get("account_context") if isinstance(proposal, dict) else {}
    balance_coin = clean_string(first_present(account_context, ["balance_coin"])) or "USDT"
    coins = wallet_entry.get("coin") if isinstance(wallet_entry.get("coin"), list) else []
    coin_record = None
    for coin in coins:
        if clean_string(first_present(coin, ["coin"])) == balance_coin:
            coin_record = coin
            break
    if coin_record is None and coins:
        coin_record = coins[0]

    return {
        "account_type": clean_string(first_present(wallet_entry, ["accountType"]))
        or clean_string(first_present(account_context, ["account_type"])),
        "balance_coin": clean_string(first_present(coin_record or {}, ["coin"])) or balance_coin,
        "equity": clean_string(
            first_present(coin_record or {}, ["equity", "walletBalance"])
        ) or clean_string(first_present(account_context, ["equity"])),
        "available_balance": clean_string(
            first_present(coin_record or {}, ["availableToWithdraw", "availableBalance", "equity"])
        ) or clean_string(first_present(account_context, ["available_balance"])),
        "source": "bybit_private_stream_wallet",
    }


def merge_snapshot_from_stream(existing_snapshot, proposal_record, topic, item):
    snapshot = dict(existing_snapshot) if isinstance(existing_snapshot, dict) else {}
    topic_root = clean_string(topic.split(".")[0] if topic else "") or "unknown"
    proposal = proposal_record.get("proposal") if isinstance(proposal_record, dict) else {}
    request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
    symbol = normalize_instrument(
        clean_string(first_present(item, ["symbol"]))
        or clean_string(first_present(request, ["symbol"]))
        or clean_string(proposal.get("symbol"))
        or clean_string(proposal_record.get("symbol"))
    )

    snapshot["proposal_id"] = proposal_record.get("proposal_id")
    snapshot["venue"] = clean_string(proposal.get("venue")) or "bybit_testnet"
    snapshot["symbol"] = symbol
    snapshot["synced_at"] = utc_now_iso()

    if topic_root == "order":
        snapshot["order"] = item
    elif topic_root == "position":
        snapshot["position"] = item
    elif topic_root == "execution":
        snapshot["last_execution"] = item
        order = snapshot.get("order") if isinstance(snapshot.get("order"), dict) else {}
        if not order:
            order = {}
        for source_key, target_key in (
            ("orderId", "orderId"),
            ("orderLinkId", "orderLinkId"),
            ("symbol", "symbol"),
            ("side", "side"),
            ("orderPrice", "orderPrice"),
            ("orderQty", "orderQty"),
            ("orderType", "orderType"),
            ("leavesQty", "leavesQty"),
        ):
            value = first_present(item, [source_key])
            if value not in (None, ""):
                order[target_key] = value
        cum_exec_qty = first_present(item, ["execQty"])
        if cum_exec_qty not in (None, "") and "cumExecQty" not in order:
            order["cumExecQty"] = cum_exec_qty
        snapshot["order"] = order
    elif topic_root == "wallet":
        snapshot["wallet"] = wallet_summary_from_stream(item, proposal_record)

    order = snapshot.get("order") if isinstance(snapshot.get("order"), dict) else {}
    position = snapshot.get("position") if isinstance(snapshot.get("position"), dict) else {}
    lifecycle_status = derive_execution_lifecycle(order, position, proposal_record)
    snapshot["derived"] = {
        "lifecycle_status": lifecycle_status,
        "order_found": bool(order),
        "position_found": bool(position),
        "stream_topic": topic_root,
    }
    return snapshot


def compact_execution_state(record):
    if not isinstance(record, dict):
        return {}
    return {
        "sync_status": clean_string(first_present(record, ["sync_status"])),
        "order_status": clean_string(first_present(record, ["order_status"])),
        "position_size": clean_string(first_present(record, ["position_size"])),
        "unrealised_pnl": clean_string(first_present(record, ["unrealised_pnl"])),
    }


def maybe_emit_lifecycle_event(runtime_key, disable_events, proposal_record, previous_state, current_state, topic):
    previous = compact_execution_state(previous_state)
    current = compact_execution_state(current_state)
    if previous == current:
        return None

    proposal_id = proposal_record.get("proposal_id")
    symbol = proposal_record.get("symbol") or current_state.get("symbol")
    summary = (
        f"{proposal_id} {symbol or 'unknown'} via {topic} "
        f"sync={current.get('sync_status') or 'unknown'} "
        f"order={current.get('order_status') or 'unset'} "
        f"size={current.get('position_size') or '0'}"
    )
    return emit_event(
        runtime_key=runtime_key,
        disable_events=disable_events,
        event_type="lifecycle_changed",
        severity="info",
        summary=summary,
        payload={
            "topic": topic,
            "previous": previous,
            "current": current,
        },
        proposal_id=proposal_id,
        symbol=symbol,
    )


def apply_stream_item(runtime_key, disable_events, topic, item):
    topic_root = clean_string(topic.split(".")[0] if topic else "") or "unknown"
    symbol = normalize_instrument(first_present(item, ["symbol"]))

    if topic_root == "wallet":
        matched = 0
        for proposal_record in active_proposals():
            previous_state = TradingAPIHandler.store.get_execution_state(proposal_record["proposal_id"])
            previous_snapshot = (
                previous_state.get("snapshot") if isinstance(previous_state, dict) else {}
            )
            snapshot = merge_snapshot_from_stream(previous_snapshot, proposal_record, topic, item)
            TradingAPIHandler.store.upsert_execution_state(proposal_record["proposal_id"], snapshot)
            current_state = TradingAPIHandler.store.get_execution_state(proposal_record["proposal_id"])
            maybe_emit_lifecycle_event(
                runtime_key,
                disable_events,
                proposal_record,
                previous_state,
                current_state,
                topic_root,
            )
            matched += 1
        return {"matched": matched, "symbol": symbol, "proposal_id": None}

    proposal_record = TradingAPIHandler.store.find_order_proposal_for_stream(
        order_id=clean_string(first_present(item, ["orderId"])),
        order_link_id=clean_string(first_present(item, ["orderLinkId"])),
        symbol=symbol,
    )
    if proposal_record is None:
        emit_event(
            runtime_key=runtime_key,
            disable_events=disable_events,
            event_type="unmatched_message",
            severity="warning",
            summary=f"unmatched {topic_root} message for {symbol or 'unknown symbol'}",
            payload={"topic": topic, "item": item},
            proposal_id=None,
            symbol=symbol,
        )
        return {"matched": 0, "symbol": symbol, "proposal_id": None}

    previous_state = TradingAPIHandler.store.get_execution_state(proposal_record["proposal_id"])
    previous_snapshot = previous_state.get("snapshot") if isinstance(previous_state, dict) else {}
    snapshot = merge_snapshot_from_stream(previous_snapshot, proposal_record, topic, item)
    TradingAPIHandler.store.upsert_execution_state(proposal_record["proposal_id"], snapshot)
    current_state = TradingAPIHandler.store.get_execution_state(proposal_record["proposal_id"])
    maybe_emit_lifecycle_event(
        runtime_key,
        disable_events,
        proposal_record,
        previous_state,
        current_state,
        topic_root,
    )
    return {
        "matched": 1,
        "symbol": symbol,
        "proposal_id": proposal_record["proposal_id"],
    }


def process_stream_message(runtime_key, disable_events, state, message):
    state = dict(state) if isinstance(state, dict) else {}
    topic = clean_string(message.get("topic"))
    state["last_message_at"] = utc_now_iso()
    state["last_message"] = {
        "topic": topic,
        "op": clean_string(message.get("op")),
        "type": clean_string(message.get("type")),
    }

    if message.get("op") == "auth":
        if message.get("success") is True:
            state["authenticated_at"] = state["last_message_at"]
            state["connection_id"] = clean_string(message.get("conn_id"))
            emit_event(
                runtime_key=runtime_key,
                disable_events=disable_events,
                event_type="authenticated",
                severity="info",
                summary="Bybit private websocket authentication succeeded",
                payload=message,
            )
        else:
            emit_event(
                runtime_key=runtime_key,
                disable_events=disable_events,
                event_type="auth_failed",
                severity="error",
                summary=clean_string(message.get("ret_msg")) or "Bybit private websocket authentication failed",
                payload=message,
            )
        return state

    if message.get("op") == "subscribe":
        if message.get("success") is True:
            state["subscribed_at"] = state["last_message_at"]
            state["connection_id"] = clean_string(message.get("conn_id")) or state.get("connection_id")
            emit_event(
                runtime_key=runtime_key,
                disable_events=disable_events,
                event_type="subscribed",
                severity="info",
                summary="Bybit private websocket subscription acknowledged",
                payload=message,
            )
        else:
            emit_event(
                runtime_key=runtime_key,
                disable_events=disable_events,
                event_type="subscribe_failed",
                severity="error",
                summary=clean_string(message.get("ret_msg")) or "Bybit private websocket subscription failed",
                payload=message,
            )
        return state

    if message.get("op") == "pong":
        state["last_pong_at"] = state["last_message_at"]
        return state

    if not topic:
        return state

    topic_root = clean_string(topic.split(".")[0]) or topic
    counts = state.get("message_counts") if isinstance(state.get("message_counts"), dict) else {}
    counts[topic_root] = counts.get(topic_root, 0) + 1
    state["message_counts"] = counts
    state["last_topic"] = topic

    data = message.get("data")
    items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    matched_updates = state.get("matched_updates") if isinstance(state.get("matched_updates"), dict) else {}
    matched_updates.setdefault(topic_root, 0)

    for item in items:
        result = apply_stream_item(runtime_key, disable_events, topic, item)
        matched_updates[topic_root] += result["matched"]
    state["matched_updates"] = matched_updates
    state["connection_id"] = clean_string(message.get("conn_id")) or state.get("connection_id")
    return state


def run_loop(args):
    runtime_key = clean_string(args.runtime_key) or "default"
    topics = normalize_topics(args.topics)
    url = build_private_ws_url(
        testnet=not args.mainnet,
        max_active_time=args.max_active_time,
        environment=("mainnet" if args.mainnet else BYBIT_ENV),
    )
    started_at = time.time()
    state = load_runtime_state(runtime_key)
    state["url"] = url
    state["topics"] = topics
    state["mode"] = "mainnet" if args.mainnet else "testnet"
    control_paused = bool(state.get("_control_paused")) if isinstance(state, dict) else False

    while True:
        control = resolve_control_state("private_stream")
        if control["effective_paused"]:
            if not control_paused:
                emit_event(
                    runtime_key=runtime_key,
                    disable_events=args.disable_events,
                    event_type="control_paused",
                    severity="warning",
                    summary=f"private stream paused: {control['effective_reason'] or 'paused by control state'}",
                    payload={"control": control},
                )
            control_paused = True
            state["_control_paused"] = True
            state["control"] = control
            persist_runtime(
                runtime_key,
                "paused",
                topics,
                state,
                connected_at=state.get("connected_at"),
                last_message_at=state.get("last_message_at"),
            )
            if args.duration_seconds and time.time() - started_at >= args.duration_seconds:
                return
            time.sleep(max(2, args.reconnect_delay_seconds))
            continue
        elif control_paused:
            emit_event(
                runtime_key=runtime_key,
                disable_events=args.disable_events,
                event_type="control_resumed",
                severity="info",
                summary="private stream resumed after control pause",
                payload={"control": control},
            )
            control_paused = False
            state["_control_paused"] = False

        if not BYBIT_API_KEY or not BYBIT_API_SECRET:
            state["last_error"] = {
                "message": "BYBIT_API_KEY and BYBIT_API_SECRET are required for the private stream loop",
                "at": utc_now_iso(),
            }
            emit_event(
                runtime_key=runtime_key,
                disable_events=args.disable_events,
                event_type="configuration_error",
                severity="error",
                summary="private stream loop is missing Bybit API credentials",
                payload={"missing": ["BYBIT_API_KEY", "BYBIT_API_SECRET"]},
            )
            persist_runtime(
                runtime_key,
                "configuration_error",
                topics,
                state,
                connected_at=state.get("connected_at"),
                last_message_at=state.get("last_message_at"),
            )
            raise SystemExit("BYBIT_API_KEY and BYBIT_API_SECRET are required for the private stream loop")

        client = None
        connected_at = None
        last_ping_at = 0.0
        try:
            state["last_error"] = None
            persist_runtime(runtime_key, "connecting", topics, state, connected_at=None, last_message_at=state.get("last_message_at"))
            client = SimpleWebSocketClient(url, timeout=args.socket_timeout_seconds)
            client.connect()
            connected_at = utc_now_iso()
            state["connected_at"] = connected_at
            state["connection_attempted_at"] = connected_at
            emit_event(
                runtime_key=runtime_key,
                disable_events=args.disable_events,
                event_type="connected",
                severity="info",
                summary=f"connected to {url}",
                payload={"url": url, "topics": topics},
            )
            persist_runtime(runtime_key, "connected", topics, state, connected_at=connected_at, last_message_at=state.get("last_message_at"))

            client.send_json(build_auth_message())
            auth_deadline = time.time() + max(5.0, args.socket_timeout_seconds)
            while time.time() < auth_deadline:
                message = client.recv_json(timeout=1.0)
                if message is None:
                    continue
                state = process_stream_message(runtime_key, args.disable_events, state, message)
                persist_runtime(runtime_key, "connected", topics, state, connected_at=connected_at, last_message_at=state.get("last_message_at"))
                if message.get("op") == "auth":
                    if message.get("success") is not True:
                        raise WebSocketError(clean_string(message.get("ret_msg")) or "websocket auth failed")
                    break
            else:
                raise WebSocketError("timed out waiting for websocket auth response")

            client.send_json(build_subscribe_message(topics))
            subscribed = False
            subscribe_deadline = time.time() + max(5.0, args.socket_timeout_seconds)
            while time.time() < subscribe_deadline:
                message = client.recv_json(timeout=1.0)
                if message is None:
                    continue
                state = process_stream_message(runtime_key, args.disable_events, state, message)
                persist_runtime(runtime_key, "connected", topics, state, connected_at=connected_at, last_message_at=state.get("last_message_at"))
                if message.get("op") == "subscribe" and message.get("success") is True:
                    subscribed = True
                    break
            if not subscribed:
                raise WebSocketError("timed out waiting for websocket subscribe response")

            persist_runtime(runtime_key, "streaming", topics, state, connected_at=connected_at, last_message_at=state.get("last_message_at"))

            while True:
                control = resolve_control_state("private_stream")
                if control["effective_paused"]:
                    if not control_paused:
                        emit_event(
                            runtime_key=runtime_key,
                            disable_events=args.disable_events,
                            event_type="control_paused",
                            severity="warning",
                            summary=f"private stream paused: {control['effective_reason'] or 'paused by control state'}",
                            payload={"control": control},
                        )
                    control_paused = True
                    state["_control_paused"] = True
                    state["control"] = control
                    persist_runtime(
                        runtime_key,
                        "paused",
                        topics,
                        state,
                        connected_at=connected_at,
                        last_message_at=state.get("last_message_at"),
                    )
                    break

                if args.duration_seconds and time.time() - started_at >= args.duration_seconds:
                    emit_event(
                        runtime_key=runtime_key,
                        disable_events=args.disable_events,
                        event_type="duration_reached",
                        severity="info",
                        summary=f"stream loop reached duration limit of {args.duration_seconds} seconds",
                        payload={"duration_seconds": args.duration_seconds},
                    )
                    return

                now = time.time()
                if now - last_ping_at >= max(5, args.ping_interval_seconds):
                    client.send_json(
                        {
                            "req_id": f"ping-{int(now * 1000)}",
                            "op": "ping",
                        }
                    )
                    last_ping_at = now
                    state["last_ping_at"] = utc_now_iso()
                    persist_runtime(runtime_key, "streaming", topics, state, connected_at=connected_at, last_message_at=state.get("last_message_at"))

                try:
                    message = client.recv_json(timeout=1.0)
                except socket.timeout:
                    continue
                if message is None:
                    continue

                state = process_stream_message(runtime_key, args.disable_events, state, message)
                persist_runtime(runtime_key, "streaming", topics, state, connected_at=connected_at, last_message_at=state.get("last_message_at"))
        except KeyboardInterrupt:
            emit_event(
                runtime_key=runtime_key,
                disable_events=args.disable_events,
                event_type="stopped",
                severity="info",
                summary="private stream loop interrupted",
                payload={"runtime_key": runtime_key},
            )
            persist_runtime(runtime_key, "stopped", topics, state, connected_at=connected_at, last_message_at=state.get("last_message_at"))
            return
        except Exception as exc:
            state["last_error"] = {
                "message": str(exc),
                "at": utc_now_iso(),
            }
            emit_event(
                runtime_key=runtime_key,
                disable_events=args.disable_events,
                event_type="stream_error",
                severity="error",
                summary=f"private stream error: {exc}",
                payload={"error": str(exc), "url": url},
            )
            persist_runtime(runtime_key, "disconnected", topics, state, connected_at=connected_at, last_message_at=state.get("last_message_at"))
            time.sleep(max(2, args.reconnect_delay_seconds))
        finally:
            if client is not None:
                client.close()


def main():
    args = parse_args()
    run_loop(args)


if __name__ == "__main__":
    main()
