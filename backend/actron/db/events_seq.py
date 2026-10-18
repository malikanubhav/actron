"""Per-request event sequence numbers that are gap-free and strictly increasing (spec A, A-AC-9).

The counter lives in `requests.seq`. The requests row is locked with `SELECT ... FOR UPDATE`, so two
writers for the same request take turns. The number is only used once the caller's transaction commits:
if the caller rolls back, the counter rolls back with it, so no number is skipped.

Call it inside the same transaction that inserts the event row.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


class RequestNotFound(LookupError):
    """No requests row exists for the given id."""


_LOCK = text("SELECT seq FROM requests WHERE id = :rid FOR UPDATE")
_BUMP = text("UPDATE requests SET seq = :seq WHERE id = :rid")


def next_seq(session: Session, request_id: str) -> int:
    """Lock the request row, bump its counter and return the new number (1, 2, 3, ...)."""
    current = session.execute(_LOCK, {"rid": request_id}).scalar_one_or_none()
    if current is None:
        raise RequestNotFound(request_id)
    seq = int(current) + 1
    session.execute(_BUMP, {"rid": request_id, "seq": seq})
    return seq


async def next_seq_async(session: AsyncSession, request_id: str) -> int:
    """Same as `next_seq` for an async session."""
    current = (await session.execute(_LOCK, {"rid": request_id})).scalar_one_or_none()
    if current is None:
        raise RequestNotFound(request_id)
    seq = int(current) + 1
    await session.execute(_BUMP, {"rid": request_id, "seq": seq})
    return seq
