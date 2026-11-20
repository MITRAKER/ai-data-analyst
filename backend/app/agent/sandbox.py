"""Run Python code written by the AI, as safely as we reasonably can.

Running code an AI model wrote is the riskiest thing this app does, so we use
several independent layers ("defense in depth"). Each layer still protects us
if another one has a gap.

1. Static check, before anything runs: we parse the code into a syntax tree
   (AST) and reject imports outside an allow-list, private names imported from
   allowed modules, dangerous built-ins such as `open`, `exec` and
   `__import__`, private attributes, file and network methods such as `to_csv`
   and `read_pickle`, doors to the interpreter's internals such as frames, and
   strings that contain "__". Python is too flexible for a list like this to
   be complete, so the next layers do not trust it.
2. A separate process: a fresh `python -I -B` process in an empty temporary
   folder, with no input and a minimal environment (no API keys). A crash or
   an endless loop can't take down the web server.
3. Operating-system limits inside that process, set just before the AI's code
   starts: CPU time, memory, a file size of zero (nothing can be written to a
   file), no new file descriptors at all (no file can be opened and no network
   connection made, even if the code closes one it already has), and no new
   processes or threads.
4. An audit hook in that process (PEP 578): Python calls it before every
   sensitive action, and it refuses opening files, starting processes,
   sending signals, sockets, ctypes, changing the limits, and importing
   modules that could get around them. The process never loads the modules
   that start subinterpreters, which would run code without the hook. And
   because Python removes the hook when it shuts down, the process ends at
   once when the code is done, without that shutdown.
5. Limits in this process: we read at most `output_bytes` of output, and a
   watchdog kills the child process when the wall-clock time limit passes.

This is a good sandbox for a portfolio project. A multi-user product should
add OS-level isolation as well: a container with no network (gVisor,
Firecracker) or a hosted code-execution service.
"""

from __future__ import annotations

import ast
import os
import re
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, override

import pandas as pd

from app.invariants import InvariantError, require
from app.watchdog import Watchdog

ALLOWED_IMPORTS: Final = frozenset(
    {
        "collections",
        "datetime",
        "decimal",
        "fractions",
        "functools",
        "itertools",
        "json",
        "math",
        "numpy",
        "pandas",
        "random",
        "re",
        "statistics",
    }
)
BLOCKED_NAMES: Final = frozenset(
    {
        "breakpoint",
        "compile",
        "copyright",
        "credits",
        "delattr",
        "eval",
        "exec",
        "exit",
        "getattr",
        "globals",
        "hasattr",
        "help",
        "input",
        "license",
        "locals",
        "memoryview",
        "open",
        "quit",
        "setattr",
        "vars",
    }
)
_FILE_READERS: Final = (
    "DataSource",
    "ExcelFile",
    "HDFStore",
    "fromfile",
    "fromregex",
    "genfromtxt",
    "load",
    "loadtxt",
    "memmap",
    "read_clipboard",
    "read_csv",
    "read_excel",
    "read_feather",
    "read_fwf",
    "read_hdf",
    "read_html",
    "read_json",
    "read_orc",
    "read_parquet",
    "read_pickle",
    "read_sas",
    "read_spss",
    "read_sql",
    "read_sql_query",
    "read_sql_table",
    "read_stata",
    "read_table",
    "read_xml",
)
_FILE_WRITERS: Final = (
    "ExcelWriter",
    "dump",
    "save",
    "savetxt",
    "savez",
    "savez_compressed",
    "to_clipboard",
    "to_csv",
    "to_excel",
    "to_feather",
    "to_hdf",
    "to_html",
    "to_json",
    "to_latex",
    "to_markdown",
    "to_orc",
    "to_parquet",
    "to_pickle",
    "to_sql",
    "to_stata",
    "to_xml",
    "tofile",
)
# Ways to run code from a string, and doors from pandas or numpy into other modules.
_ESCAPES: Final = (
    "compat",
    "ctypeslib",
    "eval",
    "f2py",
    "io",
    "lib",
    "os",
    "plotting",
    "popen",
    "query",
    "sys",
    "system",
    "testing",
    "util",
)
# Doors to the interpreter itself: frames, the built-ins behind them, and the
# modules that can run or load any code. `re.enum.bltns.exec`, for example,
# is the built-in exec() reached through modules that `re` imports.
_INTERNALS: Final = (
    "ag_frame",
    "bltns",
    "breakpoint",
    "builtins",
    "cr_frame",
    "ctypes",
    "delattr",
    "exec",
    "f_back",
    "f_builtins",
    "f_code",
    "f_globals",
    "f_locals",
    "getattr",
    "gi_code",
    "gi_frame",
    "globals",
    "import_module",
    "importlib",
    "inspect",
    "locals",
    "marshal",
    "pickle",
    "posix",
    "setattr",
    "socket",
    "subprocess",
    "tb_frame",
    "tb_next",
    "vars",
)
BLOCKED_ATTRS: Final = frozenset(_FILE_READERS + _FILE_WRITERS + _ESCAPES + _INTERNALS)

_SITE_PACKAGES: Final = re.compile(r'File "[^"]*?site-packages/')

MAX_CODE_CHARS: Final = 20_000
MAX_OUTPUT_CHARS: Final = 8_000
ERROR_TAIL_LINES: Final = 8

# The child process runs this script. It reads the AI's code and the data,
# then locks itself down, then runs the code, then ends at once. Everything
# the code might need (allowed modules, and parts of pandas that load lazily)
# is imported before the lock-down, because afterwards no file can be opened.
_RUNNER: Final = """\
import sys

# Code in a subinterpreter would run without this process's audit hook, and
# pandas does not need one, so the modules that create them are never loaded.
for name in ("_interpchannels", "_interpqueues", "_interpreters"):
    sys.modules[name] = None

import collections, datetime, decimal, fractions, functools, itertools, json, math
import random, re, statistics
import linecache, os, resource, signal

import numpy as np
import numpy.fft, numpy.linalg, numpy.polynomial, numpy.random
import pandas as pd
import pandas.core.methods.to_dict, pandas.core.reshape.reshape, pandas.io.formats.string

CPU_SECONDS, MEMORY_BYTES = int(sys.argv[1]), int(sys.argv[2])


def limit(kind, soft, hard):
    current = resource.getrlimit(kind)[1]
    if current != resource.RLIM_INFINITY:
        soft, hard = min(soft, current), min(hard, current)
    resource.setrlimit(kind, (soft, hard))


def audit(event, args, leave=os._exit, text=str):
    # Python calls this before each sensitive action, and raising stops the
    # action. It uses only constants and its own default arguments, which no
    # code can replace (see below), so code that changes this script's
    # variables or the built-ins cannot switch it off.
    if event == "cpython.PyInterpreterState_Clear":
        # Python is shutting down and removes this hook next. Code could still
        # run after that (in __del__ methods), so the process ends here.
        leave(1)
    if event == "import":  # only for modules that are not loaded yet
        blocked = False
        for part in text.split(args[0], "."):  # "a.b" is blocked if a or b is
            blocked = blocked or part.startswith(("_test", "_xx")) or part in {
                "_ctypes", "_interpchannels", "_interpqueues", "_interpreters",
                "_multiprocessing", "_posixshmem", "_posixsubprocess", "_socket", "_sqlite3",
                "_ssl", "concurrent", "ctypes", "faulthandler", "fcntl", "mmap",
                "multiprocessing", "pty", "resource", "socket", "sqlite3", "ssl", "subprocess",
                "syslog", "termios",
            }
    elif event in ("object.__setattr__", "object.__delattr__"):
        # Replacing a function's code or default arguments, this one's too.
        blocked = args[1] in ("__code__", "__defaults__", "__kwdefaults__")
    else:
        blocked = event.startswith((
            "code.__new__", "ctypes.", "gc.", "glob.", "marshal.", "open", "os.", "pickle.",
            "resource.", "shutil.", "signal.", "socket.", "sqlite3.", "subprocess.",
            "syslog.", "tempfile.",
        ))
    if blocked:
        raise PermissionError(f"Not allowed in the sandbox: {event}")


def run(code, namespace):
    # Runs the code as `python user_code.py` would, and returns the exit status.
    try:
        exec(code, namespace)
    except SystemExit as stop:  # sys.exit() follows Python's rules for the status
        if stop.code is None or isinstance(stop.code, int):
            return stop.code or 0
        sys.stdout.flush()
        print(stop.code, file=sys.stderr)
        return 1
    except BaseException:
        sys.stdout.flush()  # what the code printed comes before the error
        sys.excepthook(*sys.exc_info())
        return 1
    return 0


with open("user_code.py", encoding="utf-8") as source_file:
    source = source_file.read()
df = pd.read_pickle("data.pkl")
repr(df.head())  # pandas imports a few modules the first time it prints
linecache.cache["user_code.py"] = (len(source), None, source.splitlines(True), "user_code.py")
code = compile(source, "user_code.py", "exec")

signal.signal(signal.SIGXFSZ, signal.SIG_IGN)  # a file write fails with an error instead
limit(resource.RLIMIT_CPU, CPU_SECONDS, CPU_SECONDS + 1)
if sys.platform != "darwin":  # macOS does not support memory limits this way
    limit(resource.RLIMIT_AS, MEMORY_BYTES, MEMORY_BYTES)
limit(resource.RLIMIT_FSIZE, 0, 0)  # nothing can be written to a file
limit(resource.RLIMIT_NOFILE, 0, 0)  # no new file descriptor, even after closing one
limit(resource.RLIMIT_NPROC, 0, 0)  # no new process or thread (root is exempt)
sys.addaudithook(audit)
status = run(code, {"__name__": "__main__", "df": df, "pd": pd, "np": np})
# End the process now, without Python's normal shutdown: during that shutdown
# Python removes the audit hook, and code could still run after that.
sys.stdout.flush()
sys.stderr.flush()
os._exit(status)
"""


class SandboxError(ValueError):
    """Code rejected before it ran."""


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """How much time, CPU, memory and output the AI's code may use."""

    timeout_s: float = 15.0
    cpu_s: int = 10
    memory_mb: int = 1024
    output_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        require(self.timeout_s > 0, f"timeout_s must be positive, got {self.timeout_s}")
        require(self.cpu_s > 0, f"cpu_s must be positive, got {self.cpu_s}")
        require(self.memory_mb > 0, f"memory_mb must be positive, got {self.memory_mb}")
        require(self.output_bytes > 0, f"output_bytes must be positive, got {self.output_bytes}")


DEFAULT_LIMITS: Final = SandboxLimits()


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """What came back from a run: the printed output, and an error if it failed."""

    ok: bool
    stdout: str
    error: str | None = None

    def to_display(self) -> dict[str, object]:
        """The result as a JSON-ready dict for the UI."""
        return {"ok": self.ok, "stdout": self.stdout, "error": self.error}


@dataclass(frozen=True, slots=True)
class _ChildRun:
    """The raw outcome of one child process."""

    returncode: int
    output: str
    timed_out: bool
    overflowed: bool


class _ProcessWatchdog(Watchdog):
    """Kills the child process when the wall-clock time limit passes."""

    def __init__(self, proc: subprocess.Popen[bytes], timeout_s: float) -> None:
        super().__init__(name="sandbox-watchdog", timeout_s=timeout_s)
        self._proc = proc

    @override
    def on_timeout(self) -> None:
        self._proc.kill()


def check_code(code: str) -> None:
    """Layer 1: reject unsafe code by inspecting its syntax tree.

    Raises:
        SandboxError: If the code is too long, does not parse, or uses
            anything that is not allowed.
    """
    if len(code) > MAX_CODE_CHARS:
        raise SandboxError(f"The code is longer than {MAX_CODE_CHARS:,} characters.")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SandboxError(f"SyntaxError: {exc.msg} (line {exc.lineno})") from exc
    for node in ast.walk(tree):
        problem = _problem(node)
        if problem is not None:
            raise SandboxError(problem)


def _problem(node: ast.AST) -> str | None:
    """Describe why `node` is not allowed, or return None if it is fine."""
    match node:
        case ast.Import(names=names):
            return _import_problem([alias.name for alias in names])
        case ast.ImportFrom(module=module, names=names, level=level):
            return _from_import_problem(module, names, level)
        case ast.Name(id=name) if name in BLOCKED_NAMES or name.startswith("__"):
            return f"'{name}' is not allowed in the sandbox."
        case ast.Attribute(attr=attr) if attr.startswith("_") or attr in BLOCKED_ATTRS:
            return f"Attribute '{attr}' is not allowed in the sandbox (no files, no private parts)."
        case ast.Constant(value=str() as text) if "__" in text:
            return "Strings that contain '__' are not allowed in the sandbox."
        case _:
            return None


def _import_problem(modules: list[str]) -> str | None:
    """Describe the first import outside the allow-list, if any.

    The parts after the first dot must pass the attribute rules too, because
    `import numpy.lib as lib` reaches the same module as `numpy.lib`.
    """
    for name in modules:
        root, *parts = name.split(".")
        if root not in ALLOWED_IMPORTS:
            allowed = ", ".join(sorted(ALLOWED_IMPORTS))
            return f"Import of '{name}' is not allowed. Allowed: {allowed}."
        if any(part.startswith("_") or part in BLOCKED_ATTRS for part in parts):
            return f"Import of '{name}' is not allowed in the sandbox."
    return None


def _from_import_problem(module: str | None, names: list[ast.alias], level: int) -> str | None:
    """Describe why a `from ... import ...` statement is not allowed, if it isn't.

    `from random import _os` would hand the code the `os` module that `random`
    uses inside, and `from pandas import read_csv` a file reader, so imported
    names follow the same rules as attributes.
    """
    require(level >= 0, f"an import level is never negative, got {level}")
    if level:
        return "Relative imports are not allowed."
    problem = _import_problem([module or ""])
    if problem is not None:
        return problem
    for alias in names:
        name = alias.name
        if name == "*":
            return "'from ... import *' is not allowed in the sandbox: name what you need."
        if name.startswith("_") or name in BLOCKED_NAMES or name in BLOCKED_ATTRS:
            return f"Importing '{name}' is not allowed in the sandbox (no files, no private parts)."
    return None


def run_python(
    code: str, df: pd.DataFrame, limits: SandboxLimits = DEFAULT_LIMITS
) -> SandboxResult:
    """Run `code` with the DataFrame available as `df`. Only printed output comes back.

    Raises:
        SandboxError: If the code fails the static check, or the sandbox
            cannot run on this operating system.
    """
    if sys.platform == "win32":
        raise SandboxError("The Python sandbox needs Linux or macOS. On Windows use WSL or Docker.")
    check_code(code)
    return _run_unchecked(code, df, limits)


def _run_unchecked(code: str, df: pd.DataFrame, limits: SandboxLimits) -> SandboxResult:
    """Layers 2 to 5: run the code in a locked-down child process.

    The tests call this directly with code that the static check would reject,
    to prove that the layers behind it hold on their own.
    """
    with tempfile.TemporaryDirectory(prefix="sandbox_") as tmp:
        folder = Path(tmp)
        df.to_pickle(folder / "data.pkl")
        _ = (folder / "user_code.py").write_text(code, encoding="utf-8")
        _ = (folder / "runner.py").write_text(_RUNNER, encoding="utf-8")
        memory_bytes = limits.memory_mb * 1024 * 1024
        argv = [sys.executable, "-I", "-B", "runner.py", str(limits.cpu_s), str(memory_bytes)]
        run = _run_child(argv, folder, limits)
    return _interpret(run, limits)


def _child_env() -> dict[str, str]:
    """A minimal environment: no API keys or other secrets reach the child."""
    return {
        "PATH": os.defpath,
        "PYTHONIOENCODING": "utf-8",
        "LC_ALL": "C.UTF-8",
        # One thread keeps numpy's memory use small and predictable.
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }


def _run_child(argv: list[str], folder: Path, limits: SandboxLimits) -> _ChildRun:
    """Start the child, read its output (bounded) and wait for it (bounded)."""
    with subprocess.Popen(  # noqa: S603 -- argv is this Python, our own runner and two numbers
        argv,
        cwd=folder,
        env=_child_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ) as proc:
        watchdog = _ProcessWatchdog(proc, limits.timeout_s)
        watchdog.start()
        try:
            output = _read_output(proc, limits.output_bytes + 1)
            overflowed = len(output) > limits.output_bytes
            if overflowed:
                proc.kill()
            returncode = proc.wait()
        finally:
            timed_out = watchdog.finish()
    text = output[: limits.output_bytes].decode("utf-8", errors="replace")
    return _ChildRun(returncode, text, timed_out, overflowed)


def _read_output(proc: subprocess.Popen[bytes], max_bytes: int) -> bytes:
    """Read up to `max_bytes` of the child's output; returns early when it exits."""
    stream = proc.stdout
    if stream is None:
        raise InvariantError("the child's stdout must be a pipe")
    return stream.read(max_bytes)


def _interpret(run: _ChildRun, limits: SandboxLimits) -> SandboxResult:
    """Turn the raw outcome of a run into a result the model can act on."""
    if run.timed_out:
        return SandboxResult(ok=False, stdout="", error=f"Timed out after {limits.timeout_s:g}s.")
    if run.overflowed:
        return SandboxResult(
            ok=False, stdout=_truncate(run.output), error="Too much output: print less."
        )
    if run.returncode < 0:
        error = _signal_message(run.returncode, limits)
        return SandboxResult(ok=False, stdout=_truncate(run.output), error=error)
    if run.returncode != 0:
        printed, error = _split_traceback(run.output)
        return SandboxResult(ok=False, stdout=_truncate(printed), error=_explain(error))
    stdout = _truncate(run.output)
    if not stdout.strip():
        stdout = "(no output: use print() to show results)"
    return SandboxResult(ok=True, stdout=stdout)


def _split_traceback(output: str) -> tuple[str, str]:
    """Split merged output into (what the code printed, the end of the traceback)."""
    printed, marker, traceback = output.rpartition("Traceback (most recent call last):")
    if not marker:
        lines = output.strip().splitlines()
        return "", "\n".join(lines[-ERROR_TAIL_LINES:]) or "The code failed."
    # Drop the sandbox's own frames and shorten library paths; keep the AI's frames.
    lines = [
        _SITE_PACKAGES.sub('File "', line)
        for line in traceback.strip().splitlines()
        if "runner.py" not in line and "<frozen " not in line
    ]
    return printed.rstrip(), "\n".join(lines[-ERROR_TAIL_LINES:])


def _signal_message(returncode: int, limits: SandboxLimits) -> str:
    """Explain why the child process was stopped by a signal."""
    require(returncode < 0, f"a signal exit code is negative, got {returncode}")
    if returncode == -signal.SIGXCPU:
        return f"Stopped: used more than {limits.cpu_s}s of CPU time."
    if returncode == -signal.SIGKILL:
        return "Stopped: the process used too much memory or CPU time."
    return f"Stopped by signal {-returncode}."


def _explain(error: str) -> str:
    """Add a hint to errors caused by the sandbox's own limits."""
    if any(
        sign in error
        for sign in ("Not allowed in the sandbox", "Too many open files", "File too large")
    ):
        return f"{error}\nThe sandbox has no file or network access. Work with `df` in memory."
    if "MemoryError" in error:
        return f"{error}\nThe sandbox ran out of memory. Use fewer rows or aggregate in SQL first."
    return error


def _truncate(text: str) -> str:
    """Cut long output, keeping the beginning and saying how much was cut."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [output truncated, {len(text):,} characters total]"
