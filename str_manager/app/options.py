import json
import logging

OPTIONS_PATH = "/data/options.json"
logger = logging.getLogger(__name__)


def load() -> dict:
    try:
        with open(OPTIONS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def test_mode() -> bool:
    return bool(load().get("test_mode", False))
