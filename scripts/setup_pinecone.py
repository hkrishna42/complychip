"""ComplyChip V3 - Initialize Pinecone Index

Creates (or verifies) the Pinecone vector index used for document embeddings.

Usage:
    python -m scripts.setup_pinecone
    python -m scripts.setup_pinecone --dimension 768 --metric cosine
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.config import PINECONE_API_KEY, PINECONE_INDEX  # noqa: E402

DEFAULT_DIMENSION = 768  # Gemini embedding-001 output size
DEFAULT_METRIC = "cosine"
DEFAULT_CLOUD = "aws"
DEFAULT_REGION = "us-east-1"

METADATA_FIELDS = [
    "document_id",
    "entity_id",
    "organization_id",
    "document_type",
    "chunk_index",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize Pinecone index for ComplyChip V3")
    parser.add_argument("--index", default=PINECONE_INDEX, help=f"Index name (default: {PINECONE_INDEX})")
    parser.add_argument("--dimension", type=int, default=DEFAULT_DIMENSION, help=f"Vector dimension (default: {DEFAULT_DIMENSION})")
    parser.add_argument("--metric", default=DEFAULT_METRIC, choices=["cosine", "euclidean", "dotproduct"], help=f"Distance metric (default: {DEFAULT_METRIC})")
    parser.add_argument("--cloud", default=DEFAULT_CLOUD, help=f"Cloud provider (default: {DEFAULT_CLOUD})")
    parser.add_argument("--region", default=DEFAULT_REGION, help=f"Cloud region (default: {DEFAULT_REGION})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("=" * 50)
    print("ComplyChip V3 -- Setup Pinecone Index")
    print("=" * 50)
    print()

    # --- Validate API key ---
    print("[1/4] Checking Pinecone API key ...")
    if not PINECONE_API_KEY:
        print("ERROR: PINECONE_API_KEY is not set. Add it to your .env file.")
        sys.exit(1)
    print(f"  API key found (ends with ...{PINECONE_API_KEY[-4:]}).")
    print()

    # --- Connect ---
    print("[2/4] Connecting to Pinecone ...")
    try:
        from pinecone import Pinecone, ServerlessSpec
    except ImportError:
        print("ERROR: pinecone package is not installed. Run: pip install pinecone")
        sys.exit(1)

    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
    except Exception as exc:
        print(f"ERROR: Failed to initialize Pinecone client: {exc}")
        sys.exit(1)
    print("  Connected to Pinecone.")
    print()

    # --- Check / create index ---
    print(f"[3/4] Checking for index '{args.index}' ...")
    try:
        existing_indexes = pc.list_indexes()
        index_names = [idx.name for idx in existing_indexes]
    except Exception as exc:
        print(f"ERROR: Failed to list indexes: {exc}")
        sys.exit(1)

    if args.index in index_names:
        print(f"  Index '{args.index}' already exists.")
    else:
        print(f"  Index '{args.index}' not found -- creating ...")
        print(f"    Dimension : {args.dimension}")
        print(f"    Metric    : {args.metric}")
        print(f"    Cloud     : {args.cloud}")
        print(f"    Region    : {args.region}")
        try:
            pc.create_index(
                name=args.index,
                dimension=args.dimension,
                metric=args.metric,
                spec=ServerlessSpec(
                    cloud=args.cloud,
                    region=args.region,
                ),
            )
            print("  Index creation initiated. Waiting for it to be ready ...")
            # Poll until the index is ready (timeout after 120 s)
            deadline = time.time() + 120
            while time.time() < deadline:
                desc = pc.describe_index(args.index)
                if hasattr(desc, "status") and desc.status.get("ready", False):
                    break
                time.sleep(3)
            else:
                print("  WARNING: Timed out waiting for index to become ready. Check the Pinecone console.")
            print(f"  Index '{args.index}' created successfully.")
        except Exception as exc:
            print(f"ERROR: Failed to create index: {exc}")
            sys.exit(1)
    print()

    # --- Print stats ---
    print("[4/4] Fetching index statistics ...")
    try:
        index = pc.Index(args.index)
        stats = index.describe_index_stats()
        print(f"  Total vectors    : {stats.get('total_vector_count', 0)}")
        print(f"  Dimension        : {args.dimension}")
        print(f"  Metric           : {args.metric}")
        namespaces = stats.get("namespaces", {})
        if namespaces:
            print(f"  Namespaces       : {len(namespaces)}")
            for ns_name, ns_info in namespaces.items():
                vec_count = ns_info.get("vector_count", 0) if isinstance(ns_info, dict) else ns_info
                print(f"    - {ns_name or '(default)'}: {vec_count} vectors")
        else:
            print("  Namespaces       : 0 (empty index)")
        print()
        print("  Expected metadata fields:")
        for field in METADATA_FIELDS:
            print(f"    - {field}")
    except Exception as exc:
        print(f"WARNING: Could not retrieve index stats: {exc}")
    print()

    print("Done!  Pinecone index is ready for use.")


if __name__ == "__main__":
    main()
