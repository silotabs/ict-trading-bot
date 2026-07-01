from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from shared_utils import clean_string


def first_present(mapping, keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping:
            value = mapping.get(key)
            if value not in (None, ""):
                return value
    return None


def normalize_instrument(value):
    raw = clean_string(value)
    if not raw:
        return ""
    symbol = raw.upper()
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    symbol = symbol.replace("/", "")
    if symbol.endswith(".P"):
        symbol = symbol[:-2]
    symbol = re.sub(r"[^A-Z0-9]", "", symbol)
    return symbol


def normalize_control_key(value):
    raw = clean_string(value)
    if not raw:
        return "global"
    normalized = raw.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    return normalized or "global"


def decimal_string(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None

    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def to_decimal(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def render_decimal(value):
    if value is None:
        return None
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def round_to_increment(value, increment, rounding):
    if value is None or increment in (None, Decimal("0")):
        return value
    quotient = (value / increment).quantize(Decimal("1"), rounding=rounding)
    return quotient * increment


def string_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            cleaned = clean_string(item)
            if cleaned:
                result.append(cleaned)
        return result
    cleaned = clean_string(value)
    return [cleaned] if cleaned else []


def build_order_link_id(symbol, journal_id):
    seed = journal_id or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(":", "").replace("-", "")
    raw = f"tv-{symbol.lower()}-{seed.lower()}"
    raw = re.sub(r"[^a-z0-9-]", "", raw)
    return raw[:36]


def utc_now_ms():
    return str(int(datetime.now(timezone.utc).timestamp() * 1000))


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def median_value(values):
    ordered = sorted(value for value in values if value is not None and not math.isnan(value))
    if not ordered:
        return None
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2
