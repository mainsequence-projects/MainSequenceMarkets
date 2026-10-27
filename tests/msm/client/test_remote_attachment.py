"""Under the remote backend a provider attaches only its own tables (ADR 0047).

Its tables keep physical foreign keys to Markets registries, but a Markets table
that is only a foreign-key target is referenced by name, not attached: the
provider holds no grant on ``mainsequence.markets``.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from msm.api.remote import use_remote_backend, use_runtime_backend
from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_name
from msm.models import AssetTable
from msm.models.registration import resolve_markets_meta_table_models
from msm.settings import markets_configured_namespace


class ProviderAssetNotesTable(MarketsMetaTableMixin, MarketsBase):
    __tablename__ = markets_table_name("my_provider", "asset_notes_remote_attach")
    __metatable_namespace__: ClassVar[str] = markets_configured_namespace("my-provider")
    __metatable_identifier__ = "ProviderAssetNotes"
    __metatable_description__ = "Provider-owned notes keyed by a Markets asset."

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{AssetTable.__table__.fullname}.uid", ondelete="CASCADE"),
        primary_key=True,
    )
    note: Mapped[str] = mapped_column(String(200))


class _Backend:
    def call(self, resource, operation, arguments):  # pragma: no cover - never called
        raise AssertionError("attachment must not call the API")


def test_runtime_backend_attaches_markets_foreign_key_targets() -> None:
    assert resolve_markets_meta_table_models([ProviderAssetNotesTable]) == [
        AssetTable,
        ProviderAssetNotesTable,
    ]


def test_remote_backend_attaches_only_the_providers_own_tables() -> None:
    use_remote_backend(_Backend())
    try:
        assert resolve_markets_meta_table_models([ProviderAssetNotesTable]) == [
            ProviderAssetNotesTable
        ]
        # A Markets table the caller asks for explicitly is still attached.
        assert resolve_markets_meta_table_models([AssetTable, ProviderAssetNotesTable]) == [
            AssetTable,
            ProviderAssetNotesTable,
        ]
    finally:
        use_runtime_backend()
