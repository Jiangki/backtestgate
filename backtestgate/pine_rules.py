"""Conservative Pine Script checks with line-level evidence."""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Tuple

from .models import AuditInput, Finding


REPAINTING_DOCS = (
    "https://www.tradingview.com/pine-script-docs/concepts/repainting/"
)
STRATEGY_DOCS = "https://www.tradingview.com/pine-script-docs/faq/strategies/"


def _mask_comments_and_strings(source: str) -> str:
    """Mask comments and string contents while preserving offsets/newlines."""

    output = list(source)
    state = "code"
    quote = ""
    index = 0
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char == "/" and following == "/":
                output[index] = output[index + 1] = " "
                state = "line_comment"
                index += 2
                continue
            if char == "/" and following == "*":
                output[index] = output[index + 1] = " "
                state = "block_comment"
                index += 2
                continue
            if char in {'"', "'"}:
                quote = char
                output[index] = " "
                state = "string"
        elif state == "line_comment":
            if char == "\n":
                state = "code"
            else:
                output[index] = " "
        elif state == "block_comment":
            if char == "*" and following == "/":
                output[index] = output[index + 1] = " "
                state = "code"
                index += 2
                continue
            if char != "\n":
                output[index] = " "
        elif state == "string":
            if char == "\\" and following:
                output[index] = output[index + 1] = " "
                index += 2
                continue
            output[index] = " "
            if char == quote:
                state = "code"
        index += 1
    return "".join(output)


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _line_evidence(source: str, offset: int) -> str:
    start = source.rfind("\n", 0, offset) + 1
    end = source.find("\n", offset)
    if end < 0:
        end = len(source)
    return source[start:end].strip()[:240]


def _extract_calls(masked: str, function_name: str) -> Iterable[Tuple[int, int, str]]:
    pattern = re.compile(r"\b{}\s*\(".format(re.escape(function_name)))
    for match in pattern.finditer(masked):
        opening = masked.find("(", match.start(), match.end())
        depth = 0
        for index in range(opening, len(masked)):
            if masked[index] == "(":
                depth += 1
            elif masked[index] == ")":
                depth -= 1
                if depth == 0:
                    yield match.start(), index + 1, masked[match.start() : index + 1]
                    break


def _split_arguments(call: str) -> Sequence[str]:
    opening = call.find("(")
    closing = call.rfind(")")
    if opening < 0 or closing < opening:
        return ()
    inner = call[opening + 1 : closing]
    arguments: List[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(inner):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            arguments.append(inner[start:index].strip())
            start = index + 1
    arguments.append(inner[start:].strip())
    return arguments


def _flag(
    audit_input: AuditInput,
    rule_id: str,
    severity: str,
    offset: int,
    message: str,
    hint: str,
    source_url: str,
    evidence: str = "",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        category="code",
        path=audit_input.pine_path.name,
        line=_line_number(audit_input.pine_source, offset),
        message=message,
        evidence=evidence or _line_evidence(audit_input.pine_source, offset),
        hint=hint,
        source_url=source_url,
    )


def run_pine_rules(audit_input: AuditInput) -> List[Finding]:
    """Return only deterministic or explicitly review-level Pine findings."""

    source = audit_input.pine_source
    masked = _mask_comments_and_strings(source)
    findings: List[Finding] = []

    strategy_calls = list(_extract_calls(masked, "strategy"))
    if not strategy_calls:
        findings.append(
            Finding(
                rule_id="PINE000",
                severity="block",
                category="code",
                path=audit_input.pine_path.name,
                line=1,
                message="script has no strategy() declaration",
                evidence=source.splitlines()[0].strip()[:240] if source else "",
                hint="Provide a Pine strategy, not an indicator, before auditing Strategy Tester results.",
                source_url=STRATEGY_DOCS,
            )
        )

    version_match = re.search(r"(?m)^\s*//@version\s*=\s*(\d+)", source)
    if not version_match or int(version_match.group(1)) < 5:
        offset = version_match.start() if version_match else 0
        findings.append(
            _flag(
                audit_input,
                "PINE005",
                "warn",
                offset,
                "Pine version is missing or older than v5",
                "Declare //@version=6 so rule behavior and namespace semantics are explicit.",
                STRATEGY_DOCS,
            )
        )

    history_offset = re.compile(r"\[\s*[1-9]\d*\s*\]")
    for start, end, call in _extract_calls(masked, "request.security"):
        if not re.search(
            r"\blookahead\s*=\s*barmerge\.lookahead_on\b", call
        ):
            continue
        arguments = _split_arguments(call)
        expression = arguments[2] if len(arguments) >= 3 else ""
        if history_offset.search(expression):
            continue
        findings.append(
            _flag(
                audit_input,
                "PINE001",
                "block",
                start,
                "request.security() enables lookahead without a confirmed-history offset",
                "Request a confirmed expression such as close[1] when using lookahead_on; verify semantics against the official repainting guide.",
                REPAINTING_DOCS,
                " ".join(source[start:end].split())[:500],
            )
        )

    boolean_rules: Sequence[Tuple[str, str, str, str]] = (
        (
            "calc_on_every_tick",
            "PINE002",
            "strategy recalculates on every realtime tick",
            "Disable calc_on_every_tick or document why historical and realtime behavior can diverge.",
        ),
        (
            "calc_on_order_fills",
            "PINE003",
            "strategy recalculates immediately after simulated fills",
            "Disable calc_on_order_fills unless the fill-time behavior is explicitly validated in replay/forward tests.",
        ),
    )
    for option, rule_id, message, hint in boolean_rules:
        match = re.search(r"\b{}\s*=\s*true\b".format(option), masked)
        manifest_enabled = bool(audit_input.manifest.get(option))
        if match or manifest_enabled:
            offset = match.start() if match else 0
            findings.append(
                _flag(
                    audit_input,
                    rule_id,
                    "warn",
                    offset,
                    message,
                    hint,
                    STRATEGY_DOCS,
                )
            )

    state_rules: Sequence[Tuple[str, str, str]] = (
        (
            r"\btimenow\b",
            "timenow depends on script execution time and is not reproducible on historical bars",
            "Keep timenow out of order conditions, or verify the condition with recorded realtime data.",
        ),
        (
            r"\bvarip\b",
            "varip state can persist within realtime bars in ways history cannot reproduce",
            "Use ordinary var/bar-close state for backtested order conditions where possible.",
        ),
        (
            r"\bbarstate\.isrealtime\b",
            "order logic references realtime-only bar state",
            "Confirm that realtime-only branching cannot change entries or exits versus the backtest.",
        ),
    )
    for pattern, message, hint in state_rules:
        match = re.search(pattern, masked)
        if match:
            findings.append(
                _flag(
                    audit_input,
                    "PINE004",
                    "warn",
                    match.start(),
                    message,
                    hint,
                    REPAINTING_DOCS,
                )
            )

    return sorted(findings, key=Finding.sort_key)


def pine_uses_intrabar_orders(audit_input: AuditInput) -> bool:
    masked = _mask_comments_and_strings(audit_input.pine_source)
    return bool(
        re.search(
            r"\bstrategy\.(?:entry|order|exit)\s*\([^)]*\b(?:stop|limit)\s*=",
            masked,
            re.DOTALL,
        )
    )


def pine_uses_limit_orders(audit_input: AuditInput) -> bool:
    masked = _mask_comments_and_strings(audit_input.pine_source)
    return bool(
        re.search(
            r"\bstrategy\.(?:entry|order|exit)\s*\([^)]*\blimit\s*=",
            masked,
            re.DOTALL,
        )
    )
