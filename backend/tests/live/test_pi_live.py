"""The real `actron-pi` image (spec B, B-AC-48).

The image checks run whenever Docker and the image exist. The prompt check is `live`: it needs a model key
(MODEL_CODING and its provider key in .env) and is skipped without one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from actron.config import get_settings
from actron.flow.build import BuildEnv, BuildStop
from actron.flow.test_runner import docker_env

IMAGE = "actron-pi:latest"
PI_VERSION = "1.3.0"

pytestmark = pytest.mark.timeout(600)


def _image() -> str:
    if shutil.which("docker") is None:
        pytest.skip("Docker is not available")
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        pytest.skip(f"{IMAGE} is not built (docker build -f infra/docker/pi.Dockerfile -t {IMAGE} .)")
    return IMAGE


def _run(*args: str, env: dict[str, str] | None = None, network: str = "none") -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "run", "--rm", "--network", network, "--read-only", "--tmpfs", "/tmp"]
    for k, v in (env or {}).items():
        cmd += ["-e", f"{k}={v}"]
    return subprocess.run([*cmd, _image(), *args], capture_output=True, text=True, timeout=120)


def test_pi_version_and_help() -> None:
    """B-AC-48: the image builds and `pi --version` / `--help` run (read-only root, tmpfs /tmp, no network)."""
    out = _run("--version")
    assert out.returncode == 0 and out.stdout.strip() == PI_VERSION
    help_text = _run("--help").stdout
    for flag in ("--mode <mode>", "--session-dir", "--session-id", "--append-system-prompt", "--no-approve",
                 "--model <pattern>"):
        assert flag in help_text


def test_image_tools_and_user() -> None:
    """B-AC-48: Node 22.19+, git, Python 3.12, a JDK 17+, non-root user."""
    probe = ("node --version && git --version && python3 --version && java -version 2>&1 | head -1 && id -u")
    out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "sh", _image(), "-c", probe],
                         capture_output=True, text=True, timeout=120)
    lines = out.stdout.splitlines()
    major, minor = (int(x) for x in lines[0].lstrip("v").split(".")[:2])
    assert (major, minor) >= (22, 19)
    assert lines[1].startswith("git version") and lines[2].startswith("Python 3.12")
    assert '"17.' in lines[3] or '"21.' in lines[3]
    assert lines[4] == "1000"


def test_provider_names_for_model_keys() -> None:
    """B-AC-48: the LiteLLM-style prefixes map to Pi providers that exist in the image's catalog."""
    for prefix, key, search in (("anthropic", "ANTHROPIC_API_KEY", "claude-sonnet-4-5"),
                                ("openrouter", "OPENROUTER_API_KEY", "anthropic/claude-sonnet-4.5"),
                                ("gemini", "GEMINI_API_KEY", "gemini-2.5-flash"),
                                ("groq", "GROQ_API_KEY", "llama-3.3-70b")):
        env = BuildEnv(host_dir=Path("/tmp"), model_coding=f"{prefix}/{search}", model_keys={key: "dummy-key-1"})
        model, key_name = env.model_choice()
        provider = model.split("/", 1)[0]
        out = _run("--offline", "--list-models", search, env={key_name: "dummy-key-1"})
        assert any(line.split()[:1] == [provider] for line in out.stdout.splitlines()[1:]), out.stdout


def test_json_mode_session_and_system_prompt_without_key(tmp_path: Path) -> None:
    """B-AC-48 (without a model key): JSON mode starts, appends TASK.md to the system prompt, persists the
    session under --session-dir with --session-id, and resumes the same file on the next run."""
    ctx, work, session = tmp_path / "context", tmp_path / "work", tmp_path / "session"
    for d in (ctx, work, session):
        d.mkdir()
    (ctx / "TASK.md").write_text("# Task\nMARKER-TASK-TEXT\n")

    def run(prompt: str) -> list[dict[str, object]]:
        cmd = ["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp", "--user",
               "1000:1000", "-v", f"{work}:/work", "-v", f"{ctx}:/context:ro", "-v", f"{session}:/session",
               "-e", "ANTHROPIC_API_KEY=dummy-key-1", _image(), "--mode", "json", "--no-approve", "--model",
               "anthropic/claude-sonnet-4-5", "--session-dir", "/session", "--session-id", "actron-live1",
               "--append-system-prompt", "/context/TASK.md", prompt]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return [json.loads(line) for line in out.stdout.splitlines() if line.startswith("{")]

    first = run("Follow /context/TASK.md exactly. Start with step 1.")
    assert first[0]["type"] == "session" and first[0]["id"] == "actron-live1"
    assert "MARKER-TASK-TEXT" in json.dumps(first[:6])
    errors = [e for e in first if e.get("type") == "message_end"
              and (e.get("message") or {}).get("stopReason") == "error"]  # type: ignore[union-attr]
    assert errors, "without network the model call must fail, and Pi reports it as an error message"
    files = list(session.glob("*_actron-live1.jsonl"))
    assert len(files) == 1
    size = files[0].stat().st_size
    run("This is attempt 2.")
    assert list(session.glob("*_actron-live1.jsonl")) == files and files[0].stat().st_size > size


def test_mcp_http_config_from_env_reaches_server(tmp_path: Path) -> None:
    """B-AC-48: the entry wrapper writes mcp.json from ACTRON_MCP_URL; Pi connects over streamable HTTP and
    sends the run token from ACTRON_RUN_TOKEN as X-Actron-Run."""
    probe = tmp_path / "probe.py"
    probe.write_text(PROBE)
    log = tmp_path / "probe.log"
    port = "18766"
    with log.open("w") as fh:
        server = subprocess.Popen([sys.executable, str(probe), port], stdout=fh, stderr=subprocess.STDOUT)
    try:
        time.sleep(4)
        out = _run("mcp", "list", "--json", env={"ACTRON_MCP_URL": f"http://127.0.0.1:{port}/mcp",
                                                 "ACTRON_RUN_TOKEN": "run-tok-live"}, network="host")
        data = json.loads(out.stdout)
        server_state = data["servers"][0]
        assert server_state["name"] == "actron" and server_state["state"] == "connected"
        assert server_state["exposure"] == "direct" and server_state["tools"] == ["callers"]
        assert "x-actron-run = run-tok-live" in log.read_text()
    finally:
        server.terminate()
        server.wait(timeout=10)


PROBE = '''
import sys, uvicorn
from mcp.server.mcpserver import MCPServer
server = MCPServer("actron-probe")
@server.tool()
def callers(functionId: str) -> list[dict]:
    """Who calls a function."""
    return []
inner = server.streamable_http_app()
async def app(scope, receive, send):
    if scope["type"] == "http":
        for k, v in scope["headers"]:
            if k == b"x-actron-run":
                print("x-actron-run =", v.decode(), flush=True)
    await inner(scope, receive, send)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
'''


@pytest.mark.live
def test_trivial_prompt_with_model_key(tmp_path: Path) -> None:
    """B-AC-48: with a model key, a trivial prompt completes (skipped without MODEL_CODING and its key)."""
    try:
        model, key_name = BuildEnv.from_settings().model_choice()
    except BuildStop as stop:
        pytest.skip(f"no model key: {stop.message}")
    key = BuildEnv.from_settings().model_keys[key_name]
    cmd = ["docker", "run", "--rm", "--read-only", "--tmpfs", "/tmp", "-e", key_name, _image(), "--mode", "json",
           "--no-session", "--no-approve", "--model", model, "Reply with the single word: ready"]
    env = {**docker_env(), key_name: key}
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    ends = [json.loads(line) for line in out.stdout.splitlines() if line.startswith('{"type":"message_end"')]
    texts = [c.get("text", "") for e in ends if e["message"].get("role") == "assistant"
             for c in e["message"].get("content") or [] if isinstance(c, dict)]
    assert any("ready" in t.lower() for t in texts), out.stdout[-2000:]
    assert get_settings().MODEL_CODING
