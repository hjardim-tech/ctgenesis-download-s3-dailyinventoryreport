import argparse
import asyncio
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from utils.logging import logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Download S3 Bucket Inventory Report pipeline")
    parser.add_argument("--environment", required=True, help="Environment to use (e.g. DEV, UAT, PROD, QA)", dest="environment")
    parser.add_argument("--process", required=True, help="Process to run (e.g. ETL)", dest="process")
    parser.add_argument("--manifest", required=True, help="S3 URI to the manifest file", dest="manifest")
    parser.add_argument("--output-folder", required=True, help="Output folder for downloaded files", dest="output_folder")
    parser.add_argument("--qtd-files", type=int, default=1000, help="Max .gz files to download from S3", dest="qtd_files")
    parser.add_argument(
        "--use-key-filter",
        dest="use_key_filter",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use the configured AWS key prefix filter when extracting inventory rows",
    )
    args = parser.parse_args()

    from core import run_pipeline

    try:
        result = asyncio.run(
            run_pipeline(
                args.environment,
                args.process,
                args.manifest,
                args.output_folder,
                args.qtd_files,
                args.use_key_filter,
            )
        )
    except Exception as exc:
        logger.error("Unhandled exception running pipeline: %s", exc)
        sys.exit(1)

    status = result.get("status")
    if status == "ok":
        logger.info("Pipeline succeeded: %s", result)
        sys.exit(0)

    code = result.get("code", 1)
    logger.error("Pipeline failed: %s", result)
    sys.exit(code)


if __name__ == "__main__":
    main()