"""The script of a producer's node Job (ADR 0067, decision 5).

``run_node`` runs MetaTables' ``run_updater_node`` with the arguments the orchestrator
passed, inside the scopes ``run_portfolios`` gives its nodes.
"""

from __future__ import annotations

import metatables.updaters.job_mode as job_mode
import msm.api.calendars.core as calendars
import msm.repositories.base as repositories
import msm_portfolios.time_index.portfolios.run_rows as run_rows
from msm_portfolios.node_job import run_node

ARGV = [
    "--update-uid",
    "u",
    "--invocation-uid",
    "i",
    "--trace-id",
    "t",
    "--output-table",
    "my_tables:MyTable",
]


def test_run_node_runs_metatables_node_inside_the_run_scopes(monkeypatch) -> None:
    seen: list[tuple] = []

    def node(argv):
        seen.append(
            (
                argv,
                repositories._lookup.get() is not None,
                calendars._reads.get() is not None,
                run_rows._rows.get() is not None,
            )
        )

    monkeypatch.setattr(job_mode, "run_updater_node", node)

    run_node(ARGV)

    assert seen == [(ARGV, True, True, True)]
    assert repositories._lookup.get() is None and calendars._reads.get() is None
