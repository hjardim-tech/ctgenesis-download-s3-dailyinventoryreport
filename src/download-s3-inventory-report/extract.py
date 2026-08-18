import csv
import gzip
import json
import os
import shutil
import sys

import boto3
import pandas as pd

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from urllib.parse import urlparse

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from utils.logging import logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def get_session(
    profile_name: Optional[str],
    session_factory: Callable[..., boto3.Session] = boto3.Session,
    log: Callable[[str], None] = print,
) -> boto3.Session:
    """Return an AWS session that prefers the EC2 instance role and only uses a profile when explicitly given."""
    if session_factory is None:
        if boto3 is None:
            raise RuntimeError("boto3 is required to create an AWS session")
        session_factory = boto3.Session

    kwargs = {}
    if profile_name:
        kwargs["profile_name"] = profile_name

    session = session_factory(**kwargs)
    try:
        profile_label = profile_name or "instance-role/default-chain"
        session.client("sts").get_caller_identity()
        return session
    except (ClientError, NoCredentialsError) as exc:
        if profile_name:
            logger.warning(f"[{profile_name}] No valid session ({exc}). Falling back to the default AWS credential chain...")
            session = session_factory(**{})
            try:
                session.client("sts").get_caller_identity()
                return session
            except (ClientError, NoCredentialsError) as fallback_exc:
                logger.warning("No valid AWS credentials found via the default AWS credential chain: %s", fallback_exc)
                raise RuntimeError(
                    f"No valid AWS credentials found for profile '{profile_name}' or the default EC2/IAM chain."
                ) from fallback_exc

        logger.warning("No valid AWS credentials found via the default EC2/IAM credential chain: %s", exc)
        raise RuntimeError("No valid AWS credentials found. Ensure the EC2 instance has an attached IAM role or credentials configured.") from exc


def _unzip_data_files(input_folder: Path, files_folder: Path) -> None:
    """Recursively unzip every .gz file found under input_folder into files_folder."""
    if not input_folder.exists():
        logger.warning("Input folder does not exist: %s", input_folder)
        return

    files_folder.mkdir(parents=True, exist_ok=True)
    gz_files = sorted(input_folder.rglob("*.gz"))
    logger.info(f"Unzipping {len(gz_files)} file(s) from {input_folder} -> {files_folder}")
    for gz_path in gz_files:
        relative_path = gz_path.relative_to(input_folder)
        csv_path = files_folder / relative_path.with_suffix("")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(gz_path, "rb") as f_in, open(csv_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)


def _available_ram_bytes() -> Optional[int]:
    """Return the available RAM in bytes when the OS exposes it."""
    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            for line in meminfo_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        except OSError:
            pass

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        return page_size * available_pages
    except (AttributeError, ValueError, OSError):
        return None


def _extract_keys_from_csv_files(files_folder: Path, use_key_filter: bool = True, aws_prefixes: Optional[str] = None) -> pd.DataFrame:
    """Read every CSV in files_folder and return a memory-safe DataFrame of inventory rows."""
    csv_files = sorted(files_folder.rglob("*.csv"))
    logger.info(f"Parsing {len(csv_files)} CSV file(s) from {files_folder}")

    frames: List[pd.DataFrame] = []
    available_ram = _available_ram_bytes()
    ram_budget_ratio = 0.7

    for csv_path in csv_files:
        logger.info(f"Reading CSV file: {csv_path}")
        try:
            readers = pd.read_csv(csv_path, header=None, chunksize=100_000, dtype=str, low_memory=False)
        except pd.errors.EmptyDataError:
            continue

        for chunk in readers:
            if chunk.empty or chunk.shape[1] < 2:
                continue

            filtered = chunk.copy()
            key_column = filtered.iloc[:, 1].astype(str)

            if use_key_filter and aws_prefixes:
                prefixes = [prefix.strip() for prefix in aws_prefixes.split(",") if prefix.strip()]
                if prefixes:
                    filtered = filtered[key_column.str.startswith(tuple(prefixes), na=False)].copy()
                    key_column = filtered.iloc[:, 1].astype(str)

            filtered = filtered[key_column.str.lower().str.endswith((".xml", ".pdf"), na=False)].copy()
            if filtered.empty:
                continue

            row_count = len(filtered)
            size_values = (
                pd.to_numeric(filtered.iloc[:, 2], errors="coerce") if filtered.shape[1] > 2 else pd.Series([None] * row_count, index=filtered.index, dtype="object")
            )

            result = pd.DataFrame(
                {
                    "s3_bucket": filtered.iloc[:, 0].astype(str),
                    "key": key_column.astype(str),
                    "size": size_values,
                    "last_modified": filtered.iloc[:, 3].astype(str) if filtered.shape[1] > 3 else pd.Series([None] * row_count, index=filtered.index, dtype="object"),
                    "etag": filtered.iloc[:, 4].astype(str) if filtered.shape[1] > 4 else pd.Series([None] * row_count, index=filtered.index, dtype="object"),
                },
                index=filtered.index,
            )

            frames.append(result)
            if available_ram:
                total_memory = sum(frame.memory_usage(index=True, deep=True).sum() for frame in frames)
                if total_memory > available_ram * ram_budget_ratio:
                    raise MemoryError(
                        f"Estimated DataFrame memory usage exceeds the allowed RAM budget ({available_ram * ram_budget_ratio / (1024 ** 2):.0f} MiB). "
                        "Reduce the number of input files or increase the machine memory."
                    )

    if not frames:
        return pd.DataFrame(columns=["s3_bucket", "key", "size", "last_modified", "etag"])

    return pd.concat(frames, ignore_index=True, copy=False)


def _load_dotenv_if_present() -> None:
    """Load the repository .env file when python-dotenv is available."""
    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    if not dotenv_path.exists():
        return

    try:
        from dotenv import load_dotenv  # type: ignore
    except ModuleNotFoundError:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return

    load_dotenv(dotenv_path=str(dotenv_path), override=False)


def _get_aws_config(environment: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Read AWS configuration from the environment or .env file."""
    _load_dotenv_if_present()
    env_name = (environment or os.getenv("ENVIRONMENT", "DEV")).upper()
    prefix = f"AWS_{env_name}_"

    def _get_value(*names: str) -> Optional[str]:
        for name in names:
            value = os.getenv(name)
            if value:
                return value
        return None

    aws_profile = _get_value(f"{prefix}PROFILE", f"AWS_PROFILE")
    aws_bucket = _get_value(f"{prefix}BUCKET", f"AWS_BUCKET")
    aws_prefixes = _get_value(f"{prefix}S3_INVENTORY_REPORT_PREFIXES", f"AWS_S3_INVENTORY_REPORT_PREFIXES")
    poll_interval = _get_value(f"{prefix}POLL_INTERVAL_SECONDS", f"AWS_POLL_INTERVAL_SECONDS")
    event_max_wait = _get_value(f"{prefix}EVENT_MAX_WAIT_SECONDS", f"AWS_EVENT_MAX_WAIT_SECONDS")
    delivery_max_wait = _get_value(f"{prefix}DELIVERY_MAX_WAIT_SECONDS", f"AWS_DELIVERY_MAX_WAIT_SECONDS")

    return {
        "aws_profile": aws_profile,
        "aws_bucket": aws_bucket,
        "aws_prefixes": aws_prefixes,
        "poll_interval": poll_interval,
        "event_max_wait": event_max_wait,
        "delivery_max_wait": delivery_max_wait,
    }


def _get_manifest_content(
    s3_key: str,
    session_factory: Callable[..., boto3.Session] = boto3.Session,
    aws_config: Optional[Dict[str, Any]] = None,
    log: Callable[[str], None] = logger.info,
) -> Dict[str, Any]:
    """Resolve and read the payload for an S3 object using the configured AWS profile."""

    aws_settings = aws_config or {}
    profile_name = aws_settings.get("aws_profile")
    bucket_name = aws_settings.get("aws_bucket")
    if not bucket_name:
        raise ValueError("AWS bucket must be configured")

    session = get_session(profile_name=profile_name, session_factory=session_factory, log=log)
    s3 = session.client("s3")

    response = s3.get_object(Bucket=bucket_name, Key=s3_key)
    content = response["Body"].read()
    return json.loads(content)


def _download_data_files(
    session_factory: Callable[..., boto3.Session] = boto3.Session,
    aws_config: Optional[Dict[str, Any]] = None,
    files: Optional[List[Dict[str, Any]]] = [], 
    input_folder: Path = Path("./input"),
    log: Callable[[str], None] = logger.info,
) -> None:
    """Download every inventory data file (referenced in manifest['files']) into input_folder."""
    aws_settings = aws_config or {}
    profile_name = aws_settings.get("aws_profile")
    bucket_name = aws_settings.get("aws_bucket")
    if not bucket_name:
        raise ValueError("AWS bucket must be configured")

    session = get_session(profile_name=profile_name, session_factory=session_factory, log=log)
    s3 = session.client("s3")

    if files and input_folder:
        for file_entry in files:
            key = file_entry["key"]
            s3_key = f"s3://{bucket_name}/{key}"
            logger.info(f"Downloading {s3_key} -> {input_folder}")
            try:
                destination = input_folder / key
                destination.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket_name, key, str(destination))
            except (BotoCoreError, ClientError) as exc:
                logger.error(f"Failed to download {s3_key}: {exc}")
                raise


def extract_inventory_manifest(
    environment: str,
    manifest: str,
    qtd_files: Optional[int] = None,
    use_key_filter: Optional[bool] = True,
) -> pd.DataFrame:
    """Execute the Extraction process and return the parsed S3 inventory as a pandas DataFrame."""
    aws_config = _get_aws_config(environment)
    if not aws_config.get("aws_bucket"):
        raise ValueError(f"Missing AWS configuration for environment '{environment}'")

    input_folder = Path("./input")
    files_folder = Path("./csv_files")

    manifest_data = _get_manifest_content(
        s3_key=manifest,
        session_factory=boto3.Session,
        aws_config=aws_config,
    )
    files = manifest_data.get("files", [])
    if qtd_files is not None:
        files = files[:qtd_files]
    logger.info(f"Manifest lists {len(files)} data file(s) for source manifest '{manifest}'")
 
    _download_data_files(
        session_factory=boto3.Session,
        aws_config=aws_config,
        files=files,
        input_folder=input_folder,
        log=logger.info,
    )
    _unzip_data_files(input_folder, files_folder)
    s3_df = _extract_keys_from_csv_files(files_folder, use_key_filter=bool(use_key_filter), aws_prefixes=aws_config.get("aws_prefixes"))

    logger.info(f"Extracted {len(s3_df)} object key(s) from inventory report")
    return s3_df
