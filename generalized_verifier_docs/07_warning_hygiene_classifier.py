#!/usr/bin/env python3





























import argparse
import json
import re
import sys
from collections import Counter





_DIAG_RE = re.compile(
    r'^(?P<file>[^:\s][^:]*?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*'
    r'(?P<sev>fatal error|error|warning|note):\s*(?P<msg>.*\S)\s*$'
)
_FLAG_RE = re.compile(r'\[-W(?:error=)?([a-z0-9-]+)\]\s*$')
_QUOTED_RE = re.compile('[‘\'`]([^’\'`]+)[’\'`]')




STD_SYMBOL_HEADERS = {

    "uint8_t": "cstdint", "uint16_t": "cstdint", "uint32_t": "cstdint",
    "uint64_t": "cstdint", "int8_t": "cstdint", "int16_t": "cstdint",
    "int32_t": "cstdint", "int64_t": "cstdint",
    "size_t": "cstddef", "ptrdiff_t": "cstddef",

    "string": "string", "wstring": "string", "u16string": "string",
    "u32string": "string", "string_view": "string_view",

    "vector": "vector", "array": "array", "deque": "deque",
    "list": "list", "forward_list": "forward_list",
    "map": "map", "multimap": "map", "set": "set", "multiset": "set",
    "unordered_map": "unordered_map", "unordered_multimap": "unordered_map",
    "unordered_set": "unordered_set", "unordered_multiset": "unordered_set",
    "stack": "stack", "queue": "queue", "priority_queue": "queue",

    "pair": "utility", "make_pair": "utility", "move": "utility",
    "swap": "utility", "forward": "utility",
    "tuple": "tuple", "make_tuple": "tuple",
    "optional": "optional", "variant": "variant", "any": "any",
    "unique_ptr": "memory", "shared_ptr": "memory",
    "make_unique": "memory", "make_shared": "memory",
    "function": "functional",

    "find": "algorithm", "find_if": "algorithm", "sort": "algorithm",
    "count": "algorithm", "count_if": "algorithm", "min": "algorithm",
    "max": "algorithm", "minmax": "algorithm", "transform": "algorithm",
    "copy": "algorithm", "reverse": "algorithm", "rotate": "algorithm",
    "lower_bound": "algorithm", "upper_bound": "algorithm",
    "binary_search": "algorithm", "all_of": "algorithm",
    "any_of": "algorithm", "none_of": "algorithm", "for_each": "algorithm",
    "remove": "algorithm", "remove_if": "algorithm", "unique": "algorithm",
    "accumulate": "numeric", "inner_product": "numeric", "iota": "numeric",

    "cout": "iostream", "cin": "iostream", "cerr": "iostream",
    "endl": "ostream", "ostringstream": "sstream", "istringstream": "sstream",
    "sqrt": "cmath", "pow": "cmath", "fabs": "cmath", "floor": "cmath",
    "ceil": "cmath", "round": "cmath", "abs": "cstdlib",
    "isdigit": "cctype", "isspace": "cctype", "isalpha": "cctype",
    "isalnum": "cctype", "toupper": "cctype", "tolower": "cctype",
    "runtime_error": "stdexcept", "invalid_argument": "stdexcept",
    "out_of_range": "stdexcept", "logic_error": "stdexcept",
    "exception": "exception", "numeric_limits": "limits",
}


FLAG_CLASSES = {
    "unused-parameter": "unused-parameter",
    "unused-variable": "unused-variable",
    "unused-function": "unused-function",
    "unused-but-set-variable": "unused-variable",
    "unused-but-set-parameter": "unused-parameter",
    "sign-compare": "sign-compare",
    "return-local-addr": "return-local-addr",
    "shadow": "shadow",
    "tautological-compare": "tautological-compare",
}

FIX_HINTS = {
    "unused-parameter":
        "remove the parameter, omit its name in the definition, or mark it "
        "[[maybe_unused]]",
    "unused-variable":
        "remove the variable or mark it [[maybe_unused]]",
    "unused-function":
        "remove the function, call it, or mark it [[maybe_unused]] (an "
        "internal-linkage function that is never used is an error under "
        "-Werror)",
    "missing-include":
        "add #include <{header}> -- '{symbol}' is declared there",
    "sign-compare":
        "compare values of the same signedness: cast one side (e.g. to "
        "std::size_t) or change the variable's type",
    "return-local-addr":
        "do not return a reference/pointer to local '{symbol}'; return by "
        "value or give the storage static/member lifetime",
    "shadow":
        "rename the inner '{symbol}' so it does not shadow the outer "
        "declaration",
    "tautological-compare":
        "this comparison is always true/false; compare against a different "
        "value or delete the check",
    "constexpr-not-literal":
        "'{symbol}' has a non-literal type (non-trivial constructor or "
        "destructor); use 'const' instead of 'constexpr'",
    "private-access":
        "'{symbol}' is private; use the public interface, or add a public "
        "accessor if the API requires it",
    "undeclared-identifier":
        "'{symbol}' is not declared here; check spelling, namespace "
        "qualification, and that a declaration precedes this use",
    "missing-member":
        "'{symbol}' is not declared in namespace '{namespace}'; declare it "
        "there -- callers reference {namespace}::{symbol}",
    "other":
        "unclassified compiler diagnostic; read the full message and the "
        "source line it points at",
}


def _strip_std(symbol):
    return symbol[5:] if symbol.startswith("std::") else symbol


def _last_component(symbol):
    pass
    parts = [p for p in symbol.split("::") if p and p != "{anonymous}"]
    return parts[-1] if parts else symbol


def _quoted(msg, index=0):
    hits = _QUOTED_RE.findall(msg)
    return hits[index] if len(hits) > index else None


def classify_message(msg):
    pass
    flag_m = _FLAG_RE.search(msg)
    if flag_m:
        flag = flag_m.group(1)
        cls = FLAG_CLASSES.get(flag)
        if cls:
            return cls, _quoted(msg) or "", {}

        return "other", _quoted(msg) or "", {"flag": flag}

    m = re.search("‘(.+?)’ is private within this context", msg) or \
        re.search("'(.+?)' is private within this context", msg)
    if m:
        return "private-access", _last_component(m.group(1)), {}

    m = re.search("of ‘constexpr’ variable ‘(.+?)’ is not literal", msg) or \
        re.search("of 'constexpr' variable '(.+?)' is not literal", msg)
    if m:
        return "constexpr-not-literal", _last_component(m.group(1)), {}


    m = re.search("‘(.+?)’ in namespace ‘std’ does not name a", msg) or \
        re.search("'(.+?)' in namespace 'std' does not name a", msg)
    if m:
        sym = m.group(1)
        header = STD_SYMBOL_HEADERS.get(_strip_std(sym))
        if header:
            return "missing-include", _strip_std(sym), {"header": header}
        return "undeclared-identifier", sym, {}


    m = re.search("‘(.+?)’ is not a member of ‘(.+?)’", msg) or \
        re.search("'(.+?)' is not a member of '(.+?)'", msg)
    if m:
        sym, ns = m.group(1), m.group(2)
        if ns == "std":
            header = STD_SYMBOL_HEADERS.get(_strip_std(sym))
            if header:
                return "missing-include", _strip_std(sym), {"header": header}
            return "undeclared-identifier", sym, {}
        return "missing-member", sym, {"namespace": ns}


    m = re.search("‘(.+?)’ was not declared in this scope", msg) or \
        re.search("'(.+?)' was not declared in this scope", msg)
    if m:
        sym = m.group(1)
        header = STD_SYMBOL_HEADERS.get(_strip_std(sym))
        if header:
            return "missing-include", _strip_std(sym), {"header": header}
        return "undeclared-identifier", sym, {}

    return "other", _quoted(msg) or "", {}


def parse_stderr(text):
    pass
    findings = []
    for raw in text.splitlines():
        m = _DIAG_RE.match(raw)
        if not m:
            continue
        sev = m.group("sev")
        if sev == "note":
            continue
        msg = m.group("msg")
        cls, symbol, extra = classify_message(msg)
        hint = FIX_HINTS[cls]
        if "{header}" in hint:
            hint = hint.format(header=extra.get("header", "?"),
                               symbol=symbol)
        elif "{namespace}" in hint:
            hint = hint.format(symbol=symbol,
                               namespace=extra.get("namespace", "?"))
        elif "{symbol}" in hint:
            hint = hint.format(symbol=symbol)
        findings.append({
            "class": cls,
            "severity": "error" if sev == "fatal error" else sev,
            "file": m.group("file"),
            "line": int(m.group("line")),
            "symbol": symbol,
            "fix_hint": hint,
            "message": msg,
        })
    return findings


def dominant_class(findings):
    pass




    errors = [f for f in findings if f["severity"] == "error"]
    pool = errors or findings
    specific = [f for f in pool if f["class"] != "other"]
    if specific:
        pool = specific
    if not pool:
        return None
    counts = Counter(f["class"] for f in pool)
    best, best_n = None, -1
    for f in pool:
        c = f["class"]
        if counts[c] > best_n:
            best, best_n = c, counts[c]
    return best


def classify(text):
    findings = parse_stderr(text)
    errors = [f for f in findings if f["severity"] == "error"]
    return {
        "verdict": "FAIL" if errors else "PASS",
        "dominant_class": dominant_class(findings),
        "error_count": len(errors),
        "warning_count": len(findings) - len(errors),
        "findings": findings,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Classify raw g++ stderr into warning/hygiene classes "
                    "with actionable one-line fixes. Reads --stderr PATH or "
                    "standard input.")
    ap.add_argument("--stderr", metavar="PATH",
                    help="file containing captured g++ stderr "
                         "(default: read stdin)")
    ap.add_argument("--json", action="store_true",
                    help="emit the full machine-readable report")
    ap.add_argument("--receipt", default=None, metavar="DIR",
                    help="also write a sandbox-compatible kernel receipt "
                         "(<verifier>_kernel_receipt.json) into DIR")
    args = ap.parse_args(argv)
    if args.receipt:
        import receipt_compat
        return receipt_compat.run_with_receipt(args.receipt, run, args, argv)
    return run(args)


def run(args):
    if args.stderr:
        try:
            with open(args.stderr) as f:
                text = f.read()
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        text = sys.stdin.read()

    report = classify(text)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("--- Warning-Hygiene Classifier ---")
        if not report["findings"]:
            print("no compiler diagnostics found")
        for f in report["findings"]:
            print(f"  {f['severity'].upper():7s} [{f['class']}] "
                  f"{f['file']}:{f['line']}: {f['message']}")
            print(f"          fix: {f['fix_hint']}")
        if report["dominant_class"]:
            print(f"dominant class: {report['dominant_class']} "
                  f"({report['error_count']} errors, "
                  f"{report['warning_count']} warnings)")
        print(f"VERDICT: {report['verdict']}")
    return 1 if report["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
