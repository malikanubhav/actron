# ruff: noqa: F403
"""A-AC-49 (live, no token needed): five recent Calva PRs with reviews and comments."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from actron.connectors import github
from actron.connectors.common import Batch
from actron.graph import ids
from actron.integrations.github_client import GithubClient
from tests.fakes.support import *

pytestmark = pytest.mark.live
REPO = "BetterThanTomorrow/calva"


async def test_a_ac_49_pull_five_recent_calva_prs_with_review_comments(ws: str, store: Any) -> None:
    """A-AC-49: public API, five recent PRs, at least one GithubReviewComment is produced and stored."""
    token = os.environ.get("GITHUB_TOKEN") or None  # optional; the public limit is enough for this test
    repo = REPO.lower()
    async with GithubClient(token) as client:
        repo_json = await client.repository(REPO)
        page = await client.page(f"/repos/{REPO}/pulls", {"state": "all", "sort": "updated", "direction": "desc",
                                                         "per_page": 30})
        batch = Batch(step="pulls")
        github.map_repo(batch, repo, repo_json, is_ingested=True)
        recent = page.data[:5]
        for item in recent:
            github.map_pull(batch, repo, repo_json["id"], item, None)
            reviews = await client.get_json(f"/repos/{REPO}/pulls/{item['number']}/reviews", {"per_page": 100})
            github.map_reviews(batch, repo, item["number"], reviews)
            comments = await client.get_json(f"/repos/{REPO}/pulls/{item['number']}/comments", {"per_page": 100})
            github.map_review_comments(batch, repo, comments, repo)
        # recent review comments repo-wide: real discussion even when the newest PRs have none
        wide = await client.get_json(f"/repos/{REPO}/pulls/comments",
                                     {"sort": "updated", "direction": "desc", "per_page": 20})
        github.map_review_comments(batch, repo, wide, repo)
        taken = len(recent)
        assert client.requests_made < 60
    assert taken >= 5
    result = await asyncio.to_thread(github.write_batch, ws, "pulls", batch)
    assert result.counts.get("GithubPullRequest", 0) >= 5
    assert store.count("GithubReviewComment") >= 1
    sample = store.query("MATCH (c:GithubReviewComment) RETURN c.id AS id, c.path AS path, c.body AS body LIMIT 1",
                         read_only=True)[0]
    assert sample["id"].startswith("github:reviewcomment:") and sample["path"] and sample["body"]
    assert ids.label_of(sample["id"]) == "GithubReviewComment"
