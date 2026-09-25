"""
===============================================================================
Centralized Application Logging Infrastructure Module
===============================================================================

Purpose:
    Configures unified, thread-safe logging for the Document Translator service.
    Streams logs concurrently to:
      1. Standard console (sys.stdout) for live CLI inspection.
      2. Persistent rotating file (logs/translator.log) for diagnostics, audit,
         and debugging across server restarts.

Usage:
    from backend.core.logger_config import setup_logging, get_log_file_path, get_recent_logs

    logger = setup_logging("translator_api")
    logger.info("Application initialized.")

===============================================================================
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from typing import Optional

# Cloud-native & workspace hygiene: store persistent logs in OS temporary directory
# so local development and serverless containers never pollute the git repository
LOGS_DIR = os.getenv("LOGS_DIR", os.path.join(tempfile.gettempdir(), "translator_logs"))
LOG_FILE_PATH = os.path.join(LOGS_DIR, "translator.log")

# Guarantee logs directory exists
try:
    os.makedirs(LOGS_DIR, exist_ok=True)
except Exception:
    pass

_IS_CONFIGURED = False


def setup_logging(
    name: Optional[str] = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB per file
    backup_count: int = 5,
) -> logging.Logger:
    """
    Configures root and named loggers with console and rotating file handlers.
    Thread-safe and idempotent (subsequent calls return logger without duplicating handlers).

    Args:
        name (Optional[str]): Name of the logger to retrieve. Defaults to root logger.
        level (int): Minimum logging severity level. Defaults to logging.INFO.
        max_bytes (int): Maximum size of a single log file before rotation.
        backup_count (int): Maximum number of rolled backup log files to retain.

    Returns:
        logging.Logger: Configured logger instance.
    """
    global _IS_CONFIGURED

    root_logger = logging.getLogger()

    if not _IS_CONFIGURED:
        root_logger.setLevel(level)
        log_format = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"
        formatter = logging.Formatter(log_format, datefmt=date_format)

        # 1. Console Stream Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # 2. Rotating File Handler (UTF-8 encoded for Japanese & multilingual text)
        try:
            file_handler = RotatingFileHandler(
                filename=LOG_FILE_PATH,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except OSError as exc:
            root_logger.warning(f"Could not initialize RotatingFileHandler at {LOG_FILE_PATH}: {exc}")

        # Silence overly verbose third-party loggers if needed
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("google").setLevel(logging.INFO)

        _IS_CONFIGURED = True

    return logging.getLogger(name) if name else root_logger


def get_log_file_path() -> str:
    """Returns the absolute path to the active persistent log file."""
    return LOG_FILE_PATH


def get_recent_logs(max_lines: int = 250) -> list[str]:
    """
    Reads and returns the most recent lines from the persistent log file.

    Args:
        max_lines (int): Maximum number of recent log lines to retrieve.

    Returns:
        list[str]: Chronologically ordered list of log lines.
    """
    if not os.path.exists(LOG_FILE_PATH):
        return []

    try:
        with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return [line.rstrip("\r\n") for line in lines[-max_lines:]]
    except OSError:
        return []
