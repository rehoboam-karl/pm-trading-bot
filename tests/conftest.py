"""Add project root to sys.path so position_monitor can be imported."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
