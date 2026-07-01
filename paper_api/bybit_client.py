from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode

from shared_utils import clean_string
from trading_utils import decimal_string, to_float, utc_now_ms


def normalize_bybit_env(raw_value):
    text = str(raw_value or "").strip().lower()
    aliases = {
        "prod": "mainnet",
        "production": "mainnet",
        "live": "mainnet",
        "demo": "demo",
        "mainnet-demo": "demo",
        "prod-demo": "demo",
        "test": "testnet",
        "testnet": "testnet",
        "mainnet": "mainnet",
    }
    return aliases.get(text, "testnet")


def env_flag(*names):
    for name in names:
        raw = os.environ.get(name, "").strip().lower()
        if raw:
            return raw in {"1", "true", "yes", "on"}
    return False


def default_bybit_private_base_url(environment):
    if environment == "demo":
        return "https://api-demo.bybit.com"
    if environment == "mainnet":
        return "https://api.bybit.com"
    return "https://api-testnet.bybit.com"


BYBIT_ENV = normalize_bybit_env(os.environ.get("BYBIT_ENV", "testnet"))
BYBIT_MARKET_BASE_URL = os.environ.get("BYBIT_MARKET_BASE_URL", "https://api.bybit.com")
BYBIT_PRIVATE_BASE_URL = os.environ.get(
    "BYBIT_PRIVATE_BASE_URL",
    os.environ.get("BYBIT_TESTNET_BASE_URL", default_bybit_private_base_url(BYBIT_ENV)),
)
BYBIT_MARKET_KLINE_PATH = "/v5/market/kline"
BYBIT_MARKET_TICKERS_PATH = "/v5/market/tickers"
BYBIT_MARKET_INSTRUMENTS_PATH = "/v5/market/instruments-info"
BYBIT_ORDER_CREATE_PATH = "/v5/order/create"
BYBIT_ORDER_AMEND_PATH = "/v5/order/amend"
BYBIT_ORDER_CANCEL_PATH = "/v5/order/cancel"
BYBIT_ORDER_REALTIME_PATH = "/v5/order/realtime"
BYBIT_LEVERAGE_PATH = "/v5/position/set-leverage"
BYBIT_POSITION_LIST_PATH = "/v5/position/list"
BYBIT_TRADING_STOP_PATH = "/v5/position/trading-stop"
BYBIT_WALLET_BALANCE_PATH = "/v5/account/wallet-balance"
BYBIT_QUERY_API_KEY_PATH = "/v5/user/query-api"
BYBIT_ENABLE_PRIVATE_SUBMIT = env_flag("BYBIT_ENABLE_PRIVATE_SUBMIT", "BYBIT_ENABLE_TESTNET_SUBMIT")
BYBIT_ENABLE_TESTNET_SUBMIT = BYBIT_ENABLE_PRIVATE_SUBMIT
BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
BYBIT_RECV_WINDOW = os.environ.get("BYBIT_RECV_WINDOW", "5000")
BYBIT_HTTP_TIMEOUT = float(os.environ.get("BYBIT_HTTP_TIMEOUT", "10"))


def bybit_public_get(path, params):
    query = urlencode(params)
    url = f"{BYBIT_MARKET_BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"

    request = urlrequest.Request(url, method="GET")
    try:
        with urlrequest.urlopen(request, timeout=BYBIT_HTTP_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            status_code = response.getcode()
    except urlerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw_body": raw}
        return {
            "ok": False,
            "http_status": exc.code,
            "response": parsed,
            "url": url,
        }
    except urlerror.URLError as exc:
        return {
            "ok": False,
            "http_status": None,
            "response": {"error": str(exc.reason)},
            "url": url,
        }
    except (TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "http_status": None,
            "response": {"error": str(exc)},
            "url": url,
        }

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw_body": raw}

    return {
        "ok": status_code < 400 and parsed.get("retCode") == 0,
        "http_status": status_code,
        "response": parsed,
        "url": url,
    }

def parse_bybit_kline_list(raw_list):
    candles = []
    for item in raw_list:
        if not isinstance(item, list) or len(item) < 7:
            continue
        start_ms = int(item[0])
        candles.append(
            {
                "start_ms": start_ms,
                "start_at": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
                "open": to_float(item[1]),
                "high": to_float(item[2]),
                "low": to_float(item[3]),
                "close": to_float(item[4]),
                "volume": to_float(item[5]),
                "turnover": to_float(item[6]),
            }
        )
    candles.sort(key=lambda candle: candle["start_ms"])
    return candles

def fetch_bybit_klines(symbol, interval, limit=200, category="linear"):
    result = bybit_public_get(
        BYBIT_MARKET_KLINE_PATH,
        {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": max(1, min(1000, int(limit))),
        },
    )
    if not result["ok"]:
        return result

    raw_list = result["response"].get("result", {}).get("list", [])
    result["candles"] = parse_bybit_kline_list(raw_list)
    return result

def fetch_bybit_ticker(symbol, category="linear"):
    result = bybit_public_get(
        BYBIT_MARKET_TICKERS_PATH,
        {
            "category": category,
            "symbol": symbol,
        },
    )
    if not result["ok"]:
        return result

    ticker_list = result["response"].get("result", {}).get("list", [])
    result["ticker"] = ticker_list[0] if ticker_list else None
    return result

def fetch_bybit_instrument(symbol, category="linear"):
    result = bybit_public_get(
        BYBIT_MARKET_INSTRUMENTS_PATH,
        {
            "category": category,
            "symbol": symbol,
        },
    )
    if not result["ok"]:
        return result

    instrument_list = result["response"].get("result", {}).get("list", [])
    result["instrument"] = instrument_list[0] if instrument_list else None
    if result["instrument"] is None:
        result["ok"] = False
        result["response"] = {"error": f"instrument {symbol} not found"}
    return result

def extract_bybit_instrument_constraints(instrument):
    instrument = instrument or {}
    price_filter = instrument.get("priceFilter") or {}
    lot_size_filter = instrument.get("lotSizeFilter") or {}
    leverage_filter = instrument.get("leverageFilter") or {}

    return {
        "tick_size": decimal_string(price_filter.get("tickSize")),
        "min_price": decimal_string(price_filter.get("minPrice")),
        "max_price": decimal_string(price_filter.get("maxPrice")),
        "qty_step": decimal_string(lot_size_filter.get("qtyStep")),
        "min_order_qty": decimal_string(lot_size_filter.get("minOrderQty")),
        "max_order_qty": decimal_string(lot_size_filter.get("maxOrderQty")),
        "min_notional_value": decimal_string(lot_size_filter.get("minNotionalValue")),
        "max_leverage": decimal_string(leverage_filter.get("maxLeverage")),
        "min_leverage": decimal_string(leverage_filter.get("minLeverage")),
        "leverage_step": decimal_string(leverage_filter.get("leverageStep")),
        "unified_margin_trade": instrument.get("unifiedMarginTrade"),
    }

def bybit_private_get(path, params):
    filtered = {key: value for key, value in params.items() if value not in (None, "")}
    query = urlencode(filtered)
    timestamp = utc_now_ms()
    sign_payload = f"{timestamp}{BYBIT_API_KEY}{BYBIT_RECV_WINDOW}{query}"
    signature = hmac.new(
        BYBIT_API_SECRET.encode("utf-8"),
        sign_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    url = f"{BYBIT_PRIVATE_BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"

    request = urlrequest.Request(
        url,
        headers={
            "Content-Type": "application/json",
            "X-BAPI-API-KEY": BYBIT_API_KEY,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": BYBIT_RECV_WINDOW,
            "X-BAPI-SIGN": signature,
        },
        method="GET",
    )
    try:
        with urlrequest.urlopen(request, timeout=BYBIT_HTTP_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            status_code = response.getcode()
    except urlerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw_body": raw}
        return {"ok": False, "http_status": exc.code, "response": parsed}
    except urlerror.URLError as exc:
        return {"ok": False, "http_status": None, "response": {"error": str(exc.reason)}}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw_body": raw}

    return {
        "ok": status_code < 400 and parsed.get("retCode") == 0,
        "http_status": status_code,
        "response": parsed,
    }

def fetch_bybit_wallet_balance(account_type="UNIFIED", coin=None):
    result = bybit_private_get(
        BYBIT_WALLET_BALANCE_PATH,
        {
            "accountType": account_type,
            "coin": coin,
        },
    )
    if not result["ok"]:
        return result

    account_list = result["response"].get("result", {}).get("list", [])
    account_record = account_list[0] if account_list else None
    coin_record = None
    if account_record and coin:
        for item in account_record.get("coin", []):
            if clean_string(item.get("coin")) == coin:
                coin_record = item
                break

    result["account"] = account_record
    result["coin_record"] = coin_record
    return result

def fetch_bybit_api_key_information():
    result = bybit_private_get(BYBIT_QUERY_API_KEY_PATH, {})
    if not result["ok"]:
        return result

    result["api_info"] = result["response"].get("result", {}) if isinstance(result.get("response"), dict) else {}
    return result

def fetch_bybit_order_realtime(category, symbol=None, order_id=None, order_link_id=None, open_only=0):
    params = {
        "category": category,
        "symbol": symbol,
        "orderId": order_id,
        "orderLinkId": order_link_id,
        "openOnly": open_only,
    }
    result = bybit_private_get(BYBIT_ORDER_REALTIME_PATH, params)
    if not result["ok"]:
        return result

    order_list = result["response"].get("result", {}).get("list", [])
    result["orders"] = order_list
    result["order"] = order_list[0] if order_list else None
    return result

def fetch_bybit_positions(category, symbol=None, settle_coin=None):
    params = {
        "category": category,
        "symbol": symbol,
        "settleCoin": settle_coin,
    }
    result = bybit_private_get(BYBIT_POSITION_LIST_PATH, params)
    if not result["ok"]:
        return result

    position_list = result["response"].get("result", {}).get("list", [])
    result["positions"] = position_list
    return result

def bybit_headers(body_text):
    timestamp = utc_now_ms()
    sign_payload = f"{timestamp}{BYBIT_API_KEY}{BYBIT_RECV_WINDOW}{body_text}"
    signature = hmac.new(
        BYBIT_API_SECRET.encode("utf-8"),
        sign_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-BAPI-API-KEY": BYBIT_API_KEY,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": BYBIT_RECV_WINDOW,
        "X-BAPI-SIGN": signature,
    }

def bybit_post(path, payload):
    body_text = json.dumps(payload, separators=(",", ":"))
    request = urlrequest.Request(
        f"{BYBIT_PRIVATE_BASE_URL}{path}",
        data=body_text.encode("utf-8"),
        headers=bybit_headers(body_text),
        method="POST",
    )
    try:
        with urlrequest.urlopen(request, timeout=BYBIT_HTTP_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            status_code = response.getcode()
    except urlerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw_body": raw}
        return {
            "ok": False,
            "http_status": exc.code,
            "response": parsed,
        }
    except urlerror.URLError as exc:
        return {
            "ok": False,
            "http_status": None,
            "response": {"error": str(exc.reason)},
        }

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw_body": raw}

    return {
        "ok": status_code < 400 and parsed.get("retCode") == 0,
        "http_status": status_code,
        "response": parsed,
    }
