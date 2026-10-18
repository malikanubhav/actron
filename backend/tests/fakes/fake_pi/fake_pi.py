#!/usr/bin/env python3
"""Labelled fake Pi (spec B, B9 tests). Speaks Pi's `--mode json` event stream and edits the synthetic repo.

Runs through the same `docker run` command as the real Pi (image `actron-fake-pi:test`); the scenario comes
from FAKE_PI_SCENARIO. The synthetic repository is built by tests/integration/build/conftest.py:
`calc/ops.py` (add, total), `calc/other.py`, `tests/test_ops.py`.

Scenarios: success, env_dump, fail_then_repair, weakened_delete, weakened_skip, timeout, scope_change, stop_md,
explorer, explorer_light, no_plan, no_report, no_tests_after_edit, edits_without_callers.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time

WORK = "/work"
CTX = "/context"
ADD_ID = "code:fn:acme/calc:calc/ops.py::add"
_call = 0


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def tool(name: str, args: dict, run=None) -> str:
    global _call
    _call += 1
    cid = f"call_{_call}"
    emit({"type": "tool_execution_start", "toolCallId": cid, "toolName": name, "args": args})
    text, err = "", False
    try:
        text = run() if run else "ok"
    except Exception as exc:  # report like Pi does
        text, err = str(exc), True
    emit({"type": "tool_execution_end", "toolCallId": cid, "toolName": name,
          "result": {"content": [{"type": "text", "text": str(text)[:500]}]}, "isError": err, "durationMs": 1})
    return str(text)


def say(text: str, inp: int = 0, out: int = 0) -> None:
    usage = {"input": inp, "output": out, "cacheRead": 0, "cacheWrite": 0, "totalTokens": inp + out}
    msg = {"role": "assistant", "content": [{"type": "text", "text": text}], "stopReason": "stop", "usage": usage}
    emit({"type": "message_start", "message": {"role": "assistant", "content": []}})
    emit({"type": "message_end", "message": msg})


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as f:  # in place: some targets are bind-mounted files
        f.write(text)
    return "written"


def append(path: str, text: str) -> str:
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    return "edited"


def replace(path: str, old: str, new: str) -> str:
    body = read(path)
    if old not in body:
        raise RuntimeError(f"text not found in {path}")
    return write(path, body.replace(old, new, 1))


def run_tests() -> str:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=WORK,
                          capture_output=True, text=True, env=env, timeout=120)
    return proc.stdout[-1500:]


def session(args: list[str]) -> str:
    sid = args[args.index("--session-id") + 1] if "--session-id" in args else "none"
    sdir = args[args.index("--session-dir") + 1] if "--session-dir" in args else "/tmp"
    existing = glob.glob(os.path.join(sdir, f"*_{sid}.jsonl"))
    path = existing[0] if existing else os.path.join(sdir, f"2026-10-17T00-00-00-000Z_{sid}.jsonl")
    entries = 0
    if existing:
        with open(path, encoding="utf-8") as f:
            entries = sum(1 for _ in f)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "message", "prompt": args[-1]}) + "\n")
    emit({"type": "session", "version": 3, "id": sid, "timestamp": "2026-10-17T00:00:00.000Z", "cwd": WORK})
    return f"Resumed session with {entries} earlier entries" if existing else "New session"


SUBTRACT_BUGGY = "\n\ndef subtract(a, b):\n    return a + b  # subtract\n"
SUBTRACT_OK = "\n\ndef subtract(a, b):\n    return a - b\n"
TEST_SUBTRACT = "\n\ndef test_subtract():\n    assert subtract(5, 3) == 2\n"
REPORT = {
    "filesChanged": ["calc/ops.py", "tests/test_ops.py"],
    "testsAdded": ["tests/test_ops.py::test_subtract"],
    "testCommand": "pytest -q",
    "testsPassed": True,
    "constraintsPreserved": [{"constraint": "add keeps its signature", "how": "test_add still passes"}],
    "stopped": False,
    "notes": "Added subtract next to add and a test for it.",
}


def plan() -> None:
    tool("write", {"path": f"{CTX}/notes.md", "content": "# Plan\n..."},
         lambda: write(f"{CTX}/notes.md", "# Plan\n- Add subtract to calc/ops.py\n- Add test_subtract\n"))


def start_reading() -> None:
    tool("read", {"path": f"{CTX}/code.md"}, lambda: read(f"{CTX}/code.md")[:200])
    tool("read", {"path": f"{CTX}/notes.md"}, lambda: read(f"{CTX}/notes.md")[:200])


def add_subtract(buggy: bool = False) -> None:
    tool("edit", {"path": "calc/ops.py", "edits": [{"oldText": "", "newText": "def subtract"}]},
         lambda: append(f"{WORK}/calc/ops.py", SUBTRACT_BUGGY if buggy else SUBTRACT_OK))
    tool("edit", {"path": "tests/test_ops.py", "edits": [{"oldText": "", "newText": "def test_subtract"}]},
         lambda: (replace(f"{WORK}/tests/test_ops.py", "from calc.ops import add, total",
                          "from calc.ops import add, subtract, total"),
                  append(f"{WORK}/tests/test_ops.py", TEST_SUBTRACT))[1])


def finish(report: dict | None = REPORT, notes: bool = True) -> None:
    if notes:
        tool("edit", {"path": f"{CTX}/notes.md", "edits": []},
             lambda: append(f"{CTX}/notes.md", "\n## Done\nChanged calc/ops.py; ran pytest -q.\n"))
    if report is not None:
        tool("write", {"path": f"{CTX}/REPORT.json", "content": "{...}"},
             lambda: write(f"{CTX}/REPORT.json", json.dumps(report)))
    say("Finished the task.", inp=1200, out=300)


def happy(*, callers: bool = True, buggy: bool = False, do_plan: bool = True, report: bool = True,
          tests_last: bool = True) -> None:
    start_reading()
    if do_plan:
        plan()
    if callers:
        tool("mcp__actron__callers", {"functionId": ADD_ID, "depth": 1}, lambda: "[]")
    if not tests_last:
        tool("bash", {"command": "pytest -q"}, run_tests)
    add_subtract(buggy=buggy)
    if tests_last:
        tool("bash", {"command": "pytest -q"}, run_tests)
    rep = dict(REPORT, testsPassed=not buggy)
    finish(rep if report else None)


def explore(times: int) -> None:
    targets = [("ls", {"path": "."}), ("grep", {"pattern": "def ", "path": "."}),
               ("read", {"path": "calc/other.py"}), ("bash", {"command": "find . -name '*.py'"}),
               ("bash", {"command": "grep -rn total ."}), ("read", {"path": "pyproject.toml"})]
    for i in range(times):
        name, args = targets[i % len(targets)]
        tool(name, args, lambda: "listing")
        time.sleep(0.05)


def main() -> None:
    args = sys.argv[1:]
    if args[:1] in (["--version"], ["-v"]):
        print("fake-pi 0.0.0")
        return
    scenario = os.environ.get("FAKE_PI_SCENARIO", "success")
    repair = os.path.exists(f"{CTX}/failures.md")
    task = read(f"{CTX}/TASK.md") if os.path.exists(f"{CTX}/TASK.md") else ""
    note = session(args)
    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    say(note, inp=10, out=5)

    if scenario == "success":
        happy()
    elif scenario == "env_dump":
        # Records the names of the variables the container received (values never written), then succeeds.
        names = "\n".join(sorted(os.environ))
        tool("write", {"path": f"{CTX}/notes.md"}, lambda: write(f"{CTX}/notes.md", f"# Plan\nENV\n{names}\n"))
        tool("mcp__actron__callers", {"functionId": ADD_ID}, lambda: "[]")
        add_subtract()
        tool("bash", {"command": "pytest -q"}, run_tests)
        finish(notes=False)
    elif scenario == "fail_then_repair":
        if not repair:
            happy(buggy=True)
        else:
            start_reading()
            plan()
            tool("read", {"path": f"{CTX}/failures.md"}, lambda: read(f"{CTX}/failures.md")[:200])
            tool("edit", {"path": "calc/ops.py", "edits": []},
                 lambda: replace(f"{WORK}/calc/ops.py", "return a + b  # subtract", "return a - b"))
            tool("bash", {"command": "pytest -q"}, run_tests)
            finish()
    elif scenario in ("weakened_delete", "weakened_skip"):
        happy()
        if scenario == "weakened_delete":
            tool("edit", {"path": "tests/test_ops.py", "edits": []},
                 lambda: replace(f"{WORK}/tests/test_ops.py",
                                 "def test_total():\n    assert total([1, 2, 3]) == 6\n", ""))
        else:
            tool("edit", {"path": "tests/test_ops.py", "edits": []},
                 lambda: replace(f"{WORK}/tests/test_ops.py", "def test_total():\n",
                                 "def test_total():\n    import pytest\n    pytest.skip('flaky')\n"))
        tool("bash", {"command": "pytest -q"}, run_tests)
    elif scenario == "timeout":
        start_reading()
        time.sleep(3600)
    elif scenario == "scope_change":
        start_reading()
        plan()
        tool("mcp__actron__callers", {"functionId": ADD_ID}, lambda: "[]")
        add_subtract()
        tool("edit", {"path": "calc/other.py", "edits": []},
             lambda: append(f"{WORK}/calc/other.py", "\nEXTRA = True\n"))
        tool("bash", {"command": "pytest -q"}, run_tests)
        finish()
    elif scenario == "stop_md":
        start_reading()
        plan()
        tool("write", {"path": f"{CTX}/STOP.md"},
             lambda: write(f"{CTX}/STOP.md", "Subtract needs a new module for money rounding, outside the ticket."))
        finish(dict(REPORT, stopped=True, filesChanged=[], testsAdded=[]))
    elif scenario == "explorer":
        if task.startswith("## Reminder"):
            happy()
        else:
            start_reading()
            plan()
            explore(14)
            time.sleep(30)
    elif scenario == "explorer_light":
        start_reading()
        plan()
        explore(4)
        tool("mcp__actron__callers", {"functionId": ADD_ID}, lambda: "[]")
        add_subtract()
        tool("bash", {"command": "pytest -q"}, run_tests)
        finish()
    elif scenario == "no_plan":
        happy(do_plan=repair)
    elif scenario == "no_report":
        happy(report=repair)
    elif scenario == "no_tests_after_edit":
        happy(tests_last=repair)
    elif scenario == "edits_without_callers":
        happy(callers=False)
    else:
        say(f"unknown scenario {scenario}")
    emit({"type": "turn_end", "message": {"role": "assistant"}, "toolResults": []})
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    emit({"type": "agent_settled", "aborted": False})


if __name__ == "__main__":
    main()
