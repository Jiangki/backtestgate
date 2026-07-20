from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backtestgate.audit import audit
from backtestgate.loader import load_audit_directory
from backtestgate.report import render_json, render_share_json


PASS_FIXTURE = PROJECT_ROOT / "fixtures" / "pass"
WARN_FIXTURE = PROJECT_ROOT / "fixtures" / "warn"
BLOCK_FIXTURE = PROJECT_ROOT / "fixtures" / "block"


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backtestgate", *arguments],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class BacktestGateAcceptanceTests(unittest.TestCase):
    def test_init_creates_manifest_and_checklist_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "my-audit"
            first = run_cli("init", str(target))

            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            manifest = json.loads(
                (target / "manifest.json").read_text(encoding="utf-8")
            )
            uuid.UUID(manifest["validation_id"])
            self.assertEqual(manifest["symbol"], "REPLACE_ME")
            self.assertTrue((target / "README.txt").is_file())

            second = run_cli("init", str(target))
            self.assertEqual(second.returncode, 2)
            self.assertIn("refusing to overwrite", second.stderr)

    def test_init_placeholder_must_be_replaced_before_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "my-audit"
            self.assertEqual(run_cli("init", str(target)).returncode, 0)
            for filename in ("strategy.pine", "trades.csv", "performance.csv"):
                shutil.copy2(PASS_FIXTURE / filename, target / filename)

            result = run_cli("audit", str(target))

            self.assertEqual(result.returncode, 2)
            self.assertIn("still contains the init placeholder", result.stderr)

    def test_pass_fixture_is_clean_and_exits_zero(self) -> None:
        result = run_cli("audit", str(PASS_FIXTURE))

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Gate: PASS", result.stdout)
        self.assertIn("Findings (0)", result.stdout)
        self.assertIn("Closed trades:          40", result.stdout)

    def test_warn_fixture_reports_all_dimensions_but_exits_zero(self) -> None:
        result = run_cli("audit", str(WARN_FIXTURE))

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Gate: WARN", result.stdout)
        for rule_id in (
            "PINE002",
            "PINE003",
            "PINE004",
            "EXEC001",
            "EXEC002",
            "EXEC003",
            "EXEC004",
            "EXEC005",
            "EVID001",
            "ROBUST003",
            "ROBUST004",
        ):
            self.assertIn(rule_id, result.stdout)

    def test_fail_on_warn_is_available_for_ci(self) -> None:
        result = run_cli(
            "audit", str(WARN_FIXTURE), "--fail-on", "warn"
        )

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("Gate: WARN", result.stdout)

    def test_block_fixture_finds_future_leak_with_evidence(self) -> None:
        result = run_cli("audit", str(BLOCK_FIXTURE))

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("Gate: BLOCK", result.stdout)
        self.assertIn("PINE001", result.stdout)
        self.assertIn("strategy.pine:13", result.stdout)
        self.assertIn("lookahead = barmerge.lookahead_on", result.stdout)

    def test_json_output_is_machine_readable(self) -> None:
        result = run_cli("audit", str(BLOCK_FIXTURE), "--format", "json")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tool"], "backtestgate")
        self.assertEqual(payload["gate"], "BLOCK")
        self.assertEqual(payload["dimensions"]["code"], "BLOCK")
        self.assertTrue(
            all(
                {
                    "rule_id",
                    "severity",
                    "category",
                    "path",
                    "line",
                    "message",
                    "evidence",
                    "hint",
                    "source_url",
                }
                <= finding.keys()
                for finding in payload["findings"]
            )
        )

    def test_html_report_is_written_for_offline_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.html"
            result = run_cli(
                "audit", str(BLOCK_FIXTURE), "--output", str(report)
            )

            self.assertEqual(result.returncode, 1)
            content = report.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", content)
            self.assertIn("Audit gate", content)
            self.assertIn("PINE001", content)
            self.assertIn("No Pine code or trade data was uploaded", content)

    def test_share_receipt_omits_strategy_and_financial_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            result = run_cli(
                "audit",
                str(BLOCK_FIXTURE),
                "--share-output",
                str(receipt),
            )

            self.assertEqual(result.returncode, 1)
            content = receipt.read_text(encoding="utf-8")
            payload = json.loads(content)
            self.assertEqual(payload["schema"], "backtestgate-validation-v1")
            self.assertEqual(
                payload["validation_id"],
                "33333333-3333-4333-8333-333333333333",
            )
            self.assertEqual(payload["gate"], "BLOCK")
            self.assertIn("PINE001", payload["rule_ids"])
            self.assertNotIn("symbol", payload)
            self.assertNotIn("metrics", payload)
            self.assertNotIn("BINANCE:ETHUSDT", content)
            self.assertNotIn("futureDailyClose", content)
            self.assertNotIn("net_profit", content)

    def test_share_receipt_is_deterministic_for_the_same_result(self) -> None:
        result = audit(load_audit_directory(WARN_FIXTURE))

        first = json.loads(render_share_json(result))
        second = json.loads(render_share_json(result))

        self.assertEqual(first["receipt_id"], second["receipt_id"])
        self.assertEqual(first, second)

    def test_missing_directory_exits_two_without_traceback(self) -> None:
        missing = PROJECT_ROOT / "fixtures" / "does-not-exist"
        result = run_cli("audit", str(missing))

        self.assertEqual(result.returncode, 2)
        self.assertIn("backtestgate: error:", result.stderr)
        self.assertIn("does not exist", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_comment_that_mentions_lookahead_does_not_false_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "audit"
            shutil.copytree(PASS_FIXTURE, copied)
            pine = copied / "strategy.pine"
            pine.write_text(
                "// request.security(x, y, close, lookahead = barmerge.lookahead_on)\n"
                + pine.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            result = audit(load_audit_directory(copied))

            self.assertEqual(result.gate, "PASS")
            self.assertNotIn("PINE001", {item.rule_id for item in result.findings})

    def test_performance_summary_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "audit"
            shutil.copytree(PASS_FIXTURE, copied)
            performance = copied / "performance.csv"
            performance.write_text(
                performance.read_text(encoding="utf-8").replace(
                    "Net profit,224", "Net profit,999"
                ),
                encoding="utf-8",
            )

            result = audit(load_audit_directory(copied))

            self.assertEqual(result.gate, "WARN")
            self.assertIn("DATA001", {item.rule_id for item in result.findings})

    def test_json_uses_null_instead_of_nonstandard_infinity(self) -> None:
        audit_input = load_audit_directory(PASS_FIXTURE)
        winning_trades = tuple(
            trade for trade in audit_input.trades if trade.pnl > 0
        )
        all_win_input = replace(
            audit_input,
            trades=winning_trades,
            performance={"netprofit": sum(trade.pnl for trade in winning_trades)},
        )

        rendered = render_json(audit(all_win_input))
        payload = json.loads(rendered)

        self.assertNotIn("Infinity", rendered)
        self.assertIsNone(payload["metrics"]["profit_factor"])


if __name__ == "__main__":
    unittest.main()
