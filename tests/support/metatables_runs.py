"""MetaTables' own joined run (``run_updaters``, MetaTables ADR 0031), in process.

The graph, its order, which node runs and each updater's outcome are MetaTables' code
(``UpdateRunner``). Only what a node asks the MetaTables API is stood in: finding or
registering an updater's update record, and the start, calculation and end of a node's run. The runtime is the
test's own (``metatables.use_runtime_context``, opened by the row fixtures). Nothing
leaves the process.

``serve_joined_runs`` records each invocation (each ``UpdateRunner.run``) as the update
hashes of the nodes it ran, in order. A node's calculation is ``calculate(updater)``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


class _UpdateRecord:
    """An updater's update record as the API keeps it: its uid, and a known graph."""

    def __init__(self, update_hash: str) -> None:
        self.table_update = SimpleNamespace(
            uid=str(uuid.uuid5(uuid.NAMESPACE_URL, update_hash)), update_details=None
        )
        self.last_write_statistics = None
        self.output_metadata = None

    def ensure_table_update(self, **_kwargs) -> None:
        return None

    def set_table_update(self, table_update: Any) -> None:
        self.table_update = table_update

    def is_local_relation_tree_set(self) -> bool:
        return True

    def set_ogm_dependencies_linked(self) -> None:
        return None

    def set_ogm_dependencies_unlinked(self) -> None:
        return None

    def get_update_statistics_for_table(self) -> None:
        return None


@dataclass
class JoinedRuns:
    """Each invocation's nodes, by update hash, in the order they ran, and each node's class."""

    invocations: list[list[str]] = field(default_factory=list)
    kinds: dict[str, str] = field(default_factory=dict)

    def kinds_of(self, invocation: int) -> list[str]:
        """The classes of an invocation's nodes, in the order they ran."""

        return [self.kinds[update_hash] for update_hash in self.invocations[invocation]]


def serve_joined_runs(monkeypatch, calculate: Callable[[Any], Any]) -> JoinedRuns:
    """Run updaters through MetaTables' ``UpdateRunner`` with the API stood in."""

    import metatables.updaters.runner as runner
    from metatables import TimeIndexTableUpdater

    records: dict[str, _UpdateRecord] = {}
    runs = JoinedRuns()

    def update_manager(updater) -> _UpdateRecord:
        return records.setdefault(updater.update_hash, _UpdateRecord(updater.update_hash))

    original_run = runner.UpdateRunner.run

    def run(self):
        runs.invocations.append([])
        return original_run(self)

    def start_update(self, override_update_stats=None):
        runs.invocations[-1].append(self.updater.update_hash)
        runs.kinds[self.updater.update_hash] = type(self.updater).__name__
        return False, calculate(self.updater)

    monkeypatch.setattr(TimeIndexTableUpdater, "update_manager", property(update_manager))
    # MetaTables 0.1.83 finds or registers each update of the plan before the run (#162).
    monkeypatch.setattr(TimeIndexTableUpdater, "verify_and_build_remote_objects", lambda self: None)
    monkeypatch.setattr(runner.UpdateRunner, "run", run)
    monkeypatch.setattr(runner.UpdateRunner, "_start_update", start_update)
    return runs
