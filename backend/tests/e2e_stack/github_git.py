"""FakeGithub backed by local bare repositories, with the write endpoints the build and the request flow use.

Reads branches and commits from git (so `commits/heads/<branch>` matches what the build pushes), creates and
updates pull requests (`POST/PATCH /repos/{repo}/pulls`, `PUT .../merge`), filters `pulls?head=owner:branch`,
and derives a created PR's head, files and commits from git each time it is read.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from tests.fakes.github import FakeGithub, commit_json, user

BOT = user(900, "actron-e2e-bot", "Bot")


class GitFakeGithub(FakeGithub):
    def __init__(self, git_root: Path, *, public_base: str) -> None:
        super().__init__()
        self.git_root = git_root
        self.public_base = public_base.rstrip("/")
        self.created: dict[str, set[int]] = {}
        # Regex on "METHOD path" -> seconds to wait before answering (holds a build in a known step).
        self.delays: dict[str, float] = {}
        self.app =Starlette(routes=[Route("/{path:path}", self._entry, methods=["GET", "POST", "PATCH", "PUT"])])

    # Git
    def _bare(self, full: str) -> Path:
        return self.git_root / f"{full}.git"

    def _git(self, full: str, *args: str) -> str:
        out = subprocess.run(["git", *args], cwd=self._bare(full), capture_output=True, text=True, timeout=30)
        return out.stdout if out.returncode == 0 else ""

    def _heads(self, full: str) -> dict[str, str]:
        if not self._bare(full).is_dir():
            return {}
        refs = self._git(full, "for-each-ref", "refs/heads", "--format=%(refname:short) %(objectname)")
        return dict(line.split(" ", 1) for line in refs.splitlines() if " " in line)

    def _commit_of(self, full: str, sha: str) -> dict[str, Any] | None:
        raw = self._git(full, "show", "-s", "--format=%H%x00%an%x00%ae%x00%cI%x00%B", sha)
        if not raw:
            return None
        h, name, email, date, message = raw.split("\x00", 4)
        return commit_json(h, message.strip(), name, email, date)

    def _sync(self, full: str) -> None:
        heads = self._heads(full)
        if not heads:
            return
        self.branches[full] = [{"name": n, "commit": {"sha": s, "url": f"{self.public_base}/repos/{full}/commits/{s}"},
                                "protected": n == "main"} for n, s in sorted(heads.items())]
        for sha in heads.values():
            c = self._commit_of(full, sha)
            if c:
                self.commits[full][sha] = c

    def _refresh_pr(self, full: str, n: int) -> None:
        pr = self.pulls[full].get(n)
        if pr is None or n not in self.created.get(full, set()):
            return
        heads = self._heads(full)
        head_ref, base_ref = pr["head"]["ref"], pr["base"]["ref"]
        head = heads.get(head_ref)
        if not head:
            return
        base = heads.get(base_ref, "")
        pr["head"]["sha"] = head
        pr["base"]["sha"] = base
        rng = f"{base}...{head}"
        files: list[dict[str, Any]] = []
        for line in self._git(full, "diff", "--numstat", "--no-renames", rng).splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            add, dele, path = parts
            patch = self._git(full, "diff", "--no-renames", rng, "--", path)
            hunk = patch[patch.find("@@"):] if "@@" in patch else ""
            files.append({"filename": path, "status": "added" if "new file mode" in patch else "modified",
                          "additions": int(add) if add.isdigit() else 0, "deletions": int(dele) if dele.isdigit() else 0,
                          "patch": hunk})
        self.pr_files[full][n] = files
        commits = []
        for sha in self._git(full, "rev-list", "--reverse", f"{base}..{head}").split():
            c = self._commit_of(full, sha)
            if c:
                commits.append(c)
        self.pr_commits[full][n] = commits
        pr.update(additions=sum(f["additions"] for f in files), deletions=sum(f["deletions"] for f in files),
                  changed_files=len(files))

    # Serving
    async def _entry(self, request: Request) -> Response:
        path = request.url.path
        for pattern, seconds in list(self.delays.items()):
            if re.search(pattern, f"{request.method} {path}"):
                import asyncio

                await asyncio.sleep(seconds)
        m = re.match(r"^/repos/([^/]+/[^/]+)", path)
        full = m.group(1) if m else None
        if full:
            self._sync(full)
            for n in list(self.created.get(full, set())):
                self._refresh_pr(full, n)
        if request.method in ("POST", "PATCH", "PUT") and full:
            self.requests.append((request.method, path, dict(request.headers)))
            for inj in list(self.injected):
                if re.search(inj.match, path):
                    inj.times -= 1
                    if inj.times <= 0:
                        self.injected.remove(inj)
                    return JSONResponse(inj.body or {"message": "injected"}, status_code=inj.status)
            body = await request.json() if (await request.body()) else {}
            return self._write(request.method, full, path, body)
        mh = re.match(r"^/repos/([^/]+/[^/]+)/commits/heads/(.+)$", path)
        if mh and request.method == "GET":
            sha = self._heads(mh.group(1)).get(mh.group(2))
            c = self._commit_of(mh.group(1), sha) if sha else None
            return JSONResponse(c or {"message": "No commit found for SHA"}, status_code=200 if c else 404)
        head = request.query_params.get("head")
        mp = re.match(r"^/repos/([^/]+/[^/]+)/pulls$", path)
        if mp and head and request.method == "GET":
            branch = head.split(":", 1)[-1]
            state = request.query_params.get("state", "open")
            items = [self._list_form(p) for p in self.pulls[mp.group(1)].values()
                     if p["head"]["ref"] == branch and (state == "all" or p["state"] == state)]
            return JSONResponse(items)
        return await self._dispatch(request)

    def _write(self, method: str, full: str, path: str, body: dict[str, Any]) -> Response:
        if method == "POST" and path == f"/repos/{full}/pulls":
            heads = self._heads(full)
            head_ref, base_ref = str(body.get("head", "")).split(":")[-1], str(body.get("base", "main"))
            if head_ref not in heads:
                return JSONResponse({"message": "Validation Failed", "errors": [{"field": "head"}]}, status_code=422)
            n = max([0, *self.pulls[full].keys(), *[k for r in self.pulls.values() for k in r]]) + 1
            pr = self.add_pull(full, n, title=str(body.get("title", "")), author=BOT, updated_at=_now(),
                               created_at=_now(), head_ref=head_ref, head_sha=heads[head_ref], base_ref=base_ref,
                               body=str(body.get("body", "")))
            self.pulls[full][n]["html_url"] = f"{self.public_base}/{full}/pull/{n}"
            self.created.setdefault(full, set()).add(n)
            self._refresh_pr(full, n)
            return JSONResponse(self.pulls[full][n] | {"html_url": pr["html_url"]}, status_code=201)
        m = re.match(rf"^/repos/{re.escape(full)}/pulls/(\d+)(/merge)?$", path)
        if m and int(m.group(1)) in self.pulls[full]:
            n = int(m.group(1))
            pr = self.pulls[full][n]
            if m.group(2) and method == "PUT":
                pr.update(state="closed", merged=True, merged_at=_now(), merge_commit_sha=pr["head"]["sha"],
                          updated_at=_now(), merged_by=BOT)
                return JSONResponse({"merged": True, "sha": pr["head"]["sha"], "message": "Pull Request merged"})
            for key in ("title", "body", "state"):
                if key in body:
                    pr[key] = body[key]
            pr["updated_at"] = _now()
            if pr["state"] == "closed":
                pr["closed_at"] = _now()
            return JSONResponse(pr)
        return JSONResponse({"message": "Not Found"}, status_code=404)

    def summary(self) -> list[dict[str, Any]]:
        out = []
        for full, prs in self.pulls.items():
            for n, pr in prs.items():
                if n in self.created.get(full, set()):
                    self._refresh_pr(full, n)
                    out.append({"repo": full, "number": n, "title": pr["title"], "state": pr["state"],
                                "merged": pr.get("merged", False), "head": pr["head"], "base": pr["base"],
                                "files": [f["filename"] for f in self.pr_files[full].get(n, [])]})
        return out


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
