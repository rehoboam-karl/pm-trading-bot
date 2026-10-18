# pm-trading-bot

> Reference implementation for a Polymarket copy-trading bot in Python.

[![CI](https://github.com/rehoboam-karl/pm-trading-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/rehoboam-karl/pm-trading-bot/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

`pm-trading-bot` is the orchestration layer for Polymarket copy trading:
position tracking, real-time P&L computation, and Telegram alerts.

**No API keys required for position tracking** — uses the public Polymarket CLOB.

---

## Install

```bash
pip install requests python-dotenv
```

## Usage

```bash
# Run once
python position_monitor.py

# Run continuously (daemon mode)
python position_monitor.py --continuous --interval 60
```

## Configuration

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export OUTPUT_DIR="./data"    # default: ./data
```

## Architecture

```
┌──────────────────────────────────────────┐
│           Trading Engine                   │
│   (copies whale trades based on signals)  │
└──────────────────┬───────────────────────┘
                   │ track_entry()
                   ▼
┌──────────────────────────────────────────┐
│        position_monitor.py                 │
│  • Tracks open positions + entry prices   │
│  • Checks CLOB for current prices (60s)   │
│  • Computes unrealized P&L                │
│  • Sends Telegram alerts on changes       │
│  • Cooldown-aware (no alert spam)         │
│  • Persists state to disk (survives restarts) │
└──────────────────────────────────────────┘
```

## Key concepts

### Position Entry

Inject entries from your trading engine when a trade is placed:

```python
from position_monitor import PositionState, STATE_FILE, ENTRY_TRACKER_FILE

state = PositionState(STATE_FILE, ENTRY_TRACKER_FILE)
state.track_entry(
    token_id="0x1234...",
    outcome="Yes",
    entry_price=0.45,
    size=100.0,
    timestamp="2026-01-01T00:00:00Z",
)
```

### Alert Cooldown

The monitor tracks when alerts were sent per token and won't re-alert
within `ALERT_COOLDOWN_SECONDS` (default: 300s = 5 minutes).
Even after cooldown, only material changes trigger re-alert
(price change >5% or P&L change >$5).

### P&L Computation

```python
pnl, pnl_pct = compute_pnl(entry, current_price)
# Returns (pnl_dollars, pnl_pct)
```

P&L is calculated as: `(current_price * size) - entry_cost`

## Alert Format

```
🟢 Position Update
Token: 0x1234...5678
Status: OPEN
Entry: $0.4500
Current: $0.6200
P&L: +$17.00 (+37.8%)
Size: 100.00 shares
Held: 2h 15m
```

## Integration

### With pm-core (Rust)

```
whale_signal → pm-core risk/market checks → order filled
                                    ↓
                          track_entry() called
                                    ↓
                          position_monitor.py monitors
```

### With pm-whale-scout

```
whale_scout.py --json → current_whales list
                            ↓
              passed to recommend_changes() or --current flag
```

## State Files

| File | What it stores |
|------|---------------|
| `position_monitor_state.json` | Alert cooldown records |
| `position_entries.json` | Open position entries |

State survives restarts. Delete these files to reset state.

## License

MIT — see [LICENSE](LICENSE).
