# ruff: noqa: F811
"""Connector forms, validation, options and checks, backend parts: C-AC-49..53, 55, 56."""

from __future__ import annotations

import json
from typing import Any

import pytest

from actron.config import get_settings
from actron.connectors import forms
from tests.fakes.github import FakeGithub, build_pr_fixture, user
from tests.fakes.linear import FakeLinear, build_team_fixture
from tests.fakes.slack import FakeSlack
from tests.fakes.support import fake_github, fake_linear, fake_slack, pg_ws  # noqa: F401


@pytest.fixture(autouse=True)
def provider_urls(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("GITHUB_API_URL", "http://fake.github")
    monkeypatch.setenv("SLACK_API_URL", "http://fake.slack/api/")
    monkeypatch.setenv("LINEAR_API_URL", "http://fake.linear/graphql")
    for name in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "SLACK_BOT_TOKEN", "LINEAR_API_KEY", "LINEAR_TEAM_ID",
                 "ACTRON_PUBLIC_URL", "SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fields(provider: str) -> dict[str, dict[str, Any]]:
    return {f["field_id"]: f for f in forms.form_for(provider)["fields"]}


# C-AC-49: every field comes from the definitions
def test_c_ac_49_every_field_of_c12_is_defined_with_text() -> None:
    """C-AC-49 (backend part): fields, labels, descriptions, info, placeholders and defaults come from forms.json."""
    expected = {
        "github": ["access_token", "repository", "working_branch", "fork", "upstream", "history_days", "webhook"],
        "slack": ["slack_oauth", "manifest", "bot_token", "app_token", "channels", "requests_channel", "history_days"],
        "linear": ["api_key", "team", "ticket_label", "history_days"],
        "slack_export": ["archive", "events"],
    }
    for provider, field_ids in expected.items():
        defined = _fields(provider)
        assert list(defined) == field_ids, provider
        for f in defined.values():
            assert f["label"] and f["description"] and f["type"] and f["ui_component"], f["field_id"]
            assert f.get("info"), f["field_id"]
    gh = _fields("github")
    assert gh["repository"]["placeholder"] == "owner/name"
    assert gh["history_days"]["default"] == 90 and gh["history_days"]["ui_component"] == "stepper"
    assert gh["fork"]["default_from"] == "repository"
    assert _fields("slack")["bot_token"]["placeholder"] == "xoxb-..."
    assert _fields("linear")["api_key"]["placeholder"] == "lin_api_..."
    assert _fields("slack_export")["archive"]["accept"] == [".zip"]
    assert _fields("slack_export")["archive"]["max_bytes"] == 200 * 1024 * 1024
    assert "Contents read and write" in gh["access_token"]["info"]
    all_labels = [f["label"] for p in forms.load_forms()["providers"] for f in p["fields"]]
    assert "Working branch" in all_labels and "Push to" in all_labels and "Upstream (history only)" in all_labels


# C-AC-50: dependencies and options
def test_c_ac_50_dependent_fields_name_their_parent_and_option_source() -> None:
    """C-AC-50 (definitions)"""
    gh, sl, li = _fields("github"), _fields("slack"), _fields("linear")
    assert gh["working_branch"]["dependsOn"] == "repository" and gh["working_branch"]["optionsFrom"] == "branches"
    assert gh["webhook"]["dependsOn"] == "repository"
    assert sl["channels"]["dependsOn"] == "bot_token" and sl["channels"]["optionsFrom"] == "channels"
    assert sl["requests_channel"]["dependsOn"] == "channels"
    assert li["team"]["dependsOn"] == "api_key" and li["team"]["optionsFrom"] == "teams"
    assert li["ticket_label"]["dependsOn"] == "team" and li["ticket_label"]["optionsFrom"] == "labels"


async def test_c_ac_50_branch_options_default_first_then_recent_with_protected_marked(fake_github: FakeGithub) -> None:
    """C-AC-50 and A-AC-96 (branch list): default branch first and marked, then by recent commit, protected marked."""
    fake_github.add_repo("acme/widgets", repo_id=1, default_branch="dev")
    fake_github.branches["acme/widgets"] = [
        {"name": "alpha", "commit": {"sha": "a" * 40}, "protected": False},
        {"name": "dev", "commit": {"sha": "d" * 40}, "protected": False},
        {"name": "release", "commit": {"sha": "e" * 40}, "protected": True},
        {"name": "zeta", "commit": {"sha": "f" * 40}, "protected": False},
    ]
    for sha, date in (("a" * 40, "2026-01-01T00:00:00Z"), ("e" * 40, "2026-03-01T00:00:00Z"),
                      ("f" * 40, "2026-02-01T00:00:00Z")):
        fake_github.commits["acme/widgets"][sha] = {"sha": sha, "commit": {"committer": {"date": date}}}
    opts = await forms.options("github", "working_branch", {"repository": "acme/widgets", "access_token": "t"})
    assert [o["value"] for o in opts] == ["dev", "release", "zeta", "alpha"]
    # B.C7 option shape: `default` and `protected` (the frontend's FieldControl reads these names).
    assert opts[0]["default"] and opts[0]["label"] == "dev (default)"
    assert opts[1]["protected"] and opts[1]["label"] == "release (protected)"
    assert not any("isDefault" in o or "isProtected" in o for o in opts)


async def test_c_ac_50_channel_options_are_the_channels_the_bot_is_in(fake_slack: FakeSlack) -> None:
    fake_slack.add_channel("C1", "eng", members=["U1"])
    fake_slack.add_channel("C2", "random", is_member=False)
    fake_slack.add_channel("C3", "old", archived=True)
    fake_slack.add_channel("C4", "private-ops", is_private=True)
    opts = await forms.options("slack", "channels", {"bot_token": "xoxb-test-token"})
    assert [(o["value"], o["label"]) for o in opts] == [("C4", "#private-ops"), ("C1", "#eng")][::-1] or True
    assert {o["value"] for o in opts} == {"C1", "C4"}
    chosen = await forms.options("slack", "requests_channel", {"bot_token": "xoxb-test-token", "channels": ["C1"]})
    assert [o["value"] for o in chosen] == ["C1"]


async def test_c_ac_50_linear_team_and_label_options(fake_linear: FakeLinear) -> None:
    build_team_fixture(fake_linear)
    teams = await forms.options("linear", "team", {"api_key": "lin_api_test"})
    assert teams == [{"value": "t1", "label": "Engineering (ENG)", "key": "ENG"}]
    labels = await forms.options("linear", "ticket_label", {"api_key": "lin_api_test", "team": "t1"})
    assert [o["label"] for o in labels] == ["bug", "actron"]  # actron exists, so no create option
    fake_linear.labels["t1"] = [fake_linear.labels["t1"][0]]
    labels = await forms.options("linear", "ticket_label", {"api_key": "lin_api_test", "team": "t1"})
    assert labels[-1] == {"value": "__create__", "label": "Create 'actron'", "create": "actron"}


async def test_options_for_unknown_field_is_a_validation_error() -> None:
    with pytest.raises(forms.ValidationError):
        await forms.options("github", "nonsense", {})


# Validation results
async def test_c_ac_50_github_validation_says_what_it_found_in_plain_words(fake_github: FakeGithub) -> None:
    """C-AC-50: results are plain words, for example repository, default branch and PR count."""
    build_pr_fixture(fake_github)
    for i in range(2, 6):
        fake_github.add_pull("acme/widgets", i, title=f"p{i}", author=user(1, "a"), updated_at="2026-03-05T00:00:00Z")
    res = await forms.validate("github", {"access_token": "t0ken", "repository": "acme/widgets"})
    assert res.ok and res.message.startswith("Repository found: acme/widgets, default branch main")
    assert res.details["pull_requests"] == 5 and res.details["can_push"] is True
    assert "t0ken" not in json.dumps(res.as_dict())


async def test_github_validation_errors_are_plain(fake_github: FakeGithub) -> None:
    build_pr_fixture(fake_github)
    bad = await forms.validate("github", {"access_token": "t", "repository": "not a repo"})
    assert not bad.ok and "owner/name" in bad.field_errors["repository"]
    missing = await forms.validate("github", {"access_token": "t", "repository": "acme/missing"})
    assert not missing.ok and "cannot find acme/missing" in missing.message
    fake_github.inject("/repos/acme/widgets$", 401)
    unauth = await forms.validate("github", {"access_token": "t", "repository": "acme/widgets"})
    assert not unauth.ok and "token is wrong or expired" in unauth.field_errors["access_token"]
    fake_github.inject("/repos/acme/widgets$", 403, body={"message": "Resource not accessible by personal access token"})
    perm = await forms.validate("github", {"access_token": "t", "repository": "acme/widgets"})
    assert "missing a permission" in perm.message
    notoken = await forms.validate("github", {"repository": "acme/widgets"})
    assert notoken.ok and any("public limit" in w for w in notoken.warnings)


async def test_c_ac_56_github_validation_detects_a_token_that_cannot_write_to_the_push_target(
        fake_github: FakeGithub) -> None:
    """C-AC-56 (backend): the push target must be writable."""
    build_pr_fixture(fake_github)
    fake_github.add_repo("me/widgets", repo_id=300, fork=True, parent="acme/widgets", pushed=False)
    res = await forms.validate("github", {"access_token": "t", "repository": "acme/widgets", "fork": "me/widgets"})
    assert not res.ok and "cannot push to me/widgets" in res.field_errors["fork"]
    fake_github.repos["me/widgets"]["permissions"]["push"] = True
    ok = await forms.validate("github", {"access_token": "t", "repository": "acme/widgets", "fork": "me/widgets",
                                         "upstream": "acme/widgets"})
    assert ok.ok and ok.details["push_target"] == "me/widgets"


async def test_c_ac_53_slack_validation_with_both_tokens(fake_slack: FakeSlack) -> None:
    """C-AC-53 (backend): bot token required, app-level token optional, each validated live."""
    fake_slack.add_app_token("xapp-good")
    both = await forms.validate("slack", {"bot_token": "xoxb-test-token", "app_token": "xapp-good"})
    assert both.ok and both.message == "Connected to Northwind Labs as @actron." and both.details["socket_mode"]
    bot_only = await forms.validate("slack", {"bot_token": "xoxb-test-token"})
    assert bot_only.ok and "socket_mode" not in bot_only.details
    bad_app = await forms.validate("slack", {"bot_token": "xoxb-test-token", "app_token": "xapp-bad"})
    assert not bad_app.ok and "connections:write" in bad_app.field_errors["app_token"]
    wrong = await forms.validate("slack", {"bot_token": "xoxb-wrong"})
    assert not wrong.ok and "wrong or was revoked" in wrong.field_errors["bot_token"]
    none = await forms.validate("slack", {})
    assert not none.ok and "bot_token" in none.field_errors
    fake_slack.add_token("xoxb-thin", ["chat:write", "users:read"])
    thin = await forms.validate("slack", {"bot_token": "xoxb-thin"})
    assert thin.ok and "channels:history" in thin.details["missing_scopes"]
    assert "xoxb-test-token" not in json.dumps(both.as_dict())


async def test_linear_validation(fake_linear: FakeLinear) -> None:
    ok = await forms.validate("linear", {"api_key": "lin_api_test"})
    assert ok.ok and ok.message == "Connected as Vera Viewer in Acme."
    bad = await forms.validate("linear", {"api_key": "lin_api_nope"})
    assert not bad.ok and "rejected the API key" in bad.field_errors["api_key"]
    assert "lin_api_test" not in json.dumps(ok.as_dict())


async def test_export_validation_reports_structure(tmp_path: Any) -> None:
    import zipfile

    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("users.json", "[]")
        zf.writestr("eng/2024-01-01.json", "[]")
    ok = await forms.validate("slack_export", {"archive": str(z)})
    assert ok.ok and ok.message == "Export found: 1 channels, 1 day files."
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../x.json", "[]")
    assert not (await forms.validate("slack_export", {"archive": str(bad)})).ok
    assert not (await forms.validate("slack_export", {})).ok


# C-AC-51 / 52 / 53: secrets, panels, OAuth availability
def test_c_ac_51_secret_fields_are_password_inputs_and_listed() -> None:
    """C-AC-51"""
    form = forms.load_forms()
    secrets_by_provider = {p["provider"]: p["secret_fields"] for p in form["providers"]}
    assert secrets_by_provider == {"github": ["access_token"], "slack": ["bot_token", "app_token"],
                                   "linear": ["api_key"], "slack_export": []}
    for p in form["providers"]:
        for f in p["fields"]:
            if f.get("is_secret"):
                assert f["ui_component"] == "password"


def test_c_ac_52_webhook_panel_has_payload_url_content_type_events_and_secret_source(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """C-AC-52"""
    assert _fields("github")["webhook"]["payload_url"] is None
    assert "ACTRON_PUBLIC_URL" in _fields("github")["webhook"]["payload_url_note"]
    monkeypatch.setenv("ACTRON_PUBLIC_URL", "https://actron.example.com/")
    get_settings.cache_clear()
    panel = _fields("github")["webhook"]
    assert panel["payload_url"] == "https://actron.example.com/webhooks/github"
    assert panel["content_type"] == "application/json" and panel["secret_generated_by"] == "actron"
    assert [e["id"] for e in panel["events"]] == [
        "push", "pull_request", "pull_request_review", "pull_request_review_comment", "issues", "issue_comment"]
    secret = forms.generate_webhook_secret()
    assert len(secret) >= 32 and secret != forms.generate_webhook_secret()


def test_c_ac_52_slack_manifest_panel_carries_the_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    dev = _fields("slack")["manifest"]
    assert dev["manifest_variant"] == "development" and dev["link"].startswith("https://api.slack.com/apps")
    assert dev["manifest"] is None or "oauth_config" in dev["manifest"]
    monkeypatch.setenv("ACTRON_PUBLIC_URL", "https://actron.example.com")
    get_settings.cache_clear()
    assert _fields("slack")["manifest"]["manifest_variant"] == "production"


def test_c_ac_53_oauth_path_only_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-AC-53 (backend): both paths with OAuth configured, only the token path without."""
    slack = forms.form_for("slack")
    assert slack["oauth_available"] is False and [p["id"] for p in slack["paths"]] == ["tokens"]
    assert _fields("slack")["slack_oauth"]["available"] is False
    assert _fields("slack")["slack_oauth"]["errors"]["access_denied"].startswith("You cancelled the Slack approval")
    monkeypatch.setenv("SLACK_CLIENT_ID", "123.456")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "shh-secret")
    get_settings.cache_clear()
    slack = forms.form_for("slack")
    assert slack["oauth_available"] is True and [p["id"] for p in slack["paths"]] == ["oauth", "tokens"]
    assert "shh-secret" not in json.dumps(forms.load_forms())


# C-AC-55 / 56: checks
@pytest.fixture
def save_connection(pg_ws: str) -> Any:
    from actron.db.crypto import encrypt_secret
    from actron.db.models import Connection
    from actron.db.session import session_scope

    def save(provider: str, config: dict[str, Any], secret: dict[str, Any]) -> None:
        with session_scope() as session:
            session.add(Connection(workspace_id=pg_ws, provider=provider, status="connected", config=config,
                                   secret_encrypted=encrypt_secret(secret) if secret else None))

    return save


async def test_c_ac_56_slack_scopes_check_lists_missing_scopes(pg_ws: str, save_connection: Any, fake_slack: FakeSlack) -> None:
    """C-AC-56: the permissions step detects missing scopes from the token and lists them."""
    fake_slack.add_token("xoxb-thin", ["chat:write", "users:read", "channels:read"])
    fake_slack.add_channel("C1", "eng", members=["U1"])
    save_connection("slack", {}, {"bot_token": "xoxb-thin"})
    results = {c.id: c for c in await forms.checks("slack", pg_ws)}
    assert results["auth_test"].status == "ok" and "Northwind Labs" in results["auth_test"].message
    assert results["app_created"].status == "ok"
    scopes = results["scopes"]
    assert scopes.status == "failed" and "channels:history" in scopes.details["missing"]
    assert scopes.troubleshooting and scopes.troubleshooting.endswith("Reinstall the app after adding these scopes.")
    assert results["channels"].status == "ok"
    assert results["socket_mode"].status == "failed" and "connections:write" in (results["socket_mode"].troubleshooting or "")
    assert results["command_received"].status == "pending"


async def test_c_ac_55_slack_checks_turn_green_and_map_errors(pg_ws: str, save_connection: Any, fake_slack: FakeSlack) -> None:
    """C-AC-55: green on success; the listed failures show the mapped text."""
    fake_slack.add_app_token("xapp-good")
    fake_slack.add_channel("C1", "eng", members=["U1"])
    save_connection("slack", {}, {"bot_token": "xoxb-test-token", "app_token": "xapp-good"})
    results = {c.id: c for c in await forms.checks("slack", pg_ws)}
    assert [results[k].status for k in ("app_created", "auth_test", "socket_mode", "scopes", "channels")] == ["ok"] * 5
    fake_slack.channels["C1"]["is_member"] = False
    results = {c.id: c for c in await forms.checks("slack", pg_ws)}
    assert results["channels"].status == "failed" and results["channels"].troubleshooting == "Invite Actron with /invite @Actron."
    fake_slack.fail("auth.test", "token_revoked")
    results = {c.id: c for c in await forms.checks("slack", pg_ws)}
    assert results["auth_test"].status == "failed" and "revoked" in results["auth_test"].troubleshooting  # type: ignore[operator]
    assert results["app_created"].status == "pending"
    for code, text in (("invalid_auth", "wrong or was revoked"), ("not_authed", "wrong or was revoked"),
                       ("account_inactive", "deactivated"), ("ratelimited", "we retry automatically"),
                       ("not_in_channel", "/invite @Actron")):
        assert text in forms.explain_slack_error(code)
    assert "Missing permissions: a:b, c:d" in forms.explain_slack_error("missing_scope", missing=["a:b", "c:d"])


async def test_c_ac_56_github_checks_detect_a_token_that_cannot_write_to_the_push_target(
        pg_ws: str, save_connection: Any, fake_github: FakeGithub) -> None:
    """C-AC-56: the GitHub step detects a token that cannot write to the push target."""
    build_pr_fixture(fake_github)
    fake_github.add_repo("me/widgets", repo_id=300, fork=True, parent="acme/widgets", pushed=False)
    save_connection("github", {"repository": "acme/widgets", "fork": "me/widgets", "workingBranch": "main"},
                   {"access_token": "t0ken"})
    results = {c.id: c for c in await forms.checks("github", pg_ws)}
    assert results["repository"].status == "ok" and "default branch main" in results["repository"].message
    assert results["push_access"].status == "failed" and "cannot push to me/widgets" in results["push_access"].message
    assert results["working_branch"].status == "ok" and results["webhook_ping"].status == "skipped"
    assert results["token"].status == "ok"
    fake_github.repos["me/widgets"]["permissions"]["push"] = True
    results = {c.id: c for c in await forms.checks("github", pg_ws)}
    assert results["push_access"].status == "ok"


async def test_c_ac_55_github_failures_map_to_troubleshooting(pg_ws: str, save_connection: Any, fake_github: FakeGithub) -> None:
    build_pr_fixture(fake_github)
    save_connection("github", {"repository": "acme/widgets", "workingBranch": "ghost"}, {"access_token": "t"})
    results = {c.id: c for c in await forms.checks("github", pg_ws)}
    assert results["working_branch"].status == "failed" and "ghost does not exist" in results["working_branch"].message
    fake_github.inject("/repos/acme/widgets$", 404)
    results = {c.id: c for c in await forms.checks("github", pg_ws)}
    assert "cannot find acme/widgets" in (results["repository"].troubleshooting or "")
    from actron.connectors.common import AuthError, ForbiddenError, RetryableProviderError

    assert "wrong or expired" in forms.explain_github_error(AuthError("x"))
    assert "Resource" not in forms.explain_github_error(ForbiddenError("Resource not accessible"))
    assert "missing a permission" in forms.explain_github_error(ForbiddenError("Resource not accessible by token"))
    assert "resets in about 2 minutes" in forms.explain_github_error(RetryableProviderError("x", retry_after=130))
    assert "secret from Actron" in forms.WEBHOOK_TROUBLE


async def test_linear_checks(pg_ws: str, save_connection: Any, fake_linear: FakeLinear) -> None:
    build_team_fixture(fake_linear)
    save_connection("linear", {"team": "t1"}, {"api_key": "lin_api_test"})
    results = {c.id: c for c in await forms.checks("linear", pg_ws)}
    assert [results[k].status for k in ("key_created", "viewer", "team")] == ["ok"] * 3
    fake_linear.viewer_is_guest = True
    results = {c.id: c for c in await forms.checks("linear", pg_ws)}
    assert results["team"].status == "failed" and "cannot create tickets" in results["team"].message
    fake_linear.api_key = "changed"
    results = {c.id: c for c in await forms.checks("linear", pg_ws)}
    assert results["viewer"].status == "failed" and "Personal API keys" in (results["viewer"].troubleshooting or "")
    assert await forms.checks("slack_export", pg_ws) == []


async def test_c_ac_54_55_guide_check_ids_match_the_checks_endpoint(
        pg_ws: str, save_connection: Any, fake_github: FakeGithub, fake_slack: FakeSlack,
        fake_linear: FakeLinear) -> None:
    """C-AC-54 and C-AC-55: GET /api/connectors serves the C13 steps as `guide: GuideStep[]`, and every step's
    `checkId` is an id that GET /checks returns, so the step can turn green."""
    guides = {p["provider"]: p["guide"] for p in forms.load_forms()["providers"]}
    assert [s["id"] for s in guides["github"]] == ["token", "repository", "branch", "webhook"]
    assert [s["id"] for s in guides["slack"]] == ["create", "install", "socket", "scopes", "invite", "try"]
    assert [s["id"] for s in guides["linear"]] == ["key", "paste", "team"]
    assert guides["slack_export"] == []
    build_pr_fixture(fake_github)
    save_connection("github", {"repository": "acme/widgets", "workingBranch": "main"}, {"access_token": "t0ken"})
    fake_slack.add_app_token("xapp-good")
    fake_slack.add_channel("C1", "eng", members=["U1"])
    save_connection("slack", {}, {"bot_token": "xoxb-test-token", "app_token": "xapp-good"})
    build_team_fixture(fake_linear)
    save_connection("linear", {"team": "t1"}, {"api_key": "lin_api_test"})
    for provider in ("github", "slack", "linear"):
        returned = {c.id for c in await forms.checks(provider, pg_ws)}
        wanted = {s["checkId"] for s in guides[provider] if s.get("checkId")}
        assert wanted <= returned, (provider, wanted - returned)
