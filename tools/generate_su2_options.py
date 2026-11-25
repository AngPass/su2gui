#!/usr/bin/env python
"""Generate core/su2_options.json from an SU2 source checkout.

The catalog lists every configuration option registered in
Common/src/CConfig.cpp (add*Option("NAME", ...)), its kind, the accepted values
of enum options (maps in Common/include/option_structure.hpp), the options
documented in config_template.cfg, and the deprecated option names that SU2
reports with their replacement.

SU2 stops with an error on an unknown/deprecated option name or on an invalid
enum value, so SU2GUI uses this catalog to check the configuration before
writing it.

Usage:
    python tools/generate_su2_options.py /path/to/SU2 [core/su2_options.json]
"""

import json
import re
import subprocess
import sys
from pathlib import Path


def parse_maps(header_text):
    """static const MapType<std::string, X> Name = { MakePair("A", ...) ... };"""
    maps = {}
    for m in re.finditer(r"MapType<\s*std::string\s*,[^>]*>\s+(\w+)\s*=\s*\{(.*?)\};", header_text, re.S):
        maps[m.group(1)] = re.findall(r'MakePair\(\s*"([^"]+)"', m.group(2))
    return maps


def split_args(text):
    """Split the argument list of a call at top-level commas."""
    args, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def parse_options(cconfig_text, maps):
    options = {}
    for m in re.finditer(r'\badd(\w*)Option\(\s*"([A-Z0-9_]+)"\s*(?:,(.*?))?\)\s*;', cconfig_text, re.S):
        kind, name, rest = m.group(1), m.group(2), m.group(3) or ""
        entry = {"kind": kind or "Generic"}
        args = split_args(rest)
        map_name = next((a for a in args if re.fullmatch(r"\w+_Map", a)), None)
        if map_name and map_name in maps:
            entry["values"] = maps[map_name]
        if kind == "Bool":
            entry["values"] = ["YES", "NO"]
        if name not in options:
            options[name] = entry
    return options


def parse_deprecated(cconfig_text):
    """Deprecated names handled in CConfig::SetConfig_Parsing ('X is deprecated. Use Y')."""
    deprecated = {}
    for m in re.finditer(r'option_name\.compare\("([A-Z0-9_]+)"\)(.*?)newString\.append\("([^"]*)"', cconfig_text, re.S):
        names = [m.group(1)] + re.findall(r'option_name\.compare\("([A-Z0-9_]+)"\)', m.group(2))
        message = m.group(3).replace("\\n", " ").strip()
        use = re.search(r"Use ([A-Z][A-Z0-9_]+)", message)
        for n in names:
            deprecated[n] = {"replacement": use.group(1) if use else None, "message": message}
    return deprecated


def main():
    su2 = Path(sys.argv[1]).expanduser().resolve()
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "core" / "su2_options.json"

    cconfig = (su2 / "Common/src/CConfig.cpp").read_text(encoding="utf-8", errors="replace")
    header = (su2 / "Common/include/option_structure.hpp").read_text(encoding="utf-8", errors="replace")
    template = (su2 / "config_template.cfg").read_text(encoding="utf-8", errors="replace")

    maps = parse_maps(header)
    options = parse_options(cconfig, maps)
    deprecated = parse_deprecated(cconfig)
    in_template = sorted(set(re.findall(r"^%?\s*([A-Z][A-Z0-9_]+)\s*=", template, re.M)) & set(options))

    try:
        commit = subprocess.run(["git", "-C", str(su2), "log", "-1", "--format=%H %cs"],
                                capture_output=True, text=True, check=True).stdout.strip()
        branch = subprocess.run(["git", "-C", str(su2), "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        commit, branch = "unknown", "unknown"

    catalog = {
        "source": {"branch": branch, "commit": commit},
        "options": dict(sorted(options.items())),
        "in_config_template": in_template,
        "deprecated": dict(sorted(deprecated.items())),
    }
    out.write_text(json.dumps(catalog, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    n_enum = sum(1 for o in options.values() if "values" in o)
    print(f"{out}: {len(options)} options ({n_enum} with accepted values), "
          f"{len(deprecated)} deprecated names, SU2 {branch} {commit}")


if __name__ == "__main__":
    main()
