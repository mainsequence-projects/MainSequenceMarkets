"""Main Sequence Job: apply the ms-markets migrations before the Markets API rolls out.

The deployment workflow runs this from the candidate image, so the revisions it
applies are the ones that image ships. A failure stops the rollout and the
previous release keeps serving.
"""

from metatables import upgrade_application

PROVIDERS = ("msm_migrations:migration",)

for provider in PROVIDERS:
    result = upgrade_application(provider)
    state = "migrated" if result["migrated"] else "already current"
    print(f"{provider}: {result['revision']} ({state}) on {result['data_source_uid']}", flush=True)
