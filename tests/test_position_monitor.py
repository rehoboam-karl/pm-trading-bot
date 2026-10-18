"""Tests for pm-trading-bot."""

import tempfile
import time
from pathlib import Path

import pytest

from position_monitor import (
    PositionState, PositionEntry, PositionStatus,
    compute_pnl, AlertRecord,
)


class TestComputePnL:
    def test_profit(self):
        entry = PositionEntry(
            token_id="t1", outcome="Yes", entry_price=0.45,
            size=100.0, cost=45.0, timestamp="2026-01-01T00:00:00Z",
        )
        pnl, pct = compute_pnl(entry, 0.60)
        assert pnl == 15.0
        assert pct == 33.3

    def test_loss(self):
        entry = PositionEntry(
            token_id="t1", outcome="Yes", entry_price=0.50,
            size=100.0, cost=50.0, timestamp="2026-01-01T00:00:00Z",
        )
        pnl, pct = compute_pnl(entry, 0.30)
        assert pnl == -20.0
        assert pct == -40.0

    def test_no_cost(self):
        entry = PositionEntry(
            token_id="t1", outcome="Yes", entry_price=0.0,
            size=0.0, cost=0.0, timestamp="2026-01-01T00:00:00Z",
        )
        pnl, pct = compute_pnl(entry, 0.50)
        assert pnl == 0.0
        assert pct == 0.0


class TestPositionState:
    def test_track_and_resolve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sf = Path(tmpdir) / "state.json"
            ef = Path(tmpdir) / "entries.json"
            state = PositionState(sf, ef)

            state.track_entry(
                token_id="t1", outcome="Yes",
                entry_price=0.45, size=100.0,
                timestamp="2026-01-01T00:00:00Z",
            )
            assert "t1" in state.entries

            state.mark_resolved("t1", PositionStatus.WON)
            assert "t1" not in state.entries  # removed after resolve

    def test_should_alert_first_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sf = Path(tmpdir) / "state.json"
            ef = Path(tmpdir) / "entries.json"
            state = PositionState(sf, ef)

            assert state.should_alert("t1", 0.50, 5.0, 0.45) is True

    def test_should_alert_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sf = Path(tmpdir) / "state.json"
            ef = Path(tmpdir) / "entries.json"
            state = PositionState(sf, ef)

            state.record_alert("t1", 0.50, 5.0, 0.45)
            assert state.should_alert("t1", 0.50, 5.0, 0.45) is False

    def test_should_alert_after_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sf = Path(tmpdir) / "state.json"
            ef = Path(tmpdir) / "entries.json"
            state = PositionState(sf, ef)

            # Manually age the alert record
            state.alerts["t1"] = AlertRecord(
                token_id="t1",
                timestamp=time.time() - 400,  # 400s ago > 300s cooldown
                current_price=0.50,
                pnl=5.0,
                entry_price=0.45,
            )
            assert state.should_alert("t1", 0.50, 5.0, 0.45) is True

    def test_no_alert_small_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sf = Path(tmpdir) / "state.json"
            ef = Path(tmpdir) / "entries.json"
            state = PositionState(sf, ef)

            state.record_alert("t1", 0.50, 5.0, 0.45)
            # Small price change (<5%), small PnL change (<$5)
            assert state.should_alert("t1", 0.51, 6.0, 0.45) is False
