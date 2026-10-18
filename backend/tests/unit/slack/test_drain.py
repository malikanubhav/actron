"""slack_bot.drain(): waits for handed-off work and returns, even when tasks finish before their done callbacks
run (B-AC-51: handlers ack first and work after; tests and shutdown drain that work)."""

from __future__ import annotations

import asyncio

from actron.integrations import slack_bot


async def test_drain_returns_when_tasks_are_done_but_not_yet_removed() -> None:
    async def quick() -> None:
        return None

    task = asyncio.get_running_loop().create_task(quick())
    slack_bot._TASKS.add(task)
    await asyncio.wait([task])  # done, while a callback that would discard it may still be queued
    slack_bot._TASKS.add(task)  # the state the old busy loop never left
    await asyncio.wait_for(slack_bot.drain(), timeout=2)
    assert task not in slack_bot._TASKS


async def test_drain_waits_for_work_spawned_by_work() -> None:
    seen: list[str] = []

    async def second() -> None:
        await asyncio.sleep(0.01)
        seen.append("second")

    async def first() -> None:
        await asyncio.sleep(0.01)
        seen.append("first")
        slack_bot.spawn(second())

    slack_bot.spawn(first())
    await asyncio.wait_for(slack_bot.drain(), timeout=2)
    assert seen == ["first", "second"] and not slack_bot._TASKS
