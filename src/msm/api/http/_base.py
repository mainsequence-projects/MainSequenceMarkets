"""Shared strict model base for provider-neutral HTTP contracts."""

from pydantic import BaseModel, ConfigDict


class HttpContractModel(BaseModel):
    """Base model for stable public HTTP wire contracts."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


__all__ = ["HttpContractModel"]
