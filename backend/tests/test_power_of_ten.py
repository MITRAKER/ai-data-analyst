"""Tests for the NASA/JPL Power of Ten checker in tools/power_of_ten.py.

Each test writes a tiny package to a temporary folder, runs the checker on it
and compares the problems it reports, as "rule:line" strings.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.power_of_ten import (
    ALL_FILES,
    EXIT_BAD_INPUT,
    EXIT_OK,
    EXIT_PROBLEMS,
    MAX_FUNCTION_LINES,
    CheckerError,
    Violation,
    check,
    is_unexplained,
    load_project,
    lookup,
    main,
    module_name,
    summary,
)

BACKEND = Path(__file__).resolve().parents[1]


def write_package(tmp_path: Path, **sources: str) -> Path:
    """Write `pkg/__init__.py` and one `pkg/<name>.py` per keyword argument."""
    package = tmp_path / "pkg"
    package.mkdir()
    _ = (package / "__init__.py").write_text("", encoding="utf-8")
    for name, source in sources.items():
        text = textwrap.dedent(source).lstrip("\n")
        _ = (package / f"{name}.py").write_text(text, encoding="utf-8")
    return package


def violations(tmp_path: Path, **sources: str) -> list[Violation]:
    """Every problem in a fresh package, except the program-wide density check."""
    package = write_package(tmp_path, **sources)
    return [v for v in check(load_project([str(package)])) if v.path != ALL_FILES]


def rules(tmp_path: Path, source: str) -> list[str]:
    """The problems in one module, as 'R<rule>:<line>'."""
    return [f"{v.rule}:{v.line}" for v in violations(tmp_path, mod=source)]


# ---------- rule 1: no recursion ----------


def test_direct_recursion(tmp_path: Path) -> None:
    found = violations(
        tmp_path,
        mod="""
        def countdown(n: int) -> int:
            return countdown(n - 1) if n else 0
        """,
    )
    assert [(v.rule, v.line) for v in found] == [("R1", 1)]
    assert "`countdown` calls itself directly" in found[0].message


def test_mutual_recursion_names_the_partner(tmp_path: Path) -> None:
    found = violations(
        tmp_path,
        mod="""
        def ping(n: int) -> int:
            return pong(n - 1)


        def pong(n: int) -> int:
            return ping(n - 1) if n else 0
        """,
    )
    assert [(v.rule, v.line) for v in found] == [("R1", 1), ("R1", 5)]
    assert "through `pkg.mod.pong`" in found[0].message


def test_recursion_across_modules(tmp_path: Path) -> None:
    found = violations(
        tmp_path,
        a="""
        from pkg import b


        def ping() -> None:
            b.pong()
        """,
        b="""
        from pkg.a import ping


        def pong() -> None:
            ping()
        """,
    )
    assert [(Path(v.path).name, v.rule) for v in found] == [("a.py", "R1"), ("b.py", "R1")]


def test_recursion_through_relative_imports(tmp_path: Path) -> None:
    found = violations(
        tmp_path,
        a="""
        from . import b


        def ping() -> None:
            b.pong()
        """,
        b="""
        from .a import ping


        def pong() -> None:
            ping()
        """,
    )
    assert [v.rule for v in found] == ["R1", "R1"]


def test_recursion_through_methods(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        class Walker:
            def walk(self, n: int) -> int:
                return self.step(n)

            def step(self, n: int) -> int:
                return self.walk(n - 1)
        """,
    ) == ["R1:2", "R1:5"]


def test_recursion_through_an_object_held_in_a_field(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        from __future__ import annotations


        class Agent:
            def __init__(self, store: Store | None) -> None:
                self.store = store

            def ask(self) -> int:
                return self.store.load(self) if self.store else 0


        class Store:
            def load(self, agent: Agent) -> int:
                return agent.ask()
        """,
    ) == ["R1:8", "R1:13"]


def test_recursion_through_an_override(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        class Base:
            def run(self) -> None:
                self.step()

            def step(self) -> None:
                print("base")


        class Child(Base):
            def step(self) -> None:
                self.run()
        """,
    ) == ["R1:2", "R1:10"]


def test_recursion_through_a_constructor(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        class Node:
            def __init__(self, depth: int) -> None:
                self.child = Node(depth - 1) if depth else None
        """,
    ) == ["R1:2"]


def test_recursion_through_super_and_a_new_object(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        class A:
            def go(self) -> int:
                return helper()


        class B(A):
            def go(self) -> int:
                return super().go()


        def helper() -> int:
            return B().go()
        """,
    ) == ["R1:2", "R1:7", "R1:11"]


def test_recursion_through_local_variables_and_with(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        from dataclasses import dataclass


        @dataclass
        class Holder:
            box: "Box"

            def go(self) -> None:
                helper = Helper()
                helper.run(self)


        class Helper:
            def run(self, holder: Holder) -> None:
                with Box() as box:
                    box.open(holder)


        class Box:
            def __enter__(self) -> None:
                print("enter")

            def open(self, holder: Holder) -> None:
                holder.go()
        """,
    ) == ["R1:8", "R1:14", "R1:23"]


def test_recursion_through_a_protocol(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        from typing import Protocol


        class Runner(Protocol):
            def run(self) -> None: ...


        class Engine:
            def __init__(self, runner: Runner) -> None:
                self.runner = runner

            def run(self) -> None:
                self.runner.run()
        """,
    ) == ["R1:12"]


def test_calls_without_cycles_are_fine(tmp_path: Path) -> None:
    assert (
        rules(
            tmp_path,
            """
            class Store:
                def run(self) -> int:
                    return 1


            class Agent:
                def __init__(self, store: Store) -> None:
                    self._store = store

                def run(self) -> int:
                    return self._store.run() + helper()


            def helper() -> int:
                return len([1, 2])
            """,
        )
        == []
    )


# ---------- rule 2: loops with a fixed bound ----------


def test_while_loops(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        def wait(ready: bool) -> None:
            while not ready:
                ready = True
        """,
    ) == ["R2:2"]


def test_iterators_without_an_end(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        import itertools
        from itertools import count


        def numbers() -> None:
            print(itertools.count(), count(), itertools.cycle([1]), itertools.repeat(1))
            print(iter(input, ""))
            print(itertools.repeat(1, 3), itertools.repeat(1, times=3), iter([1]))
        """,
    ) == ["R2:6", "R2:6", "R2:6", "R2:6", "R2:7"]


# ---------- rule 3: bounded memory ----------


def test_reads_without_a_limit(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        from pathlib import Path

        import pandas as pd


        def load(path: Path) -> None:
            with path.open() as handle:
                print(handle.read(), handle.read(100), handle.readline(), handle.readlines())
            print(path.read_text(), path.read_bytes())
            print(pd.read_csv(path), pd.read_csv(path, nrows=10))
        """,
    ) == ["R3:8", "R3:8", "R3:8", "R3:9", "R3:9", "R3:10"]


# ---------- rule 4: short functions ----------


def long_function(statements: int) -> str:
    body = "\n".join(f"    x{number} = {number}" for number in range(statements))
    docstring = '    """A docstring.\n\n    It does not count.\n    """\n'
    return f"def long() -> None:\n{docstring}    # Comments do not count.\n\n{body}\n"


def test_function_length_limit(tmp_path: Path) -> None:
    assert rules(tmp_path, long_function(MAX_FUNCTION_LINES - 1)) == []


def test_function_too_long(tmp_path: Path) -> None:
    found = violations(tmp_path, mod=long_function(MAX_FUNCTION_LINES))
    assert [(v.rule, v.line) for v in found] == [("R4", 1)]
    assert f"has {MAX_FUNCTION_LINES + 1} lines of code" in found[0].message


# ---------- rule 5: checks ----------


def test_asserts_and_checks_with_side_effects(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        from app.invariants import require


        def checked(x: int) -> None:
            assert x > 0
            require(x > 0, "x must be positive")
            require((y := x) > 0, f"{y}")
        """,
    ) == ["R5:5", "R5:7"]


def test_assertion_density(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        mod="""
        from typing import Protocol


        class Shape(Protocol):
            def area(self) -> float: ...


        def one() -> int:
            return 1


        def two() -> int:
            return 2
        """,
    )
    found = check(load_project([str(package)]))
    assert [(v.path, v.rule) for v in found] == [(ALL_FILES, "R5")]
    assert "0 checks in 2 functions" in found[0].message  # the protocol stub does not count


def test_enough_checks(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        mod="""
        from typing import assert_never


        def one(x: int) -> int:
            if x < 0:
                raise ValueError(x)
            return x


        def two(x: int | str) -> int:
            if isinstance(x, int):
                return x
            if isinstance(x, str):
                return len(x)
            assert_never(x)
        """,
    )
    assert check(load_project([str(package)])) == []


# ---------- rule 6: smallest scope ----------


def test_shared_mutable_state(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        import collections
        from typing import Final

        CACHE: Final = {}
        NAMES = ["a"]
        SEEN = set()
        COUNTS = collections.Counter()
        SQUARES = [n * n for n in range(3)]
        ALLOWED: Final = frozenset({"a"})
        PAIR = (1, 2)
        TOTAL = 0
        TOTAL += 1


        class Config:
            options: list[str] = []
            name = "x"


        def counter() -> int:
            global TOTAL
            local = []
            return len(local)


        def outer() -> None:
            count = 0

            def inner() -> None:
                nonlocal count
                count += 1

            inner()
        """,
    ) == ["R6:4", "R6:5", "R6:6", "R6:7", "R6:8", "R6:12", "R6:16", "R6:21", "R6:30"]


# ---------- rule 7: no ignored errors ----------


def test_ignored_errors(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        import contextlib


        def quiet(text: str) -> int:
            try:
                return int(text)
            except ValueError:
                pass
            try:
                return int(text, 16)
            except ValueError:
                ...
            with contextlib.suppress(ValueError):
                return int(text, 8)
            try:
                return int(text, 2)
            except ValueError as error:
                raise RuntimeError(text) from error
        """,
    ) == ["R7:7", "R7:11", "R7:13"]


# ---------- rule 8: no metaprogramming ----------


def test_metaprogramming(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        import importlib
        import pickle as p
        from ctypes import cdll
        from importlib import import_module


        class Meta(type):
            pass


        class Thing(metaclass=Meta):
            pass


        def dynamic(obj: object, name: str) -> object:
            print(eval("1"), getattr(obj, name), obj.__class__)
            print(type("X", (), {}), type(obj))
            return __import__("os")
        """,
    ) == ["R8:1", "R8:2", "R8:3", "R8:4", "R8:11", "R8:16", "R8:16", "R8:16", "R8:17", "R8:18"]


def test_super_init_is_allowed(tmp_path: Path) -> None:
    source = """
        class Base:
            def __init__(self) -> None:
                self.ready = True


        class Child(Base):
            def __init__(self) -> None:
                super().__init__()
                self.extra = True
        """
    assert rules(tmp_path, source) == []


# ---------- rule 9: no function pointers ----------


def test_functions_used_as_values(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        from collections.abc import Callable


        def double(n: int) -> int:
            return n * 2


        def apply(f: Callable[[int], int]) -> int:
            return f(1)


        def use() -> None:
            print(apply(double), double(2))
            handler = double
            print(handler, sorted([2, 1], key=lambda n: -n))
            callback: Callable[[], None] | None = None
            print(callback)
        """,
    ) == ["R9:8", "R9:13", "R9:14", "R9:15", "R9:16"]


def test_methods_used_as_values(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        import functools


        def decorate(item: object) -> object:
            return item


        class Greeter:
            @property
            def name(self) -> str:
                return "x"

            @functools.cached_property
            def title(self) -> str:
                return "y"

            @decorate
            def hello(self) -> str:
                return self.name + self.title

            def wave(self) -> str:
                method = self.hello
                return method() + str(Greeter.hello) + str(Greeter)
        """,
    ) == ["R9:22", "R9:23"]


# ---------- rule 10: explained suppressions ----------


@pytest.mark.parametrize(
    ("comment", "unexplained"),
    [
        ("# noqa", True),
        ("# noqa: S603", True),
        ("# noqa:S603", True),
        ("# noqa: S603 --", True),
        ("# noqa: S603 -- fixed command, no user input", False),
        ("# NOQA: E501, S603 -- long but clear", False),
        ("# noqa: S603  # the command is fixed", False),
        ("# type: ignore", True),
        ("# type: ignore[assignment]", True),
        ("# type: ignore[assignment]  # the stub is wrong", False),
        ("# type: ignore[assignment] -- the stub is wrong", False),
        ("# pyright: ignore[reportAssignmentType]", True),
        ("# pyright: ignore[reportAssignmentType]  # the stub is wrong", False),
        ("# type: ignore[assignment]  # noqa: E501", True),
        ("# noqa: S603 -- why  # type: ignore[x]  # because", False),
        ("# a comment that mentions noqa and type: ignore", False),
        ("# plain comment", False),
    ],
)
def test_suppression_reasons(comment: str, unexplained: bool) -> None:
    assert is_unexplained(comment) is unexplained


def test_suppressions_in_code(tmp_path: Path) -> None:
    assert rules(
        tmp_path,
        """
        def run() -> None:
            x: int = "a"  # type: ignore[assignment]
            y: int = "b"  # type: ignore[assignment]  # testing a bad value on purpose
            text = "# noqa: E501 is only a comment when it is outside a string"
            print(x, y, text)
        """,
    ) == ["R10:2"]


# ---------- loading files ----------


def test_module_names(tmp_path: Path) -> None:
    package = write_package(tmp_path, mod="")
    sub = package / "sub"
    sub.mkdir()
    _ = (sub / "__init__.py").write_text("", encoding="utf-8")
    _ = (sub / "deep.py").write_text("", encoding="utf-8")
    _ = (tmp_path / "script.py").write_text("", encoding="utf-8")
    assert module_name(package / "mod.py") == ("pkg.mod", "pkg")
    assert module_name(package / "__init__.py") == ("pkg", "pkg")
    assert module_name(sub / "deep.py") == ("pkg.sub.deep", "pkg.sub")
    assert module_name(sub / "__init__.py") == ("pkg.sub", "pkg.sub")
    assert module_name(tmp_path / "script.py") == ("script", "")


def test_parent_relative_imports(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        top="""
        from pkg.sub.deep import deep


        def helper() -> None:
            deep()
        """,
    )
    sub = package / "sub"
    sub.mkdir()
    _ = (sub / "__init__.py").write_text("", encoding="utf-8")
    source = "from .. import top\n\n\ndef deep() -> None:\n    top.helper()\n"
    _ = (sub / "deep.py").write_text(source, encoding="utf-8")
    found = check(load_project([str(package)]))
    assert sorted(v.rule for v in found if v.path != ALL_FILES) == ["R1", "R1"]


def test_each_file_is_checked_once(tmp_path: Path) -> None:
    package = write_package(tmp_path, mod="def f() -> None:\n    f()\n")
    project = load_project([str(package), str(package.resolve()), str(package / "mod.py")])
    assert len(project.modules) == 2  # __init__.py and mod.py
    assert [v.rule for v in check(project) if v.path != ALL_FILES] == ["R1"]


def test_checker_finds_its_own_bugs(tmp_path: Path) -> None:
    project = load_project([str(write_package(tmp_path, mod=""))])
    with pytest.raises(CheckerError, match="unknown class"):
        _ = lookup("pkg.mod.Missing", "run", project)


# ---------- the command line ----------


def test_main_reports_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package = write_package(tmp_path, mod="def f() -> None:\n    while True:\n        pass\n")
    assert main([str(package)]) == EXIT_PROBLEMS
    out = capsys.readouterr().out
    assert f"{package / 'mod.py'}:2:5: R2 `while` loop" in out
    assert out.strip().endswith("2 problems.")  # the loop, and too few checks


def test_main_on_clean_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package = write_package(
        tmp_path,
        mod="""
        def f(x: int) -> int:
            if x < 0:
                raise ValueError(x)
            return x
        """,
    )
    assert main([str(package)]) == EXIT_OK
    assert "2 files, 1 function, 1.00 checks per function, 0 problems." in capsys.readouterr().out


def test_this_repository_follows_the_rules(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(BACKEND / "app"), str(BACKEND / "tools")]) == EXIT_OK
    assert "0 problems." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ([], "usage:"),
        (["no/such/folder"], "no such file or folder"),
    ],
)
def test_main_rejects_bad_arguments(
    arguments: list[str], error: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(arguments) == EXIT_BAD_INPUT
    assert error in capsys.readouterr().err


def test_main_rejects_bad_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "broken.py"
    _ = broken.write_text("def f(:\n", encoding="utf-8")
    assert main([str(broken)]) == EXIT_BAD_INPUT
    not_utf8 = tmp_path / "latin1.py"
    _ = not_utf8.write_bytes(b"name = '\xe9'\n")
    assert main([str(not_utf8)]) == EXIT_BAD_INPUT
    assert "power_of_ten:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "case",
    [
        ("MAX_FILES", 1, "more than 1 files"),
        ("MAX_FILE_BYTES", 5, "larger than 5 bytes"),
        ("MAX_NODES", 3, "syntax tree too large"),
    ],
)
def test_main_enforces_its_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, int, str],
) -> None:
    limit, value, error = case
    package = write_package(tmp_path, mod="def f() -> int:\n    return 1\n")
    monkeypatch.setattr(f"tools.power_of_ten.{limit}", value)
    assert main([str(package)]) == EXIT_BAD_INPUT
    assert error in capsys.readouterr().err


def test_violation_and_summary_text(tmp_path: Path) -> None:
    violation = Violation("app/x.py", 3, 5, "R2", "`while` loop")
    assert str(violation) == "app/x.py:3:5: R2 `while` loop"
    project = load_project([str(write_package(tmp_path, mod=""))])
    assert summary(project, [violation]).endswith("0.00 checks per function, 1 problem.")
