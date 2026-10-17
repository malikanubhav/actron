"""Explicit local setup, connected runtime, source ingestion and measured experiments."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from actron.contracts import Payload, Rejected, Sources, Unavailable, canonical, digest

ROOT = Path(__file__).resolve().parents[1]


def required(*names: str) -> list[str]:
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise Rejected("Missing configuration: " + ", ".join(missing))
    return [os.environ[name] for name in names]


def environment_json(name: str, default: Any) -> Any:
    try:
        return json.loads(os.environ.get(name, json.dumps(default)))
    except ValueError as exc:
        raise Rejected(f"{name} must be JSON") from exc


def store() -> Any:
    from actron.graph import FalkorStore

    return FalkorStore(
        os.environ.get("FALKORDB_URL", "redis://127.0.0.1:6389"),
        os.environ.get("FALKORDB_GRAPH", "actron_demo"),
    )


def coding() -> Any:
    from actron.worker import CommandCoding

    command = environment_json("ACTRON_CODING_COMMAND", [])
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise Rejected(
            "ACTRON_CODING_COMMAND must be a nonempty JSON argv array for a real model CLI"
        )
    required("ACTRON_MODEL")
    return CommandCoding(
        command,
        image=os.environ.get("ACTRON_CODING_IMAGE", "actron-coding"),
        environment=environment_json("ACTRON_CODING_ENV", []),
    )


def run_runtime(args: argparse.Namespace) -> None:
    from actron.connectors import LinearTickets
    from actron.github import GitHubPRs
    from actron.ingestion import Investigator
    from actron.ingress import SlackAPI, SlackIngress, serve
    from actron.worker import RepositoryWorker
    from actron.workflow import Workflow

    token, secret, user, channel, linear, team, github, repository, dedicated, checkout = required(
        "SLACK_BOT_TOKEN",
        "SLACK_SIGNING_SECRET",
        "ACTRON_DEMO_USER",
        "ACTRON_DEMO_CHANNEL",
        "LINEAR_API_KEY",
        "LINEAR_TEAM_ID",
        "GITHUB_TOKEN",
        "GITHUB_REPOSITORY",
        "ACTRON_DEDICATED_REPOSITORY",
        "ACTRON_REPOSITORY",
    )
    worker = RepositoryWorker(
        checkout,
        os.environ.get("ACTRON_ARTIFACTS", ".actron/runs"),
        coding(),
        max_attempts=int(os.environ.get("ACTRON_MAX_ATTEMPTS", "2")),
        timeout=float(os.environ.get("ACTRON_TIMEOUT", "300")),
        max_tokens=int(os.environ.get("ACTRON_MAX_TOKENS", "12000")),
        check_commands={
            "exports": ["python", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
        },
    )
    graph = store()
    slack = SlackAPI(token, store=graph)
    prs = GitHubPRs(
        repository,
        github,
        dedicated,
        required_checks=environment_json("ACTRON_REQUIRED_CHECKS", ["suite"]),
        reviews_required=int(os.environ.get("ACTRON_REVIEWS_REQUIRED", "1")),
    )
    workflow = Workflow(
        graph,
        slack,
        LinearTickets(linear, team),
        prs,
        worker,
        Investigator(graph),
        {"demo_user": user, "demo_channel": channel},
    )
    ingress = SlackIngress(graph, workflow, secret)
    print(
        f"Listening on {args.host}:{args.port}; one durable dispatcher for graph {graph.graph}",
        flush=True,
    )
    # No lease expiry: after a crash an operator must confirm the old runtime is dead.
    with graph.lock("runtime"):
        serve(ingress, args.host, args.port)


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Actron demo",
            "-c",
            "user.email=demo@example.invalid",
            *arguments,
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def populate(args: argparse.Namespace) -> None:
    """Populate synthetic *source files*, not graph nodes; ingest via FileSources."""
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    repository = output / "repository"
    if not repository.exists():
        shutil.copytree(ROOT / "demo/repository", repository)
        git(repository, "init", "--initial-branch=main")
        git(repository, "add", ".")
        git(repository, "commit", "-m", "Synthetic export policy baseline")
    if git(repository, "status", "--porcelain"):
        raise Rejected("Demo source repository has uncommitted changes; commit before refreshing")
    base = git(repository, "rev-parse", "HEAD")
    data = json.loads((ROOT / "demo/sources/history.json").read_text())
    mapping = json.loads((ROOT / "demo/sources/code-map.json").read_text())
    files = {
        path: (repository / path).read_text()
        for path in mapping["paths"]
        if (repository / path).is_file()
    }
    records = data["records"] + [
        {
            "id": "repository:" + base,
            "provider": "git",
            "revision": base,
            "project": "atlas",
            "behavior": "report_export",
            "locator": repository.as_uri(),
            "content": canonical(files),
            "snapshot": {
                "repo": str(repository),
                "commit": base,
                "components": mapping["components"],
                "checks": mapping["checks"],
                "gaps": mapping["gaps"],
            },
        }
    ]
    path = output / "sources.json"
    path.write_text(json.dumps({"records": records}, indent=2))
    manifest = {
        "label": "Local synthetic connector sources; no external writes or live approvals",
        "sources": str(path),
        "repository": str(repository),
        "base": base,
        "project": "atlas",
        "behavior": "report_export",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


def populate_live(args: argparse.Namespace) -> None:
    """Write only explicitly named dedicated resources, then fetch through connectors."""
    from actron.connectors import GitHubSources, LinearSources, LinearTickets, SlackSources
    from actron.contracts import UnknownOutcome
    from actron.ingress import SlackAPI

    token, linear, github, channel, team, dedicated = required(
        "SLACK_BOT_TOKEN",
        "LINEAR_API_KEY",
        "GITHUB_TOKEN",
        "ACTRON_DEMO_CHANNEL",
        "LINEAR_TEAM_ID",
        "ACTRON_DEDICATED_REPOSITORY",
    )
    if not args.live or (args.channel, args.team, args.repository) != (channel, team, dedicated):
        raise Rejected(
            "Live population needs --live and explicit channel/team/repository matching demo env"
        )
    if len(dedicated.split("/")) != 2 or any(
        not x or not x.replace("-", "").replace("_", "").replace(".", "").isalnum()
        for x in dedicated.split("/")
    ):
        raise Rejected("Invalid dedicated GitHub owner/name")
    populate(args)
    output = Path(args.output).resolve()
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    ledger_path = output / "live-writes.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}

    def save() -> None:
        temporary = ledger_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(ledger, indent=2))
        temporary.replace(ledger_path)

    def once(key: str, action: Any) -> Any:
        if key in ledger:
            if ledger[key]["state"] != "confirmed":
                raise UnknownOutcome(
                    f"Population {key} uncertain; inspect provider before manual reconciliation"
                )
            return ledger[key]["result"]
        ledger[key] = {"state": "unknown"}
        save()
        result = action()
        ledger[key] = {"state": "confirmed", "result": result}
        save()
        return result

    repository = Path(manifest["repository"])
    remote = f"https://github.com/{dedicated}.git"
    existing = git(repository, "ls-remote", "--heads", remote)
    if existing and existing != manifest["base"] + "\trefs/heads/main":
        raise Rejected(
            "Dedicated repository must be empty or already contain only this exact baseline main"
        )
    if not existing:
        once("github-push", lambda: git(repository, "push", "--", remote, "HEAD:refs/heads/main"))
    history = json.loads((ROOT / "demo/sources/history.json").read_text())["records"]
    slack = SlackAPI(token)
    root = once(
        "slack-root",
        lambda: slack.post(
            channel,
            "Synthetic Northstar history. Fixture approvals describe historical evidence; they do not authorize Actron work.",
        ),
    )
    slack_mapping: Payload = {}
    for index, record in enumerate(item for item in history if item["provider"] == "slack"):
        timestamp = once(
            f"slack-message-{index}",
            lambda record=record: slack.post(channel, record["content"], root),
        )
        slack_mapping[timestamp] = {key: record[key] for key in ("project", "behavior", "claims")}
    records = SlackSources(token, channel, root, slack_mapping).fetch()["records"]
    tickets = LinearTickets(linear, team)
    operation = "actron-population:" + digest({"output": str(output), "repository": dedicated})[:20]
    first, second = [item for item in history if item["provider"] == "linear"]
    issue = once(
        "linear-create",
        lambda: (
            tickets.find(operation)
            or tickets.create(
                operation,
                {
                    "objective": "Synthetic ATLAS-17 original unapproved proposal",
                    "history": first["content"],
                },
            )
        ),
    )
    first_snapshot = once(
        "linear-source-v1",
        lambda: LinearSources(
            linear,
            [issue["id"]],
            {issue["id"]: {key: first[key] for key in ("project", "behavior", "claims")}},
        ).fetch(),
    )
    records.extend(first_snapshot["records"])
    once(
        "linear-update",
        lambda: tickets.update(
            issue["id"],
            {
                "objective": "Synthetic ATLAS-17 revised unapproved proposal",
                "history": second["content"],
            },
        ),
    )
    records.extend(
        LinearSources(
            linear,
            [issue["id"]],
            {issue["id"]: {key: second[key] for key in ("project", "behavior", "claims")}},
        ).fetch()["records"]
    )
    mapping = json.loads((ROOT / "demo/sources/code-map.json").read_text())
    records.extend(
        GitHubSources(github, dedicated, manifest["base"], "atlas", mapping).fetch()["records"]
    )
    live_sources = output / "live-sources.json"
    live_sources.write_text(json.dumps({"records": records}, indent=2))
    manifest.update(
        label="Real provider writes/reads of synthetic dedicated resources; no live workflow merge yet",
        sources=str(live_sources),
        repo=dedicated,
        channel=channel,
        thread=root,
        linear_issue=issue["id"],
        slack_mapping=slack_mapping,
        linear_mapping={
            issue["id"]: {key: second[key] for key in ("project", "behavior", "claims")}
        },
    )
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


def refresh_live(args: argparse.Namespace) -> None:
    """Read currently configured sources; preserve explicit mappings, never infer approval."""
    from actron.connectors import GitHubSources, LinearSources, SlackSources
    from actron.ingestion import Ingestor

    manifest = json.loads(Path(args.manifest).read_text())
    slack, linear, github = required("SLACK_BOT_TOKEN", "LINEAR_API_KEY", "GITHUB_TOKEN")
    graph = store()
    coordinator = Ingestor(graph)
    mapping = json.loads((ROOT / "demo/sources/code-map.json").read_text())
    sources: list[tuple[str, Sources]] = [
        (
            "live-slack",
            SlackSources(slack, manifest["channel"], manifest["thread"], manifest["slack_mapping"]),
        ),
        (
            "live-linear",
            LinearSources(linear, [manifest["linear_issue"]], manifest["linear_mapping"]),
        ),
        ("live-github", GitHubSources(github, manifest["repo"], args.ref, "atlas", mapping)),
    ]
    for name, source in sources:
        print(canonical(coordinator.sync(name, source)))


def ingest(args: argparse.Namespace) -> None:
    from actron.connectors import FileSources
    from actron.ingestion import Ingestor

    path = Path(args.source).resolve()
    # Future stimuli and evaluator answers must be deliberately separate forever.
    if "evaluator" in path.parts:
        raise Rejected("Evaluator/future sources cannot be ingested")
    print(canonical(Ingestor(store()).sync(args.id or str(path), FileSources(path))))


def investigate(args: argparse.Namespace) -> None:
    from actron.ingestion import Investigator

    print(
        json.dumps(
            Investigator(store()).evidence(args.project, args.behavior, args.repo, args.base),
            indent=2,
        )
    )


def demo(args: argparse.Namespace) -> None:
    print(
        "LOCAL PROVIDER-FAKE CONTRACT DEMO: real FalkorDB + disposable git/checks; "
        "Slack/Linear/GitHub authorization is simulated, not a live deployment.",
        flush=True,
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_ingress.py",
        "tests/test_workflow.py",
        "-v",
        "-s",
    ]
    raise SystemExit(subprocess.call(command, cwd=ROOT))


def live_smoke(args: argparse.Namespace) -> None:
    from actron.connectors import _linear, http_json
    from actron.ingress import SlackAPI

    token, linear, github = required("SLACK_BOT_TOKEN", "LINEAR_API_KEY", "GITHUB_TOKEN")
    slack = SlackAPI(token)
    result: Payload = {
        "slack": slack.call("auth.test", {}),
        "linear": _linear("https://api.linear.app/graphql", linear, "query{viewer{id name}}", {}),
        "github": http_json("https://api.github.com/user", github),
    }
    # Print IDs only; provider tokens and full user/profile payloads stay off stdout.
    print(
        canonical(
            {
                "slack_user": result["slack"].get("user_id"),
                "linear_user": result["linear"].get("viewer", {}).get("id"),
                "github_user": result["github"].get("login"),
            }
        )
    )
    if args.write:
        if not args.live:
            raise Rejected("External demo writes require --live --write")
        channel, team = required("ACTRON_DEMO_CHANNEL", "LINEAR_TEAM_ID")
        if args.channel != channel or args.team != team:
            raise Rejected("--channel and --team must explicitly match the isolated demo resources")
        from actron.connectors import LinearTickets

        operation = "actron-smoke:" + args.operation
        tickets = LinearTickets(linear, team)
        issue = tickets.find(operation) or tickets.create(
            operation,
            {
                "objective": "Actron isolated live integration smoke (synthetic)",
                "acceptance": ["Read-only auth plus explicitly requested isolated write"],
            },
        )
        ts = slack.post(channel, "Actron synthetic live smoke. Operation: " + operation)
        print(
            canonical(
                {
                    "issue": issue,
                    "slack_timestamp": ts,
                    "label": "Observed isolated writes; no end-to-end merge claim",
                }
            )
        )


def evaluate_command(args: argparse.Namespace) -> None:
    import uuid

    from actron.connectors import FileSources
    from actron.evaluation import evaluate
    from actron.graph import FalkorStore
    from actron.ingestion import Ingestor, Investigator

    manifest = json.loads(Path(args.manifest).read_text())
    records = json.loads(Path(manifest["sources"]).read_text())["records"]
    # Build a fresh historical graph for each comparison. A graph previously used
    # for delivery can contain merged outcomes that would leak future answers.
    source_path = Path(manifest["sources"]).resolve()
    if "evaluator" in source_path.parts:
        raise Rejected("Evaluator sources cannot become model comparison context")
    evaluation_graph = FalkorStore(
        os.environ.get("FALKORDB_URL", "redis://127.0.0.1:6389"),
        "actron_evaluation_" + uuid.uuid4().hex,
    )
    Ingestor(evaluation_graph).sync("historical-comparison", FileSources(source_path))
    context = Investigator(evaluation_graph).evidence(
        manifest["project"],
        manifest["behavior"],
        manifest.get("repo", manifest["repository"]),
        manifest["base"],
    )
    variants: dict[str, Payload] = {
        "request-only": {"request": "Allow project admins to export reports."},
        "flat-history": {"history": records},
        "graph-context": context,
    }
    report = evaluate(
        manifest["repository"],
        manifest["base"],
        coding(),
        variants,
        Path(args.output).resolve(),
        model=required("ACTRON_MODEL")[0],
        max_tokens=int(os.environ.get("ACTRON_MAX_TOKENS", "12000")),
        timeout=float(os.environ.get("ACTRON_TIMEOUT", "300")),
        max_attempts=int(os.environ.get("ACTRON_MAX_ATTEMPTS", "2")),
    )
    print(
        canonical(
            {
                "results": str(Path(args.output) / "results.json"),
                "variants": [
                    {
                        "name": item["variant"],
                        "status": item["worker"]["status"],
                        "acceptance": item["acceptance"]["status"],
                    }
                    for item in report["runs"]
                ],
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="actron")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the signed Slack HTTP dispatcher")
    run.add_argument("--host", default=os.environ.get("ACTRON_HOST", "127.0.0.1"))
    run.add_argument("--port", type=int, default=int(os.environ.get("ACTRON_PORT", "8080")))
    run.set_defaults(function=run_runtime)
    source = sub.add_parser(
        "populate", help="Create local synthetic connector sources and a git repo"
    )
    source.add_argument("--output", default=".actron/demo")
    source.set_defaults(function=populate)
    live = sub.add_parser(
        "populate-live", help="Write synthetic sources into explicitly isolated live resources"
    )
    live.add_argument("--live", action="store_true", required=True)
    live.add_argument("--channel", required=True)
    live.add_argument("--team", required=True)
    live.add_argument("--repository", required=True)
    live.add_argument("--output", default=".actron/live")
    live.set_defaults(function=populate_live)
    refresh = sub.add_parser(
        "refresh-live", help="Refresh connected source edits and current GitHub snapshot"
    )
    refresh.add_argument("--manifest", default=".actron/live/manifest.json")
    refresh.add_argument("--ref", default="main")
    refresh.set_defaults(function=refresh_live)
    ingestion = sub.add_parser(
        "ingest", help="Ingest a source JSON file through the file connector"
    )
    ingestion.add_argument("--source", default=".actron/demo/sources.json")
    ingestion.add_argument("--id")
    ingestion.set_defaults(function=ingest)
    evidence = sub.add_parser("investigate", help="Print provenance and current snapshot evidence")
    for name in ("project", "behavior", "repo", "base"):
        evidence.add_argument("--" + name, required=True)
    evidence.set_defaults(function=investigate)
    demonstration = sub.add_parser(
        "demo", help="Run the explicitly labelled local provider contract demo"
    )
    demonstration.set_defaults(function=demo)
    smoke = sub.add_parser(
        "live-smoke", help="Check real provider identity; explicit isolated writes optional"
    )
    smoke.add_argument("--live", action="store_true")
    smoke.add_argument("--write", action="store_true")
    smoke.add_argument("--channel")
    smoke.add_argument("--team")
    smoke.add_argument("--operation", default="manual-smoke")
    smoke.set_defaults(function=live_smoke)
    comparison = sub.add_parser(
        "evaluate", help="Execute all three contexts with the same real model"
    )
    comparison.add_argument("--manifest", default=".actron/demo/manifest.json")
    comparison.add_argument("--output", required=True)
    comparison.set_defaults(function=evaluate_command)
    args = parser.parse_args()
    try:
        args.function(args)
    except (Rejected, Unavailable, ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"actron: {exc}\n")


if __name__ == "__main__":
    main()
