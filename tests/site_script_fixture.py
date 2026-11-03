"""Load tracked site adapters for parsing tests without a third-party checkout."""
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "thirdparty_goverment_spider"


def _load(path, alias):
    spec = importlib.util.spec_from_file_location(alias, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_site_script(filename, alias):
    # These tests exercise pure parsers, not the third-party output/logging layer.
    # Fail loudly if a test accidentally enters a write or delay path.
    utils = types.ModuleType("utils")
    utils.logger = Mock()
    utils.now = "2026-10-28"
    utils.year_month = "2026-10"
    utils.write_file = Mock(side_effect=AssertionError("Unexpected file output"))
    utils.sleep_time = 0
    site_fetch = _load(SCRIPTS / "site_fetch.py", "fixture_site_fetch")
    with patch.dict(sys.modules, {"utils": utils, "site_fetch": site_fetch}), \
            patch.object(sys, "path", sys.path.copy()):
        return _load(SCRIPTS / filename, alias)
