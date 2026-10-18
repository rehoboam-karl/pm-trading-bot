# pm-trading-bot

> Reference implementation for a Polymarket copy-trading bot in Python.

`pm-trading-bot` is the orchestration layer: it tracks positions, computes P&L,
sends Telegram alerts, and coordinates with the scoring and execution layers.

**What it does:**
- Tracks open positions with entry price, size, and timestamp
- Computes unrealized P&L in real-time using CLOB book prices
- Sends Telegram alerts on position changes (won/lost/open P&L updates)
- Cooldown-aware alerting (no spam)
- Persists state to disk (survives restarts)
- Daemon mode for continuous monitoring

**Architecture:**

```
pm-trading-bot/
├── position_monitor.py    ← Position tracking + P&L + Telegram alerts
├── whale_pnl_tracker.py   ← Per-whale P&L attribution
└── entry_scorer_server.py ← Async HTTP scorer (uvloop + aiohttp)
```

**Combine with:**
- [`pm-whale-scout`](https://github.com/rehoboam-karl/pm-whale-scout) — whale discovery
- [`pm-core`](https://github.com/rehoboam-karl/pm-core) — Rust risk/market engine

---

## Quick Start

```bash
pip install requests python-dotenv
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export OUTPUT_DIR="./data"

python position_monitor.py
```

Daemon mode:

```bash
python position_monitor.py --continuous --interval 60
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Destination chat ID |
| `OUTPUT_DIR` | `./data` | Where to store state files |
| `ALERT_COOLDOWN_SECONDS` | 300 | Min seconds between alerts per token |

## Position Entry Tracking

You can inject entries from your trading engine:

```python
from position_monitor import PositionState, STATE_FILE, ENTRY_TRACKER_FILE

state = PositionState(STATE_FILE, ENTRY_TRACKER_FILE)
state.track_entry(
    token_id="0x1234...",
    outcome="Yes",
    entry_price=0.45,
    size=100.0,
    timestamp=datetime.utcnow().isoformat() + "Z",
)
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Your Trading Engine                │
│   (copies whale trades based on scoring signals)    │
└──────────────────────┬──────────────────────────────┘
                       │ track_entry()
                       ▼
┌─────────────────────────────────────────────────────┐
│              position_monitor.py                     │
│  • Tracks open positions + entry prices             │
│  • Checks CLOB for current prices every N seconds    │
│  • Computes P&L (unrealized)                        │
│  • Sends Telegram alerts on significant changes     │
└─────────────────────────────────────────────────────┘
```

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

## License

MIT — see [LICENSE](LICENSE).
