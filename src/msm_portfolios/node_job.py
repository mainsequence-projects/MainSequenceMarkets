"""The script of a producer's node Job (ADR 0067, decision 5).

``run_portfolios(..., node_job="<Job name>")`` starts one run of that Job for each node of
the run's graph: each ledger, rebalance, computed signal, interpolation and input
(MetaTables ADR 0032). The Job's script is the same two lines in every producer::

    # jobs/run_updater_node.py
    from msm_portfolios.node_job import run_node

    if __name__ == "__main__":
        run_node()

``run_node`` runs MetaTables' ``run_updater_node()``: it rebuilds the node's updater from
its saved configuration, importing its classes by their address, and runs it as a node of
the orchestrator's invocation. It runs it inside the scopes ``run_portfolios`` gives its
nodes: one lookup of the MetaTables runtime for the node's Markets statements (#140), one
read of each calendar (#137) and the rows the node keeps for itself (#139). Another node's
result is read from its table.

The Job is declared in the producer's workflow file and deployed with its image, as
MetaTables' guidance shows; its workload is a branch's, so a computed signal it publishes
has the same manager as the orchestrator (ADR 0060).
"""

from __future__ import annotations


def run_node(argv: list[str] | None = None) -> None:
    """Run the one node the orchestrator passed in ``argv`` (the process's arguments)."""

    from metatables.updaters.job_mode import run_updater_node

    from msm.api.calendars import calendar_reads
    from msm.repositories.base import one_runtime_lookup
    from msm_portfolios.time_index.portfolios.run_rows import run_rows

    with one_runtime_lookup(), calendar_reads(), run_rows():
        run_updater_node(argv)


if __name__ == "__main__":
    run_node()


__all__ = ["run_node"]
