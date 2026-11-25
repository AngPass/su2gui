"""Check a configuration against the options of SU2 (catalog in su2_options.json).

SU2 stops with an error when the .cfg contains an unknown option, a deprecated
option name or an invalid value of an enum option (CConfig::SetConfig_Parsing).
The catalog is generated from the SU2 sources with
``python tools/generate_su2_options.py /path/to/SU2`` and records the SU2
branch/commit it comes from: if SU2_CFD is a different version, some messages
may not apply, so the GUI only reports them and never blocks a run.

No trame dependency.
"""

import difflib
import json
import re
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "su2_options.json"

_catalog = None


def catalog():
    global _catalog
    if _catalog is None:
        try:
            _catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _catalog = {"source": {}, "options": {}, "deprecated": {}, "in_config_template": []}
    return _catalog


def option_names():
    return set(catalog()["options"])


def source():
    s = catalog().get("source", {})
    return f"SU2 {s.get('branch', '?')} {s.get('commit', '?')[:10]}"


def migrate(config):
    """Rename the deprecated options that have a replacement (e.g. INC_INLET_USENORMAL ->
    INLET_USE_NORMAL) and drop the ones without replacement.

    Returns (new_config, messages); the input is not modified.
    """
    deprecated = catalog().get("deprecated", {})
    out, messages = {}, []
    for key, value in config.items():
        if key in deprecated and key not in option_names():
            new = deprecated[key].get("replacement")
            if new and new in option_names():
                if new not in config:
                    out[new] = value
                messages.append(f"{key} is deprecated in SU2, renamed to {new}")
            else:
                messages.append(f"{key} is deprecated in SU2 and was removed: {deprecated[key].get('message', '')}")
            continue
        out[key] = value
    return out, messages


def _tokens(value):
    """Values of an enum list option: lists, or strings separated by spaces/commas."""
    if isinstance(value, (list, tuple)):
        items = []
        for v in value:
            items.extend(_tokens(v))
        return items
    return [t for t in re.split(r"[\s,()]+", str(value)) if t]


def check(config):
    """Problems that would make SU2 stop: list of (option, message)."""
    options = catalog().get("options", {})
    if not options:
        return []
    names = set(options)
    issues = []
    for key, value in config.items():
        if key not in names:
            hint = difflib.get_close_matches(key, names, n=1)
            issues.append((key, f"unknown SU2 option {key}" + (f" (did you mean {hint[0]}?)" if hint else "")))
            continue
        entry = options[key]
        accepted = entry.get("values")
        if not accepted:
            continue
        kind = entry.get("kind")
        if kind == "Bool":
            if not isinstance(value, bool) and str(value).strip().upper() not in ("YES", "NO"):
                issues.append((key, f"{key}= {value}: expected YES or NO"))
            continue
        if kind not in ("Enum", "EnumList"):
            continue
        tokens = _tokens(value)
        if kind == "Enum" and len(tokens) > 1:
            issues.append((key, f"{key} accepts a single value, found {tokens}"))
        bad = [t for t in tokens if t not in accepted]
        if bad:
            issues.append((key, f"{key}= {value}: invalid value {bad}, accepted: {', '.join(accepted)}"))
    return issues
