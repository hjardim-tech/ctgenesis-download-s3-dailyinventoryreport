from pathlib import Path
from typing import Union

PathLike = Union[str, Path]


def validate_input(environment: str, process: str, manifest: str, output_folder: str) -> int:
    """Validate pipeline input parameters and ensure output directories exist."""
    if not environment:
        return 100
    if not process:
        return 101
    if process not in {"ETL"}:
        return 102
    if not manifest:
        return 103
    if not output_folder:
        return 104

    try:
        Path("./logs").mkdir(parents=True, exist_ok=True)
        Path(output_folder).mkdir(parents=True, exist_ok=True)
    except Exception:
        return 106

    return 0
