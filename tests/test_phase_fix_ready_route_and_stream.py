from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import server as trading_server
from public_market_stream import SimpleWebSocketClient, WebSocketError


class PhaseFixReadyRouteAndStreamTests(unittest.TestCase):
    def test_readiness_http_status_treats_degraded_fallback_as_ready_enough(self):
        self.assertEqual(trading_server.readiness_http_status({"status": "healthy_primary"}), 200)
        self.assertEqual(trading_server.readiness_http_status({"status": "degraded_fallback"}), 200)
        self.assertEqual(trading_server.readiness_http_status({"status": "not_ready"}), 503)

    def test_public_stream_connect_wraps_socket_failures_as_websocket_errors(self):
        client = SimpleWebSocketClient("wss://stream.bybit.com/v5/public/linear", timeout=1.0)
        with patch("public_market_stream.socket.create_connection", side_effect=socket.gaierror(8, "nodename nor servname provided")):
            with self.assertRaises(WebSocketError) as exc:
                client.connect()

        self.assertIn("websocket connect failed", str(exc.exception))
        self.assertIsNone(client.sock)

    def test_public_stream_receive_wraps_socket_resets_as_websocket_errors(self):
        class ResetSocket:
            def settimeout(self, timeout):
                self.timeout = timeout

            def recv(self, size):
                raise ConnectionResetError(54, "Connection reset by peer")

            def close(self):
                self.closed = True

        client = SimpleWebSocketClient("wss://stream.bybit.com/v5/public/linear", timeout=1.0)
        client.sock = ResetSocket()

        with self.assertRaises(WebSocketError) as exc:
            client.recv_json(timeout=1.0)

        self.assertIn("websocket receive failed", str(exc.exception))
        self.assertIsNone(client.sock)

    def test_public_stream_ping_frame_yields_to_scan_loop_after_pong(self):
        client = SimpleWebSocketClient("wss://stream.bybit.com/v5/public/linear", timeout=1.0)
        sent_frames = []

        def fake_recv_frame(timeout=None):
            return {"opcode": 0x9, "payload": b"heartbeat", "fin": True}

        def fake_send_frame(opcode, payload=b""):
            sent_frames.append((opcode, payload))

        client._recv_frame = fake_recv_frame
        client._send_frame = fake_send_frame

        self.assertIsNone(client.recv_json(timeout=1.0))
        self.assertEqual(sent_frames, [(0xA, b"heartbeat")])

    def test_bybit_public_get_wraps_timeouts_into_structured_failure(self):
        with patch("server.urlrequest.urlopen", side_effect=TimeoutError("timed out")):
            result = trading_server.bybit_public_get("/v5/market/tickers", {"symbol": "BTCUSDT"})

        self.assertFalse(result["ok"])
        self.assertIsNone(result["http_status"])
        self.assertIn("timed out", result["response"]["error"])
        self.assertIn("/v5/market/tickers", result["url"])


if __name__ == "__main__":
    unittest.main()
