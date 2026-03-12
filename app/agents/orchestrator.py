"""Multi-agent orchestration engine.

Implements three orchestration patterns:
    1. Supervisor: A supervisor agent delegates tasks to worker agents
    2. Pipeline: Sequential agent chain (output of A → input of B)
    3. Fan-out: Run multiple agents concurrently, aggregate results

Workflows are defined as DAGs with steps, transitions, and conditions.
The engine manages state transitions and coordinates agent execution.
"""

from __future__ import annotations

import asyncio
import json as _json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.events import (
    WorkflowRunCompleted,
    WorkflowRunFailed,
    WorkflowRunStarted,
    WorkflowStepCompleted,
)
from app.agents.executor import AgentExecutor
from app.agents.models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
)
from app.core.events import emit
from app.db.session import async_session_factory, set_tenant_context

logger = structlog.stdlib.get_logger()

# Maximum characters for serialized step output before truncation.
_MAX_STEP_OUTPUT_SIZE = 50_000


class OrchestrationError(Exception):
    """Raised when workflow orchestration fails."""


class AgentOrchestrator:
    """Multi-agent workflow orchestration engine.

    Executes workflow definitions by:
    1. Resolving the DAG entry step
    2. Running agents for each step
    3. Evaluating transition conditions
    4. Aggregating results

    Workflow definition format:
    {
        "entry_step": "step_name",
        "steps": [
            {
                "name": "step_name",
                "agent_id": "uuid-of-agent-definition",
                "pattern": "single",  # "single", "parallel", "supervisor"
                "input_mapping": {"key": "$.previous_step.output.field"},
                "timeout_seconds": 300
            }
        ],
        "transitions": [
            {
                "from": "step_a",
                "to": "step_b",
                "condition": "always"  # "always", "on_success", "on_failure", or JSONPath expression
            }
        ]
    }
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_workflow(
        self,
        *,
        workflow_id: uuid.UUID,
        tenant_id: uuid.UUID,
        input_data: dict[str, Any],
        api_key: str,
        key_source: str = "platform",
    ) -> WorkflowRun:
        """Execute a workflow definition from start to finish."""
        await set_tenant_context(self.db, str(tenant_id))

        # Load workflow definition (filtered by tenant_id for isolation)
        workflow = await self._load_workflow(workflow_id, tenant_id)
        if not workflow:
            raise OrchestrationError(f"Workflow {workflow_id} not found")
        if workflow.status != WorkflowStatus.ACTIVE:
            raise OrchestrationError(f"Workflow '{workflow.name}' is not active")

        # Create workflow run
        run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            status=WorkflowRunStatus.RUNNING,
            input_data=input_data,
            started_at=datetime.now(UTC),
            state={"completed_steps": [], "current_step": None, "step_outputs": {}},
        )
        self.db.add(run)
        await self.db.flush()

        await emit(
            WorkflowRunStarted(
                tenant_id=str(tenant_id),
                workflow_id=str(workflow_id),
                run_id=str(run.id),
            ),
            durable=True,
        )

        definition = workflow.definition
        steps = {s["name"]: s for s in definition.get("steps", [])}
        transitions = definition.get("transitions", [])
        entry_step = definition.get("entry_step")

        if not entry_step or entry_step not in steps:
            run.status = WorkflowRunStatus.FAILED
            run.error = "Invalid workflow: missing or unknown entry_step"
            await self.db.commit()
            raise OrchestrationError(run.error)

        try:
            start_time = datetime.now(UTC)
            step_outputs: dict[str, Any] = {"_input": input_data}
            current_step_name = entry_step
            max_workflow_steps = len(steps) * 2 + 10  # Safety bound for cycles
            executed_steps = 0

            while current_step_name:
                executed_steps += 1
                if executed_steps > max_workflow_steps:
                    raise OrchestrationError(
                        f"Workflow exceeded maximum step count ({max_workflow_steps}). "
                        "Possible cyclic transition graph."
                    )

                step_def = steps.get(current_step_name)
                if not step_def:
                    raise OrchestrationError(f"Unknown step: {current_step_name}")

                # Update run state
                run.state = {
                    **run.state,
                    "current_step": current_step_name,
                }
                await self.db.flush()

                # Build step input
                step_input = self._resolve_input(
                    step_def.get("input_mapping", {}),
                    step_outputs,
                    input_data,
                )

                # Execute the step
                pattern = step_def.get("pattern", "single")
                step_result = await self._execute_step(
                    step_def=step_def,
                    pattern=pattern,
                    step_input=step_input,
                    tenant_id=tenant_id,
                    api_key=api_key,
                    key_source=key_source,
                    workflow_run=run,
                )

                # Truncate large step outputs to prevent unbounded JSONB growth.
                serialized = _json.dumps(step_result, default=str)
                if len(serialized) > _MAX_STEP_OUTPUT_SIZE:
                    step_result = {
                        "_truncated": True,
                        "_original_size": len(serialized),
                        "summary": serialized[:_MAX_STEP_OUTPUT_SIZE],
                    }
                step_outputs[current_step_name] = step_result
                run.total_steps += 1

                # Emit step completion event
                await emit(
                    WorkflowStepCompleted(
                        tenant_id=str(tenant_id),
                        run_id=str(run.id),
                        step_name=current_step_name,
                        agent_id=step_def.get("agent_id", ""),
                        status="completed",
                    ),
                    durable=True,
                )

                # Update completed steps
                completed = list(run.state.get("completed_steps", []))
                completed.append(current_step_name)
                run.state = {**run.state, "completed_steps": completed, "step_outputs": step_outputs}

                # Find next step via transitions
                current_step_name = self._resolve_next_step(
                    current_step_name, transitions, step_result,
                )

            # Workflow completed
            run.status = WorkflowRunStatus.COMPLETED
            run.output_data = step_outputs
            run.completed_at = datetime.now(UTC)
            await self.db.commit()

            duration = (run.completed_at - start_time).total_seconds()
            await emit(
                WorkflowRunCompleted(
                    tenant_id=str(tenant_id),
                    workflow_id=str(workflow_id),
                    run_id=str(run.id),
                    total_steps=run.total_steps,
                    total_cost_usd=run.total_cost_usd,
                    duration_seconds=duration,
                ),
                durable=True,
            )

            return run

        except Exception as exc:
            # Sanitize error messages: only expose OrchestrationError details
            # (controlled messages). For unexpected errors, use a generic message
            # and log the full trace server-side.
            if isinstance(exc, OrchestrationError):
                safe_error = str(exc)[:2000]
            else:
                safe_error = "Internal workflow execution error"
                logger.error(
                    "workflow_run_failed",
                    workflow_id=str(workflow_id),
                    run_id=str(run.id),
                    exc_info=True,
                )

            run.status = WorkflowRunStatus.FAILED
            run.error = safe_error
            run.completed_at = datetime.now(UTC)
            run.output_data = {
                "error_code": "WORKFLOW_FAILED",
                "failed_step": run.state.get("current_step", ""),
                "completed_steps": run.state.get("completed_steps", []),
            }
            await self.db.commit()

            await emit(
                WorkflowRunFailed(
                    tenant_id=str(tenant_id),
                    workflow_id=str(workflow_id),
                    run_id=str(run.id),
                    error=safe_error[:500],
                    failed_step=run.state.get("current_step", ""),
                ),
                durable=True,
            )

            raise

    async def _execute_step(
        self,
        *,
        step_def: dict[str, Any],
        pattern: str,
        step_input: dict[str, Any],
        tenant_id: uuid.UUID,
        api_key: str,
        key_source: str,
        workflow_run: WorkflowRun,
    ) -> dict[str, Any]:
        """Execute a single workflow step using the specified pattern.

        Enforces per-step timeout from step definition.
        """
        if pattern == "parallel":
            coro = self._execute_parallel(
                step_def, step_input, tenant_id, api_key, key_source, workflow_run,
            )
        else:
            # "single" or "supervisor" — both use single agent execution
            coro = self._execute_single(
                step_def, step_input, tenant_id, api_key, key_source, workflow_run,
            )

        timeout = step_def.get("timeout_seconds")
        if timeout:
            try:
                return await asyncio.wait_for(coro, timeout=timeout)
            except TimeoutError as exc:
                raise OrchestrationError(
                    f"Step '{step_def.get('name', '?')}' timed out after {timeout}s"
                ) from exc
        return await coro

    async def _execute_single(
        self,
        step_def: dict[str, Any],
        step_input: dict[str, Any],
        tenant_id: uuid.UUID,
        api_key: str,
        key_source: str,
        workflow_run: WorkflowRun,
    ) -> dict[str, Any]:
        """Execute a single-agent step."""
        agent_id = step_def.get("agent_id")
        if not agent_id:
            raise OrchestrationError(f"Step '{step_def['name']}' has no agent_id")

        executor = AgentExecutor(self.db)
        instance = await executor.run(
            definition_id=uuid.UUID(agent_id),
            tenant_id=tenant_id,
            input_data=step_input,
            api_key=api_key,
            key_source=key_source,
        )

        # Accumulate metrics
        workflow_run.total_tokens += instance.tokens_used
        workflow_run.total_cost_usd += instance.cost_usd

        return instance.output_data

    async def _execute_parallel(
        self,
        step_def: dict[str, Any],
        step_input: dict[str, Any],
        tenant_id: uuid.UUID,
        api_key: str,
        key_source: str,
        workflow_run: WorkflowRun,
    ) -> dict[str, Any]:
        """Execute multiple agents in parallel (fan-out pattern).

        Each parallel branch gets its own AsyncSession to prevent session
        state corruption from concurrent coroutines. Metrics are accumulated
        under a lock and applied to the parent workflow run after completion.
        """
        agent_ids = step_def.get("agent_ids", [])
        if not agent_ids:
            raise OrchestrationError(f"Parallel step '{step_def['name']}' has no agent_ids")

        # Collect metrics separately to avoid concurrent += on the ORM object.
        step_metrics: list[tuple[int, float]] = []
        _metrics_lock = asyncio.Lock()

        async def run_one(aid: str) -> dict[str, Any]:
            # Each branch gets its own session to avoid AsyncSession corruption.
            async with async_session_factory() as branch_session:
                await set_tenant_context(branch_session, str(tenant_id))
                executor = AgentExecutor(branch_session)
                instance = await executor.run(
                    definition_id=uuid.UUID(aid),
                    tenant_id=tenant_id,
                    input_data=step_input,
                    api_key=api_key,
                    key_source=key_source,
                )
                async with _metrics_lock:
                    step_metrics.append((instance.tokens_used, instance.cost_usd))
                return {"agent_id": aid, "output": instance.output_data}

        results = await asyncio.gather(
            *[run_one(aid) for aid in agent_ids],
            return_exceptions=True,
        )

        # Apply accumulated metrics atomically after all tasks complete.
        for tokens, cost in step_metrics:
            workflow_run.total_tokens += tokens
            workflow_run.total_cost_usd += cost

        outputs = []
        for r in results:
            if isinstance(r, Exception):
                outputs.append({"error": "Agent execution failed"})
            else:
                outputs.append(r)

        return {"parallel_results": outputs}

    # Pattern for safe path components — prevents __dict__, __class__ traversal.
    # Blocks components starting with double underscore (dunder attributes).
    _SAFE_PATH_RE = __import__("re").compile(r"^(?!__)[a-zA-Z0-9_]+$")
    _MAX_PATH_DEPTH = 10

    def _resolve_input(
        self,
        input_mapping: dict[str, str],
        step_outputs: dict[str, Any],
        original_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve input data for a step using JSONPath-like mappings.

        Supports simple dot-notation references:
            "$.previous_step.output.field" → step_outputs["previous_step"]["output"]["field"]
            "$._input.messages" → original_input["messages"]

        Path components are validated to prevent attribute traversal attacks.
        """
        if not input_mapping:
            return original_input

        resolved = {}
        for key, path in input_mapping.items():
            if not isinstance(path, str) or not path.startswith("$."):
                resolved[key] = path
                continue

            parts = path[2:].split(".")

            # Validate path depth and component safety
            if len(parts) > self._MAX_PATH_DEPTH:
                logger.warning("input_mapping_path_too_deep", path=path)
                resolved[key] = None
                continue

            valid = True
            for part in parts:
                if not self._SAFE_PATH_RE.match(part):
                    logger.warning(
                        "input_mapping_invalid_path_component",
                        path=path, component=part,
                    )
                    valid = False
                    break
            if not valid:
                resolved[key] = None
                continue

            current: Any = step_outputs
            try:
                for part in parts:
                    if isinstance(current, dict):
                        current = current[part]
                    else:
                        current = None
                        break
                resolved[key] = current
            except (KeyError, IndexError, TypeError):
                resolved[key] = None

        return resolved

    def _resolve_next_step(
        self,
        current_step: str,
        transitions: list[dict[str, str]],
        step_result: dict[str, Any],
    ) -> str | None:
        """Find the next step based on transition conditions."""
        for t in transitions:
            if t.get("from") != current_step:
                continue

            condition = t.get("condition", "always")
            if (
                condition == "always"
                or (condition == "on_success" and not step_result.get("error"))
                or (condition == "on_failure" and step_result.get("error"))
            ):
                return t.get("to")

        return None  # No more steps — workflow complete

    async def _load_workflow(
        self, workflow_id: uuid.UUID, tenant_id: uuid.UUID | None = None,
    ) -> WorkflowDefinition | None:
        conditions = [
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.deleted_at.is_(None),
        ]
        if tenant_id is not None:
            conditions.append(WorkflowDefinition.tenant_id == tenant_id)
        stmt = select(WorkflowDefinition).where(*conditions)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
