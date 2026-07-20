# BacktestGate

Offline trust gate for **TradingView Pine Script backtests**.

BacktestGate reads a Pine strategy, TradingView CSV exports, and the actual run assumptions. It then produces a deterministic `PASS`, `WARN`, or `BLOCK` report with line-level evidence and small, explainable robustness checks.

> Status: open-source pre-release experiment for demand validation. It is not a strategy generator, profitability score, certification, or investment recommendation.

## What the demo shows

```text
strategy.pine + trades.csv + performance.csv + manifest.json
                              │
                              ▼
          code integrity / execution realism
          evidence sufficiency / robustness
                              │
                              ▼
                    PASS / WARN / BLOCK
```

The tool is read-only and offline. It does not execute Pine, connect to TradingView, call an LLM, upload source code, or place orders.

## Requirements

- Python 3.9+
- No third-party runtime dependencies

## Run the fixtures

```bash
# In github-hot-tracker:
cd experiments/backtestgate

# Clean sample: exit 0
python3 -m backtestgate audit fixtures/pass

# Fragile assumptions: WARN, exit 0
python3 -m backtestgate audit fixtures/warn

# Confirmed future leak: BLOCK, exit 1
python3 -m backtestgate audit fixtures/block

# Generate an offline visual report
python3 -m backtestgate audit fixtures/block --output block-report.html
```

Open `block-report.html` in any browser. No server is required.

Optional editable install:

```bash
python3 -m pip install -e .
backtestgate audit fixtures/warn
```

## Expected fixture results

| Fixture | Gate | Exit | Representative evidence |
|---|---|---:|---|
| `fixtures/pass` | PASS | 0 | confirmed `request.security` value, non-zero costs, 40 trades / 390 days |
| `fixtures/warn` | WARN | 0 | tick/fill recalculation, zero costs, Heikin Ashi, small/unstable sample |
| `fixtures/block` | BLOCK | 1 | `PINE001` at `strategy.pine:13`: `lookahead_on` without a confirmed expression offset |

For stricter CI behavior:

```bash
python3 -m backtestgate audit fixtures/warn --fail-on warn
# exit 1
```

## Audit your own export

Initialize one private local directory:

```bash
python3 -m backtestgate init my-audit
```

The command refuses to overwrite a non-empty directory. It creates a manifest with a random `validation_id` and a local checklist:

```text
my-audit/
├── README.txt
└── manifest.json
```

Then:

1. Save the exact Pine source used for the run as `my-audit/strategy.pine`.
2. In TradingView Strategy Report, export the **List of trades** tab as `my-audit/trades.csv`.
3. Export the **Performance** tab as `my-audit/performance.csv`.
4. Replace every `REPLACE_ME` and assumption in `manifest.json` with the actual Properties-panel values.
5. Run:

```bash
python3 -m backtestgate audit my-audit --output my-report.html
```

The MVP accepts English TradingView headers. It identifies columns such as `Type`, `Date and time`, `Qty`/`Position size`, and `Net P&L <currency>`. Only `Exit` rows are treated as closed trades.

### `manifest.json`

```json
{
  "validation_id": "d152cf18-8c83-4dfe-8612-0b8104f07bd2",
  "symbol": "BINANCE:BTCUSDT",
  "timeframe": "1h",
  "chart_type": "standard",
  "commission_value": 0.1,
  "slippage_ticks": 2,
  "bar_magnifier": true,
  "limit_fill_assumption_ticks": 1,
  "calc_on_every_tick": false,
  "calc_on_order_fills": false,
  "stress_cost_per_trade": 2.0
}
```

`stress_cost_per_trade` is an **additional round-trip cost scenario** applied to each closed trade. It does not claim to infer the correct broker cost.

Why is the manifest required? Pine defaults can be overridden in TradingView's Properties panel. Source code alone therefore cannot prove which assumptions produced the exported result.

Keep `validation_id` unchanged when fixing and rerunning an audit. It is a random identifier, not an account, and allows a voluntary follow-up receipt to demonstrate repeat use.

## Gate semantics

| Gate | Meaning | Default exit |
|---|---|---:|
| PASS | No issue found by the rules covered in this version | 0 |
| WARN | Review execution, evidence, or robustness before relying on the run | 0 |
| BLOCK | A high-confidence correctness issue was found | 1 |

Invalid/missing input exits `2`. `PASS` deliberately means **PASS CHECKS**, not “safe” and never “will make money.”

## Rules in v0.2

### Code integrity

| ID | Gate | Check |
|---|---|---|
| `PINE000` | BLOCK | Missing `strategy()` declaration |
| `PINE001` | BLOCK | `request.security(... lookahead_on)` without a confirmed-history offset in the requested expression |
| `PINE002` | WARN | `calc_on_every_tick=true` |
| `PINE003` | WARN | `calc_on_order_fills=true` |
| `PINE004` | WARN | `timenow`, `varip`, or realtime-only state appears |
| `PINE005` | WARN | Missing/old Pine version |

`PINE001` understands the official safe shape `request.security(..., close[1], lookahead = barmerge.lookahead_on)` and does not block it.

### Execution realism

| ID | Gate | Check |
|---|---|---|
| `EXEC001` | WARN | Zero commission |
| `EXEC002` | WARN | Zero slippage |
| `EXEC003` | WARN | Stop/limit orders without Bar Magnifier |
| `EXEC004` | WARN | Non-standard chart type |
| `EXEC005` | WARN | Limit orders with zero fill-verification ticks |

### Evidence and result robustness

| ID | Gate | Check |
|---|---|---|
| `DATA001` | WARN | Trade P&L does not reconcile with Performance Summary |
| `EVID001` | WARN | Fewer than 30 closed trades |
| `EVID002` | WARN | Less than 180 calendar days |
| `ROBUST001` | WARN | Five best trades contribute at least half of net profit |
| `ROBUST002` | WARN | Removing the best trade removes all profit |
| `ROBUST003` | WARN | Additional-cost stress makes net profit non-positive |
| `ROBUST004` | WARN | One chronological half is non-profitable |

The 30-trade and 180-day values are warning floors, not universal statistical sufficiency claims.

## Output formats

```bash
python3 -m backtestgate audit fixtures/warn --format json
python3 -m backtestgate audit fixtures/warn --format markdown
python3 -m backtestgate audit fixtures/warn --format html

python3 -m backtestgate audit fixtures/warn --output report.json
python3 -m backtestgate audit fixtures/warn --output report.md
python3 -m backtestgate audit fixtures/warn --output report.html
```

The output file format is inferred from its suffix.

### Privacy-safe validation receipt

Full reports intentionally include code evidence and financial metrics for local diagnosis. Do not attach them to a public issue unless you intend to disclose that data.

For validation feedback, generate a minimized receipt instead:

```bash
python3 -m backtestgate audit my-audit \
  --share-output validation-receipt.json
```

The receipt contains the gate, dimension statuses, rule IDs, broad sample-size buckets, tool version, and random `validation_id`. It omits Pine source, symbols, timeframes, paths, P&L, prices, and individual trades. The CLI never uploads it; inspect the JSON before sharing.

See [VALIDATION.md](VALIDATION.md) for the feedback protocol and evidence-counting rules. Fixtures and maintainer runs do not count as external use.

## Important limits

- BacktestGate does not execute Pine and cannot prove full script semantics.
- The Pine scanner is deliberately conservative; it is not a complete parser.
- Realized drawdown is reconstructed from closed trades, not intratrade equity.
- A single exported run cannot establish Probability of Backtest Overfitting or a Deflated Sharpe Ratio.
- Static checks cannot rule out every repainting or future-data pattern.
- Report findings require human review.

Not yet included:

- localized/non-English TradingView export headers
- pyramiding and partial-exit reconciliation
- multiple-run PBO/Deflated Sharpe analysis
- bootstrap/Monte Carlo reports
- comparison between strategy versions
- TradingView alert or broker-fill drift monitoring
- automatic mapping of every locale/export layout

## Development

```bash
python3 -m unittest discover -s tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before changing rule severity or the share-receipt schema.

## License

MIT — see [LICENSE](LICENSE).
