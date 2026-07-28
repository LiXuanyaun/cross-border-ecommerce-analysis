from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


LOGGER_NAME = "crossborder.api"


def configure_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(event: str, **fields: Any) -> None:
    logger = configure_logging()
    payload = {
        "event": event,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **{key: value for key, value in fields.items() if value is not None},
    }
    logger.info(json.dumps(payload, ensure_ascii=False, default=str))
