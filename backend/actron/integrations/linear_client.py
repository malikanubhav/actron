"""Linear GraphQL client (spec A, A10): reads with paging, writes with deterministic ids, typed errors.

Personal API keys go in the `Authorization` header as they are (no `Bearer`). Every request names
its operation (`operationName`), which keeps logs readable and lets the test server route calls.
"""

from __future__ import annotations

import contextlib
import hashlib
import time
import uuid
from collections.abc import Mapping
from typing import Any

import httpx

from actron.config import get_settings
from actron.connectors.common import (
    DEFAULT_TIMEOUT,
    AuthError,
    ProviderError,
    RetryableProviderError,
    TransientError,
    parse_retry_after,
    transport_for,
    with_backoff,
)

PAGE = 50

ISSUE_FIELDS = """
  id identifier number title description priority estimate url branchName createdAt updatedAt completedAt
  canceledAt dueDate
  state { id name type } assignee { id } creator { id } team { id } project { id } parent { id }
  labels { nodes { id } }
  attachments { nodes { url title sourceType } }
  comments(first: 50) {
    nodes { id body url createdAt updatedAt editedAt user { id } parent { id } }
    pageInfo { hasNextPage endCursor }
  }
"""

Q_VIEWER = "query Viewer { viewer { id name displayName email organization { id name urlKey } } }"
Q_TEAMS = "query Teams($after: String) { teams(first: 50, after: $after) { nodes { id name key description createdAt updatedAt } pageInfo { hasNextPage endCursor } } }"
Q_USERS = "query Users($after: String) { users(first: 50, after: $after) { nodes { id name displayName email active admin avatarUrl lastSeen } pageInfo { hasNextPage endCursor } } }"
Q_STATES = "query States($team: ID!, $after: String) { workflowStates(first: 50, after: $after, filter: {team: {id: {eq: $team}}}) { nodes { id name type color position team { id } } pageInfo { hasNextPage endCursor } } }"
Q_LABELS = "query Labels($team: ID!, $after: String) { issueLabels(first: 50, after: $after, filter: {team: {id: {eq: $team}}}) { nodes { id name color team { id } parent { id } } pageInfo { hasNextPage endCursor } } }"
Q_PROJECTS = "query Projects($after: String) { projects(first: 50, after: $after) { nodes { id name description state lead { id } startDate targetDate createdAt updatedAt teams { nodes { id } } } pageInfo { hasNextPage endCursor } } }"
Q_ISSUES = (
    "query Issues($team: ID!, $since: DateTimeOrDuration!, $after: String) { "
    "issues(first: 50, after: $after, orderBy: updatedAt, filter: {team: {id: {eq: $team}}, updatedAt: {gt: $since}}) { "
    f"nodes {{ {ISSUE_FIELDS} }} pageInfo {{ hasNextPage endCursor }} }} }}"
)
Q_ISSUES_ALL_TEAMS = (
    "query IssuesAll($since: DateTimeOrDuration!, $after: String) { "
    "issues(first: 50, after: $after, orderBy: updatedAt, filter: {updatedAt: {gt: $since}}) { "
    f"nodes {{ {ISSUE_FIELDS} }} pageInfo {{ hasNextPage endCursor }} }} }}"
)
Q_COMMENTS = "query IssueComments($id: String!, $after: String) { issue(id: $id) { comments(first: 50, after: $after) { nodes { id body url createdAt updatedAt editedAt user { id } parent { id } } pageInfo { hasNextPage endCursor } } } }"
Q_ISSUE = f"query Issue($id: String!) {{ issue(id: $id) {{ {ISSUE_FIELDS} }} }}"
M_ISSUE_CREATE = "mutation IssueCreate($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier number url title description team { id } } } }"
M_ISSUE_UPDATE = "mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { id identifier url title description updatedAt } } }"
M_COMMENT_CREATE = "mutation CommentCreate($input: CommentCreateInput!) { commentCreate(input: $input) { success comment { id body url createdAt } } }"
Q_TEAM_ACCESS = "query TeamAccess($id: String!) { team(id: $id) { id name key } viewer { id guest } }"


def deterministic_issue_id(ws: str, request_id: str) -> str:
    """A UUID v4 formatted id derived from sha256(ws + request_id), so a retried create cannot duplicate."""
    raw = bytearray(hashlib.sha256(f"{ws}{request_id}".encode()).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


class LinearClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key
        headers = {"Content-Type": "application/json", "User-Agent": "actron"}
        if api_key:
            headers["Authorization"] = api_key
        self._url = base_url or get_settings().LINEAR_API_URL
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(timeout or get_settings().LINEAR_TIMEOUT_SECONDS or DEFAULT_TIMEOUT),
            transport=transport or transport_for("linear"),
        )
        self.requests_made = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> LinearClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def query(self, text: str, variables: Mapping[str, Any] | None = None) -> dict[str, Any]:
        operation = text.split("(", 1)[0].split("{", 1)[0].split()[-1]
        payload = {"query": text, "variables": dict(variables or {}), "operationName": operation}

        async def attempt() -> httpx.Response:
            self.requests_made += 1
            response = await self._client.post(self._url, json=payload)
            if response.status_code >= 500:
                raise TransientError(f"Linear answered {response.status_code}")
            return response

        response = await with_backoff(attempt)
        body: dict[str, Any] = {}
        with contextlib.suppress(ValueError):
            body = response.json()
        if response.status_code == 429:
            raise _rate_limited(response, "Linear rate limit")
        if response.status_code in (401, 403) and not body.get("errors"):
            raise AuthError("Linear rejected the API key", status=response.status_code)
        errors = body.get("errors") or []
        if errors:
            self._raise_for_errors(errors, response)
        if response.status_code >= 400:
            raise ProviderError(f"Linear answered {response.status_code}", status=response.status_code)
        data: dict[str, Any] = body.get("data") or {}
        return data

    @staticmethod
    def _raise_for_errors(errors: list[dict[str, Any]], response: httpx.Response) -> None:
        for err in errors:
            ext = err.get("extensions") or {}
            code = str(ext.get("code") or "")
            kind = str(ext.get("type") or "").lower()
            if code == "RATELIMITED" or "ratelimit" in kind:
                raise _rate_limited(response, str(err.get("message") or "Linear rate limit"))
        for err in errors:
            ext = err.get("extensions") or {}
            code = str(ext.get("code") or "")
            kind = str(ext.get("type") or "").lower()
            message = str(err.get("message") or "unknown error")
            if code in ("AUTHENTICATION_ERROR", "FORBIDDEN") or "authentication" in kind:
                raise AuthError(f"Linear refused the API key: {message}", code=code or kind)
        first = errors[0]
        path = ".".join(str(p) for p in first.get("path") or [])
        where = f" on {path}" if path else ""
        first_code = str((first.get("extensions") or {}).get("code") or "") or None
        raise ProviderError(f"Linear error{where}: {first.get('message')}", code=first_code)

    # Reads
    async def viewer(self) -> dict[str, Any]:
        data = await self.query(Q_VIEWER)
        viewer: dict[str, Any] = data["viewer"]
        return viewer

    async def connection(self, text: str, key: str, variables: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        """One page of a connection: (nodes, next cursor or None)."""
        data = await self.query(text, variables)
        conn = data[key]
        info = conn.get("pageInfo") or {}
        return list(conn.get("nodes") or []), (info.get("endCursor") if info.get("hasNextPage") else None)

    async def all_comments(self, issue_id: str, after: str | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor = after
        while cursor:
            data = await self.query(Q_COMMENTS, {"id": issue_id, "after": cursor})
            conn = (data.get("issue") or {}).get("comments") or {}
            out.extend(conn.get("nodes") or [])
            info = conn.get("pageInfo") or {}
            cursor = info.get("endCursor") if info.get("hasNextPage") else None
        return out

    async def issue(self, issue_id: str) -> dict[str, Any] | None:
        data = await self.query(Q_ISSUE, {"id": issue_id})
        found: dict[str, Any] | None = data.get("issue")
        return found

    # Writes (used by the request flow)
    async def issue_create(self, *, issue_id: str, team_id: str, title: str, description: str,
                           priority: int | None = None, label_ids: list[str] | None = None,
                           assignee_id: str | None = None) -> dict[str, Any]:
        """Create an issue with a caller-chosen id. If that id already exists the existing issue is returned."""
        payload: dict[str, Any] = {"id": issue_id, "teamId": team_id, "title": title, "description": description}
        if priority is not None:
            payload["priority"] = priority
        if label_ids:
            payload["labelIds"] = label_ids
        if assignee_id:
            payload["assigneeId"] = assignee_id
        try:
            data = await self.query(M_ISSUE_CREATE, {"input": payload})
        except RetryableProviderError:
            raise
        except ProviderError:
            existing = await self.issue(issue_id)  # a retry after a lost answer: the first call may have worked
            if existing is not None:
                return existing
            raise
        result = data["issueCreate"]
        if not result.get("success"):
            raise ProviderError("Linear did not create the issue", code="issue_create_failed")
        created: dict[str, Any] = result["issue"]
        return created

    async def issue_update(self, issue_id: str, *, title: str | None = None,
                           description: str | None = None) -> dict[str, Any]:
        payload = {k: v for k, v in {"title": title, "description": description}.items() if v is not None}
        data = await self.query(M_ISSUE_UPDATE, {"id": issue_id, "input": payload})
        result = data["issueUpdate"]
        if not result.get("success"):
            raise ProviderError("Linear did not update the issue", code="issue_update_failed")
        updated: dict[str, Any] = result["issue"]
        return updated

    async def comment_create(self, issue_id: str, body: str) -> dict[str, Any]:
        data = await self.query(M_COMMENT_CREATE, {"input": {"issueId": issue_id, "body": body}})
        result = data["commentCreate"]
        if not result.get("success"):
            raise ProviderError("Linear did not create the comment", code="comment_create_failed")
        comment: dict[str, Any] = result["comment"]
        return comment


def _rate_limited(response: httpx.Response, message: str) -> RetryableProviderError:
    delay = parse_retry_after(response.headers.get("retry-after"))
    if delay is None:
        reset = response.headers.get("x-ratelimit-requests-reset") or response.headers.get("x-ratelimit-reset")
        if reset and reset.isdigit():
            value = float(reset)
            delay = max(1.0, (value / 1000.0 if value > 1e11 else value) - time.time())
    return RetryableProviderError(f"{message}; retry after {delay or 60:.0f} s", retry_after=delay or 60.0,
                                  status=response.status_code, code="RATELIMITED")
