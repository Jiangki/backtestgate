# Contributing to BacktestGate

## Principles

- Keep audits deterministic, local, and offline.
- Never execute Pine or import code from an audit directory.
- Reserve `BLOCK` for high-confidence correctness failures; uncertain checks are `WARN`.
- Every rule needs a stable ID, evidence, remediation hint, and fixture/test coverage.
- Do not describe PASS as strategy certification or future profitability.

## Setup

BacktestGate has no third-party runtime dependencies:

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 -m backtestgate audit fixtures/pass
```

## Changing rules

1. State the exact risky behavior and false-positive boundary.
2. Add safe and unsafe test cases.
3. Update the README rule table.
4. Keep JSON and validation-receipt schemas backward-compatible or version them.
5. Link authoritative TradingView documentation where available.

## Privacy

Full reports may contain source lines, symbols, and financial metrics. The `--share-output` receipt must remain privacy-minimized. Any added receipt field requires a documented reason and a test proving sensitive inputs remain omitted.

See [VALIDATION.md](VALIDATION.md) before handling external feedback.
