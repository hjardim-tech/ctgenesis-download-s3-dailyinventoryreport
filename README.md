# S3 Inventory Report Downloader

A Python ETL pipeline that downloads AWS S3 Inventory report files, extracts matching object keys, and stores a deduplicated Parquet dataset.

## How It Works

1. Reads an S3 Inventory manifest from the configured AWS bucket.
2. Downloads up to the requested number of `.gz` data files into `input/`.
3. Decompresses the files into `csv_files/`.
4. Keeps inventory rows whose keys end in `.xml` or `.pdf`.
5. Optionally filters keys by configured AWS prefixes.
6. Appends only new keys to `s3-bucket-inventory.parquet` in the output folder.
7. Removes temporary files from `input/` and `csv_files/` after a successful run.

## Requirements

- Python 3.9 or newer
- AWS credentials with permission to call STS and read the configured inventory bucket
- The `aws` CLI when using an AWS SSO profile
- A Parquet engine such as `pyarrow` for writing the output dataset

Install the Python dependencies from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install pyarrow
```

## AWS Configuration

Configuration is loaded from environment variables or a `.env` file in the project root. Environment-specific variables take precedence over their generic counterparts. For example, with `--environment DEV`, the pipeline checks `AWS_DEV_BUCKET` before `AWS_BUCKET`.

| Variable | Purpose |
| --- | --- |
| `AWS_<ENV>_BUCKET` | S3 bucket containing the manifest and inventory files. Required. |
| `AWS_<ENV>_PROFILE` | Optional AWS CLI profile to use. |
| `AWS_<ENV>_S3_INVENTORY_REPORT_PREFIXES` | Optional comma-separated key prefixes to keep. |
| `AWS_<ENV>_POLL_INTERVAL_SECONDS` | Optional polling interval setting. |
| `AWS_<ENV>_EVENT_MAX_WAIT_SECONDS` | Optional event wait timeout setting. |
| `AWS_<ENV>_DELIVERY_MAX_WAIT_SECONDS` | Optional delivery wait timeout setting. |

`<ENV>` is the uppercase value passed to `--environment`, such as `DEV`, `UAT`, `QA`, or `PROD`.

Example `.env`:

```dotenv
AWS_DEV_BUCKET=my-inventory-bucket
AWS_DEV_PROFILE=my-aws-profile
AWS_DEV_S3_INVENTORY_REPORT_PREFIXES=documents/,archive/
```

The pipeline uses the configured profile when provided and otherwise uses the standard AWS credential chain, including an EC2 instance role. Verify access before running:

```bash
aws sts get-caller-identity --profile my-aws-profile
```

## Usage

Run the CLI from the repository root:

```bash
python src/download-s3-inventory-report/cli.py \
  --environment DEV \
  --process ETL \
  --manifest path/to/manifest.json \
  --output-folder output
```

`--manifest` is the object key of the manifest inside the configured bucket. The CLI help describes it as an S3 URI, but the implementation passes the value as the S3 `Key`; use the object key expected by the bucket configuration.

### Options

- `--environment` (required): Environment configuration name, for example `DEV`.
- `--process` (required): Processing mode. Currently only `ETL` is supported.
- `--manifest` (required): S3 object key for the inventory manifest.
- `--output-folder` (required): Directory where the Parquet dataset is created or updated.
- `--qtd-files` (optional): Maximum number of manifest data files to download. Defaults to `1000`.
- `--use-key-filter` / `--no-use-key-filter` (optional): Enable or disable the configured prefix filter. Defaults to enabled.

Example with a smaller batch and no configured prefix filter:

```bash
python src/download-s3-inventory-report/cli.py \
  --environment UAT \
  --process ETL \
  --manifest reports/2026-08-18/manifest.json \
  --output-folder output \
  --qtd-files 50 \
  --no-use-key-filter
```

## Output and Logs

The output directory contains:

```text
output/
└── s3-bucket-inventory.parquet
```

Existing Parquet data is read and new rows are deduplicated by S3 key before being written. The dataset includes `s3_bucket`, `s3_key`, `key`, `size`, `last_modified`, and `etag` columns.

Each run writes a timestamped log file to `logs/` and also logs to standard output. Temporary downloaded and decompressed files are retained when the ETL fails, which can help with troubleshooting.

## Project Layout

```text
src/download-s3-inventory-report/
├── cli.py                 # Command-line interface
├── core.py                # Pipeline orchestration
├── extract.py             # S3 download, decompression, and filtering
├── load.py                # Parquet loading and deduplication
├── validate.py            # Input validation
└── utils/                 # AWS and logging helpers
```
