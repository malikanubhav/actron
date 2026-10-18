"""Loads `tests/fixtures/graph_small.cypher` (a hand-written test fixture) into a graph store.

Also exposes the fixture's well-known ids so tests read clearly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "graph_small.cypher"

REPO = "fixture/calva-lite"
FN = "code:fn:fixture/calva-lite:"
EVAL_CODE = FN + "src/evaluate.ts::evaluateCode"
EVAL_SAVE = FN + "src/evaluate.ts::evaluateOnSave"
EVAL_SEL = FN + "src/evaluate.ts::evaluateSelection"
EVAL_TOP = FN + "src/evaluate.ts::evaluateTopLevelForm"
FORMAT = FN + "src/evaluate.ts::formatEvalResult"
FORMAT_OLD = FN + "src/evaluate.ts::formatResult"
LEGACY = FN + "src/evaluate.ts::legacyEvaluate"
REGISTER = FN + "src/extension.ts::registerCommands"
ACTIVATE = FN + "src/extension.ts::activate"
DEACTIVATE = FN + "src/extension.ts::deactivate"
CONNECT = FN + "src/connector.ts::connect"
DISCONNECT = FN + "src/connector.ts::disconnect"
SEND = FN + "src/connector.ts::sendMessage"
REPL_EVAL = FN + "src/connector.ts::ReplSession.eval"
GET_CONFIG = FN + "src/settings.ts::getConfig"
AUTO_EVAL = FN + "src/settings.ts::autoEvaluateEnabled"
PRETTY = FN + "src/printer.ts::prettyPrint"
PRETTY_MAP = FN + "src/printer.ts::prettyPrintMap"
SHOW = FN + "src/results/output.ts::showResult"
APPEND = FN + "src/results/output.ts::appendToOutput"
T_EVAL = FN + "src/extension-test/evaluate.test.ts::evaluate > evaluates a form"
T_SAVE = FN + "src/extension-test/evaluate.test.ts::evaluate > skips evaluation on save when disabled"
T_PRINT = FN + "src/extension-test/printer.test.ts::printer > pretty prints maps"
REPL_CLASS = "code:class:fixture/calva-lite:src/connector.ts::ReplSession"
EVAL_FILE = "code:file:fixture/calva-lite:src/evaluate.ts"
CONN_FILE = "code:file:fixture/calva-lite:src/connector.ts"
FEATURE_SAVE = "actron:feature:evaluate-on-save"
D_SAVE = "actron:decision:fixture-save-off"
D_WIDTH = "actron:decision:fixture-print-width"
D_INLINE = "actron:decision:fixture-inline-only"
D_OUTPUT = "actron:decision:fixture-output-window"
D_CACHE = "actron:decision:fixture-cache"
D_PREFIX = "actron:decision:fixture-ns-prefix"
D_NREPL = "actron:decision:fixture-nrepl-format"
D_REJECTED = "actron:decision:fixture-rejected"
D_INACTIVE = "actron:decision:fixture-selection-trim"
PR101 = "github:pr:fixture/calva-lite#101"
PR102 = "github:pr:fixture/calva-lite#102"
PR103 = "github:pr:fixture/calva-lite#103"
PR104 = "github:pr:fixture/calva-lite#104"
RC1 = "github:reviewcomment:7000001"
ISSUE55 = "github:issue:fixture/calva-lite#55"
LI12 = "linear:issue:fx-cal-12"
LI20 = "linear:issue:fx-cal-20"
M1 = "slack:msg:CFIXTURE:1709200000.000100"
M2 = "slack:msg:CFIXTURE:1709200100.000200"
M4 = "slack:msg:CFIXTURE:1717000000.000400"
M7 = "slack:msg:CFIXTURE:1715500000.000700"
M9 = "slack:msg:CFIXTURE:1718500000.000900"
ALICE = "actron:person:fixture-alice"
BOB = "actron:person:fixture-bob"
CAROL = "actron:person:fixture-carol"
PROC_EVAL = "actron:procedure:src-evaluate"
REQUEST = "actron:request:req_fixture_save"
REQUEST_ID = "req_fixture_save"


def statements(text: str) -> list[str]:
    """Drop `//` comment lines; split on lines that are exactly `;`."""
    out: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if stripped == ";":
            if "".join(buf).strip():
                out.append("\n".join(buf))
            buf = []
            continue
        buf.append(line)
    if "".join(buf).strip():
        out.append("\n".join(buf))
    return out


def load_fixture_graph(store: Any) -> Any:
    """Run every statement of the fixture against `store` (a GraphStore). Returns the store."""
    params = {"ws": store.workspace_id, "ontologyVersion": store.ontology.version}
    for stmt in statements(FIXTURE.read_text(encoding="utf-8")):
        used = {k: v for k, v in params.items() if f"${k}" in stmt}
        store.query(stmt, used or None, timeout_ms=30000)
    return store
