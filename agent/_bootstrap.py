"""Shared import bootstrap for the Recur agent.

The agent targets hosts that may have no package manager access (air-gapped
machines). PyYAML is the only non-stdlib dependency; when the system Python
has no ``yaml`` module, this bootstrap falls back to the pure-Python copy
vendored in ``agent/vendor/yaml/`` (PyYAML, MIT licensed, no C extension
required).

Usage in any agent module:

    from _bootstrap import ensure_yaml

    yaml = ensure_yaml()
"""

from __future__ import annotations

import sys
from pathlib import Path

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"


def ensure_yaml():
    """Return an importable ``yaml`` module.

    Prefers the system/distribution PyYAML; when it is absent, prepends the
    vendored directory to ``sys.path`` and imports the bundled pure-Python
    copy. Raises ``ImportError`` if neither is available.
    """
    try:
        import yaml  # noqa: F401
    except ImportError:
        if not (_VENDOR_DIR / "yaml").is_dir():
            raise
        if str(_VENDOR_DIR) not in sys.path:
            sys.path.insert(0, str(_VENDOR_DIR))
        import yaml  # noqa: F401
    return yaml
