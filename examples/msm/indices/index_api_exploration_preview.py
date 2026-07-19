"""Build or submit a non-mutating Index exploration and deletion preview.

This example never calls a deletion endpoint. Supplying ``--base-url`` only
submits the read-only preview request.
"""

from __future__ import annotations

import argparse
import json
import uuid
from urllib import request as urllib_request

from msm.services.indices import IndexBulkDeletePreviewRequest

EXAMPLE_INDEX_UID = uuid.UUID("00000000-0000-0000-0000-000000000010")


def route_sequence(index_uid: uuid.UUID) -> tuple[str, ...]:
    return (
        "/api/v1/index/?search=USD_SWAP_10Y",
        f"/api/v1/index/{index_uid}/summary/",
        f"/api/v1/index/{index_uid}/methodologies/",
        f"/api/v1/index/{index_uid}/datasets/",
        f"/api/v1/index/{index_uid}/related-meta-tables/",
    )


def build_preview_request(index_uid: uuid.UUID) -> IndexBulkDeletePreviewRequest:
    return IndexBulkDeletePreviewRequest(
        index_uids=(index_uid,),
        mode="identity_and_values",
    )


def submit_preview(
    *,
    base_url: str,
    user_uid: uuid.UUID,
    payload: IndexBulkDeletePreviewRequest,
) -> dict:
    endpoint = f"{base_url.rstrip('/')}/api/v1/index/bulk-delete/preview/"
    http_request = urllib_request.Request(
        endpoint,
        data=json.dumps(payload.model_dump(mode="json")).encode(),
        headers={
            "Content-Type": "application/json",
            "X-User-UID": str(user_uid),
        },
        method="POST",
    )
    with urllib_request.urlopen(http_request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", help="Optional deployed apps/v1 base URL.")
    parser.add_argument("--index-uid", type=uuid.UUID, default=EXAMPLE_INDEX_UID)
    parser.add_argument("--user-uid", type=uuid.UUID)
    args = parser.parse_args()

    payload = build_preview_request(args.index_uid)
    print("Exploration sequence:")
    for endpoint in route_sequence(args.index_uid):
        print(f"  GET {endpoint}")
    print("Read-only preview payload:")
    print(json.dumps(payload.model_dump(mode="json"), indent=2))

    if args.base_url:
        if args.user_uid is None:
            parser.error("--user-uid is required when --base-url is supplied")
        preview = submit_preview(
            base_url=args.base_url,
            user_uid=args.user_uid,
            payload=payload,
        )
        print("Preview consequences (no mutation was requested):")
        print(json.dumps(preview, indent=2))


if __name__ == "__main__":
    main()
