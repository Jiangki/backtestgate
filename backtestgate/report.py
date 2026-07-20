"""Terminal, JSON, Markdown, and offline HTML report renderers."""

from __future__ import annotations

import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any, Dict, Optional

from . import __version__
from .models import AuditMetrics, AuditResult, CATEGORY_LABELS, Finding


def _number(value: float) -> str:
    if math.isinf(value):
        return "∞"
    return "{:,.2f}".format(value)


def _percent(value: Optional[float]) -> str:
    return "n/a" if value is None else "{:.1%}".format(value)


def _location(finding: Finding) -> str:
    return (
        "{}:{}".format(finding.path, finding.line)
        if finding.line is not None
        else finding.path
    )


def _metrics_data(metrics: AuditMetrics) -> Dict[str, Any]:
    json_profit_factor = metrics.profit_factor
    if json_profit_factor is not None and not math.isfinite(json_profit_factor):
        json_profit_factor = None
    return {
        "closed_trades": metrics.closed_trades,
        "coverage_days": metrics.coverage_days,
        "net_profit": metrics.net_profit,
        "win_rate": metrics.win_rate,
        "profit_factor": json_profit_factor,
        "max_realized_drawdown": metrics.max_realized_drawdown,
        "best_trade": metrics.best_trade,
        "net_without_best_trade": metrics.net_without_best_trade,
        "top_five_profit_share": metrics.top_five_profit_share,
        "stressed_net_profit": metrics.stressed_net_profit,
        "first_half_net_profit": metrics.first_half_net_profit,
        "second_half_net_profit": metrics.second_half_net_profit,
    }


def _finding_data(finding: Finding) -> Dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "severity": finding.severity,
        "category": finding.category,
        "path": finding.path,
        "line": finding.line,
        "message": finding.message,
        "evidence": finding.evidence,
        "hint": finding.hint,
        "source_url": finding.source_url,
    }


def report_data(result: AuditResult) -> Dict[str, Any]:
    return {
        "tool": "backtestgate",
        "version": __version__,
        "gate": result.gate,
        "target": result.audit_input.root.name,
        "symbol": result.audit_input.manifest["symbol"],
        "timeframe": result.audit_input.manifest["timeframe"],
        "dimensions": result.dimensions,
        "metrics": _metrics_data(result.metrics),
        "findings": [_finding_data(finding) for finding in result.findings],
        "limitations": list(result.limitations),
    }


def _sample_bucket(value: int, boundaries: tuple[int, ...], labels: tuple[str, ...]) -> str:
    for boundary, label in zip(boundaries, labels):
        if value < boundary:
            return label
    return labels[-1]


def share_data(result: AuditResult) -> Dict[str, Any]:
    """Return a privacy-minimized receipt suitable for voluntary feedback."""

    counts = {"block": 0, "warn": 0}
    for finding in result.findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    safe_payload: Dict[str, Any] = {
        "schema": "backtestgate-validation-v1",
        "tool": "backtestgate",
        "version": __version__,
        "validation_id": result.audit_input.manifest.get("validation_id"),
        "gate": result.gate,
        "dimensions": result.dimensions,
        "finding_counts": counts,
        "rule_ids": sorted({finding.rule_id for finding in result.findings}),
        "sample": {
            "closed_trades": _sample_bucket(
                result.metrics.closed_trades,
                (10, 30, 100, 300),
                ("<10", "10-29", "30-99", "100-299", "300+"),
            ),
            "coverage_days": _sample_bucket(
                result.metrics.coverage_days,
                (30, 180, 365, 730),
                ("<30", "30-179", "180-364", "365-729", "730+"),
            ),
        },
        "performance_reconciled": not any(
            finding.rule_id == "DATA001" for finding in result.findings
        ),
        "omits": [
            "Pine source",
            "symbol and timeframe",
            "file paths and line evidence",
            "P&L and prices",
            "individual trades",
        ],
    }
    canonical = json.dumps(
        safe_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return {
        **safe_payload,
        "receipt_id": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20],
    }


def render_share_json(result: AuditResult) -> str:
    return json.dumps(
        share_data(result),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )


def render_json(result: AuditResult) -> str:
    return json.dumps(
        report_data(result),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )


def render_text(result: AuditResult) -> str:
    metrics = result.metrics
    lines = [
        "BacktestGate {} audited {} ({} @ {})".format(
            __version__,
            result.audit_input.root.name,
            result.audit_input.manifest["symbol"],
            result.audit_input.manifest["timeframe"],
        ),
        "Gate: {}".format(result.gate),
        "",
        "Dimensions",
    ]
    for category, status in result.dimensions.items():
        lines.append("  {:<22} {}".format(CATEGORY_LABELS[category] + ":", status))
    lines.extend(
        [
            "",
            "Metrics",
            "  Closed trades:          {}".format(metrics.closed_trades),
            "  Coverage:               {} days".format(metrics.coverage_days),
            "  Net profit:             {}".format(_number(metrics.net_profit)),
            "  Win rate:               {}".format(_percent(metrics.win_rate)),
            "  Profit factor:          {}".format(
                "n/a"
                if metrics.profit_factor is None
                else _number(metrics.profit_factor)
            ),
            "  Realized max drawdown:  {}".format(
                _number(metrics.max_realized_drawdown)
            ),
            "  Net without best trade: {}".format(
                _number(metrics.net_without_best_trade)
            ),
            "  Additional-cost stress: {}".format(
                _number(metrics.stressed_net_profit)
            ),
            "",
            "Findings ({})".format(len(result.findings)),
        ]
    )
    if not result.findings:
        lines.append(
            "  PASS CHECKS — no issue was found by the rules covered in this version."
        )
    for finding in result.findings:
        lines.extend(
            [
                "  {} [{}] {} {}".format(
                    _location(finding),
                    finding.severity.upper(),
                    finding.rule_id,
                    finding.message,
                ),
                "    Evidence: {}".format(finding.evidence),
                "    Fix: {}".format(finding.hint),
            ]
        )
    lines.extend(["", "Limits"])
    lines.extend("  - {}".format(item) for item in result.limitations)
    return "\n".join(lines)


def render_markdown(result: AuditResult) -> str:
    metrics = result.metrics
    lines = [
        "# BacktestGate report",
        "",
        "> **Gate: {}** — `{}` / `{}` @ `{}`".format(
            result.gate,
            result.audit_input.root.name,
            result.audit_input.manifest["symbol"],
            result.audit_input.manifest["timeframe"],
        ),
        "",
        "## Dimensions",
        "",
        "| Dimension | Status |",
        "|---|---|",
    ]
    for category, status in result.dimensions.items():
        lines.append("| {} | **{}** |".format(CATEGORY_LABELS[category], status))
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            "| Metric | Value |",
            "|---|---:|",
            "| Closed trades | {} |".format(metrics.closed_trades),
            "| Coverage | {} days |".format(metrics.coverage_days),
            "| Net profit | {} |".format(_number(metrics.net_profit)),
            "| Win rate | {} |".format(_percent(metrics.win_rate)),
            "| Profit factor | {} |".format(
                "n/a"
                if metrics.profit_factor is None
                else _number(metrics.profit_factor)
            ),
            "| Realized max drawdown | {} |".format(
                _number(metrics.max_realized_drawdown)
            ),
            "| Net without best trade | {} |".format(
                _number(metrics.net_without_best_trade)
            ),
            "| Additional-cost stressed net | {} |".format(
                _number(metrics.stressed_net_profit)
            ),
            "",
            "## Findings",
            "",
        ]
    )
    if not result.findings:
        lines.append(
            "PASS CHECKS — no issue was found by the rules covered in this version."
        )
    for finding in result.findings:
        lines.extend(
            [
                "### {} · {}".format(finding.rule_id, finding.severity.upper()),
                "",
                "- Category: {}".format(CATEGORY_LABELS[finding.category]),
                "- Location: `{}`".format(_location(finding)),
                "- Problem: {}".format(finding.message),
                "- Evidence: `{}`".format(finding.evidence.replace("`", "\\`")),
                "- Suggested action: {}".format(finding.hint),
            ]
        )
        if finding.source_url:
            lines.append("- Source: {}".format(finding.source_url))
        lines.append("")
    lines.extend(["## Limits", ""])
    lines.extend("- {}".format(item) for item in result.limitations)
    return "\n".join(lines)


def _status_badge(status: str) -> str:
    return '<span class="badge {}">{}</span>'.format(
        status.lower(), html.escape(status)
    )


def render_html(result: AuditResult) -> str:
    metrics = result.metrics
    dimension_cards = "".join(
        '<div class="dimension"><span>{}</span>{}</div>'.format(
            html.escape(CATEGORY_LABELS[category]), _status_badge(status)
        )
        for category, status in result.dimensions.items()
    )
    metric_values = (
        ("Closed trades", str(metrics.closed_trades)),
        ("Coverage", "{} days".format(metrics.coverage_days)),
        ("Net profit", _number(metrics.net_profit)),
        ("Win rate", _percent(metrics.win_rate)),
        (
            "Profit factor",
            "n/a"
            if metrics.profit_factor is None
            else _number(metrics.profit_factor),
        ),
        ("Realized max drawdown", _number(metrics.max_realized_drawdown)),
        ("Net without best", _number(metrics.net_without_best_trade)),
        ("Cost-stressed net", _number(metrics.stressed_net_profit)),
    )
    metric_cards = "".join(
        '<div class="metric"><span>{}</span><strong>{}</strong></div>'.format(
            html.escape(label), html.escape(value)
        )
        for label, value in metric_values
    )
    if result.findings:
        finding_cards = "".join(
            """
            <article class="finding {severity}">
              <div class="finding-head">{badge}<code>{rule}</code><span>{category}</span></div>
              <h3>{message}</h3>
              <p class="location">{location}</p>
              <pre>{evidence}</pre>
              <p><strong>Suggested action:</strong> {hint}</p>
              {source}
            </article>
            """.format(
                severity=finding.severity,
                badge=_status_badge(finding.severity.upper()),
                rule=html.escape(finding.rule_id),
                category=html.escape(CATEGORY_LABELS[finding.category]),
                message=html.escape(finding.message),
                location=html.escape(_location(finding)),
                evidence=html.escape(finding.evidence),
                hint=html.escape(finding.hint),
                source=(
                    '<p><a href="{}">Official/reference documentation</a></p>'.format(
                        html.escape(finding.source_url, quote=True)
                    )
                    if finding.source_url
                    else ""
                ),
            )
            for finding in result.findings
        )
    else:
        finding_cards = (
            '<div class="empty">PASS CHECKS — no issue was found by the rules '
            "covered in this version.</div>"
        )
    limits = "".join("<li>{}</li>".format(html.escape(item)) for item in result.limitations)
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BacktestGate report — {target}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#0b1020; --panel:#141b2d; --line:#29324a;
      --text:#edf2ff; --muted:#9da9c5; --pass:#27c08a; --warn:#f5b942; --block:#ff667a; }}
    * {{ box-sizing:border-box }} body {{ margin:0; background:var(--bg); color:var(--text);
      font:15px/1.55 ui-sans-serif,system-ui,-apple-system,sans-serif }}
    main {{ max-width:1050px; margin:auto; padding:48px 24px 80px }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-start;
      padding-bottom:28px; border-bottom:1px solid var(--line) }}
    h1 {{ margin:0 0 8px; font-size:30px }} h2 {{ margin-top:38px }} h3 {{ margin:12px 0 4px }}
    p {{ color:var(--muted) }} .gate {{ text-align:right }} .gate .badge {{ font-size:20px; padding:8px 14px }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px }}
    .dimension,.metric,.finding,.empty {{ background:var(--panel); border:1px solid var(--line);
      border-radius:12px; padding:16px }}
    .dimension {{ display:flex; justify-content:space-between; align-items:center }}
    .metric span {{ display:block; color:var(--muted); font-size:13px }} .metric strong {{ font-size:22px }}
    .badge {{ display:inline-block; border-radius:999px; padding:3px 8px; font-weight:800; letter-spacing:.03em }}
    .badge.pass {{ color:var(--pass); background:#123c35 }} .badge.warn {{ color:var(--warn); background:#47391c }}
    .badge.block {{ color:var(--block); background:#471f2b }}
    .finding {{ margin:12px 0; border-left:4px solid var(--warn) }}
    .finding.block {{ border-left-color:var(--block) }} .finding-head {{ display:flex; align-items:center; gap:10px }}
    .finding-head span:last-child,.location {{ margin-left:auto; color:var(--muted) }}
    code,pre {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace }}
    pre {{ overflow:auto; padding:12px; background:#090d18; border-radius:8px; color:#dce5ff }}
    a {{ color:#8cb4ff }} .empty {{ color:var(--pass); font-weight:700 }}
    footer {{ margin-top:42px; color:var(--muted); font-size:13px }}
    @media(max-width:640px) {{ header {{ display:block }} .gate {{ text-align:left; margin-top:20px }}
      .finding-head {{ flex-wrap:wrap }} .finding-head span:last-child {{ margin-left:0 }} }}
  </style>
</head>
<body><main>
  <header>
    <div><h1>BacktestGate</h1><p>{target} · {symbol} @ {timeframe}</p></div>
    <div class="gate"><p>Audit gate</p>{gate}</div>
  </header>
  <h2>Dimensions</h2><section class="grid">{dimensions}</section>
  <h2>Trade-level metrics</h2><section class="grid">{metrics}</section>
  <h2>Findings ({count})</h2><section>{findings}</section>
  <h2>Limits</h2><ul>{limits}</ul>
  <footer>Generated locally by BacktestGate {version}. No Pine code or trade data was uploaded.</footer>
</main></body></html>
""".format(
        target=html.escape(result.audit_input.root.name),
        symbol=html.escape(str(result.audit_input.manifest["symbol"])),
        timeframe=html.escape(str(result.audit_input.manifest["timeframe"])),
        gate=_status_badge(result.gate),
        dimensions=dimension_cards,
        metrics=metric_cards,
        count=len(result.findings),
        findings=finding_cards,
        limits=limits,
        version=html.escape(__version__),
    )


def infer_output_format(path: Path) -> str:
    suffix = path.suffix.lower()
    return {".html": "html", ".json": "json", ".md": "markdown"}.get(
        suffix, "markdown"
    )


def render(result: AuditResult, output_format: str) -> str:
    renderers = {
        "text": render_text,
        "json": render_json,
        "markdown": render_markdown,
        "html": render_html,
    }
    return renderers[output_format](result)


def write_report(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        raise OSError("cannot write report '{}': {}".format(path, exc)) from exc
