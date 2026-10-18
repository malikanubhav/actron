"""The investigation label rule (spec B, B5).

- conflict: any decision has J6 `restricts` >= the conflict threshold (0.8 by default);
- possible_conflict: any decision has `restricts` between the possible-conflict threshold (0.5) and the
  conflict threshold, or a seed's criticality percentile is >= 90 and no decision constrains the seeds;
- nothing_found: no seeds above the relevance threshold and no decisions;
- clear: everything else.
Thresholds come from settings (`CONFLICT_THRESHOLD`, `POSSIBLE_CONFLICT_THRESHOLD`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from actron.flow.findings import ConflictLabel, Label

CRITICAL_PERCENTILE = 90.0


@dataclass(frozen=True)
class Thresholds:
    conflict: float = 0.8
    possible: float = 0.5

    @classmethod
    def from_settings(cls) -> Thresholds:
        from actron.config import get_settings

        s = get_settings()
        return cls(conflict=s.CONFLICT_THRESHOLD, possible=s.POSSIBLE_CONFLICT_THRESHOLD)


def conflict_label(restricts: float, thresholds: Thresholds) -> ConflictLabel:
    if restricts >= thresholds.conflict:
        return "conflict"
    if restricts >= thresholds.possible:
        return "possible_conflict"
    return "none"


def compute_label(
    *,
    restricts: Sequence[float],
    seed_count: int,
    decision_count: int,
    max_seed_criticality: float | None,
    thresholds: Thresholds | None = None,
) -> Label:
    """Apply the B5 rule. `restricts` holds one J6 `restricts` probability per decision."""
    th = thresholds or Thresholds()
    if any(p >= th.conflict for p in restricts):
        return "conflict"
    if any(th.possible <= p < th.conflict for p in restricts):
        return "possible_conflict"
    if decision_count == 0 and max_seed_criticality is not None and max_seed_criticality >= CRITICAL_PERCENTILE:
        return "possible_conflict"
    if seed_count == 0 and decision_count == 0:
        return "nothing_found"
    return "clear"
