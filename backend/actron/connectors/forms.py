"""Connector forms, live validation, option lists and setup checks (spec C, C12 and C13, backend parts).

`load_forms()` serves `forms.json` to `GET /api/connectors`, with the parts that depend on this
deployment filled in (webhook payload URL, Slack manifest, whether "Add to Slack" is available).
`validate()`, `options()` and `checks()` make live calls through the same clients the connectors
use and turn provider errors into the plain sentences of C13. Secrets are read from the values or
the connection and never appear in any result.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from actron.config import REPO_ROOT, get_settings
from actron.connectors.common import (
    AuthError,
    ForbiddenError,
    NotFoundError,
    ProviderError,
    ValidationError,
    resolve_config,
)
from actron.integrations.github_client import GithubClient
from actron.integrations.linear_client import LinearClient
from actron.integrations.slack_client import SlackApiError, SlackClient
from actron.logging import get_logger

log = get_logger(__name__)

FORMS_PATH = Path(__file__).with_name("forms.json")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FALLBACK_SLACK_SCOPES = (
    "app_mentions:read", "channels:history", "channels:read", "chat:write", "commands", "groups:history",
    "groups:read", "im:write", "reactions:read", "team:read", "users:read", "users:read.email",
)


def required_slack_scopes() -> tuple[str, ...]:
    try:
        from actron.integrations.slack_common import BOT_SCOPES

        return tuple(BOT_SCOPES)
    except ImportError:
        return FALLBACK_SLACK_SCOPES


# Forms
def generate_webhook_secret() -> str:
    """A fresh secret for the GitHub webhook; the caller stores it encrypted in the connection."""
    return secrets.token_urlsafe(32)


def _manifest_text(https: bool) -> tuple[str | None, str]:
    name = "manifest.yaml" if https else "manifest.dev.yaml"
    path = REPO_ROOT / "infra" / "slack" / name
    try:
        return path.read_text(encoding="utf-8"), name
    except OSError:
        return None, name


def load_forms() -> dict[str, Any]:
    """Form definitions for every provider. The frontend renders these and hard-codes no fields."""
    forms: dict[str, Any] = json.loads(FORMS_PATH.read_text(encoding="utf-8"))
    settings = get_settings()
    public = (settings.ACTRON_PUBLIC_URL or "").rstrip("/")
    https = public.startswith("https://")
    oauth_ready = bool(settings.SLACK_CLIENT_ID and settings.SLACK_CLIENT_SECRET)
    for form in forms["providers"]:
        form["secret_fields"] = [f["field_id"] for f in form["fields"] if f.get("is_secret")]
        for f in form["fields"]:
            if f["field_id"] == "webhook":
                f["payload_url"] = f"{public}{f['payload_path']}" if public else None
                f["payload_url_note"] = (
                    None if public else "Set ACTRON_PUBLIC_URL to the address GitHub can reach, then reload.")
                f["secret_generated_by"] = "actron"
            if f["field_id"] == "manifest":
                text, name = _manifest_text(https)
                f["manifest"] = text
                f["manifest_file"] = name
                f["manifest_variant"] = "production" if https else "development"
                f["link_prefilled"] = None
            if f["field_id"] == "slack_oauth":
                f["available"] = oauth_ready
        if form["provider"] == "slack":
            form["oauth_available"] = oauth_ready
            form["paths"] = [p for p in form["paths"] if p.get("always") or oauth_ready]
            form["socket_mode_needed"] = not https
    return forms


def form_for(provider: str) -> dict[str, Any]:
    for form in load_forms()["providers"]:
        if form["provider"] == provider:
            return form  # type: ignore[no-any-return]
    raise ValidationError(f"unknown connector {provider!r}")


# Results
@dataclass
class ValidationResult:
    ok: bool
    message: str
    field_errors: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckResult:
    id: str
    title: str
    status: str  # ok | failed | pending | skipped
    message: str
    troubleshooting: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Plain-language explanations (C13 troubleshooting)
SLACK_TROUBLE: dict[str, str] = {
    "invalid_auth": "The token is wrong or was revoked. Copy it again from OAuth & Permissions.",
    "not_authed": "The token is wrong or was revoked. Copy it again from OAuth & Permissions.",
    "token_revoked": "Slack says this token was revoked. Install the app again and copy the new token.",
    "token_expired": "Slack says this token expired. Install the app again and copy the new token.",
    "account_inactive": "The Slack account behind this token is deactivated. Install the app again with an active account.",
    "not_in_channel": "Invite Actron with /invite @Actron.",
    "ratelimited": "Slack asked us to slow down; we retry automatically.",
    "missing_scope": "The app is missing a permission. Add it under OAuth & Permissions, then reinstall the app.",
}
SOCKET_TROUBLE = "Turn on Socket Mode and check the app-level token has connections:write."


def explain_slack_error(code: str | None, *, missing: list[str] | None = None) -> str:
    if code == "missing_scope" and missing:
        return f"Missing permissions: {', '.join(missing)}. Reinstall the app after adding these scopes."
    return SLACK_TROUBLE.get(code or "", f"Slack answered with {code or 'an error'}. Check the app settings and try again.")


def _wait_text(seconds: float | None) -> str:
    if not seconds:
        return "a little while"
    minutes = int(seconds // 60)
    if minutes >= 1:
        return f"about {minutes} minute{'s' if minutes != 1 else ''}"
    return f"{int(seconds)} seconds"


def explain_github_error(exc: Exception, *, repo: str | None = None) -> str:
    from actron.connectors.common import RetryableProviderError

    if isinstance(exc, AuthError):
        return "GitHub says the token is wrong or expired. Create a new token and paste it again."
    if isinstance(exc, ForbiddenError):
        if "not accessible" in str(exc).lower():
            return ("The token is missing a permission for this repository. It needs Contents, Pull requests, "
                    "Issues, Metadata, Actions and Checks.")
        return "GitHub refused the request. Check the token's permissions and the repository's access settings."
    if isinstance(exc, NotFoundError):
        return (f"GitHub cannot find {repo}. Check the name, and that the token can see this repository."
                if repo else "GitHub cannot find that. Check the name and the token's access.")
    if isinstance(exc, RetryableProviderError):
        return f"GitHub's rate limit is used up. It resets in {_wait_text(exc.retry_after)}."
    return f"GitHub could not be reached: {exc}"


WEBHOOK_TROUBLE = "The signature did not match. Copy the secret from Actron into the webhook again."


def explain_linear_error(exc: Exception) -> str:
    from actron.connectors.common import RetryableProviderError

    if isinstance(exc, AuthError):
        return "Linear rejected the API key. Create a new one under Settings, Security & access, Personal API keys."
    if isinstance(exc, RetryableProviderError):
        return "Linear asked us to slow down; we retry automatically."
    return f"Linear answered with an error: {exc}"


def _settings_value(values: Mapping[str, Any], key: str, fallback: str | None) -> str | None:
    value = values.get(key)
    return str(value).strip() if value else fallback


# Validation
async def validate(provider: str, values: Mapping[str, Any]) -> ValidationResult:
    """A live test call for the first fields of a form. Never raises for provider problems."""
    handlers = {"github": _validate_github, "slack": _validate_slack, "linear": _validate_linear,
                "slack_export": _validate_export}
    handler = handlers.get(provider)
    if handler is None:
        return ValidationResult(False, f"Unknown connector {provider}.")
    return await handler(values)


async def _validate_github(values: Mapping[str, Any]) -> ValidationResult:
    s = get_settings()
    repo = _settings_value(values, "repository", s.GITHUB_REPOSITORY)
    token = _settings_value(values, "access_token", s.GITHUB_TOKEN)
    errors: dict[str, str] = {}
    if not repo or not REPO_RE.match(repo):
        errors["repository"] = "Write the repository as owner/name, for example BetterThanTomorrow/calva."
    for key in ("fork", "upstream"):
        v = values.get(key)
        if v and not REPO_RE.match(str(v)):
            errors[key] = "Write the repository as owner/name."
    if errors:
        return ValidationResult(False, "Check the highlighted fields.", errors)
    assert repo
    warnings: list[str] = []
    details: dict[str, Any] = {}
    async with GithubClient(token, base_url=_settings_value(values, "api_url", None)) as client:
        try:
            info = await client.repository(repo)
            details.update(repository=info["full_name"], default_branch=info.get("default_branch"),
                           private=bool(info.get("private")), has_token=bool(token))
            try:
                details["pull_requests"] = await client.pull_count(repo)
            except ProviderError:
                details["pull_requests"] = None
        except (ProviderError, ValidationError) as exc:
            key = "access_token" if isinstance(exc, AuthError) else "repository"
            return ValidationResult(False, explain_github_error(exc, repo=repo), {key: explain_github_error(exc, repo=repo)})
        if not token:
            warnings.append("No token was given, so Actron reads GitHub at the public limit and cannot push.")
        target = _settings_value(values, "fork", None) or repo
        details["push_target"] = target
        if token:
            can_push, push_message = await _can_push(client, target, info if target == repo else None)
            details["can_push"] = can_push
            if not can_push:
                errors["fork"] = push_message
        upstream = values.get("upstream")
        if upstream:
            try:
                await client.repository(str(upstream))
            except ProviderError as exc:
                errors["upstream"] = explain_github_error(exc, repo=str(upstream))
    prs = details.get("pull_requests")
    pr_text = f", {prs:,} pull requests" if isinstance(prs, int) else ""
    message = f"Repository found: {details['repository']}, default branch {details['default_branch']}{pr_text}."
    if errors:
        return ValidationResult(False, message + " " + " ".join(errors.values()), errors, details, warnings)
    return ValidationResult(True, message, {}, details, warnings)


async def _can_push(client: GithubClient, target: str, known: Mapping[str, Any] | None) -> tuple[bool, str]:
    try:
        info = known or await client.repository(target)
    except ProviderError as exc:
        return False, explain_github_error(exc, repo=target)
    perms = info.get("permissions") or {}
    if perms.get("push") or perms.get("admin") or perms.get("maintain"):
        return True, f"Actron can push to {target}."
    return False, (f"The token cannot push to {target}. Give it Contents read and write on that repository, "
                   "or choose a fork you own.")


async def _validate_slack(values: Mapping[str, Any]) -> ValidationResult:
    s = get_settings()
    token = _settings_value(values, "bot_token", s.SLACK_BOT_TOKEN)
    app_token = _settings_value(values, "app_token", None)
    base = _settings_value(values, "api_url", None)
    errors: dict[str, str] = {}
    details: dict[str, Any] = {}
    warnings: list[str] = []
    if not token:
        return ValidationResult(False, "Paste the bot token to check the connection.",
                                {"bot_token": "The bot token is required."})
    if not token.startswith("xoxb-"):
        warnings.append("Bot tokens start with xoxb-. This one does not, so check you copied the right token.")
    async with SlackClient(token, base_url=base) as client:
        try:
            auth = await client.auth_test()
        except AuthError as exc:
            msg = explain_slack_error(exc.code)
            return ValidationResult(False, msg, {"bot_token": msg})
        except ProviderError as exc:
            msg = explain_slack_error(exc.code)
            return ValidationResult(False, msg, {"bot_token": msg})
        details.update(team_id=auth.get("team_id"), team=auth.get("team"), bot_user=auth.get("user"),
                       bot_user_id=auth.get("user_id"), scopes=client.scopes)
        missing = [x for x in required_slack_scopes() if client.scopes and x not in client.scopes]
        if missing:
            details["missing_scopes"] = missing
            warnings.append(explain_slack_error("missing_scope", missing=missing))
        if app_token:
            try:
                await client.open_socket_mode(app_token)
                details["socket_mode"] = True
            except ProviderError:
                errors["app_token"] = SOCKET_TROUBLE
    message = f"Connected to {auth.get('team')} as @{auth.get('user')}."
    if errors:
        return ValidationResult(False, message + " " + SOCKET_TROUBLE, errors, details, warnings)
    return ValidationResult(True, message, {}, details, warnings)


async def _validate_linear(values: Mapping[str, Any]) -> ValidationResult:
    key = _settings_value(values, "api_key", get_settings().LINEAR_API_KEY)
    if not key:
        return ValidationResult(False, "Paste the API key to check the connection.",
                                {"api_key": "The API key is required."})
    async with LinearClient(key, base_url=_settings_value(values, "api_url", None)) as client:
        try:
            viewer = await client.viewer()
        except (ProviderError, ValidationError) as exc:
            msg = explain_linear_error(exc)
            return ValidationResult(False, msg, {"api_key": msg})
    org = (viewer.get("organization") or {}).get("name")
    details = {"viewer": viewer.get("name"), "organization": org, "viewer_id": viewer.get("id")}
    where = f" in {org}" if org else ""
    return ValidationResult(True, f"Connected as {viewer.get('name')}{where}.", {}, details)


async def _validate_export(values: Mapping[str, Any]) -> ValidationResult:
    from actron.connectors.slack_export import ExportValidationError, validate_export

    path = values.get("archive") or values.get("path")
    if not path:
        return ValidationResult(False, "Choose the export zip file.", {"archive": "The export is required."})
    try:
        report = await asyncio.to_thread(validate_export, Path(str(path)))
    except ExportValidationError as exc:
        return ValidationResult(False, exc.reason, {"archive": exc.reason})
    msg = f"Export found: {report.channels} channels, {report.day_files} day files."
    return ValidationResult(True, msg, {}, {"channels": report.channels, "day_files": report.day_files,
                                            "has_events": report.has_events}, report.warnings)


# Options for dependent fields
async def options(provider: str, field_id: str, values: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Choices for a select whose `optionsFrom` names a source (branches, channels, teams, labels)."""
    key = (provider, field_id)
    if key == ("github", "working_branch"):
        return await _branch_options(values)
    if provider == "slack" and field_id in ("channels", "requests_channel"):
        return await _channel_options(values, limit_to=values.get("channels") if field_id == "requests_channel" else None)
    if key == ("linear", "team"):
        return await _team_options(values)
    if key == ("linear", "ticket_label"):
        return await _label_options(values)
    raise ValidationError(f"{provider} has no options for {field_id}")


async def _branch_options(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    s = get_settings()
    repo = _settings_value(values, "repository", s.GITHUB_REPOSITORY)
    token = _settings_value(values, "access_token", s.GITHUB_TOKEN)
    if not repo or not REPO_RE.match(repo):
        raise ValidationError("Check the repository first.")
    async with GithubClient(token, base_url=_settings_value(values, "api_url", None)) as client:
        info = await client.repository(repo)
        branches = await client.branches(repo)
        default = info.get("default_branch")
        recent = [b for b in branches if b["name"] != default][:20]

        async def commit_date(b: Mapping[str, Any]) -> str | None:
            try:
                cj = await client.commit(repo, b["commit"]["sha"])
                return str(((cj.get("commit") or {}).get("committer") or {}).get("date") or "") or None
            except ProviderError:
                return None

        dates = await asyncio.gather(*(commit_date(b) for b in recent))
    by_name = {b["name"]: d for b, d in zip(recent, dates, strict=True)}
    out: list[dict[str, Any]] = []
    for b in branches:
        name = b["name"]
        marks = [m for m, on in (("default", name == default), ("protected", bool(b.get("protected")))) if on]
        out.append({"value": name, "label": f"{name} ({', '.join(marks)})" if marks else name,
                    "default": name == default, "protected": bool(b.get("protected")),
                    "lastCommitAt": by_name.get(name)})
    out.sort(key=lambda o: (not o["default"], o["lastCommitAt"] is None, _neg(o["lastCommitAt"]), o["value"]))
    return out


def _neg(date: str | None) -> tuple[int, ...]:
    """Sort key so that later ISO dates come first."""
    return tuple(-ord(c) for c in (date or ""))


async def _channel_options(values: Mapping[str, Any], limit_to: Any = None) -> list[dict[str, Any]]:
    token = _settings_value(values, "bot_token", get_settings().SLACK_BOT_TOKEN)
    if not token:
        raise ValidationError("Check the bot token first.")
    wanted = set(limit_to or [])
    out: list[dict[str, Any]] = []
    async with SlackClient(token, base_url=_settings_value(values, "api_url", None)) as client:
        cursor: str | None = None
        while True:
            body = await client.conversations_list(cursor)
            for c in body.get("channels", []):
                if not c.get("is_member") or c.get("is_archived"):
                    continue
                if wanted and c["id"] not in wanted:
                    continue
                out.append({"value": c["id"], "label": f"#{c['name']}", "isPrivate": bool(c.get("is_private")),
                            "memberCount": c.get("num_members")})
            cursor = (body.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
    out.sort(key=lambda o: o["label"])
    return out


async def _team_options(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    from actron.integrations import linear_client as lc

    key = _settings_value(values, "api_key", get_settings().LINEAR_API_KEY)
    if not key:
        raise ValidationError("Check the API key first.")
    out: list[dict[str, Any]] = []
    async with LinearClient(key, base_url=_settings_value(values, "api_url", None)) as client:
        cursor: str | None = None
        while True:
            nodes, cursor = await client.connection(lc.Q_TEAMS, "teams", {"after": cursor})
            out.extend({"value": t["id"], "label": f"{t['name']} ({t['key']})", "key": t.get("key")} for t in nodes)
            if not cursor:
                break
    return out


async def _label_options(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    from actron.integrations import linear_client as lc

    key = _settings_value(values, "api_key", get_settings().LINEAR_API_KEY)
    team = _settings_value(values, "team", get_settings().LINEAR_TEAM_ID)
    if not key or not team:
        raise ValidationError("Choose the team first.")
    out: list[dict[str, Any]] = []
    async with LinearClient(key, base_url=_settings_value(values, "api_url", None)) as client:
        cursor: str | None = None
        while True:
            nodes, cursor = await client.connection(lc.Q_LABELS, "issueLabels", {"team": team, "after": cursor})
            out.extend({"value": n["id"], "label": n["name"]} for n in nodes)
            if not cursor:
                break
    if not any(o["label"].lower() == "actron" for o in out):
        out.append({"value": "__create__", "label": "Create 'actron'", "create": "actron"})
    return out


# Setup checks (C13)
async def checks(provider: str, ws: str) -> list[CheckResult]:
    """Live checks for the in-app setup guide, from the saved connection (with `.env` fallbacks)."""
    runners = {"github": _checks_github, "slack": _checks_slack, "linear": _checks_linear}
    runner = runners.get(provider)
    if runner is None:
        return []
    config = (await asyncio.to_thread(resolve_config, ws, provider)).values
    return await runner(ws, config)


def _redis_flag(key: str) -> bool:
    import redis

    try:
        client = redis.Redis.from_url(get_settings().REDIS_URL, socket_timeout=3)
        try:
            return bool(client.exists(key))
        finally:
            client.close()
    except redis.RedisError:
        return False


async def _checks_github(ws: str, config: Mapping[str, Any]) -> list[CheckResult]:
    """Check ids are the `checkId`s of the GitHub guide in forms.json: token, push_access, working_branch,
    webhook_ping (plus `repository`, shown with the form)."""
    repo, token = config.get("repository"), config.get("token")
    out: list[CheckResult] = []
    if not repo:
        return [CheckResult("repository", "Repository", "failed", "No repository is set.",
                            "Fill in the repository as owner/name.")]
    async with GithubClient(token, base_url=config.get("api_url")) as client:
        info: dict[str, Any] | None = None
        repo_error: Exception | None = None
        try:
            info = await client.repository(repo)
            prs = await client.pull_count(repo)
            pr_text = f", {prs:,} pull requests" if isinstance(prs, int) else ""
            out.append(CheckResult("repository", "Repository found", "ok",
                                   f"{info['full_name']}, default branch {info.get('default_branch')}{pr_text}.",
                                   details={"default_branch": info.get("default_branch"), "pull_requests": prs}))
        except (ProviderError, ValidationError) as exc:
            repo_error = exc
            out.append(CheckResult("repository", "Repository found", "failed", explain_github_error(exc, repo=repo),
                                   explain_github_error(exc, repo=repo)))
        if not token:
            out.append(CheckResult("token", "Access token", "failed", "There is no access token yet.",
                                   "Create a fine-grained token and paste it on the Repository card."))
        elif isinstance(repo_error, AuthError):
            msg = explain_github_error(repo_error, repo=repo)
            out.append(CheckResult("token", "Access token", "failed", msg, msg))
        else:
            out.append(CheckResult("token", "Access token", "ok", "GitHub accepted the access token."))
        target = config.get("fork") or repo
        if not token:
            out.append(CheckResult("push_access", "Push access", "failed", "There is no token, so Actron cannot push.",
                                   "Paste a fine-grained token with Contents read and write."))
        else:
            can, message = await _can_push(client, str(target), info if target == repo else None)
            out.append(CheckResult("push_access", "Push access", "ok" if can else "failed", message,
                                   None if can else message, {"push_target": target}))
        branch = config.get("working_branch")
        if not branch:
            out.append(CheckResult("working_branch", "Working branch", "pending", "No working branch is chosen yet.",
                                   "Choose the branch your team builds on."))
        else:
            try:
                names = [b["name"] for b in await client.branches(str(repo))]
                ok = branch in names
                out.append(CheckResult("working_branch", "Working branch", "ok" if ok else "failed",
                                       f"Actron keeps {branch} in memory." if ok else f"{branch} does not exist in {repo}.",
                                       None if ok else "Choose a branch from the list."))
            except ProviderError as exc:
                out.append(CheckResult("working_branch", "Working branch", "failed", explain_github_error(exc, repo=repo),
                                       explain_github_error(exc, repo=repo)))
    public = (get_settings().ACTRON_PUBLIC_URL or "")
    if not public.startswith("https://"):
        out.append(CheckResult("webhook_ping", "Instant updates", "skipped",
                               "Actron has no public HTTPS address, so it polls GitHub every five minutes."))
    else:
        seen = await asyncio.to_thread(_redis_flag, f"github:ping:{ws}")
        out.append(CheckResult("webhook_ping", "Instant updates", "ok" if seen else "pending",
                               "GitHub's ping arrived and was verified." if seen else "Waiting for GitHub's ping.",
                               None if seen else WEBHOOK_TROUBLE))
    return out


APP_PENDING = "Waiting for the app: Actron confirms it once the bot token works."


async def _checks_slack(ws: str, config: Mapping[str, Any]) -> list[CheckResult]:
    """Check ids are the `checkId`s of the Slack guide in forms.json: app_created, auth_test, socket_mode,
    scopes, channels, command_received."""
    token, app_token = config.get("token"), config.get("app_token")
    out: list[CheckResult] = []
    if not token:
        return [CheckResult("app_created", "Slack app", "pending", APP_PENDING),
                CheckResult("auth_test", "Bot token", "failed", "There is no bot token yet.",
                            "Install the app and copy the Bot User OAuth Token.")]
    public = (get_settings().ACTRON_PUBLIC_URL or "")
    async with SlackClient(token, base_url=config.get("api_url")) as client:
        try:
            auth = await client.auth_test()
            out.append(CheckResult("app_created", "Slack app", "ok",
                                   f"The app is installed in {auth.get('team')} as @{auth.get('user')}."))
            out.append(CheckResult("auth_test", "Bot token", "ok",
                                   f"Connected to {auth.get('team')} as @{auth.get('user')}.",
                                   details={"team": auth.get("team"), "bot_user": auth.get("user")}))
        except ProviderError as exc:
            msg = explain_slack_error(exc.code)
            return [CheckResult("app_created", "Slack app", "pending", APP_PENDING),
                    CheckResult("auth_test", "Bot token", "failed", msg, msg, {"code": exc.code})]
        if public.startswith("https://"):
            out.append(CheckResult("socket_mode", "Socket Mode", "skipped",
                                   "Actron has a public HTTPS address, so Slack sends events there."))
        elif not app_token:
            out.append(CheckResult("socket_mode", "Socket Mode", "failed", "There is no app-level token.", SOCKET_TROUBLE))
        else:
            try:
                await client.open_socket_mode(str(app_token))
                out.append(CheckResult("socket_mode", "Socket Mode", "ok", "A Socket Mode connection opened."))
            except ProviderError:
                out.append(CheckResult("socket_mode", "Socket Mode", "failed", "Slack did not open a Socket Mode connection.",
                                       SOCKET_TROUBLE))
        granted = client.scopes
        needed = list(required_slack_scopes())
        missing = [x for x in needed if x not in granted]
        out.append(CheckResult(
            "scopes", "Permissions", "ok" if not missing else "failed",
            "Every permission Actron needs is granted." if not missing
            else f"Missing: {', '.join(missing)}.",
            None if not missing else explain_slack_error("missing_scope", missing=missing),
            {"granted": granted, "required": needed, "missing": missing}))
        try:
            member = await _channel_options({"bot_token": token, "api_url": config.get("api_url")})
            out.append(CheckResult("channels", "Channels", "ok" if member else "failed",
                                   f"Actron is in {len(member)} channel{'s' if len(member) != 1 else ''}." if member
                                   else "Actron is not in any channel yet.",
                                   None if member else explain_slack_error("not_in_channel"),
                                   {"channels": member}))
        except (ProviderError, SlackApiError) as exc:
            out.append(CheckResult("channels", "Channels", "failed", explain_slack_error(getattr(exc, "code", None)),
                                   explain_slack_error(getattr(exc, "code", None))))
    seen = await asyncio.to_thread(_redis_flag, f"slack:command_seen:{ws}")
    out.append(CheckResult("command_received", "Try it", "ok" if seen else "pending",
                           "Actron received /actron and replied." if seen else "Waiting for the first /actron command."))
    return out


async def _checks_linear(ws: str, config: Mapping[str, Any]) -> list[CheckResult]:
    from actron.integrations import linear_client as lc

    """Check ids are the `checkId`s of the Linear guide in forms.json: key_created, viewer, team (the team's
    issues can be read and the key may create tickets there)."""
    key, team = config.get("token"), config.get("team")
    if not key:
        return [CheckResult("key_created", "API key", "pending", "There is no API key yet.",
                            "Create a personal API key and paste it."),
                CheckResult("viewer", "API key", "failed", "There is no API key yet.",
                            "Create a personal API key and paste it.")]
    out: list[CheckResult] = []
    async with LinearClient(key, base_url=config.get("api_url")) as client:
        try:
            viewer = await client.viewer()
            org = (viewer.get("organization") or {}).get("name")
            out.append(CheckResult("key_created", "API key", "ok", "Linear accepted the API key."))
            out.append(CheckResult("viewer", "API key", "ok",
                                   f"Connected as {viewer.get('name')}" + (f" in {org}." if org else "."),
                                   details={"viewer": viewer.get("name"), "organization": org}))
        except (ProviderError, ValidationError) as exc:
            msg = explain_linear_error(exc)
            return [CheckResult("key_created", "API key", "failed", msg, msg),
                    CheckResult("viewer", "API key", "failed", msg, msg)]
        if not team:
            out.append(CheckResult("team", "Team", "pending", "No team is chosen yet.", "Choose the team."))
            return out
        problems: list[str] = []
        sample = 0
        try:
            nodes, _ = await client.connection(
                lc.Q_ISSUES, "issues", {"team": team, "since": "2000-01-01T00:00:00.000Z", "after": None})
            sample = len(nodes)
        except (ProviderError, ValidationError) as exc:
            problems.append("This key cannot see that team. Ask a team admin to add you, or choose another team."
                            if not isinstance(exc, AuthError) else explain_linear_error(exc))
        try:
            access = await client.query(lc.Q_TEAM_ACCESS, {"id": team})
            guest = bool((access.get("viewer") or {}).get("guest"))
            if access.get("team") is None or guest:
                problems.append("This key cannot create tickets in this team. Use a key from a member who can "
                                "create issues in the team (not a guest).")
        except (ProviderError, ValidationError) as exc:
            problems.append(explain_linear_error(exc))
        if problems:
            out.append(CheckResult("team", "Team", "failed", problems[0], " ".join(problems)))
        else:
            out.append(CheckResult("team", "Team", "ok", "Actron can read the team's issues and create tickets there.",
                                   details={"sample": sample}))
    return out
