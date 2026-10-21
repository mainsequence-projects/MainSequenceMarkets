from __future__ import annotations

from typing import Any

from mainsequence.client.models_user import User

from .contracts import IndexActor


def actor_from_user(user: Any) -> IndexActor:
    """Build the actor from a request identity or an SDK `User`.

    Only the UID identifies the actor; no Index operation authorizes by Team.
    A request identity names no Teams, because the platform's caller assertions
    carry only the caller and its Organization-admin flag, so its actor has
    empty `team_uids`. An SDK `User` still lists its `organization_teams`.
    """

    user_uid = getattr(user, "uid", None)
    if user_uid in (None, ""):
        raise RuntimeError("Authenticated platform user has no UID")
    team_uids = tuple(
        sorted(
            str(uid)
            for team in (getattr(user, "organization_teams", None) or ())
            if (uid := team if isinstance(team, str) else getattr(team, "uid", None))
            not in (None, "")
        )
    )
    return IndexActor(
        user_uid=str(user_uid),
        username=getattr(user, "username", None),
        team_uids=team_uids,
    )


def resolve_authenticated_index_actor() -> IndexActor:
    """Resolve standalone Python calls from the authenticated SDK session."""

    return actor_from_user(User.get_authenticated_user_details())


__all__ = ["actor_from_user", "resolve_authenticated_index_actor"]
