"""Real GitHub REST operations constrained to one explicitly dedicated demo repository."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from actron.contracts import Payload, Rejected, Unavailable, UnknownOutcome, canonical


class GitHubPRs:
    def __init__(
        self,
        repository: str,
        token: str,
        dedicated_repository: str,
        remote: str | None = None,
        required_checks: list[str] | None = None,
        reviews_required: int = 1,
    ):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or repository != dedicated_repository:
            raise Rejected("GitHub writes require the explicitly dedicated demo repository")
        if not token or reviews_required < 1:
            raise Rejected("GitHub token and at least one review are required")
        expected = {f"https://github.com/{repository}.git", f"git@github.com:{repository}.git"}
        self.remote = remote or f"https://github.com/{repository}.git"
        if self.remote not in expected:
            raise Rejected("Push remote must exactly match the dedicated GitHub repository")
        self.repository, self.token = repository, token
        self.required_checks = required_checks or ["suite"]
        self.reviews_required = reviews_required
        self.prefix = f"/repos/{repository}"

    def _request(self, method: str, path: str, payload: Payload | None = None) -> Any:
        request = Request(
            "https://api.github.com" + path,
            method=method,
            data=canonical(payload).encode() if payload is not None else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "actron-demo",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            if method != "GET" and error.code >= 500:
                raise UnknownOutcome(
                    f"GitHub {method} outcome unknown: HTTP {error.code}"
                ) from error
            raise Unavailable(f"GitHub {method} {path}: HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            cls = UnknownOutcome if method != "GET" else Unavailable
            raise cls(f"GitHub {method} {path} unavailable: {error}") from error

    def _pages(self, path: str, field: str | None = None) -> list[Payload]:
        values: list[Payload] = []
        for page in range(1, 101):
            query = "&" if "?" in path else "?"
            response = self._request(
                "GET", path + query + urlencode({"per_page": 100, "page": page})
            )
            batch = response[field] if field else response
            if not isinstance(batch, list):
                raise Unavailable("Malformed GitHub list response")
            values.extend(batch)
            if len(batch) < 100:
                return values
        raise Unavailable("GitHub pagination limit reached; completeness unknown")

    def _marker(self, operation: str) -> str:
        return "<!-- actron-operation:" + hashlib.sha256(operation.encode()).hexdigest() + " -->"

    def find(self, operation: str) -> Payload | None:
        marker = self._marker(operation)
        prs = self._pages(self.prefix + "/pulls?state=all")
        matches = [pr for pr in prs if marker in (pr.get("body") or "")]
        if len(matches) > 1:
            raise UnknownOutcome("Multiple PRs claim one operation; manual reconciliation required")
        return self.read(str(matches[0]["number"])) if matches else None

    def _number(self, pr: str) -> str:
        if pr.isdigit():
            return pr
        match = re.fullmatch(
            r"https://github\.com/" + re.escape(self.repository) + r"/pull/(\d+)", pr
        )
        if not match:
            raise Rejected("PR does not belong to configured dedicated repository")
        return match[1]

    def _push(self, run: Payload) -> None:
        branch, head = run["branch"], run["commit"]
        if not re.fullmatch(r"actron/[a-f0-9]{24}", branch) or not re.fullmatch(
            r"[a-f0-9]{40,64}", head
        ):
            raise Rejected("Worker branch or commit is invalid")
        checkout = Path(run["path"])
        actual = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", branch], text=True
        ).strip()
        if actual != head:
            raise Rejected("Worker branch no longer matches tested commit")
        try:
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(checkout),
                    "push",
                    "--porcelain",
                    self.remote,
                    head + ":refs/heads/" + branch,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, OSError) as error:
            raise UnknownOutcome(
                "Git push outcome unknown; inspect dedicated remote branch"
            ) from error
        if result.returncode:
            raise UnknownOutcome("Git push did not confirm success: " + result.stderr)

    def create(self, operation: str, run: Payload, scope: Payload) -> Payload:
        existing = self.find(operation)
        if existing and existing["head"] == run.get("commit"):
            return existing
        if existing and (existing["merged"] or existing["branch"] != run.get("branch")):
            raise Rejected("Existing PR cannot be revised by this worker branch")
        if run.get("status") != "succeeded" or run.get("commit") == run.get("base"):
            raise Rejected("Only a changed, successfully validated worker commit can open a PR")
        checks = [check for check in run.get("checks", []) if check.get("head") == run["commit"]]
        if not any(c.get("kind") == "suite" for c in checks) or any(
            c.get("exit_code") != 0 for c in checks
        ):
            raise Rejected("Current worker head lacks passing complete suite")
        self._push(run)
        marker = self._marker(operation)
        validation = [
            {key: check.get(key) for key in ("command", "exit_code", "head", "output")}
            for check in checks
        ]
        body = (
            str(scope.get("objective", "Approved implementation"))
            + "\n\nApproved ticket and revision:\n"
            + canonical(
                {key: scope.get(key) for key in ("ticket", "revision", "scope_hash", "request")}
            )
            + "\n\nAcceptance criteria:\n"
            + canonical(scope.get("acceptance", []))
            + "\n\nPreserved constraints:\n"
            + canonical(scope.get("constraints", []))
            + "\n\nSource evidence:\n"
            + canonical(scope.get("evidence", []))
            + "\n\nActual validation:\n```json\n"
            + json.dumps(validation, indent=2)
            + "\n```\n"
            + marker
        )
        candidates = self._pages(
            self.prefix
            + "/pulls?"
            + urlencode(
                {"state": "open", "head": self.repository.split("/")[0] + ":" + run["branch"]}
            )
        )
        if len(candidates) > 1:
            raise UnknownOutcome("Multiple PRs found for worker branch")
        if candidates:
            old = candidates[0]
            self._request(
                "PATCH",
                self.prefix + f"/pulls/{old['number']}",
                {"body": (old.get("body") or "") + "\n\nRevision:\n" + body},
            )
            return self.read(str(old["number"]))
        repo = self._request("GET", self.prefix)
        response = self._request(
            "POST",
            self.prefix + "/pulls",
            {
                "title": str(scope.get("objective", "Approved implementation"))[:200],
                "head": run["branch"],
                "base": repo["default_branch"],
                "body": body,
            },
        )
        if not response.get("number") or not response.get("html_url"):
            raise UnknownOutcome("GitHub did not confirm created PR identity")
        return self.read(str(response["number"]))

    def read(self, pr: str) -> Payload:
        number = self._number(pr)
        data = self._request("GET", self.prefix + f"/pulls/{number}")
        head, base = data["head"]["sha"], data["base"]["ref"]
        runs = self._pages(self.prefix + f"/commits/{head}/check-runs", "check_runs")
        statuses = self._pages(self.prefix + f"/commits/{head}/statuses")
        checks = [
            {
                "name": run["name"],
                "head": run["head_sha"],
                "app_id": run.get("app", {}).get("id"),
                "status": (
                    "success"
                    if run.get("conclusion") == "success"
                    else "pending"
                    if run["status"] != "completed"
                    else "failed"
                ),
                "conclusion": run.get("conclusion"),
                "id": run["id"],
            }
            for run in runs
        ]
        checks += [
            {
                "name": status["context"],
                "head": head,
                "status": status["state"],
                "app_id": None,
                "id": status["id"],
            }
            for status in statuses
        ]
        reviews_raw = self._pages(self.prefix + f"/pulls/{number}/reviews")
        reviews = [
            {"state": r["state"], "head": r["commit_id"], "user": r["user"]["login"], "id": r["id"]}
            for r in reviews_raw
        ]
        # Dismissed approvals and changes requested supersede that reviewer's prior approval.
        latest_reviews: dict[str, Payload] = {}
        for review in reviews:
            if review["state"] != "COMMENTED":
                latest_reviews[review["user"]] = review
        approvals = sum(
            r["state"] == "APPROVED" and r["head"] == head for r in latest_reviews.values()
        )
        blocked = any(r["state"] == "CHANGES_REQUESTED" for r in latest_reviews.values())
        required = set(self.required_checks)
        required_approvals = self.reviews_required
        metadata_complete = True
        app_requirements: dict[str, int] = {}
        try:
            protection = self._request(
                "GET", self.prefix + f"/branches/{quote(base, safe='')}/protection"
            )
            status_policy = protection.get("required_status_checks") or {}
            required.update(status_policy.get("contexts", []))
            for requirement in status_policy.get("checks", []):
                required.add(requirement["context"])
                if requirement.get("app_id") is not None:
                    app_requirements[requirement["context"]] = requirement["app_id"]
            required_approvals = max(
                required_approvals,
                (protection.get("required_pull_request_reviews") or {}).get(
                    "required_approving_review_count", 0
                ),
            )
            # Rulesets may add requirements beyond legacy branch protection.
            rules = self._request("GET", self.prefix + f"/rules/branches/{quote(base, safe='')}")
            for rule in rules:
                parameters = rule.get("parameters", {})
                if rule["type"] == "required_status_checks":
                    for check in parameters.get("required_status_checks", []):
                        required.add(check["context"])
                        if check.get("integration_id") is not None:
                            app_requirements[check["context"]] = check["integration_id"]
                if rule["type"] == "pull_request":
                    required_approvals = max(
                        required_approvals, parameters.get("required_approving_review_count", 0)
                    )
        except Unavailable:
            metadata_complete = False
        # Retain latest result for each check producer; old success cannot mask a newer failure.
        latest: dict[tuple[str, Any], Payload] = {}
        for check in checks:
            key = (check["name"], check.get("app_id"))
            if key not in latest or check["id"] > latest[key]["id"]:
                latest[key] = check
        checks_complete = metadata_complete and bool(required)
        for name in required:
            matches = [
                c
                for c in latest.values()
                if c["name"] == name
                and c["head"] == head
                and (name not in app_requirements or c.get("app_id") == app_requirements[name])
            ]
            checks_complete = (
                checks_complete and bool(matches) and all(c["status"] == "success" for c in matches)
            )
        return {
            "id": number,
            "url": data["html_url"],
            "head": head,
            "base": base,
            "branch": data["head"]["ref"],
            "state": data["state"],
            "merged": data["merged"],
            "merge_commit": data.get("merge_commit_sha"),
            "checks": list(latest.values()),
            "check_history": checks,
            "reviews": list(latest_reviews.values()),
            "review_history": reviews,
            "required_checks": sorted(required),
            "reviews_required": required_approvals,
            "checks_complete": checks_complete,
            "reviews_complete": approvals >= required_approvals and not blocked,
            "protection_complete": metadata_complete,
            "mergeable": data.get("mergeable"),
        }

    def merge(self, pr: str, expected_head: str) -> Payload:
        current = self.read(pr)
        if current["head"] != expected_head:
            raise Rejected("PR head changed after authorization")
        if current["merged"]:
            return current
        if not current["checks_complete"] or not current["reviews_complete"]:
            raise Rejected(
                "Required current-head checks or reviews are missing, failed, or unknown"
            )
        if current["state"] != "open":
            raise Rejected("PR is not open")
        response = self._request(
            "PUT",
            self.prefix + f"/pulls/{self._number(pr)}/merge",
            {"sha": expected_head, "merge_method": "merge"},
        )
        if not response.get("merged") or not response.get("sha"):
            raise Rejected("GitHub did not confirm merge: " + str(response.get("message")))
        return {**current, "merged": True, "state": "closed", "merge_commit": response["sha"]}
