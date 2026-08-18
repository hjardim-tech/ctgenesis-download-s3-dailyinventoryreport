from pathlib import Path
from typing import Any, Iterable, List, Optional

import pandas as pd

from utils.logging import logger


def _resolve_parquet_path(output_folder: str) -> Path:
    """Return the target parquet file path and create its parent folder if needed."""
    folder = Path(output_folder)
    folder.mkdir(parents=True, exist_ok=True)

    candidates = [
        folder / "s3-bucket-inventory",
        folder / "s3-bucket-inventory.parquet",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return folder / "s3-bucket-inventory.parquet"


def _normalize_row(row: Any) -> Optional[dict]:
    """Extract the S3 key from a pandas row, accepting either s3_key or key."""
    if hasattr(row, "s3_key"):
        s3_key = getattr(row, "s3_key")
    elif hasattr(row, "key"):
        s3_key = getattr(row, "key")
    else:
        s3_key = None

    if s3_key is None or str(s3_key).strip() == "":
        return None

    payload: dict = {}
    for column in ["s3_bucket", "s3_key", "key", "size", "last_modified", "etag"]:
        value = getattr(row, column, None)
        if value is not None:
            payload[column] = value

    payload["s3_key"] = str(s3_key)
    if "key" not in payload:
        payload["key"] = str(s3_key)
    return payload


def load_inventory_data(extracted_df: pd.DataFrame, output_folder: str) -> int:
    """Load unique S3 keys into a parquet dataset under the provided output folder."""
    if extracted_df is None or extracted_df.empty:
        logger.info("No extracted rows to load into parquet dataset.")
        return 0

    parquet_path = _resolve_parquet_path(output_folder)
    if parquet_path.exists():
        try:
            existing_df = pd.read_parquet(parquet_path)
        except Exception:
            existing_df = pd.DataFrame()
    else:
        existing_df = pd.DataFrame()

    if existing_df.empty:
        existing_keys = set()
        dataset = pd.DataFrame(columns=["s3_bucket", "s3_key", "key", "size", "last_modified", "etag"])
    else:
        dataset = existing_df.copy()
        if "s3_key" not in dataset.columns and "key" in dataset.columns:
            dataset = dataset.rename(columns={"key": "s3_key"})
        if "s3_key" not in dataset.columns:
            dataset["s3_key"] = ""
        if "key" not in dataset.columns:
            dataset["key"] = dataset["s3_key"]
        existing_keys = set(dataset["s3_key"].fillna("").astype(str).tolist())

    new_rows: List[dict] = []
    for row in extracted_df.itertuples(index=False):
        normalized = _normalize_row(row)
        if normalized is None:
            continue

        s3_key = str(normalized["s3_key"])
        if s3_key in existing_keys:
            continue

        new_rows.append(normalized)
        existing_keys.add(s3_key)

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        for column in ["s3_bucket", "s3_key", "key", "size", "last_modified", "etag"]:
            if column not in new_df.columns:
                new_df[column] = None

        dataset = pd.concat([dataset, new_df[["s3_bucket", "s3_key", "key", "size", "last_modified", "etag"]]], ignore_index=True, copy=False)
        dataset.to_parquet(parquet_path, index=False)

    logger.info("Loaded %s new row(s) into parquet dataset %s", len(new_rows), parquet_path)
    return len(new_rows)
