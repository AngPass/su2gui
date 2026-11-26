#!/usr/bin/env python
"""Generate core/su2_options.json from an SU2 source checkout.

The catalog lists every configuration option registered in
Common/src/CConfig.cpp (add*Option("NAME", ...)) with:

- kind: the add*Option flavour (Double, Bool, Enum, StringList, Inlet, ...);
- values: the accepted values of enum options (maps in Common/include/option_structure.hpp);
- default: the default value set in CConfig.cpp, when it is a literal;
- category: the CONFIG_CATEGORY of CConfig.cpp the option is registered in;
- section: the section of config_template.cfg the option is documented in;
- description: the comment of config_template.cfg (or of CConfig.cpp) for the option;
- example: the value written for the option in config_template.cfg;
- order: position of the option in config_template.cfg (CConfig.cpp for the others).

It also lists the options documented in config_template.cfg, and the
deprecated option names that SU2 reports with their replacement.

SU2 stops with an error on an unknown/deprecated option name or on an invalid
enum value, so SU2GUI uses this catalog to check the configuration before
writing it; the GUI also uses it to edit any option (core/cfg_layout.py).

Usage:
    python tools/generate_su2_options.py /path/to/SU2 [core/su2_options.json]
"""

import json
import re
import subprocess
import sys
from pathlib import Path


def parse_maps(header_text):
    """static const MapType<std::string, X> Name = { MakePair("A", X::A) ... };

    Returns {map name: [(string, C++ enum value), ...]}.
    """
    maps = {}
    for m in re.finditer(r"MapType<\s*std::string\s*,[^>]*>\s+(\w+)\s*=\s*\{(.*?)\};", header_text, re.S):
        maps[m.group(1)] = re.findall(r'MakePair\(\s*"([^"]+)"\s*,\s*([^)]*?)\s*\)', m.group(2))
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


_NUMBER = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


def _literal_default(kind, arg, map_pairs):
    """Default value of an option from the last argument of add*Option (None if not a literal)."""
    arg = arg.strip()
    if kind == "Bool":
        low = arg.lower()
        if low in ("true", "yes"):
            return "YES"
        if low in ("false", "no"):
            return "NO"
        return None
    if kind == "String":
        m = re.fullmatch(r'(?:string|std::string)?\(?\s*"([^"]*)"\s*\)?', arg)
        return m.group(1) if m else None
    if kind == "Enum":
        if not map_pairs:
            return None
        value = arg.split("::")[-1]
        for name, cpp in map_pairs:
            if cpp == arg or cpp.split("::")[-1] == value:
                return name
        return None
    if kind in ("Double", "UnsignedLong", "UnsignedShort", "Long"):
        text = arg.rstrip("fFuUlL") if not arg.lower().startswith("0x") else arg
        return text if _NUMBER.match(text) else None
    return None


def _clean_doc(comment, name):
    """Text of a doxygen comment of CConfig.cpp."""
    text = comment.strip()
    text = re.sub(r"^/\*!?", "", text)
    text = re.sub(r"\*/$", "", text)
    text = re.sub(r"\\link\s+(\S+)\s*\\endlink", r"\1", text)
    text = re.sub(r"\\brief\s+\S+", "", text)
    text = re.sub(r"\\(ingroup\s+\w+|n|par)", " ", text)
    text = re.sub(r"^\s*\*\s?", "", text, flags=re.M)
    text = re.sub(r"\bDESCRIPTION:\s*", "", text)
    text = re.sub(r"\s*\bDEFAULT:?.*$", "", text, flags=re.S)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text.startswith(name):
        text = text[len(name):].strip(" :")
    return text


def parse_options(cconfig_text, maps):
    categories = [(m.start(), m.group(1).strip())
                  for m in re.finditer(r"CONFIG_CATEGORY:\s*(.+?)\s*(?:\\ingroup[^*]*)?\*/", cconfig_text)]
    options = {}
    last_end = 0
    for index, m in enumerate(re.finditer(
            r'\badd(\w*)Option\(\s*"([A-Z0-9_]+)"\s*(?:,(.*?))?\)\s*;', cconfig_text, re.S)):
        kind, name, rest = m.group(1) or "Generic", m.group(2), m.group(3) or ""
        gap = cconfig_text[last_end:m.start()]
        last_end = m.end()
        if name in options:
            continue
        entry = {"kind": kind}
        args = split_args(rest)
        map_name = next((a for a in args if re.fullmatch(r"\w+_Map", a)), None)
        if map_name and map_name in maps:
            entry["values"] = [n for n, _ in maps[map_name]]
        if kind == "Bool":
            entry["values"] = ["YES", "NO"]
        elif kind == "Convect":
            # central or upwind scheme (Centered_Map + Upwind_Map), not checked by core.su2_options.check
            values = [n for map_ in ("Centered_Map", "Upwind_Map") for n, _ in maps.get(map_, [])]
            entry["values"] = list(dict.fromkeys(values))
        elif kind == "MathProblem":
            entry["values"] = ["DIRECT", "CONTINUOUS_ADJOINT", "DISCRETE_ADJOINT"]
        if args:
            default = _literal_default(kind, args[-1], maps.get(map_name))
            if default is not None:
                entry["default"] = default
        cat = [c for pos, c in categories if pos < m.start()]
        entry["category"] = cat[-1] if cat else "Other"
        comments = re.findall(r"/\*.*?\*/", gap, re.S)
        if comments:
            doc = _clean_doc(comments[-1], name)
            if doc and "CONFIG_CATEGORY" not in doc:
                entry["cconfig_description"] = doc
        entry["cconfig_order"] = index
        options[name] = entry
    return options


_SECTION = re.compile(r"^%\s*-{3,}\s*(.+?)\s*-{3,}\s*%?\s*$")
_OPTION_LINE = re.compile(r"^(%\s*)?([A-Z][A-Z0-9_]+)\s*=\s*(.*?)\s*$")


def parse_template(template_text, names):
    """{option: {section, description, example, order}} from config_template.cfg."""
    docs = {}
    section = "Other"
    buffer = []
    order = 0
    for raw in template_text.splitlines():
        line = raw.rstrip()
        sec = _SECTION.match(line)
        if sec:
            section = re.sub(r"\s+", " ", sec.group(1)).strip()
            buffer = []
            continue
        opt = _OPTION_LINE.match(line)
        if opt and opt.group(2) in names:
            name = opt.group(2)
            if name not in docs:
                docs[name] = {
                    "section": section,
                    "description": " ".join(buffer).strip(),
                    "example": opt.group(3).split("%")[0].strip(),
                    "order": order,
                }
                order += 1
            if not opt.group(1):
                buffer = []
            continue
        if line.strip() == "%" or not line.strip():
            buffer = []
        elif line.startswith("%"):
            buffer.append(re.sub(r"\s+", " ", line.lstrip("%").strip()))
    return docs


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
    docs = parse_template(template, set(options))

    # template order first, then the options that are only in CConfig.cpp (in CConfig.cpp order)
    n_template = len(docs)
    for name, entry in options.items():
        doc = docs.get(name)
        cdesc = entry.pop("cconfig_description", "")
        corder = entry.pop("cconfig_order")
        if doc:
            entry["section"] = doc["section"]
            entry["description"] = doc["description"] or cdesc
            if doc["example"]:
                entry["example"] = doc["example"]
            entry["order"] = doc["order"]
        else:
            entry["description"] = cdesc
            entry["order"] = n_template + corder
        if not entry["description"]:
            del entry["description"]

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
        "in_config_template": sorted(docs),
        "deprecated": dict(sorted(deprecated.items())),
    }
    out.write_text(json.dumps(catalog, indent=1, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")
    n_enum = sum(1 for o in options.values() if "values" in o)
    n_doc = sum(1 for o in options.values() if "description" in o)
    print(f"{out}: {len(options)} options ({n_enum} with accepted values, {n_doc} documented), "
          f"{len(deprecated)} deprecated names, SU2 {branch} {commit}")


if __name__ == "__main__":
    main()
