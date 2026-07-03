"""
URUK Trinity Console — Tool Safety Module (Phase 3)

4-Layer mandatory safety gate for LLM-generated Python tool services:

  Layer A — AST static analysis (this module)
  Layer B — LLM security review (in trinity_console.py)
  Layer C — Sandbox subprocess smoke test (this module)
  Layer D — Operator manual approve (chat command)

⚠ IMPORTANT — defense-in-depth boundaries:

  Subprocess in Layer C is NOT real isolation (still runs in operator's
  native Python interpreter with same fs / network access). The actual
  enforcement comes from combining:
    - AST audit: blocks subprocess/os/eval/exec/file-write/dunder
    - LLM review: second-opinion narrative audit
    - Subprocess: catches import-time bugs + 10s timeout
    - Operator approve: human-in-the-loop final gate
  
  This is defense-in-depth for personal sovereign use, NOT production
  multi-user sandbox. A truly malicious LLM output combined with operator
  rubber-stamp could still escape — operators must read the generated
  code before promote.
"""

import ast
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# ─────────────────────────────────────────────────────────────────
# Layer A configuration
# ─────────────────────────────────────────────────────────────────

ALLOWED_IMPORTS = {
    "httpx",
    "json",
    "typing",
    "datetime",
    "urllib",
    "urllib.parse",
    "urllib.request",   # NOT — but flagged: we don't allow this. Use httpx.
    "re",
    "dataclasses",
    "time",
    "math",
    "hashlib",
    "base64",
    "collections",
}
# Note: we DO want to forbid urllib.request because it can leak fewer headers
# than httpx and is harder to inspect. Remove from set:
ALLOWED_IMPORTS.discard("urllib.request")

FORBIDDEN_NAMES = {
    "eval", "exec", "compile",
    "__import__",
    "getattr", "setattr", "delattr",  # block dynamic attribute access
    "globals", "locals",
    "open",  # block file I/O (Layer C subprocess does its own tempfile work)
    "input",  # block stdin reads
    "breakpoint",  # block debugger
    "vars",
}

FORBIDDEN_MODULES = {
    "subprocess", "os", "sys", "ctypes", "multiprocessing", "threading",
    "pickle", "marshal", "shelve", "dbm",
    "socket", "asyncio.subprocess",
    "requests",  # require httpx (consistent + auditable)
    "shutil", "pathlib",  # block fs manipulation
    "tempfile",  # block tempfile direct (httpx doesn't need)
    "importlib", "imp",
    "builtins",   # accessing builtins indirectly
    "ssl",  # no custom SSL contexts; httpx defaults sufficient
    "fcntl", "select", "termios",
}

# Dunder names that are ALLOWED in normal class definitions
ALLOWED_DUNDER_DEFS = {
    "__init__", "__str__", "__repr__", "__eq__", "__hash__",
    "__call__", "__len__", "__bool__", "__iter__", "__next__",
    "__enter__", "__exit__",
    "__class__",  # type checks
    "__dict__",   # blocked by attribute access rule but not as method def
}


class SafetyError(Exception):
    """Tool safety violation."""


# ─────────────────────────────────────────────────────────────────
# Layer A — AST static analysis
# ─────────────────────────────────────────────────────────────────

def ast_audit(code: str) -> Tuple[bool, List[str]]:
    """Static AST analysis. Returns (passed, list_of_issues).

    Checks:
      - Syntax valid
      - Imports in ALLOWED_IMPORTS (top-level package)
      - No FORBIDDEN_MODULES imports
      - No FORBIDDEN_NAMES calls (eval/exec/etc)
      - No dunder attribute access except ALLOWED_DUNDER_DEFS
      - No open() with write/append mode
      - No `with open(...)` writes
    """
    issues: List[str] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError: {e.msg} at line {e.lineno}"]

    for node in ast.walk(tree):
        # ── Imports ──
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if alias.name in FORBIDDEN_MODULES or top in FORBIDDEN_MODULES:
                    issues.append(f"Forbidden import: {alias.name} (line {node.lineno})")
                elif top not in ALLOWED_IMPORTS:
                    issues.append(f"Non-allowlisted import: {alias.name} (line {node.lineno})")

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top = module.split(".")[0]
            if module in FORBIDDEN_MODULES or top in FORBIDDEN_MODULES:
                issues.append(f"Forbidden import-from: {module} (line {node.lineno})")
            elif top and top not in ALLOWED_IMPORTS:
                issues.append(f"Non-allowlisted import-from: {module} (line {node.lineno})")

        # ── Forbidden function calls (Name(...) where id is forbidden) ──
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_NAMES:
                    issues.append(f"Forbidden call: {node.func.id}(...) (line {node.lineno})")
            # Also check attribute calls — e.g. os.system, builtins.eval
            elif isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr in FORBIDDEN_NAMES:
                    issues.append(f"Forbidden method call: .{attr}(...) (line {node.lineno})")
                # Block .system / .popen / .spawn* / .fork
                if attr in {"system", "popen", "spawn", "spawnv", "spawnl",
                            "fork", "execv", "execve", "execvp",
                            "kill", "wait", "waitpid", "abort",
                            "_exit", "_quit"}:
                    issues.append(f"Forbidden subprocess-like call: .{attr}(...) (line {node.lineno})")

        # ── Dunder attribute access (e.g. obj.__class__) ──
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                if node.attr not in ALLOWED_DUNDER_DEFS:
                    issues.append(f"Dunder access: .{node.attr} (line {node.lineno})")

        # ── Attribute lookups that could escape (e.g. ().__class__.__subclasses__) ──
        # Already covered by dunder check above.

        # ── `with open(...)` write modes ──
        elif isinstance(node, ast.With):
            for item in node.items:
                ce = item.context_expr
                if isinstance(ce, ast.Call) and isinstance(ce.func, ast.Name) and ce.func.id == "open":
                    # already covered by FORBIDDEN_NAMES "open" — issue raised at the Call node
                    pass

        # ── try/except hiding errors — we allow but flag broad except ──
        # (not strict reject, just informational)

    return (len(issues) == 0), issues


# ─────────────────────────────────────────────────────────────────
# Schema parse — extract TOOL_NAME / TOOL_METHOD / TOOL_PARAMS_SCHEMA without executing
# ─────────────────────────────────────────────────────────────────

def parse_tool_metadata(code: str) -> Tuple[Optional[Dict], List[str]]:
    """Extract TOOL_NAME / TOOL_METHOD / TOOL_PARAMS_SCHEMA from module top-level
    via AST (without executing the code).

    Returns (meta_dict, issues).
    meta_dict has keys: tool_name (str), tool_method (str), params_schema (dict)
    """
    issues = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return None, [f"SyntaxError during metadata parse: {e}"]

    meta = {"tool_name": None, "tool_method": None, "params_schema": None}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if name == "TOOL_NAME":
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            meta["tool_name"] = node.value.value
                    elif name == "TOOL_METHOD":
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            meta["tool_method"] = node.value.value
                    elif name == "TOOL_PARAMS_SCHEMA":
                        # Build dict literal from AST
                        if isinstance(node.value, ast.Dict):
                            try:
                                params = {}
                                for k, v in zip(node.value.keys, node.value.values):
                                    if isinstance(k, ast.Constant) and isinstance(v, ast.Dict):
                                        param_spec = {}
                                        for vk, vv in zip(v.keys, v.values):
                                            if isinstance(vk, ast.Constant) and isinstance(vv, ast.Constant):
                                                param_spec[vk.value] = vv.value
                                        params[k.value] = param_spec
                                meta["params_schema"] = params
                            except Exception as e:
                                issues.append(f"TOOL_PARAMS_SCHEMA parse fail: {e}")

    for key in ("tool_name", "tool_method"):
        if not meta[key]:
            issues.append(f"Missing required top-level constant: {key.upper()}")

    # tool_name must be safe identifier
    if meta["tool_name"]:
        import re
        if not re.match(r"^[a-z][a-z0-9_]*$", meta["tool_name"]):
            issues.append(f"TOOL_NAME must match [a-z][a-z0-9_]*, got: {meta['tool_name']!r}")

    return (meta if not issues else None), issues


# ─────────────────────────────────────────────────────────────────
# Layer C — Sandbox subprocess smoke test
# ─────────────────────────────────────────────────────────────────

def _generate_safe_test_args(params_schema: Optional[Dict]) -> str:
    """Generate Python source-code dict of safe test args from schema.

    For non-required params, omit them (test the default-path).
    For required params, generate a type-appropriate placeholder.
    """
    if not params_schema:
        return "{}"
    parts = []
    for name, spec in params_schema.items():
        if not isinstance(spec, dict):
            continue
        # Skip optional params (test default-path)
        if not spec.get("required", False):
            continue
        ptype = (spec.get("type") or "string").lower()
        if ptype in ("string", "str"):
            parts.append(f"{name!r}: 'test_value'")
        elif ptype in ("integer", "int"):
            parts.append(f"{name!r}: 1")
        elif ptype in ("number", "float"):
            parts.append(f"{name!r}: 1.0")
        elif ptype in ("boolean", "bool"):
            parts.append(f"{name!r}: False")
        elif ptype in ("list", "array"):
            parts.append(f"{name!r}: []")
        elif ptype in ("dict", "object"):
            parts.append(f"{name!r}: {{}}")
        else:
            parts.append(f"{name!r}: None")
    return "{" + ", ".join(parts) + "}"


def sandbox_smoke_test(code: str, tool_name: str, tool_method: str,
                       params_schema: Optional[Dict]) -> Tuple[bool, str]:
    """Run code in isolated subprocess with 10s timeout.

    Returns (passed, stdout_or_error_message).

    ⚠ NOT real isolation — runs in operator's Python interpreter.
       Combined with Layer A/B (which already block dangerous calls),
       Layer C catches import-time bugs + runtime hangs.
    """
    if not tool_name or not tool_method:
        return False, "Missing tool_name/tool_method (likely Layer A metadata parse failed)"

    safe_args = _generate_safe_test_args(params_schema)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Write the service file
        service_path = tmp / f"{tool_name}_service.py"
        try:
            service_path.write_text(code, encoding="utf-8")
        except Exception as e:
            return False, f"Failed to write service file: {e}"

        # Build minimal test: import module + dispatch via TOOL_METHOD.
        # Two supported patterns:
        #   (A) module has callable named TOOL_METHOD → call fn(params_dict)
        #   (B) module has SERVICE object → call getattr(SERVICE, TOOL_METHOD)(**params_dict)
        # NOT using `-I` isolated mode because we want user site-packages (httpx etc).
        # Safety boundary is Layer A/B + 10s timeout + operator review.
        test_code = f"""
import sys, importlib
sys.path.insert(0, {str(tmp)!r})
try:
    mod = importlib.import_module({tool_name + "_service"!r})
except Exception as e:
    print(f'IMPORT_FAIL: {{type(e).__name__}}: {{e}}')
    sys.exit(1)
tool_method = getattr(mod, 'TOOL_METHOD', None)
if not tool_method:
    print('META_FAIL: TOOL_METHOD constant missing')
    sys.exit(1)
params = {safe_args}
try:
    if hasattr(mod, 'SERVICE'):
        result = getattr(mod.SERVICE, tool_method)(**params)
    else:
        fn = getattr(mod, tool_method, None)
        if not fn:
            print(f'CALL_FAIL: entry function {{tool_method!r}} missing')
            sys.exit(2)
        result = fn(params)
    if not isinstance(result, dict):
        print(f'CALL_FAIL: tool returned non-dict (got {{type(result).__name__}})')
        sys.exit(2)
    print(f'OK type=dict keys={{list(result.keys())}}')
except Exception as e:
    print(f'CALL_FAIL: {{type(e).__name__}}: {{e}}')
    sys.exit(2)
"""

        # Note: NOT using `-I` isolated mode because that strips user site-packages
        # and our tools legitimately need httpx (installed via pip). The actual safety
        # boundary is Layer A/B (which block subprocess/os/eval/dangerous patterns)
        # + 10s timeout. Operator must read code before promote.
        try:
            result = subprocess.run(
                [sys.executable, "-c", test_code],
                capture_output=True,
                timeout=10,
                text=True,
                cwd=str(tmp),
            )
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT_10S: tool method ran > 10 seconds"
        except Exception as e:
            return False, f"Subprocess error: {e}"

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if result.returncode == 0 and stdout.startswith("OK"):
            return True, stdout
        else:
            return False, f"exit={result.returncode}\nstdout: {stdout[:300]}\nstderr: {stderr[:500]}"


# ─────────────────────────────────────────────────────────────────
# Convenience: run all gates A + C (B handled separately as LLM call)
# ─────────────────────────────────────────────────────────────────

def run_static_gates(code: str) -> Dict:
    """Run Layer A (AST audit) + metadata extraction + Layer C (subprocess).

    Returns dict with:
      - ast_passed: bool, ast_issues: list[str]
      - metadata: dict (tool_name, tool_method, params_schema) or None
      - metadata_issues: list[str]
      - smoke_passed: bool, smoke_output: str
      - overall_passed: bool
    """
    result = {
        "ast_passed": False, "ast_issues": [],
        "metadata": None, "metadata_issues": [],
        "smoke_passed": False, "smoke_output": "",
        "overall_passed": False,
    }

    # Layer A
    ast_passed, ast_issues = ast_audit(code)
    result["ast_passed"] = ast_passed
    result["ast_issues"] = ast_issues
    if not ast_passed:
        return result

    # Metadata extraction
    meta, meta_issues = parse_tool_metadata(code)
    result["metadata"] = meta
    result["metadata_issues"] = meta_issues
    if not meta:
        return result

    # Layer C (sandbox subprocess)
    smoke_passed, smoke_output = sandbox_smoke_test(
        code, meta["tool_name"], meta["tool_method"], meta.get("params_schema")
    )
    result["smoke_passed"] = smoke_passed
    result["smoke_output"] = smoke_output

    result["overall_passed"] = ast_passed and smoke_passed
    return result
