"""Small live provider adapters; fixtures use the same source-fetch boundary."""

import base64
import json
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .contracts import Payload, Rejected, Unavailable, UnknownOutcome, canonical, digest


def http_json(
    url: str,
    token: str = "",
    body: Payload | None = None,
    *,
    method: str | None = None,
    timeout: float = 30,
) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "actron-poc"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = canonical(body).encode() if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise Unavailable(f"provider request failed: {type(exc).__name__}") from exc


class FileSources:
    def __init__(self, path: str | Path, page_size: int = 100) -> None:
        self.path = Path(path)
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.page_size = page_size

    def fetch(self, cursor: str | None = None) -> Payload:
        data = json.loads(self.path.read_text())
        records = data if isinstance(data, list) else data["records"]
        offset = int(cursor or "0")
        end = offset + self.page_size
        return {
            "records": records[offset:end],
            "cursor": str(end) if end < len(records) else None,
            "complete": end >= len(records),
            "gaps": [] if isinstance(data, list) else data.get("gaps", []),
        }


FileSource = FileSources


class SlackSources:
    """Read one dedicated thread, including edit timestamps, with explicit mapping.

    `mapping` maps stable message ts to curated project/behavior/claim metadata.
    No approval is extracted from message text or Slack display names.
    """

    def __init__(
        self,
        token: str,
        channel: str,
        thread: str,
        mapping: Payload,
        endpoint: str = "https://slack.com/api",
    ) -> None:
        self.token, self.channel, self.thread = token, channel, thread
        self.mapping, self.endpoint = mapping, endpoint.rstrip("/")

    def fetch(self, cursor: str | None = None) -> Payload:
        params = {"channel": self.channel, "ts": self.thread, "limit": "100"}
        if cursor:
            params["cursor"] = cursor
        response = http_json(
            f"{self.endpoint}/conversations.replies?{urlencode(params)}", self.token
        )
        if not response.get("ok"):
            raise Unavailable(f"Slack thread unavailable: {response.get('error', 'unknown')}")
        records = []
        for message in response.get("messages", []):
            ts = message["ts"]
            metadata = self.mapping.get(ts, {})
            if not metadata:
                continue
            revision = str(message.get("edited", {}).get("ts", ts))
            records.append(
                {
                    **metadata,
                    "id": f"{self.channel}:{ts}",
                    "provider": "slack",
                    "revision": revision,
                    "content": message.get("text", ""),
                    "timestamp": ts,
                    "locator": f"slack://channel/{self.channel}/thread/{self.thread}/message/{ts}",
                    "availability": "available",
                    "thread": self.thread,
                    "author": message.get("user"),
                }
            )
        next_cursor = response.get("response_metadata", {}).get("next_cursor") or None
        return {
            "records": records,
            "cursor": next_cursor,
            "complete": next_cursor is None,
            "gaps": [
                "Slack coverage: one configured thread; message deletion requires an explicit tombstone source event"
            ],
        }


class LinearSources:
    def __init__(
        self,
        token: str,
        issue_ids: list[str],
        mapping: Payload,
        endpoint: str = "https://api.linear.app/graphql",
    ) -> None:
        self.token, self.issue_ids, self.mapping, self.endpoint = (
            token,
            issue_ids,
            mapping,
            endpoint,
        )

    def fetch(self, cursor: str | None = None) -> Payload:
        index = int(cursor or "0")
        if index >= len(self.issue_ids):
            return {"records": [], "cursor": None, "complete": True}
        issue_id = self.issue_ids[index]
        response = _linear(
            self.endpoint,
            self.token,
            "query($id:String!){issue(id:$id){id identifier title description updatedAt url}}",
            {"id": issue_id},
        )
        issue = response.get("issue")
        if not issue:
            raise Unavailable(
                "Linear issue unavailable; emit explicit tombstone only after access loss is confirmed"
            )
        record = {
            **self.mapping.get(issue_id, {}),
            "id": issue["id"],
            "provider": "linear",
            "revision": issue["updatedAt"],
            "content": f"{issue['title']}\n{issue.get('description') or ''}",
            "locator": issue["url"],
            "timestamp": issue["updatedAt"],
            "availability": "available",
        }
        more = index + 1 < len(self.issue_ids)
        return {
            "records": [record],
            "cursor": str(index + 1) if more else None,
            "complete": not more,
            "gaps": [
                "Linear coverage: configured issues and observed revisions; pre-import revision history is not exhaustive"
            ],
        }


def _linear(endpoint: str, token: str, query: str, variables: Payload) -> Payload:
    # Linear personal API keys use the raw Authorization value.
    request = Request(
        endpoint,
        data=canonical({"query": query, "variables": variables}).encode(),
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise Unavailable(f"Linear request failed: {type(exc).__name__}") from exc
    if result.get("errors"):
        raise Unavailable("Linear GraphQL errors")
    return dict(result.get("data") or {})


class LinearTickets:
    """Write exact canonical scope in a dedicated issue description.

    Deterministic issue UUIDs reconcile a timed-out create by reading that UUID.
    Any edit to the managed description invalidates scope approval on `read`.
    """

    def __init__(
        self, token: str, team_id: str, endpoint: str = "https://api.linear.app/graphql"
    ) -> None:
        self.token, self.team_id, self.endpoint = token, team_id, endpoint

    def _id(self, operation: str) -> str:
        # Linear requires UUID-v4 format, including for caller-supplied IDs.
        # Deterministic operation entropy preserves reconciliation after restart.
        raw = bytes.fromhex(digest(["actron", self.team_id, operation])[:32])
        return str(uuid.UUID(bytes=raw, version=4))

    def _description(self, operation: str, scope: Payload) -> str:
        return f"Actron operation: {operation}\nScope SHA256: {digest(scope)}\n```json\n{canonical(scope)}\n```"

    def _result(self, issue: Payload) -> Payload:
        text = issue.get("description") or ""
        try:
            scope = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
            operation = text.splitlines()[0].removeprefix("Actron operation: ")
            if text != self._description(operation, scope):
                scope = {**scope, "external_edit": digest(text)}
        except (ValueError, IndexError, TypeError):
            scope = {"external_edit": digest(text)}
        # A changed title is also an external scope edit.
        if issue.get("title") != str(scope.get("objective", "Actron approved change"))[:200]:
            scope = {**scope, "external_title": issue.get("title")}
        return {
            "id": issue["id"],
            "url": issue.get("url", ""),
            "scope": scope,
            "hash": digest(scope),
            "description": text,
        }

    def create(self, operation: str, scope: Payload) -> Payload:
        issue_id = self._id(operation)
        try:
            data = _linear(
                self.endpoint,
                self.token,
                "mutation($input:IssueCreateInput!){issueCreate(input:$input){success issue{id title description url}}}",
                {
                    "input": {
                        "id": issue_id,
                        "teamId": self.team_id,
                        "title": str(scope.get("objective", "Actron approved change"))[:200],
                        "description": self._description(operation, scope),
                    }
                },
            )
            payload = data.get("issueCreate", {})
            if not payload.get("success") or not payload.get("issue"):
                raise UnknownOutcome("Linear creation unconfirmed; reconcile operation UUID")
            return self._result(payload["issue"])
        except Unavailable as exc:
            raise UnknownOutcome(
                "Linear creation outcome unknown; reconcile operation UUID"
            ) from exc

    def find(self, operation: str) -> Payload | None:
        # A null issue is confirmed absence; transport errors are never absence.
        data = _linear(
            self.endpoint,
            self.token,
            "query($id:ID!){issues(filter:{id:{eq:$id}},first:1){nodes{id title description url}}}",
            {"id": self._id(operation)},
        )
        issues = data.get("issues", {}).get("nodes", [])
        issue = issues[0] if issues else None
        return self._result(issue) if issue else None

    def read(self, issue: str) -> Payload:
        data = _linear(
            self.endpoint,
            self.token,
            "query($id:String!){issue(id:$id){id title description url}}",
            {"id": issue},
        )
        if not data.get("issue"):
            raise Unavailable("Linear ticket unavailable")
        return self._result(data["issue"])

    def update(self, issue: str, scope: Payload) -> Payload:
        current = self.read(issue)
        description = current["description"]
        operation = description.splitlines()[0].removeprefix("Actron operation: ")
        try:
            data = _linear(
                self.endpoint,
                self.token,
                "mutation($id:String!,$input:IssueUpdateInput!){issueUpdate(id:$id,input:$input){success issue{id title description url}}}",
                {
                    "id": issue,
                    "input": {
                        "title": str(scope.get("objective", "Actron approved change"))[:200],
                        "description": self._description(operation, scope),
                    },
                },
            )
            payload = data.get("issueUpdate", {})
            if not payload.get("success") or not payload.get("issue"):
                raise UnknownOutcome("Linear update unconfirmed; read ticket before retry")
            return self._result(payload["issue"])
        except Unavailable as exc:
            raise UnknownOutcome("Linear update outcome unknown; read ticket before retry") from exc


class GitHubSources:
    """Read a coherent GitHub commit and bounded, explicitly mapped artifacts."""

    def __init__(
        self,
        token: str,
        repo: str,
        ref: str,
        project: str,
        mapping: Payload,
        endpoint: str = "https://api.github.com",
    ) -> None:
        if len(repo.split("/")) != 2 or any(part in ("", ".", "..") for part in repo.split("/")):
            raise ValueError("GitHub repo must be owner/name")
        self.token, self.repo, self.ref, self.project, self.mapping = (
            token,
            repo,
            ref,
            project,
            mapping,
        )
        self.endpoint = f"{endpoint.rstrip('/')}/repos/{repo}"

    def fetch(self, cursor: str | None = None) -> Payload:
        from urllib.parse import quote

        commit = http_json(f"{self.endpoint}/commits/{quote(self.ref, safe='')}", self.token)
        sha = commit["sha"]
        tree = http_json(
            f"{self.endpoint}/git/trees/{commit['commit']['tree']['sha']}?recursive=1", self.token
        )
        entries = {item["path"]: item for item in tree.get("tree", []) if item["type"] == "blob"}
        paths = self.mapping.get("paths", sorted(entries))
        if len(paths) > 200:
            raise Rejected("GitHub import exceeds 200 configured files; narrow paths")
        records: list[Payload] = []
        for path in paths:
            entry = entries.get(path)
            if not entry:
                raise Unavailable(f"configured GitHub path absent at commit: {path}")
            if entry.get("size", 0) > 1_000_000:
                raise Rejected("GitHub artifact exceeds one megabyte import bound")
            blob = http_json(f"{self.endpoint}/git/blobs/{entry['sha']}", self.token)
            try:
                content = base64.b64decode(blob["content"]).decode("utf-8")
            except (UnicodeError, ValueError) as exc:
                raise Rejected(f"GitHub artifact is not UTF-8 text: {path}") from exc
            records.append(
                {
                    "id": f"{self.repo}:{path}",
                    "provider": "github",
                    "revision": sha,
                    "project": self.project,
                    "content": content,
                    "timestamp": commit["commit"]["committer"]["date"],
                    "locator": f"https://github.com/{self.repo}/blob/{sha}/{path}",
                    "path": path,
                    "repo": self.repo,
                    "commit": sha,
                    "availability": "available",
                }
            )
        gaps = [
            "Static mapping is curated; dynamic calls and unconfigured files are not complete dependency coverage"
        ]
        if tree.get("truncated"):
            gaps.append("GitHub recursive tree was truncated; import coverage is partial")
        snapshot = {
            "repo": self.repo,
            "commit": sha,
            "components": self.mapping.get("components", []),
            "checks": self.mapping.get("checks", []),
            "gaps": gaps,
        }
        records.append(
            {
                "id": f"{self.repo}:snapshot",
                "provider": "github",
                "revision": sha,
                "project": self.project,
                "content": commit.get("commit", {}).get("message", ""),
                "timestamp": commit["commit"]["committer"]["date"],
                "locator": commit.get("html_url", f"https://github.com/{self.repo}/commit/{sha}"),
                "availability": "available",
                "snapshot": snapshot,
            }
        )
        for number in self.mapping.get("history_prs", []):
            pr = http_json(f"{self.endpoint}/pulls/{int(number)}", self.token)
            reviews = http_json(f"{self.endpoint}/pulls/{int(number)}/reviews", self.token)
            records.append(
                {
                    "id": f"{self.repo}:pr:{number}",
                    "provider": "github",
                    "revision": pr["updated_at"],
                    "project": self.project,
                    "content": canonical({"pr": pr, "reviews": reviews}),
                    "timestamp": pr["updated_at"],
                    "locator": pr["html_url"],
                    "availability": "available",
                }
            )
        return {"records": records, "cursor": None, "complete": True, "gaps": gaps}
