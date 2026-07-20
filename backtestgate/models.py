"""Core immutable data models for BacktestGate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


CATEGORIES: Tuple[str, ...] = ("code", "execution", "evidence", "robustness")
CATEGORY_LABELS: Mapping[str, str] = {
    "code": "Code integrity",
    "execution": "Execution realism",
    "evidence": "Evidence sufficiency",
    "robustness": "Result robustness",
}


@dataclass(frozen=True)
class Trade:
    """One closed trade reconstructed from a TradingView List of Trades export."""

    trade_number: str
    closed_at: datetime
    pnl: float
    quantity: float


@dataclass(frozen=True)
class AuditInput:
    """Validated local input consumed by the deterministic audit engine."""

    root: Path
    pine_path: Path
    pine_source: str
    trades: Tuple[Trade, ...]
    performance: Mapping[str, float]
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class Finding:
    """One evidence-backed rule result."""

    rule_id: str
    severity: str
    category: str
    path: str
    line: Optional[int]
    message: str
    evidence: str
    hint: str
    source_url: Optional[str] = None

    def sort_key(self) -> Tuple[int, int, str, int]:
        severity_rank = {"block": 0, "warn": 1}
        category_rank = {name: index for index, name in enumerate(CATEGORIES)}
        return (
            severity_rank.get(self.severity, 2),
            category_rank.get(self.category, len(CATEGORIES)),
            self.rule_id,
            self.line or 0,
        )


@dataclass(frozen=True)
class AuditMetrics:
    """Small, explainable set of trade-level robustness metrics."""

    closed_trades: int
    coverage_days: int
    net_profit: float
    win_rate: float
    profit_factor: Optional[float]
    max_realized_drawdown: float
    best_trade: float
    net_without_best_trade: float
    top_five_profit_share: Optional[float]
    stressed_net_profit: float
    first_half_net_profit: float
    second_half_net_profit: float


@dataclass(frozen=True)
class AuditResult:
    """Complete result rendered by all output adapters."""

    audit_input: AuditInput
    metrics: AuditMetrics
    findings: Tuple[Finding, ...]
    limitations: Tuple[str, ...]

    @property
    def gate(self) -> str:
        if any(finding.severity == "block" for finding in self.findings):
            return "BLOCK"
        if self.findings:
            return "WARN"
        return "PASS"

    @property
    def dimensions(self) -> Dict[str, str]:
        statuses: Dict[str, str] = {}
        for category in CATEGORIES:
            relevant = [
                finding for finding in self.findings if finding.category == category
            ]
            if any(finding.severity == "block" for finding in relevant):
                statuses[category] = "BLOCK"
            elif relevant:
                statuses[category] = "WARN"
            else:
                statuses[category] = "PASS"
        return statuses

    @property
    def finding_list(self) -> List[Finding]:
        return list(self.findings)
