#!/usr/bin/env python3
"""
Position Monitor — tracks open positions, computes P&L, emits Telegram alerts.

Reference implementation for a Polymarket copy-trading bot.
Shows: position tracking, entry/exit logic, P&L computation, Telegram alerts.

Usage:
    python3 position_monitor.py                 # Run once
    python3 position_monitor.py --continuous   # Run as daemon

Environment:
    TELEGRAM_BOT_TOKEN   Telegram bot token
    TELEGRAM_CHAT_ID     Telegram chat ID
    OUTPUT_DIR           Where to write state files (default: ./data)
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# ─── Config ──────────────────────────────────────────────────────────────────

load_dotenv()  # loads TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID from .env

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./data"))
STATE_FILE = OUTPUT_DIR / "position_monitor_state.json"
LOG_FILE = OUTPUT_DIR / "position_monitor.log"
ENTRY_TRACKER_FILE = OUTPUT_DIR / "position_entries.json"

ALERT_COOLDOWN_SECONDS = 300  # 5 min between alerts for same token
POSITION_CHECK_INTERVAL = 60   # seconds between checks (daemon mode)


# ─── Domain Models ─────────────────────────────────────────────────────────────

class PositionStatus(str, Enum):
    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"


@dataclass
class PositionEntry:
    token_id: str
    outcome: str
    entry_price: float
    size: float          # number of shares
    cost: float         # cost = size * entry_price
    timestamp: str      # ISO 8601
    status: PositionStatus = PositionStatus.OPEN


@dataclass
class AlertRecord:
    token_id: str
    timestamp: float     # Unix timestamp of last alert
    entry_price: float
    current_price: float
    pnl: float


# ─── State ────────────────────────────────────────────────────────────────────

class PositionState:
    """
    Tracks open positions and entry records.
    Persists to disk so state survives restarts.
    """

    def __init__(self, state_file: Path, entry_file: Path):
        self.state_file = state_file
        self.entry_file = entry_file
        self.entries: dict[str, PositionEntry] = {}
        self.alerts: dict[str, AlertRecord] = {}
        self._load()

    def _load(self):
        if self.state_file.exists():
            raw = json.loads(self.state_file.read_text())
            self.alerts = {
                k: AlertRecord(**v) for k, v in raw.get("alerts", {}).items()
            }
        if self.entry_file.exists():
            raw = json.loads(self.entry_file.read_text())
            self.entries = {
                k: PositionEntry(**v) for k, v in raw.get("entries", {}).items()
            }

    def save(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({
            "alerts": {k: asdict(v) for k, v in self.alerts.items()},
        }, indent=2))
        self.entry_file.write_text(json.dumps({
            "entries": {k: asdict(v) for k, v in self.entries.items()},
        }, indent=2))

    # ─── Entry tracking ───────────────────────────────────────────────────────

    def track_entry(self, token_id: str, outcome: str, entry_price: float,
                    size: float, timestamp: str):
        """Record a new position entry."""
        self.entries[token_id] = PositionEntry(
            token_id=token_id,
            outcome=outcome,
            entry_price=entry_price,
            size=size,
            cost=size * entry_price,
            timestamp=timestamp,
        )
        self.save()

    def mark_resolved(self, token_id: str, status: PositionStatus):
        """Mark a position as resolved (won or lost). Removes from open entries."""
        if token_id in self.entries:
            self.entries[token_id].status = status
            del self.entries[token_id]
            self.save()

    # ─── Alerts ──────────────────────────────────────────────────────────────

    def should_alert(self, token_id: str, current_price: float, pnl: float,
                     entry_price: float) -> bool:
        """True if we should send a Telegram alert for this token (cooldown-aware)."""
        now = time.time()
        record = self.alerts.get(token_id)

        if record is None:
            return True

        if now - record.timestamp < ALERT_COOLDOWN_SECONDS:
            return False  # Still in cooldown

        # Price changed enough to warrant re-alert?
        price_delta_pct = abs(current_price - record.current_price) / (record.current_price + 1e-9)
        if price_delta_pct < 0.05 and abs(pnl - record.pnl) < 5.0:
            return False  # Not enough change

        return True

    def record_alert(self, token_id: str, current_price: float, pnl: float,
                     entry_price: float):
        """Record that we sent an alert for this token."""
        self.alerts[token_id] = AlertRecord(
            token_id=token_id,
            timestamp=time.time(),
            entry_price=entry_price,
            current_price=current_price,
            pnl=pnl,
        )
        self.save()


# ─── PnL ─────────────────────────────────────────────────────────────────────

def compute_pnl(entry: PositionEntry, current_price: float) -> tuple[float, float]:
    """
    Compute unrealized P&L for a position.

    Returns (pnl_dollars, pnl_pct) given current price.
    """
    current_value = entry.size * current_price
    pnl = current_value - entry.cost
    pnl_pct = (pnl / entry.cost * 100) if entry.cost > 0 else 0.0
    return round(pnl, 2), round(pnl_pct, 2)


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(text: str) -> bool:
    """Send a message via Telegram. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
        return True
    except Exception:
        return False


def format_position_alert(token_id: str, entry: PositionEntry,
                          current_price: float, pnl: float, pnl_pct: float) -> str:
    """Format a Telegram alert for a position update."""
    emoji = "🟢" if pnl >= 0 else "🔴"
    lines = [
        f"{emoji} <b>Position Update</b>",
        f"Token: <code>{token_id[:20]}...</code>",
        f"Status: {entry.status.value}",
        f"Entry: ${entry.entry_price:.4f}",
        f"Current: ${current_price:.4f}",
        f"P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)",
        f"Size: {entry.size:.2f} shares",
        f"Held: {time_since(entry.timestamp)}",
    ]
    return "\n".join(lines)


def time_since(iso_timestamp: str) -> str:
    """Human-readable time since a UTC ISO timestamp."""
    try:
        then = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - then
        h = int(delta.total_seconds() // 3600)
        m = int((delta.total_seconds() % 3600) // 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"
    except Exception:
        return "?"


# ─── Market Data ──────────────────────────────────────────────────────────────

def get_current_price(token_id: str) -> Optional[float]:
    """
    Fetch current best ask price from Polymarket CLOB.
    Returns None on failure.
    """
    try:
        r = requests.get(
            f"https://clob.polymarket.com/book?token_id={token_id}",
            timeout=5,
        )
        if r.status_code != 200:
            return None
        book = r.json()
        # Best ask
        asks = book.get("asks", [])
        if asks:
            return float(asks[0][0])  # [price, size]
        return None
    except Exception:
        return None


# ─── Core Loop ────────────────────────────────────────────────────────────────

def check_positions(state: PositionState) -> int:
    """
    Check all open positions, send alerts for significant changes.
    Returns number of alerts sent.
    """
    alerts_sent = 0

    for token_id, entry in list(state.entries.items()):
        current_price = get_current_price(token_id)
        if current_price is None:
            continue

        pnl, pnl_pct = compute_pnl(entry, current_price)

        # Check if resolved
        if current_price >= 0.95:
            state.mark_resolved(token_id, PositionStatus.WON)
            send_telegram(format_position_alert(
                token_id, entry, current_price, pnl, pnl_pct))
            alerts_sent += 1
            continue

        if current_price <= 0.02 and entry.cost > 0:
            state.mark_resolved(token_id, PositionStatus.LOST)
            send_telegram(format_position_alert(
                token_id, entry, current_price, pnl, pnl_pct))
            alerts_sent += 1
            continue

        # Open position — check if we should alert
        if state.should_alert(token_id, current_price, pnl, entry.entry_price):
            state.record_alert(token_id, current_price, pnl, entry.entry_price)
            send_telegram(format_position_alert(
                token_id, entry, current_price, pnl, pnl_pct))
            alerts_sent += 1

    return alerts_sent


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Polymarket Position Monitor")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=POSITION_CHECK_INTERVAL,
                        help="Seconds between checks (daemon mode)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    state = PositionState(STATE_FILE, ENTRY_TRACKER_FILE)
    print(f"Loaded {len(state.entries)} open positions")

    if args.continuous:
        print(f"Running continuously (every {args.interval}s). Ctrl+C to stop.")
        while True:
            n = check_positions(state)
            if n:
                print(f"Sent {n} alert(s)")
            time.sleep(args.interval)
    else:
        n = check_positions(state)
        print(f"Done. Checked {len(state.entries)} positions, sent {n} alert(s).")


if __name__ == "__main__":
    main()
