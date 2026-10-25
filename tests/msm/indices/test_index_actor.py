from __future__ import annotations

from types import SimpleNamespace

from mainsequence.client.models_user import RequestUserIdentity

from msm.services.indices import IndexActor, actor_from_user

USER_UID = "9b4d2f8e-1a3c-4e5b-8d7f-6c0a2e4b6d35"
FIRST_TEAM_UID = "1a7c3e9b-5d2f-4b8a-8c6e-0f4a2d6b8e13"
SECOND_TEAM_UID = "3c9e1f7a-5b2d-4e8c-a6f0-7d1b3e5a9c24"


def test_actor_from_a_request_identity_names_no_teams() -> None:
    identity = RequestUserIdentity(uid=USER_UID, username="analyst")

    assert actor_from_user(identity) == IndexActor(user_uid=USER_UID, username="analyst")


def test_actor_from_an_sdk_user_keeps_its_organization_teams_without_reading_team_uids() -> None:
    class SdkUser(SimpleNamespace):
        @property
        def team_uids(self):
            # SDK 9.0.25/26 raised here when an assertion listed no Teams.
            raise AssertionError("actor_from_user must not read team_uids")

    user = SdkUser(
        uid=USER_UID,
        username="analyst",
        organization_teams=[SimpleNamespace(uid=SECOND_TEAM_UID), FIRST_TEAM_UID],
    )

    assert actor_from_user(user) == IndexActor(
        user_uid=USER_UID,
        username="analyst",
        team_uids=(FIRST_TEAM_UID, SECOND_TEAM_UID),
    )
