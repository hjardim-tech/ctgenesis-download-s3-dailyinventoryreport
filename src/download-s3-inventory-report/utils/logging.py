"""Logging configuration module."""

import logging
import sys
from pathlib import Path
from datetime import datetime


def configure_logging(level=logging.INFO):
    """Configure logging for the application."""
    # Get the root logger instead of __name__
    logger = logging.getLogger("genesis")  # Change to use root logger name

    # Clear any existing handlers to avoid duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.setLevel(level)

    # Create formatter for all handlers
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Create console handler with a higher log level
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Create file handler with timestamped filename
    logs_dir = Path("./logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = logs_dir / f"genesis_{timestamp}.log"
    fh = logging.FileHandler(str(log_filename))
    fh.setLevel(level)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


# Create a single logger instance to be used across the application
logger = configure_logging()
