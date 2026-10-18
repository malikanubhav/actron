"""PROMPT phase 2: the Temporal wiring works (time-skipping environment and the real server, namespace `actron`)."""

from __future__ import annotations

import uuid

import pytest
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from actron.config import get_settings
from actron.workflows.smoke import ACTIVITIES, WORKFLOWS, SmokeWorkflow

pytestmark = pytest.mark.integration


async def test_smoke_in_time_skipping_environment() -> None:
    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:  # the test server binary is downloaded on first use
        pytest.skip(f"time-skipping test server unavailable: {exc}")
    async with env:
        queue = f"smoke-{uuid.uuid4().hex[:8]}"
        async with Worker(env.client, task_queue=queue, workflows=WORKFLOWS, activities=ACTIVITIES):
            result = await env.client.execute_workflow(
                SmokeWorkflow.run, "actron", id=f"smoke-{uuid.uuid4().hex[:8]}", task_queue=queue
            )
    assert result == "hello actron @ True"


async def test_smoke_against_the_real_server(temporal_address: str) -> None:
    settings = get_settings()
    client = await Client.connect(temporal_address, namespace=settings.TEMPORAL_NAMESPACE)
    queue = f"smoke-{uuid.uuid4().hex[:8]}"
    async with Worker(client, task_queue=queue, workflows=WORKFLOWS, activities=ACTIVITIES):
        handle = await client.start_workflow(
            SmokeWorkflow.run, "real server", id=f"smoke-{uuid.uuid4().hex[:8]}", task_queue=queue
        )
        result = await handle.result()
        history = [e async for e in handle.fetch_history_events()]
    assert result == "hello real server @ True"
    kinds = {e.event_type for e in history}
    assert len(history) >= 6  # started, scheduled, started, completed activity, completed workflow
    assert kinds


async def test_namespace_actron_exists(temporal_address: str) -> None:
    client = await Client.connect(temporal_address, namespace="actron")
    info = await client.workflow_service.describe_namespace(
        DescribeNamespaceRequest(namespace="actron")
    )
    assert info.namespace_info.name == "actron"
