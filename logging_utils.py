from __future__ import annotations

import logging
from pathlib import Path


LOGGER_NAME = "codingpet"


def setup_logging(log_path: str | Path = "codingpet.log") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    target = Path(log_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    )

    logger.setLevel(logging.INFO)
    logger.propagate = False

    file_handler = logging.FileHandler(target, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger
