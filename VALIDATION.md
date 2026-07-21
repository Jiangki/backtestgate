# Feedback and privacy-safe receipts

Use this guide when reporting a real BacktestGate run without sharing strategy or trade data.

## Generate a receipt

```bash
# Create a local audit workspace.
python3 -m backtestgate init my-audit

# Follow my-audit/README.txt, then run the audit.
python3 -m backtestgate audit my-audit --output report.html

# Optional: create a receipt safe to attach to feedback.
python3 -m backtestgate audit my-audit \
  --share-output validation-receipt.json
```

The receipt contains:

- tool/schema version and a random `validation_id`
- PASS/WARN/BLOCK dimensions and rule IDs
- broad trade-count and coverage buckets
- whether exported net profit reconciled

It deliberately omits:

- Pine source and line evidence
- symbol, timeframe, paths, prices, P&L
- individual trades

The CLI never sends the receipt. Read it before sharing. Keep the generated `validation_id` unchanged if you fix findings and rerun; that allows repeat runs to be linked without an account.

## What to include in feedback

1. Did you complete an audit using your own strategy export?
2. Which input or instruction caused friction?
3. Did any finding cause a code/configuration change?
4. Was any BLOCK incorrect? Include the minimum non-sensitive explanation.
5. Did you run the same `validation_id` again after a change?
6. Which missing check would block continued use?

Open a **Real audit feedback** issue: https://github.com/Jiangki/backtestgate/issues/new/choose

Never attach Pine source or raw CSV unless you independently intend to make them public.

## Maintainer notes

- Prefer privacy-safe receipts over full HTML/Markdown reports in public issues.
- Redact or delete accidental strategy or trade-data disclosures.
- Fixture and maintainer self-test runs are useful for development, but they are not a substitute for external user reports.
