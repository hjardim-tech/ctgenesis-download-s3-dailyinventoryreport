import sys
from pathlib import Path
from typing import Any, Dict, Optional

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from utils.logging import logger
from validate import validate_input


def _cleanup_temp_directories() -> None:
    """Remove temporary input and CSV files after a successful ETL run."""
    for folder_name in ["input", "csv_files"]:
        folder = Path(folder_name)
        if not folder.exists():
            continue
        for child in folder.iterdir():
            if child.is_dir():
                for nested in sorted(child.rglob("*"), reverse=True):
                    if nested.is_file() or nested.is_symlink():
                        nested.unlink()
                    elif nested.is_dir():
                        nested.rmdir()
                child.rmdir()
            else:
                child.unlink()
        logger.info("Cleaned temporary folder: %s", folder)


async def run_pipeline(
    environment: str,
    process: str,
    manifest: str,
    output_folder: str,
    qtd_files: Optional[int] = None,
    use_key_filter: Optional[bool] = True,
) -> Dict[str, Any]:
    if (rc := validate_input(environment, process, manifest, output_folder)) != 0:
        return {"status": "error", "code": rc}

    if process != "ETL":
        return {"status": "error", "code": 107}

    logger.info("Initiating ETL process. This may take a while...")

    from extract import extract_inventory_manifest

    try:
        extracted_df = extract_inventory_manifest(
            environment=environment,
            manifest=manifest,
            qtd_files=qtd_files,
            use_key_filter=use_key_filter,
        )
        extracted_count = len(extracted_df)
        logger.info("ETL process completed. Extracted %s rows from manifest %s", extracted_count, manifest)

        if extracted_df.empty:
            _cleanup_temp_directories()
            return {
                "status": "ok",
                "process": "ETL",
                "extracted": 0,
                "loaded": 0,
                "failed": 0,
            }

        from load import load_inventory_data

        loaded_count = load_inventory_data(extracted_df, output_folder)
        logger.info("ETL process completed. Extracted=%s loaded=%s failed=%s", extracted_count, loaded_count, 0)
        _cleanup_temp_directories()

    except Exception as exc:
        logger.warning("ETL pipeline failed: %s", exc)
        return {"status": "error", "sub_process": "ETL", "message": str(exc)}

    return {
        "status": "ok",
        "process": "ETL",
        "extracted": extracted_count,
        "loaded": loaded_count,
        "failed": 0,
    }
