"""Freshness gate reads the branch head without spending the public GitHub API limit (B2)."""

from __future__ import annotations

from typing import Any

import pytest

from actron.activities import request as act


async def test_no_token_uses_ls_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    """B-AC-77: without a token the gate uses `git ls-remote` on the public URL, never the rate-limited API."""
    calls: list[tuple[str, str]] = []

    def fake_ls_remote(url: str, branch: str) -> str:
        calls.append((url, branch))
        return "a" * 40

    def no_client(cfg: dict[str, Any]) -> Any:
        raise AssertionError("the GitHub API must not be called without a token")

    monkeypatch.setattr(act, "_ls_remote", fake_ls_remote)
    monkeypatch.setattr(act, "_github_client", no_client)
    head = await act.remote_head("dev", "published", {"repository": "BetterThanTomorrow/calva", "token": None})
    assert head == "a" * 40
    assert calls == [("https://github.com/BetterThanTomorrow/calva.git", "published")]


async def test_token_uses_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """B-AC-77: with a token the gate asks the GitHub API (private repositories work)."""

    class Client:
        async def commit(self, repo: str, ref: str) -> dict[str, Any]:
            assert (repo, ref) == ("me/calva", "heads/dev")
            return {"sha": "b" * 40}

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(act, "_github_client", lambda cfg: Client())
    head = await act.remote_head("dev", "dev", {"repository": "me/calva", "token": "x" * 20})
    assert head == "b" * 40
