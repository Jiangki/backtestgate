"""Strict, read-only loaders for BacktestGate audit directories."""

from __future__ import annotations

import csv
import json
import math
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .models import AuditInput, Trade


INPUT_FILENAMES = {
    "pine": "strategy.pine",
    "trades": "trades.csv",
    "performance": "performance.csv",
    "manifest": "manifest.json",
}

REQUIRED_MANIFEST_FIELDS = {
    "symbol": str,
    "timeframe": str,
    "chart_type": str,
    "commission_value": (int, float),
    "slippage_ticks": (int, float),
    "bar_magnifier": bool,
    "limit_fill_assumption_ticks": (int, float),
    "calc_on_every_tick": bool,
    "calc_on_order_fills": bool,
    "stress_cost_per_trade": (int, float),
}


class InputError(Exception):
    """Raised for actionable input problems without exposing a traceback."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError("{} must be UTF-8 text".format(path.name)) from exc
    except OSError as exc:
        raise InputError("cannot read '{}': {}".format(path, exc)) from exc


def _normalise_header(value: str) -> str:
    lowered = value.strip().lower().replace("&", "n")
    return re.sub(r"[^a-z0-9%]+", "", lowered)


def _pick_header(
    headers: Iterable[str],
    exact: Sequence[str] = (),
    prefixes: Sequence[str] = (),
) -> str:
    normalised = {_normalise_header(header): header for header in headers if header}
    for candidate in exact:
        if candidate in normalised:
            return normalised[candidate]
    for candidate in prefixes:
        for key, original in normalised.items():
            if key.startswith(candidate) and "%" not in key:
                return original
    raise InputError(
        "CSV is missing a required column (expected one of: {})".format(
            ", ".join((*exact, *prefixes))
        )
    )


def _parse_number(raw: Any, field: str) -> float:
    text = str(raw or "").strip()
    if not text:
        raise InputError("empty numeric value for {}".format(field))
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9eE+\-.,]", "", text)
    if "," in cleaned and "." not in cleaned:
        # TradingView's common exports use commas as thousands separators. A
        # quoted "1,234" is therefore treated as 1234, not a decimal comma.
        cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise InputError("invalid numeric value for {}: {!r}".format(field, text)) from exc
    if negative:
        value = -abs(value)
    if not math.isfinite(value):
        raise InputError("non-finite numeric value for {}: {!r}".format(field, text))
    return value


def _parse_datetime(raw: str) -> datetime:
    text = (raw or "").strip()
    if not text:
        raise InputError("trade row has an empty date/time")
    candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    for pattern in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise InputError("unsupported trade date/time: {!r}".format(text))


def _load_trades(path: Path) -> List[Trade]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise InputError("cannot read '{}': {}".format(path, exc)) from exc
    with handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise InputError("trades.csv has no header row")
        type_header = _pick_header(reader.fieldnames, exact=("type",))
        date_header = _pick_header(
            reader.fieldnames,
            exact=("dateandtime", "datetime"),
            prefixes=("dateandtime",),
        )
        pnl_header = _pick_header(
            reader.fieldnames,
            exact=("netpnl",),
            prefixes=("netpnl",),
        )
        try:
            trade_number_header = _pick_header(
                reader.fieldnames, exact=("trade", "trade#"), prefixes=("trade",)
            )
        except InputError:
            trade_number_header = ""
        try:
            quantity_header = _pick_header(
                reader.fieldnames,
                exact=("qty", "quantity", "positionsize"),
                prefixes=("positionsize",),
            )
        except InputError:
            quantity_header = ""

        trades: List[Trade] = []
        for row_index, row in enumerate(reader, start=2):
            trade_type = (row.get(type_header) or "").strip().lower()
            if "exit" not in trade_type:
                continue
            pnl = _parse_number(row.get(pnl_header), "Net P&L row {}".format(row_index))
            quantity = (
                abs(
                    _parse_number(
                        row.get(quantity_header),
                        "quantity row {}".format(row_index),
                    )
                )
                if quantity_header
                else 1.0
            )
            trades.append(
                Trade(
                    trade_number=(row.get(trade_number_header) or str(row_index)).strip()
                    if trade_number_header
                    else str(row_index),
                    closed_at=_parse_datetime(row.get(date_header) or ""),
                    pnl=pnl,
                    quantity=quantity or 1.0,
                )
            )
    if not trades:
        raise InputError("trades.csv contains no Exit rows")
    return sorted(trades, key=lambda trade: (trade.closed_at, trade.trade_number))


def _load_performance(path: Path) -> Dict[str, float]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise InputError("cannot read '{}': {}".format(path, exc)) from exc
    with handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(reader.fieldnames) < 2:
            raise InputError("performance.csv needs Metric and All columns")
        metric_header = reader.fieldnames[0]
        all_header = next(
            (
                header
                for header in reader.fieldnames[1:]
                if _normalise_header(header) in {"all", "alltrades", "value"}
            ),
            reader.fieldnames[1],
        )
        performance: Dict[str, float] = {}
        for row_index, row in enumerate(reader, start=2):
            metric = _normalise_header(row.get(metric_header) or "")
            if not metric:
                continue
            performance[metric] = _parse_number(
                row.get(all_header), "performance row {}".format(row_index)
            )
    if not any(key.startswith("netprofit") for key in performance):
        raise InputError("performance.csv does not contain a Net profit metric")
    return performance


def _load_manifest(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise InputError(
            "manifest.json is invalid JSON at line {}: {}".format(
                exc.lineno, exc.msg
            )
        ) from exc
    if not isinstance(payload, dict):
        raise InputError("manifest.json must contain a JSON object")
    for field, expected_type in REQUIRED_MANIFEST_FIELDS.items():
        if field not in payload:
            raise InputError("manifest.json is missing required field: {}".format(field))
        value = payload[field]
        # bool is an int subclass, so reject it explicitly for numeric fields.
        if expected_type == (int, float) and isinstance(value, bool):
            raise InputError("manifest field {} must be numeric".format(field))
        if not isinstance(value, expected_type):
            type_name = (
                "number" if expected_type == (int, float) else expected_type.__name__
            )
            raise InputError(
                "manifest field {} must be {}".format(field, type_name)
            )
    for field in (
        "commission_value",
        "slippage_ticks",
        "limit_fill_assumption_ticks",
        "stress_cost_per_trade",
    ):
        if float(payload[field]) < 0:
            raise InputError("manifest field {} cannot be negative".format(field))
    if not payload["symbol"].strip() or not payload["timeframe"].strip():
        raise InputError("manifest symbol and timeframe cannot be empty")
    for field in ("symbol", "timeframe"):
        if "REPLACE_ME" in payload[field].strip().upper():
            raise InputError(
                "manifest field {} still contains the init placeholder".format(field)
            )
    validation_id = payload.get("validation_id")
    if validation_id is not None:
        if not isinstance(validation_id, str):
            raise InputError("manifest field validation_id must be a UUID string")
        try:
            uuid.UUID(validation_id)
        except ValueError as exc:
            raise InputError(
                "manifest field validation_id must be a valid UUID"
            ) from exc
    return payload


def load_audit_directory(path: Path) -> AuditInput:
    """Load a conventional BacktestGate directory without executing its contents."""

    try:
        root = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InputError("audit directory does not exist: {}".format(path)) from exc
    if not root.is_dir():
        raise InputError("audit target is not a directory: {}".format(path))

    resolved: Dict[str, Path] = {}
    for key, filename in INPUT_FILENAMES.items():
        candidate = root / filename
        if not candidate.is_file():
            raise InputError("audit directory is missing {}".format(filename))
        if candidate.is_symlink():
            raise InputError("{} must not be a symbolic link".format(filename))
        resolved[key] = candidate

    return AuditInput(
        root=root,
        pine_path=resolved["pine"],
        pine_source=_read_text(resolved["pine"]),
        trades=tuple(_load_trades(resolved["trades"])),
        performance=_load_performance(resolved["performance"]),
        manifest=_load_manifest(resolved["manifest"]),
    )
