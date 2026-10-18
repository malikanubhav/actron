"""A small fake Linear GraphQL server (ASGI) for contract and integration tests (spec A, A10).

Routing is by `operationName`. It pages connections with opaque offset cursors, filters issues by team and
`updatedAt`, enforces unique issue ids on `issueCreate` (a duplicate id is an error, as in Linear), and can
inject rate limits and errors. All data is synthetic and in memory.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

BASE = "http://fake.linear/graphql"


@dataclass
class Injected:
    operation: str
    status: int
    body: dict[str, Any]
    headers: dict[str, str]
    times: int = 1


class FakeLinear:
    def __init__(self, api_key: str = "lin_api_test") -> None:
        self.api_key = api_key
        self.teams: list[dict[str, Any]] = []
        self.users: list[dict[str, Any]] = []
        self.states: dict[str, list[dict[str, Any]]] = {}
        self.labels: dict[str, list[dict[str, Any]]] = {}
        self.projects: list[dict[str, Any]] = []
        self.issues: dict[str, dict[str, Any]] = {}
        self.comments: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self.injected: list[Injected] = []
        self.created_ids: list[str] = []
        self.lose_next_create_answer = False
        self.viewer_is_guest = False
        self._seq = 100
        self.page_size = 50
        self.app = Starlette(routes=[Route("/graphql", self._handle, methods=["POST"])])

    def transport(self) -> httpx.ASGITransport:
        return httpx.ASGITransport(app=self.app)

    # Data builders
    def add_team(self, tid: str, key: str, name: str) -> None:
        self.teams.append({"id": tid, "name": name, "key": key, "description": f"{name} team",
                           "createdAt": "2025-01-01T00:00:00.000Z", "updatedAt": "2025-01-01T00:00:00.000Z"})
        self.states.setdefault(tid, [])
        self.labels.setdefault(tid, [])

    def add_user(self, uid: str, name: str, email: str, *, display: str | None = None) -> None:
        self.users.append({"id": uid, "name": name, "displayName": display or name.split()[0].lower(),
                           "email": email, "active": True, "admin": False, "avatarUrl": None,
                           "lastSeen": "2026-03-01T00:00:00.000Z"})

    def add_state(self, team: str, sid: str, name: str, type_: str, position: float = 0.0) -> None:
        self.states[team].append({"id": sid, "name": name, "type": type_, "color": "#999", "position": position,
                                  "team": {"id": team}})

    def add_label(self, team: str, lid: str, name: str, parent: str | None = None) -> None:
        self.labels[team].append({"id": lid, "name": name, "color": "#f00", "team": {"id": team},
                                  "parent": {"id": parent} if parent else None})

    def add_project(self, pid: str, name: str, team: str, lead: str | None = None) -> None:
        self.projects.append({"id": pid, "name": name, "description": f"{name} project", "state": "started",
                              "lead": {"id": lead} if lead else None, "startDate": "2026-01-01",
                              "targetDate": "2026-06-01", "createdAt": "2026-01-01T00:00:00.000Z",
                              "updatedAt": "2026-02-01T00:00:00.000Z", "teams": {"nodes": [{"id": team}]}})

    def add_issue(self, iid: str, team: str, number: int, key: str, title: str, *, updated_at: str,
                  description: str = "", state: str | None = None, assignee: str | None = None,
                  creator: str | None = None, project: str | None = None, parent: str | None = None,
                  labels: list[str] | None = None, branch: str | None = None,
                  attachments: list[dict[str, str]] | None = None, comments: list[dict[str, Any]] | None = None
                  ) -> dict[str, Any]:
        st = next((s for s in self.states.get(team, []) if s["id"] == state), None)
        issue = {
            "id": iid, "identifier": f"{key}-{number}", "number": number, "title": title,
            "description": description, "priority": 2, "estimate": None,
            "url": f"https://linear.app/acme/issue/{key}-{number}", "branchName": branch or f"{key.lower()}-{number}",
            "createdAt": "2026-01-10T00:00:00.000Z", "updatedAt": updated_at, "completedAt": None,
            "canceledAt": None, "dueDate": None,
            "state": {"id": st["id"], "name": st["name"], "type": st["type"]} if st else None,
            "assignee": {"id": assignee} if assignee else None, "creator": {"id": creator} if creator else None,
            "team": {"id": team}, "project": {"id": project} if project else None,
            "parent": {"id": parent} if parent else None,
            "labels": {"nodes": [{"id": lid} for lid in labels or []]},
            "attachments": {"nodes": attachments or []},
        }
        self.issues[iid] = issue
        self.comments[iid] = list(comments or [])
        return issue

    def make_comment(self, cid: str, body: str, *, user: str | None, created: str, parent: str | None = None,
                     edited: str | None = None) -> dict[str, Any]:
        return {"id": cid, "body": body, "url": f"https://linear.app/acme/comment/{cid}", "createdAt": created,
                "updatedAt": edited or created, "editedAt": edited, "user": {"id": user} if user else None,
                "parent": {"id": parent} if parent else None}

    def edit_issue(self, iid: str, *, updated_at: str, **fields: Any) -> None:
        self.issues[iid].update({"updatedAt": updated_at, **fields})

    def inject(self, operation: str, *, status: int = 200, body: dict[str, Any] | None = None,
               headers: dict[str, str] | None = None, times: int = 1) -> None:
        self.injected.append(Injected(operation, status, body or {}, headers or {}, times))

    def rate_limit(self, operation: str, times: int = 1) -> None:
        self.inject(operation, status=400, times=times, body={"errors": [{
            "message": "Rate limit exceeded", "extensions": {"type": "ratelimited", "code": "RATELIMITED"}}]},
            headers={"retry-after": "7"})

    def calls(self, operation: str) -> list[dict[str, Any]]:
        return [v for op, v, _ in self.requests if op == operation]

    # Serving
    def _page(self, items: list[Any], variables: dict[str, Any], key: str = "nodes") -> dict[str, Any]:
        start = int(variables["after"]) if variables.get("after") else 0
        chunk = items[start : start + self.page_size]
        more = start + self.page_size < len(items)
        return {key: chunk, "pageInfo": {"hasNextPage": more, "endCursor": str(start + self.page_size) if more else None}}

    async def _handle(self, request: Request) -> Response:
        body = await request.json()
        op = body.get("operationName") or ""
        variables = body.get("variables") or {}
        self.requests.append((op, variables, dict(request.headers)))
        for inj in list(self.injected):
            if inj.operation == op:
                inj.times -= 1
                if inj.times <= 0:
                    self.injected.remove(inj)
                return JSONResponse(inj.body, status_code=inj.status, headers=inj.headers)
        if request.headers.get("authorization") != self.api_key:
            return JSONResponse({"errors": [{"message": "Authentication required", "extensions": {
                "type": "authentication error", "code": "AUTHENTICATION_ERROR"}}]}, status_code=401)
        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            return JSONResponse({"errors": [{"message": f"Unknown operation {op}"}]}, status_code=400)
        result = handler(variables)
        if isinstance(result, dict) and "errors" in result:
            return JSONResponse(result)
        return JSONResponse({"data": result})

    def _op_Viewer(self, v: dict[str, Any]) -> dict[str, Any]:
        return {"viewer": {"id": "u-viewer", "name": "Vera Viewer", "displayName": "vera",
                           "email": "vera@acme.test", "organization": {"id": "org1", "name": "Acme", "urlKey": "acme"}}}

    def _op_TeamAccess(self, v: dict[str, Any]) -> dict[str, Any]:
        team = next((t for t in self.teams if t["id"] == v["id"]), None)
        return {"team": {k: team[k] for k in ("id", "name", "key")} if team else None,
                "viewer": {"id": "u-viewer", "guest": self.viewer_is_guest}}

    def _op_Teams(self, v: dict[str, Any]) -> dict[str, Any]:
        return {"teams": self._page(self.teams, v)}

    def _op_Users(self, v: dict[str, Any]) -> dict[str, Any]:
        return {"users": self._page(self.users, v)}

    def _op_States(self, v: dict[str, Any]) -> dict[str, Any]:
        return {"workflowStates": self._page(self.states.get(v["team"], []), v)}

    def _op_Labels(self, v: dict[str, Any]) -> dict[str, Any]:
        return {"issueLabels": self._page(self.labels.get(v["team"], []), v)}

    def _op_Projects(self, v: dict[str, Any]) -> dict[str, Any]:
        return {"projects": self._page(self.projects, v)}

    def _issue_view(self, issue: dict[str, Any]) -> dict[str, Any]:
        view = copy.deepcopy(issue)
        comments = self.comments.get(issue["id"], [])
        first = comments[: self.page_size]
        more = len(comments) > self.page_size
        view["comments"] = {"nodes": first, "pageInfo": {
            "hasNextPage": more, "endCursor": str(self.page_size) if more else None}}
        return view

    def _issues(self, v: dict[str, Any], team: str | None) -> dict[str, Any]:
        items = [i for i in self.issues.values() if (team is None or i["team"]["id"] == team)
                 and i["updatedAt"] > v["since"]]
        items.sort(key=lambda i: i["updatedAt"], reverse=True)
        page = self._page(items, v)
        page["nodes"] = [self._issue_view(i) for i in page["nodes"]]
        return {"issues": page}

    def _op_Issues(self, v: dict[str, Any]) -> dict[str, Any]:
        return self._issues(v, v["team"])

    def _op_IssuesAll(self, v: dict[str, Any]) -> dict[str, Any]:
        return self._issues(v, None)

    def _op_IssueComments(self, v: dict[str, Any]) -> dict[str, Any]:
        issue = self.issues.get(v["id"])
        if issue is None:
            return {"issue": None}
        return {"issue": {"comments": self._page(self.comments.get(v["id"], []), v)}}

    def _op_Issue(self, v: dict[str, Any]) -> dict[str, Any]:
        issue = self.issues.get(v["id"])
        return {"issue": self._issue_view(issue) if issue else None}

    def _op_IssueCreate(self, v: dict[str, Any]) -> dict[str, Any]:
        data = v["input"]
        if data["id"] in self.issues:
            return {"errors": [{"message": "Entity already exists: an issue with this id exists",
                                "path": ["issueCreate"], "extensions": {"type": "invalid input", "code": "INVALID_INPUT"}}]}
        team = data["teamId"]
        self._seq += 1
        key = next((t["key"] for t in self.teams if t["id"] == team), "ENG")
        self.add_issue(data["id"], team, self._seq, key, data["title"], updated_at="2026-04-01T00:00:00.000Z",
                       description=data.get("description", ""), assignee=data.get("assigneeId"),
                       labels=data.get("labelIds"))
        self.created_ids.append(data["id"])
        issue = self.issues[data["id"]]
        if self.lose_next_create_answer:  # the write happened, the answer is lost (client timeout)
            self.lose_next_create_answer = False
            raise httpx.ReadTimeout("answer lost")
        return {"issueCreate": {"success": True, "issue": {
            k: issue[k] for k in ("id", "identifier", "number", "url", "title", "description", "team")}}}

    def _op_IssueUpdate(self, v: dict[str, Any]) -> dict[str, Any]:
        issue = self.issues.get(v["id"])
        if issue is None:
            return {"errors": [{"message": "Entity not found: Issue", "path": ["issueUpdate"],
                                "extensions": {"code": "INVALID_INPUT"}}]}
        issue.update(v["input"])
        issue["updatedAt"] = "2026-04-02T00:00:00.000Z"
        return {"issueUpdate": {"success": True, "issue": {k: issue[k] for k in (
            "id", "identifier", "url", "title", "description", "updatedAt")}}}

    def _op_CommentCreate(self, v: dict[str, Any]) -> dict[str, Any]:
        data = v["input"]
        if data["issueId"] not in self.issues:
            return {"errors": [{"message": "Entity not found: Issue", "path": ["commentCreate"],
                                "extensions": {"code": "INVALID_INPUT"}}]}
        self._seq += 1
        comment = self.make_comment(f"cm-{self._seq}", data["body"], user="u-viewer", created="2026-04-02T00:00:00.000Z")
        self.comments[data["issueId"]].append(comment)
        return {"commentCreate": {"success": True, "comment": {k: comment[k] for k in ("id", "body", "url", "createdAt")}}}


def build_team_fixture(fake: FakeLinear) -> dict[str, str]:
    """Two users, one team with states and labels, a project, and issues with paginated comments."""
    fake.add_team("t1", "ENG", "Engineering")
    fake.add_user("u1", "Ada Lovelace", "ada@acme.test", display="ada")
    fake.add_user("u2", "Bob Builder", "bob@acme.test", display="bob")
    fake.add_state("t1", "s1", "Todo", "unstarted", 1)
    fake.add_state("t1", "s2", "In Progress", "started", 2)
    fake.add_state("t1", "s3", "Done", "completed", 3)
    fake.add_label("t1", "l1", "bug")
    fake.add_label("t1", "l2", "actron")
    fake.add_project("p1", "Sync rewrite", "t1", lead="u1")
    many = [fake.make_comment(f"c{i}", f"comment {i}", user="u1" if i % 2 else "u2",
                              created=f"2026-02-{(i % 27) + 1:02d}T00:00:00.000Z") for i in range(1, 61)]
    many[1]["body"] = "cc @bob please look"
    many[2]["parent"] = {"id": "c1"}
    fake.add_issue("i1", "t1", 1, "ENG", "Retry on rate limit", updated_at="2026-03-01T00:00:00.000Z",
                   description="Sync crashes on 429.", state="s2", assignee="u1", creator="u2", project="p1",
                   labels=["l1"], branch="ada/eng-1-retry",
                   attachments=[{"url": "https://github.com/acme/widgets/pull/7", "title": "PR", "sourceType": "github"}],
                   comments=many)
    fake.add_issue("i2", "t1", 2, "ENG", "Sub task", updated_at="2026-03-05T00:00:00.000Z", state="s1",
                   creator="u1", parent="i1")
    return {"team": "t1", "issue": "i1"}
