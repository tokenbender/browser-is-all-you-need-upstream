#!/usr/bin/env python3
"""
Verifier 01: Structural API Gate (generalized).

Derives the required public API (namespace::identifier pairs, plus
template/constructor usage) from the task's official test file and checks
that the candidate sources declare every required symbol with the required
shape. No task names are hardcoded; all task knowledge enters via
--test / --header / --source.

    python3 01_structural_api_gate.py --test <task>_test.cpp \
        --header candidate.h [--source candidate.cpp ...] [--json]

Exit code 0 = PASS, 1 = structural FAIL, 2 = usage/IO error.
"""

import argparse
import json
import re
import sys

# Namespaces provided by the toolchain / test framework, never by the
# candidate; everything else the test qualifies is part of the task contract.
EXTERNAL_NAMESPACES = frozenset({
    "std", "Catch", "catch2", "Catch2", "detail", "testing", "boost",
    "__gnu_cxx", "gnu_cxx",
})

CONTROL_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "catch", "return", "sizeof", "static_cast",
    "reinterpret_cast", "const_cast", "dynamic_cast", "decltype", "requires",
    "noexcept", "alignof", "typeid", "new", "delete", "throw", "static_assert",
})


# ---------------------------------------------------------------------------
# Lexical helpers (backend)
# ---------------------------------------------------------------------------

def strip_comments_and_literals(code):
    """Remove // and /* */ comments; blank out string/char literal contents.

    Preprocessor lines are kept (they carry no declarations we track, and
    keeping line structure makes diagnostics stable).
    """
    out = []
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if c == '/' and i + 1 < n and code[i + 1] == '/':
            while i < n and code[i] != '\n':
                i += 1
        elif c == '/' and i + 1 < n and code[i + 1] == '*':
            i += 2
            while i + 1 < n and not (code[i] == '*' and code[i + 1] == '/'):
                out.append('\n' if code[i] == '\n' else ' ')
                i += 1
            i += 2
        elif c in '"\'':
            quote = c
            out.append(c)
            i += 1
            while i < n and code[i] != quote:
                if code[i] == '\\':
                    i += 1
                if i < n and code[i] != quote:
                    out.append(' ' if code[i] != '\n' else '\n')
                i += 1
            if i < n:
                out.append(quote)
                i += 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def match_brace(code, open_idx):
    """Given index of '{', return index just past the matching '}'."""
    depth = 0
    for i in range(open_idx, len(code)):
        if code[i] == '{':
            depth += 1
        elif code[i] == '}':
            depth -= 1
            if depth == 0:
                return i + 1
    return len(code)


# ---------------------------------------------------------------------------
# Test-file analysis: derive required symbols (backend)
# ---------------------------------------------------------------------------

class RequiredSymbol:
    def __init__(self, namespace, ident):
        self.namespace = namespace
        self.ident = ident
        self.used_as_template = False
        self.constructed = False      # call/temporary/value-init syntax seen
        self.used_as_type = False     # variable declared of this type

    def key(self):
        return (self.namespace, self.ident)

    def __repr__(self):
        return f"<required {self.namespace}::{self.ident}>"


_CHAIN_RE = re.compile(r'\b([A-Za-z_]\w*(?:::[A-Za-z_]\w*)+)')
_USING_DECL_RE = re.compile(
    r'\busing\s+(?:typename\s+)?(?:[A-Za-z_]\w*::)+([A-Za-z_]\w*)\s*;'
)
_USING_ALIAS_RE = re.compile(r'\busing\s+([A-Za-z_]\w*)\s*=')
_LOCAL_TYPE_RE = re.compile(
    r'\b(?:class|struct|enum(?:\s+class)?)\s+([A-Za-z_]\w*)'
)


def _test_local_scope_names(code):
    """Return names that a test introduces as type/member scopes.

    A chain such as ``weekly_time::at`` does not name a namespace when the
    test previously wrote ``using cyclic_schedule::weekly_time``.  The API
    contract in that case is the imported ``cyclic_schedule::weekly_time``;
    member existence and signatures are checked by the compile gate.  The
    same rule applies to ``using Alias = ...`` and test-local type
    declarations.
    """
    return {
        *(match.group(1) for match in _USING_DECL_RE.finditer(code)),
        *(match.group(1) for match in _USING_ALIAS_RE.finditer(code)),
        *(match.group(1) for match in _LOCAL_TYPE_RE.finditer(code)),
    }


def required_symbols_from_test(test_code):
    """Extract required (namespace, identifier) pairs from the official test.

    Only the FIRST two components of a qualified chain matter:
    ``a::b::c`` requires symbol ``b`` in namespace ``a`` (``c`` is a member
    of ``b``). Usage flags (template / constructed / type) are recorded.
    """
    code = strip_comments_and_literals(test_code)
    local_scopes = _test_local_scope_names(code)
    symbols = {}
    for m in _CHAIN_RE.finditer(code):
        parts = m.group(1).split('::')
        ns, ident = parts[0], parts[1]
        if ns in EXTERNAL_NAMESPACES or ns in local_scopes:
            continue
        sym = symbols.setdefault((ns, ident), RequiredSymbol(ns, ident))
        rest = code[m.start(1) + len(ns) + 2 + len(ident):]
        rest = rest.lstrip()
        if rest.startswith('<'):
            sym.used_as_template = True
            # Skip balanced template args to see what follows them.
            depth = 0
            for j, ch in enumerate(rest):
                if ch == '<':
                    depth += 1
                elif ch == '>':
                    depth -= 1
                    if depth == 0:
                        rest = rest[j + 1:].lstrip()
                        break
        if rest.startswith('(') or rest.startswith('{'):
            sym.constructed = True
        else:
            # ns::Ident <var> {/(/=/;  -> a variable of this type is declared
            vm = re.match(r'[A-Za-z_]\w*\s*[{(&=;]', rest)
            if vm:
                sym.used_as_type = True
                sym.constructed = True
    return sorted(symbols.values(), key=lambda s: s.key())


# ---------------------------------------------------------------------------
# Candidate parsing: declarations per namespace (backend)
# ---------------------------------------------------------------------------

class ClassDecl:
    def __init__(self, name, kind, is_template):
        self.name = name
        self.kind = kind            # 'class' | 'struct' | 'enum'
        self.is_template = is_template
        self.ctor_access = []       # access labels of user-declared ctors
        self.full_definition = False


class CandidateModel:
    def __init__(self):
        self.classes = {}    # (ns, name) -> ClassDecl
        self.functions = {}  # ns -> set(names)
        self.aliases = {}    # ns -> set(names)

    def has_symbol(self, ns, ident):
        if (ns, ident) in self.classes:
            return True
        return ident in self.functions.get(ns, ()) or ident in self.aliases.get(ns, ())

    def get_class(self, ns, ident):
        return self.classes.get((ns, ident))


_DECL_RE = re.compile(
    r'(?P<tmpl>template\s*<[^;{}]*?>\s*)?'
    r'(?P<kind>class|struct|enum(?:\s+class)?)\s+'
    r'(?P<name>[A-Za-z_]\w*)'
    r'(?P<tail>\s*final)?\s*'
    r'(?P<body>[{;:])'
)
_FUNC_RE = re.compile(
    r'\b(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*?\)\s*'
    r'(?:const\b\s*)?(?:noexcept\b\s*)?(?:->[^{;]*?)?[;{]'
)
_ALIAS_RE = re.compile(r'\busing\s+([A-Za-z_]\w*)\s*=')
_ACCESS_RE = re.compile(r'\b(public|private|protected)\s*:')
_NS_OPEN_RE = re.compile(r'\bnamespace\s+([A-Za-z_]\w*)?\s*\{')


def _parse_class_body(body, decl):
    """Record constructor access sections from a class/struct body."""
    default_access = 'public' if decl.kind == 'struct' else 'private'
    access = default_access
    depth = 0
    i = 0
    segment_start = 0
    # Walk top level of the body, splitting on access labels.
    events = []  # (access_label, text_segment)
    while i < len(body):
        ch = body[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        elif depth == 0:
            m = _ACCESS_RE.match(body, i)
            if m:
                events.append((access, body[segment_start:i]))
                access = m.group(1)
                i = m.end()
                segment_start = i
                continue
        i += 1
    events.append((access, body[segment_start:]))
    ctor_re = re.compile(r'(?:explicit\s+)?~?' + re.escape(decl.name) + r'\s*\(')
    for label, text in events:
        for m in ctor_re.finditer(text):
            if text[m.start():].lstrip().startswith('~'):
                continue  # destructor, not a constructor
            decl.ctor_access.append(label)


def _record_declarations(model, ns, body):
    """Record class/enum/function/alias declarations from a namespace body."""
    masked = list(body)
    for m in _DECL_RE.finditer(body):
        kind = m.group('kind').split()[0]
        name = m.group('name')
        is_template = bool(m.group('tmpl'))
        punct = m.group('body')
        key = (ns, name)
        if punct == '{':
            end = match_brace(body, m.end() - 1)
            inner = body[m.end():end - 1]
            existing = model.classes.get(key)
            if existing is None or not existing.full_definition:
                decl = ClassDecl(name, kind, is_template)
                decl.full_definition = True
                if kind in ('class', 'struct'):
                    _parse_class_body(inner, decl)
                model.classes[key] = decl
            for j in range(m.start(), end):
                masked[j] = ' '
        else:
            # forward declaration: record only if nothing known yet
            model.classes.setdefault(key, ClassDecl(name, kind, is_template))
            for j in range(m.start(), m.end()):
                masked[j] = ' '
    rest = ''.join(masked)
    funcs = model.functions.setdefault(ns, set())
    for m in _FUNC_RE.finditer(rest):
        name = m.group('name')
        if name not in CONTROL_KEYWORDS:
            funcs.add(name)
    aliases = model.aliases.setdefault(ns, set())
    for m in _ALIAS_RE.finditer(rest):
        aliases.add(m.group(1))


def _parse_scope(model, code, ns_stack, start, end):
    """Recursively walk [start, end) of code, entering namespace blocks."""
    i = start
    while i < end:
        m = _NS_OPEN_RE.search(code, i, end)
        if not m:
            break
        # Anything between i and m.start() belongs to the current namespace.
        if ns_stack and ns_stack[-1] is not None:
            _record_declarations(model, '::'.join(ns_stack),
                                 code[i:m.start()])
        name = m.group(1)
        close = match_brace(code, m.end() - 1)
        _parse_scope(model, code, ns_stack + [name], m.end(), close - 1)
        i = close
    else:
        pass
    # Trailing text after the last namespace block in this scope.
    if ns_stack and ns_stack[-1] is not None:
        _record_declarations(model, '::'.join(ns_stack), code[i:end])


def parse_candidate(header_code, extra_codes=()):
    """Build a CandidateModel from the candidate header (authoritative for
    access visibility) plus optional extra sources (e.g. .cpp), which may only
    ADD symbols, never override header declarations."""
    model = CandidateModel()
    for code in (header_code,) + tuple(extra_codes):
        clean = strip_comments_and_literals(code)
        sub = CandidateModel()
        _parse_scope(sub, clean, [], 0, len(clean))
        # Merge: header wins on conflicts (it was parsed first).
        for key, decl in sub.classes.items():
            if key not in model.classes:
                model.classes[key] = decl
        for ns, names in sub.functions.items():
            model.functions.setdefault(ns, set()).update(names)
        for ns, names in sub.aliases.items():
            model.aliases.setdefault(ns, set()).update(names)
    return model


# ---------------------------------------------------------------------------
# Verdict logic (backend-independent)
# ---------------------------------------------------------------------------

def check_candidate(required, model):
    """Return list of per-symbol verdict dicts."""
    verdicts = []
    for sym in required:
        ns, ident = sym.namespace, sym.ident
        entry = {"symbol": f"{ns}::{ident}", "ok": True, "messages": []}
        if not model.has_symbol(ns, ident):
            entry["ok"] = False
            entry["messages"].append(
                f"required symbol '{ident}' not declared in namespace '{ns}'")
            verdicts.append(entry)
            continue
        decl = model.get_class(ns, ident)
        if decl is not None:
            if sym.used_as_template and not decl.is_template:
                entry["ok"] = False
                entry["messages"].append(
                    f"required symbol '{ident}' is used as a template "
                    f"('{ns}::{ident}<T>') but is not declared as a template "
                    f"in namespace '{ns}'")
            if sym.constructed and decl.kind in ('class', 'struct'):
                if decl.ctor_access and 'public' not in decl.ctor_access:
                    entry["ok"] = False
                    entry["messages"].append(
                        f"'{ident}' constructor is "
                        f"{decl.ctor_access[0]} -- the test constructs "
                        f"'{ns}::{ident}' and needs a public constructor")
        verdicts.append(entry)
    return verdicts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Structural API gate: derive the required API from the "
                    "official test file and check the candidate declares it.")
    ap.add_argument("--test", required=True,
                    help="path to the task's official test .cpp")
    ap.add_argument("--header", required=True,
                    help="path to the candidate header")
    ap.add_argument("--source", action="append", default=[],
                    help="candidate .cpp (repeatable); may add symbols but "
                         "never overrides header declarations")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable verdicts")
    ap.add_argument("--receipt", default=None, metavar="DIR",
                    help="also write a sandbox-compatible kernel receipt "
                         "(<verifier>_kernel_receipt.json) into DIR")
    args = ap.parse_args(argv)
    if args.receipt:
        import receipt_compat
        return receipt_compat.run_with_receipt(args.receipt, run, args, argv)
    return run(args)


def run(args):
    try:
        with open(args.test) as f:
            test_code = f.read()
        with open(args.header) as f:
            header_code = f.read()
        extra = []
        for path in args.source:
            with open(path) as f:
                extra.append(f.read())
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    required = required_symbols_from_test(test_code)
    model = parse_candidate(header_code, extra)
    verdicts = check_candidate(required, model)

    failed = [v for v in verdicts if not v["ok"]]
    if args.json:
        print(json.dumps({
            "required_symbols": [v["symbol"] for v in verdicts],
            "verdicts": verdicts,
            "passed": not failed,
        }, indent=2))
    else:
        print("--- Structural API Gate ---")
        print(f"Required symbols derived from test: "
              f"{', '.join(v['symbol'] for v in verdicts) or '(none)'}")
        for v in verdicts:
            if v["ok"]:
                print(f"  OK    {v['symbol']}")
            else:
                for msg in v["messages"]:
                    print(f"  FAIL  {msg}")
        if failed:
            print(f"VERDICT: FAIL ({len(failed)}/{len(verdicts)} symbols)")
        else:
            print(f"VERDICT: PASS ({len(verdicts)} symbols)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
