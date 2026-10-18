"""Graph routes (spec B, B.C7) on a small seeded workspace graph (B-AC-57)."""

from __future__ import annotations

import httpx
import pytest

from actron.graph.store import store_for
from tests.api._fixtures import W6Env
from tests.api.conftest import Api

F1 = "code:fn:o/r:src/export.py::export_csv"
F2 = "code:fn:o/r:src/views.py::download"
F3 = "code:fn:o/r:src/api.py::handler"


@pytest.fixture
def seeded(w6: W6Env) -> W6Env:
    store = store_for(w6.ws)
    meta = "source: 'code', workspaceId: $ws, ingestedAt: '2026-10-17T00:00:00Z', refreshedAt: '2026-10-17T00:00:00Z'"
    for fid, name in ((F1, "export_csv"), (F2, "download"), (F3, "handler")):
        store.query(f"CREATE (:CodeFunction {{id: $id, name: $name, qualifiedName: $name, {meta}}})",
                    {"id": fid, "name": name, "ws": w6.ws})
    store.query("MATCH (a:CodeFunction {id: $a}), (b:CodeFunction {id: $b}) "
                "CREATE (a)-[:CALLS {method: 'structural', confidence: 1.0}]->(b)", {"a": F2, "b": F1})
    store.query("MATCH (a:CodeFunction {id: $a}), (b:CodeFunction {id: $b}) "
                "CREATE (a)-[:CALLS {method: 'structural', confidence: 0.7}]->(b)", {"a": F3, "b": F2})
    return w6


async def test_node_inspector(api: Api, seeded: W6Env, anon: httpx.AsyncClient) -> None:
    r = await api.get(f"/api/graph/nodes/{F1}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["node"]["type"] == "CodeFunction" and data["node"]["group"] == "code"
    assert data["node"]["label"] == "export_csv"
    assert data["incoming"] == [{"from": F2, "to": F1, "type": "CALLS", "method": "structural", "confidence": 1.0}]
    assert (await api.get("/api/graph/nodes/code:fn:o/r:none.py::x")).status_code == 404
    assert (await api.get("/api/graph/nodes/garbage")).status_code == 404
    assert (await anon.get(f"/api/graph/nodes/{F1}")).status_code == 401


async def test_neighbours(api: Api, seeded: W6Env) -> None:
    r = await api.get(f"/api/graph/nodes/{F2}/neighbours?limit=10")
    assert r.status_code == 200
    ids_ = {n["id"] for n in r.json()["nodes"]}
    assert ids_ == {F1, F2, F3} and r.json()["mode"] == "expanded"
    assert (await api.get(f"/api/graph/nodes/{F2}/neighbours?limit=500")).status_code == 422
    r = await api.get(f"/api/graph/nodes/{F2}/neighbours?types=Decision")
    assert [n["id"] for n in r.json()["nodes"]] == [F2]


async def test_sample_and_stats(api: Api, seeded: W6Env) -> None:
    r = await api.get("/api/graph/sample?limit=100")
    assert r.status_code == 200 and len(r.json()["links"]) == 2
    assert (await api.get("/api/graph/sample?limit=5000")).status_code == 422
    stats = (await api.get("/api/graph/stats")).json()
    assert stats["nodes"] == 3 and stats["links"] == 2
    assert stats["byType"] == [{"type": "CodeFunction", "group": "code", "count": 3}]
    assert stats["ontology"]["types"] > 50


async def test_quick_callers(api: Api, seeded: W6Env) -> None:
    r = await api.get(f"/api/graph/quick/callers?ids={F1}&depth=2")
    assert r.status_code == 200, r.text
    assert {c["id"] for c in r.json()} == {F2, F3}
    assert (await api.get(f"/api/graph/quick/drop_all?ids={F1}")).status_code == 404
    assert (await api.get("/api/graph/quick/callers")).status_code == 422


async def test_path(api: Api, seeded: W6Env) -> None:
    r = await api.get(f"/api/graph/path?from={F3}&to={F1}")
    assert r.status_code == 200, r.text
    assert r.json()["found"] is True and {n["id"] for n in r.json()["nodes"]} == {F1, F2, F3}
    assert (await api.get(f"/api/graph/path?from={F3}")).status_code == 422


async def test_search(api: Api, seeded: W6Env) -> None:
    from actron.graph.ontology import default_ontology, ensure_indexes

    ensure_indexes(store_for(seeded.ws), default_ontology())
    r = await api.get("/api/graph/search?q=export_csv")
    assert r.status_code == 200, r.text
    assert any(x["id"] == F1 for x in r.json()["results"])
    assert (await api.get("/api/graph/search?q=")).status_code == 422


async def test_subgraph(api: Api, seeded: W6Env) -> None:
    req = (await api.post("/api/requests", {"text": "Change export", "kindHint": "feature"})).json()["request"]
    r = await api.get(f"/api/graph/subgraph?requestId={req['id']}&mode=expanded")
    assert r.status_code == 200 and r.json()["mode"] == "expanded"
    assert (await api.get("/api/graph/subgraph?requestId=req_none")).status_code == 404
    assert (await api.get(f"/api/graph/subgraph?requestId={req['id']}&mode=bad")).status_code == 422
