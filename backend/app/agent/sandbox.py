"""Run Python code written by the AI, as safely as we reasonably can.

Running code an LLM wrote is the riskiest thing this app does, so we again use
several independent layers ("defense in depth"):

1. Static check (before running): we parse the code into a syntax tree (AST) and
   reject imports outside an allow-list and dangerous built-ins like `open`,
   `exec` or `__import__`. Parsing is more reliable than searching the text.
2. Separate process: the code runs in a fresh `python -I` subprocess, so a crash
   or infinite loop can't take down the web server.
3. Resource limits: a wall-clock timeout, plus CPU-time and memory caps
   (Linux/macOS) set inside the child process.
4. Empty working directory and a minimal environment: no API keys are passed in.

This is a good sandbox for a portfolio project. For a real multi-user product,
you'd add OS-level isolation as well: a container with no network (Docker,
gVisor, Firecracker), or a hosted code-execution service.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ALLOWED_IMPORTS = {
    "pandas", "numpy", "math", "statistics", "datetime", "collections",
    "itertools", "functools", "re", "json", "decimal", "fractions", "random",
    "scipy", "sklearn",
}
BLOCKED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview",
}
BLOCKED_ATTRS = {"read_pickle", "to_pickle", "read_csv", "to_csv", "read_parquet",
                 "to_parquet", "read_sql", "to_sql", "system", "popen"}

MAX_OUTPUT_CHARS = 8_000


class SandboxError(ValueError):
    """Code rejected before it ran."""


@dataclass
class SandboxResult:
    ok: bool
    stdout: str
    error: str | None = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "stdout": self.stdout, "error": self.error}


def check_code(code: str) -> None:
    """Layer 1: reject obviously unsafe code by inspecting its syntax tree."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SandboxError(f"SyntaxError: {exc.msg} (line {exc.lineno})") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_module(alias.name)
        elif isinstance(node, ast.ImportFrom):
            _check_module(node.module or "")
        elif isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            raise SandboxError(f"'{node.id}' is not allowed in the sandbox.")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in BLOCKED_ATTRS:
                raise SandboxError(f"Attribute '{node.attr}' is not allowed in the sandbox.")


def _check_module(name: str) -> None:
    root = name.split(".")[0]
    if root not in ALLOWED_IMPORTS:
        raise SandboxError(
            f"Import of '{name}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_IMPORTS))}."
        )


# This runs inside the child process before the AI's code. It applies resource
# limits, then loads the data we prepared into a DataFrame called `df`.
_PRELUDE = """
import sys
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, ({cpu}, {cpu}))
    resource.setrlimit(resource.RLIMIT_AS, ({mem}, {mem}))
except Exception:
    pass  # resource limits aren't available on Windows
import pandas as pd
import numpy as np
df = pd.read_pickle({data_path!r})
del sys
"""


def run_python(
    code: str,
    df: pd.DataFrame,
    timeout_s: float = 15.0,
    cpu_s: int = 10,
    memory_mb: int = 1024,
) -> SandboxResult:
    """Run `code` with the DataFrame available as `df`. Only printed output comes back."""
    check_code(code)

    with tempfile.TemporaryDirectory(prefix="sandbox_") as tmp:
        data_path = str(Path(tmp) / "data.pkl")
        df.to_pickle(data_path)
        prelude = _PRELUDE.format(cpu=cpu_s, mem=memory_mb * 1024 * 1024, data_path=data_path)
        script = Path(tmp) / "main.py"
        script.write_text(prelude + "\n# ---- AI-written code ----\n" + code)

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            # One thread keeps numpy's memory use small and predictable.
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
        }
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(ok=False, stdout="", error=f"Timed out after {timeout_s:.0f}s.")

    stdout = _truncate(proc.stdout)
    if proc.returncode != 0:
        # Keep only the end of the traceback: that's the useful part for the agent.
        err = _strip_paths(proc.stderr.strip().splitlines()[-6:], data_path)
        return SandboxResult(ok=False, stdout=stdout, error="\n".join(err) or f"Exit code {proc.returncode}")
    if not stdout.strip():
        stdout = "(no output: use print() to show results)"
    return SandboxResult(ok=True, stdout=stdout)


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [output truncated, {len(text):,} chars total]"


def _strip_paths(lines: list[str], data_path: str) -> list[str]:
    tmp_dir = str(Path(data_path).parent)
    return [line.replace(tmp_dir + os.sep, "") for line in lines]


