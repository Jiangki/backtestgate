"""Create a safe, explicit starter directory for a real audit."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


MANIFEST_TEMPLATE = {
    "validation_id": "",
    "symbol": "REPLACE_ME",
    "timeframe": "REPLACE_ME",
    "chart_type": "standard",
    "commission_value": 0,
    "slippage_ticks": 0,
    "bar_magnifier": False,
    "limit_fill_assumption_ticks": 0,
    "calc_on_every_tick": False,
    "calc_on_order_fills": False,
    "stress_cost_per_trade": 0,
}

CHECKLIST = """BacktestGate real-audit checklist
=================================

This directory was created locally. BacktestGate will not upload its contents.

1. Save the exact tested Pine source as:
     strategy.pine

2. Export TradingView Strategy Report -> List of trades, then save as:
     trades.csv

3. Export TradingView Strategy Report -> Performance, then save as:
     performance.csv

4. Edit every assumption in manifest.json.
   - Replace REPLACE_ME values.
   - Use the actual Properties-panel values for this exported run.
   - stress_cost_per_trade is an additional round-trip cost scenario.
   - Keep validation_id unchanged so repeat audits can be linked anonymously.

5. From the BacktestGate project directory, run:
     python3 -m backtestgate audit "{audit_dir}" --output report.html

6. To create a privacy-safe receipt for public feedback:
     python3 -m backtestgate audit "{audit_dir}" --share-output validation-receipt.json

The receipt omits source code, symbol, timeframe, paths, P&L, and individual trades.
PASS means only that no covered rule found an issue; it is not a profit guarantee.
"""


class ScaffoldError(Exception):
    """Raised when initialization would overwrite user data."""


def initialise_audit_directory(path: Path) -> Path:
    """Create a starter manifest and checklist without overwriting anything."""

    try:
        target = path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ScaffoldError("cannot resolve init target: {}".format(path)) from exc
    if target.exists() and not target.is_dir():
        raise ScaffoldError("init target is not a directory: {}".format(path))
    if target.exists():
        try:
            has_entries = next(target.iterdir(), None) is not None
        except OSError as exc:
            raise ScaffoldError("cannot inspect '{}': {}".format(target, exc)) from exc
        if has_entries:
            raise ScaffoldError(
                "init target is not empty; refusing to overwrite: {}".format(path)
            )
    try:
        target.mkdir(parents=True, exist_ok=True)
        manifest = dict(MANIFEST_TEMPLATE)
        manifest["validation_id"] = str(uuid.uuid4())
        (target / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        (target / "README.txt").write_text(
            CHECKLIST.format(audit_dir=str(target).replace('"', '\\"')),
            encoding="utf-8",
        )
    except OSError as exc:
        raise ScaffoldError("cannot initialize '{}': {}".format(target, exc)) from exc
    return target
