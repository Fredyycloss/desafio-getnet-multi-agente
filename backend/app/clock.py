"""'Today' for the synthetic demo data. DEMO_TODAY=YYYY-MM-DD freezes it (replay of a recorded run
on a later day: the fixtures, the 'yesterday' queries and the Critic's today_utc then match the
recording). Unset: the real date."""
from __future__ import annotations

import os
from datetime import date


def today() -> date:
    value = os.getenv("DEMO_TODAY", "").strip()
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return date.today()
