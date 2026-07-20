"""Deterministic audit orchestration and trade-level robustness checks."""

from __future__ import annotations

import math
from typing import List, Optional

from .models import AuditInput, AuditMetrics, AuditResult, Finding
from .pine_rules import (
    STRATEGY_DOCS,
    pine_uses_intrabar_orders,
    pine_uses_limit_orders,
    run_pine_rules,
)


STRATEGY_PROPERTIES_DOCS = (
    "https://www.tradingview.com/support/solutions/43000628599-strategy-properties/"
)
BROKER_EMULATOR_DOCS = (
    "https://www.tradingview.com/support/solutions/43000786181-broker-emulator/"
)

LIMITATIONS = (
    "PASS means only that this rule version found no covered issue; it is not a profitability or safety guarantee.",
    "BacktestGate does not execute Pine Script and cannot prove semantic equivalence with TradingView.",
    "Trade-level drawdown uses closed P&L only; intratrade equity risk needs bar/fill data.",
    "One exported run cannot establish Probability of Backtest Overfitting or a Deflated Sharpe Ratio.",
)


def _performance_net_profit(audit_input: AuditInput) -> Optional[float]:
    for key, value in audit_input.performance.items():
        if key.startswith("netprofit") and "%" not in key:
            return value
    return None


def calculate_metrics(audit_input: AuditInput) -> AuditMetrics:
    trades = list(audit_input.trades)
    pnls = [trade.pnl for trade in trades]
    closed_trades = len(pnls)
    net_profit = sum(pnls)
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = -sum(value for value in pnls if value < 0)
    wins = sum(1 for value in pnls if value > 0)
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (math.inf if gross_profit > 0 else None)
    )

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    best_trade = max(pnls)
    positive = sorted((value for value in pnls if value > 0), reverse=True)
    top_five_profit_share = (
        sum(positive[:5]) / net_profit if net_profit > 0 and positive else None
    )
    midpoint = max(1, closed_trades // 2)
    stress_cost = float(audit_input.manifest["stress_cost_per_trade"])

    return AuditMetrics(
        closed_trades=closed_trades,
        coverage_days=max(
            0, (trades[-1].closed_at.date() - trades[0].closed_at.date()).days
        ),
        net_profit=net_profit,
        win_rate=wins / closed_trades,
        profit_factor=profit_factor,
        max_realized_drawdown=max_drawdown,
        best_trade=best_trade,
        net_without_best_trade=net_profit - best_trade,
        top_five_profit_share=top_five_profit_share,
        stressed_net_profit=net_profit - stress_cost * closed_trades,
        first_half_net_profit=sum(pnls[:midpoint]),
        second_half_net_profit=sum(pnls[midpoint:]),
    )


def _finding(
    rule_id: str,
    category: str,
    message: str,
    evidence: str,
    hint: str,
    source_url: Optional[str] = None,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity="warn",
        category=category,
        path="manifest.json" if category == "execution" else "trades.csv",
        line=None,
        message=message,
        evidence=evidence,
        hint=hint,
        source_url=source_url,
    )


def _execution_findings(audit_input: AuditInput) -> List[Finding]:
    manifest = audit_input.manifest
    findings: List[Finding] = []
    if float(manifest["commission_value"]) <= 0:
        findings.append(
            _finding(
                "EXEC001",
                "execution",
                "commission is zero",
                "commission_value={}".format(manifest["commission_value"]),
                "Set the actual per-order, per-contract, or percentage commission used by the broker.",
                STRATEGY_PROPERTIES_DOCS,
            )
        )
    if float(manifest["slippage_ticks"]) <= 0:
        findings.append(
            _finding(
                "EXEC002",
                "execution",
                "slippage is zero",
                "slippage_ticks={}".format(manifest["slippage_ticks"]),
                "Use a conservative non-zero slippage assumption appropriate for the instrument.",
                STRATEGY_PROPERTIES_DOCS,
            )
        )
    if pine_uses_intrabar_orders(audit_input) and not manifest["bar_magnifier"]:
        findings.append(
            _finding(
                "EXEC003",
                "execution",
                "stop/limit orders rely on intrabar assumptions without Bar Magnifier",
                "bar_magnifier=false and strategy uses stop/limit order arguments",
                "Enable Bar Magnifier when available and compare results; forward-test execution assumptions.",
                BROKER_EMULATOR_DOCS,
            )
        )
    if str(manifest["chart_type"]).strip().lower() != "standard":
        findings.append(
            _finding(
                "EXEC004",
                "execution",
                "backtest uses a non-standard chart type",
                "chart_type={!r}".format(manifest["chart_type"]),
                "Re-run on standard OHLC prices or explicitly configure standard-bar fills.",
                BROKER_EMULATOR_DOCS,
            )
        )
    if (
        pine_uses_limit_orders(audit_input)
        and float(manifest["limit_fill_assumption_ticks"]) <= 0
    ):
        findings.append(
            _finding(
                "EXEC005",
                "execution",
                "limit orders fill as soon as price merely touches the level",
                "limit_fill_assumption_ticks={}".format(
                    manifest["limit_fill_assumption_ticks"]
                ),
                "Require price to move through the limit by at least one tick and compare the result.",
                STRATEGY_PROPERTIES_DOCS,
            )
        )
    return findings


def _evidence_findings(
    audit_input: AuditInput, metrics: AuditMetrics
) -> List[Finding]:
    findings: List[Finding] = []
    if metrics.closed_trades < 30:
        findings.append(
            _finding(
                "EVID001",
                "evidence",
                "the report contains fewer than 30 closed trades",
                "closed_trades={}".format(metrics.closed_trades),
                "Collect a larger sample across multiple market conditions; 30 is a warning floor, not proof of sufficiency.",
            )
        )
    if metrics.coverage_days < 180:
        findings.append(
            _finding(
                "EVID002",
                "evidence",
                "the report covers less than 180 calendar days",
                "coverage_days={}".format(metrics.coverage_days),
                "Test across a longer period and multiple regimes; 180 days is only an early warning threshold.",
            )
        )
    reported = _performance_net_profit(audit_input)
    if reported is not None:
        tolerance = max(0.01, abs(reported) * 0.001)
        if abs(reported - metrics.net_profit) > tolerance:
            findings.append(
                _finding(
                    "DATA001",
                    "evidence",
                    "trade rows do not reconcile with Performance Summary net profit",
                    "trade_sum={:.2f}, reported_net_profit={:.2f}".format(
                        metrics.net_profit, reported
                    ),
                    "Export both tabs from the same run and verify currency/locale parsing.",
                )
            )
    return findings


def _robustness_findings(metrics: AuditMetrics) -> List[Finding]:
    findings: List[Finding] = []
    share = metrics.top_five_profit_share
    if metrics.net_profit > 0 and share is not None and share >= 0.5:
        findings.append(
            _finding(
                "ROBUST001",
                "robustness",
                "the five best trades contribute at least half of total net profit",
                "top_five_profit_share={:.1%}".format(share),
                "Review the outlier trades and test whether the result survives their removal.",
            )
        )
    if metrics.net_profit > 0 and metrics.net_without_best_trade <= 0:
        findings.append(
            _finding(
                "ROBUST002",
                "robustness",
                "removing the best trade eliminates all net profit",
                "net_without_best_trade={:.2f}".format(
                    metrics.net_without_best_trade
                ),
                "Treat the result as outlier-dependent and collect independent forward evidence.",
            )
        )
    if metrics.net_profit > 0 and metrics.stressed_net_profit <= 0:
        findings.append(
            _finding(
                "ROBUST003",
                "robustness",
                "the configured additional cost stress turns net profit non-positive",
                "stressed_net_profit={:.2f}".format(metrics.stressed_net_profit),
                "Recheck broker costs, spread and slippage; the backtested edge is smaller than the stress allowance.",
            )
        )
    if metrics.net_profit > 0 and (
        metrics.first_half_net_profit <= 0 or metrics.second_half_net_profit <= 0
    ):
        findings.append(
            _finding(
                "ROBUST004",
                "robustness",
                "one chronological half of the trade sample is non-profitable",
                "first_half={:.2f}, second_half={:.2f}".format(
                    metrics.first_half_net_profit,
                    metrics.second_half_net_profit,
                ),
                "Inspect regime dependence and validate on an untouched later period.",
            )
        )
    return findings


def audit(audit_input: AuditInput) -> AuditResult:
    """Run all offline checks and return one reproducible result."""

    metrics = calculate_metrics(audit_input)
    findings = [
        *run_pine_rules(audit_input),
        *_execution_findings(audit_input),
        *_evidence_findings(audit_input, metrics),
        *_robustness_findings(metrics),
    ]
    return AuditResult(
        audit_input=audit_input,
        metrics=metrics,
        findings=tuple(sorted(findings, key=Finding.sort_key)),
        limitations=LIMITATIONS,
    )
