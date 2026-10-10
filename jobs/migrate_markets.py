"""Main Sequence Job: apply the ms-markets migrations before the Markets API rolls out.

The deployment workflow runs this from the candidate image, so the revisions it
applies are the ones that image ships. A failure stops the rollout and the
previous release keeps serving.
"""

import logging
import sys

from metatables import upgrade_application

PROVIDERS = ("msm_migrations:migration",)

# Expose the shared runner's phase timings without logging connection material.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("metatables.migrations.runner").setLevel(logging.INFO)

for provider in PROVIDERS:
    print(f"Applying and reconciling {provider}", flush=True)
    # Always run the shared lifecycle, even at head: catalog finalization and
    # missing-table checks are still required. Exceptions must fail this Job.
    result = upgrade_application(provider)
    state = "migrated" if result["migrated"] else "already current"
    print(f"{provider}: {result['revision']} ({state}) on {result['data_source_uid']}", flush=True)
