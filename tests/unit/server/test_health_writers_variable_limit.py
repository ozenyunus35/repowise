"""The update's health writers stay under SQLite's bound-variable limit (#4401).

SQLite refuses a statement that binds more values than its variable limit
("too many SQL variables"), and on a large repository the health persist and
queue rebuild bound one per file, or more. The limit is lowered on the test
connection so a few hundred files stand in for that repository.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from repowise.core.analysis.health.perf.opportunities import link_performance_findings
from repowise.core.persistence import crud
from repowise.core.persistence.crud.analysis.actions import write_read_snapshots
from repowise.core.persistence.models import HealthFinding
from repowise.core.pipeline.incremental.health import persist_partial_health
from tests.unit.server.conftest import create_test_repo
from tests.unit.server.test_performance_opportunities import _finding as _performance_finding
from tests.unit.server.test_refactoring_opportunities import _finding as _defect_finding
from tests.unit.server.test_refactoring_opportunities import _plan

#: Above the 500-value batches the writers bind, and below the files seeded.
_LIMIT = 600
_FILES = 700


async def _lower_variable_limit(engine) -> None:
    async with engine.connect() as conn:
        raw = await conn.get_raw_connection()
        # aiosqlite keeps the sqlite3 connection on ``_conn``; the test engine's
        # StaticPool hands every session this one connection.
        raw.driver_connection._conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, _LIMIT)


@pytest.mark.asyncio
async def test_health_persist_and_queue_rebuild_bind_in_batches(app, client, test_engine):
    repo_id = (await create_test_repo(client))["id"]
    paths = [f"pkg{i % 7}/mod{i}.py" for i in range(_FILES)]
    performance = [_performance_finding(p, 10, [f"{p}::run", "src/db.py::fetch"]) for p in paths]
    link_performance_findings(performance)
    await _lower_variable_limit(test_engine)

    async with app.state.session_factory() as session:
        await crud.save_health_findings(
            session,
            repo_id,
            [_defect_finding(p, function_name=f"sym{i}") for i, p in enumerate(paths)],
        )
        await crud.save_refactoring_suggestions(
            session, repo_id, [_plan(p, f"sym{i}") for i, p in enumerate(paths)]
        )
        # What ``repowise update`` runs for a change touching every file.
        await persist_partial_health(
            session,
            repo_id,
            SimpleNamespace(
                metrics=[{"file_path": p, "nloc": 10, "health_score": 7.0} for p in paths],
                findings=performance,
                refactoring_suggestions=[],
                function_blame_rows=[],
                authoritative_paths=set(paths),
                performance_authoritative_paths=set(),
                performance_plan_policy=None,
            ),
        )
        # And the queue rebuild after a prune.
        await crud.finalize_performance_opportunities(session, repo_id)
        await crud.finalize_refactoring_opportunities(session, repo_id)
        # A snapshot that fails is logged and returned, not raised.
        assert await write_read_snapshots(session, repo_id) == []
        await session.commit()

        stored = await session.scalar(
            select(func.count())
            .select_from(HealthFinding)
            .where(HealthFinding.repository_id == repo_id, HealthFinding.dimension == "performance")
        )
    assert stored == _FILES
