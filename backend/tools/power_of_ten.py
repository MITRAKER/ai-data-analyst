"""Check Python code against NASA/JPL's "Power of Ten" rules, adapted to Python.

Gerard Holzmann wrote ten rules for safety-critical C code at NASA's Jet
Propulsion Laboratory (JPL). Their goal is code that tools can analyze and
people can review with confidence. This checker enforces our Python version of
them (see docs/CODING_STANDARD.md). Ruff, mypy and basedpyright check the parts
they already know how to check, such as complexity and unused return values,
and every tool treats warnings as errors.

Run it from the backend folder:

    uv run python -m tools.power_of_ten app tools

It prints one line per problem and then a summary. The exit code is 0 when
the code follows every rule, 1 when it does not, and 2 when the input is bad.

The checker follows its own rules: no recursion, no `while` loops, and a fixed
upper bound on every loop and on every file it reads.
"""

from __future__ import annotations

import ast
import io
import itertools
import re
import sys
import tokenize
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, override

MAX_FUNCTION_LINES: Final = 60  # rule 4: a function fits on one printed page
MIN_ASSERTION_DENSITY: Final = 0.5  # rule 5: checks per function, averaged over all code
MAX_FILES: Final = 5_000
MAX_FILE_BYTES: Final = 1_000_000
MAX_NODES: Final = 2_000_000  # upper bound for every walk over a syntax tree
MAX_DEPTH: Final = 1_000  # upper bound for nested scopes and dotted names
ITER_SENTINEL_ARGS: Final = 2  # iter(callable, sentinel) has no fixed end
DYNAMIC_TYPE_ARGS: Final = 3  # type(name, bases, namespace) builds a class at run time
ALL_FILES: Final = "(all files)"  # where the program-wide density problem is reported
EXIT_OK: Final = 0
EXIT_PROBLEMS: Final = 1
EXIT_BAD_INPUT: Final = 2

BANNED_CALLS: Final = frozenset(
    {
        "__import__",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "hasattr",
        "locals",
        "setattr",
        "vars",
    }
)
BANNED_MODULES: Final = frozenset(
    {"code", "codeop", "ctypes", "imp", "importlib", "marshal", "pickle", "runpy", "shelve"}
)
UNBOUNDED_ITERATORS: Final = frozenset({"itertools.count", "itertools.cycle"})
MUTABLE_FACTORIES: Final = frozenset(
    {
        "bytearray",
        "collections.Counter",
        "collections.OrderedDict",
        "collections.defaultdict",
        "collections.deque",
        "dict",
        "list",
        "set",
    }
)
MUTABLE_DISPLAYS: Final = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
SIZED_READS: Final = frozenset({"read", "readline", "readlines"})  # need a size argument
WHOLE_READS: Final = frozenset({"communicate", "read_bytes", "read_text"})  # read everything
ROW_READERS: Final = frozenset({"read_csv", "read_excel", "read_fwf", "read_table"})
SILENCERS: Final = frozenset({"contextlib.suppress"})
CHECK_FUNCTIONS: Final = frozenset({"assert_never", "require"})
PROPERTY_DECORATORS: Final = frozenset({"cached_property", "functools.cached_property", "property"})
ACCESSOR_DECORATORS: Final = frozenset({"deleter", "getter", "setter"})
PROTOCOLS: Final = frozenset({"typing.Protocol", "typing_extensions.Protocol"})
DECORATED: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
NESTED_SCOPES: Final = (*DECORATED, ast.Lambda)
SIDE_EFFECTS: Final = (ast.NamedExpr, ast.Await, ast.Yield, ast.YieldFrom)
DUNDER: Final = re.compile(r"__\w+__")
SUPPRESSION: Final = re.compile(
    r"\s*(?:noqa\b(?::\s*[A-Z]+[0-9]+(?:\s*,\s*[A-Z]+[0-9]+)*)?"
    r"|(?:type|pyright):\s*ignore\b(?:\[[^\]]*\])?)(?P<rest>.*)",
    re.IGNORECASE,
)
REASON: Final = re.compile(r"\s*--\s*\w")
REASON_MESSAGE: Final = "a suppression needs a reason: `# noqa: CODE -- why it is safe`"

type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
type Problem = tuple[str, str]  # (rule, message)


# ---------------------------------------------------------------------------
# What the checker knows about the code
# ---------------------------------------------------------------------------


class CheckerError(RuntimeError):
    """A bug in the checker itself: one of its own invariants did not hold."""


def require(condition: bool, message: str) -> None:
    """Rule 5 for the checker itself: stop with CheckerError if `condition` is false.

    Raises:
        CheckerError: If `condition` is false.
    """
    if not condition:
        raise CheckerError(message)


@dataclass(frozen=True, order=True)
class Violation:
    """One broken rule at one place in the code."""

    path: str
    line: int
    column: int
    rule: str
    message: str

    @override
    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: {self.rule} {self.message}"


@dataclass(frozen=True)
class Module:
    """A parsed source file, and the names that its imports bring in."""

    path: str
    name: str
    tree: ast.Module
    source: str
    lines: tuple[str, ...]
    imports: dict[str, str]


@dataclass(frozen=True)
class Function:
    """A function or method, with its fully qualified name."""

    qualname: str
    node: FunctionNode
    module: Module
    owner: str | None  # the class that `self` means inside this function, if any


@dataclass(frozen=True)
class ClassInfo:
    """A class, with its base classes and the names of its methods."""

    qualname: str
    node: ast.ClassDef
    module: Module
    bases: tuple[str, ...]
    methods: frozenset[str]
    properties: frozenset[str]
    is_protocol: bool


@dataclass(frozen=True)
class Project:
    """Everything the checker knows about the code it checks."""

    modules: tuple[Module, ...]
    functions: dict[str, Function]
    classes: dict[str, ClassInfo]
    lineage: dict[str, tuple[str, ...]]  # each class, then its bases in the checked code
    function_at: dict[ast.AST, Function]  # the Function for each `def` node
    fields: dict[str, dict[str, str]]  # class -> {field of self: the class of its value}


@dataclass(frozen=True)
class Site:
    """One syntax-tree node and where it is."""

    node: ast.AST
    parent: ast.AST | None
    function: Function | None  # the function the node is in, or None at module level
    module: Module
    project: Project


# ---------------------------------------------------------------------------
# Loading files
# ---------------------------------------------------------------------------


def python_files(paths: Sequence[str]) -> list[Path]:
    """Every .py file in the given files and folders, sorted.

    Raises:
        ValueError: If a path does not exist, or there are too many files.
    """
    found: dict[Path, Path] = {}  # the real location -> the path as given, so each file counts once
    for name in paths:
        path = Path(name)
        if path.is_dir():
            files = list(itertools.islice(path.rglob("*.py"), MAX_FILES + 1))
        elif path.is_file():
            files = [path]
        else:
            raise ValueError(f"{name}: no such file or folder")
        for file in files:
            _ = found.setdefault(file.resolve(), file)
        if len(found) > MAX_FILES:
            raise ValueError(f"more than {MAX_FILES} files to check")
    return sorted(found.values())


def read_source(path: Path) -> str:
    """The text of a source file, read with a size limit (rule 3).

    Raises:
        ValueError: If the file is too large, or is not UTF-8.
    """
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"{path}: larger than {MAX_FILE_BYTES} bytes")
    return data.decode("utf-8")


def module_name(path: Path) -> tuple[str, str]:
    """The dotted name of a file's module, and of the package that holds it.

    `app/agent/tools.py` gives `("app.agent.tools", "app.agent")`. The name is
    found by walking up through the folders that have an `__init__.py`.
    """
    absolute = path.resolve()
    is_package = absolute.stem == "__init__"
    parts = [] if is_package else [absolute.stem]
    folder = absolute.parent
    for _ in range(MAX_DEPTH):
        if not (folder / "__init__.py").is_file():
            break
        parts.append(folder.name)
        folder = folder.parent
    name = ".".join(reversed(parts))
    require(bool(name), f"{path}: cannot work out the module name")
    return name, name if is_package else name.rpartition(".")[0]


def import_map(tree: ast.Module, package: str) -> dict[str, str]:
    """Map each name that a module imports to the fully qualified thing it means."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.partition(".")[0]
                names[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom):
            base = absolute_module(node, package)
            for alias in node.names:
                names[alias.asname or alias.name] = f"{base}.{alias.name}"
    return names


def absolute_module(node: ast.ImportFrom, package: str) -> str:
    """The absolute module name in `from module import name`, also for `from . import x`."""
    if not node.level:
        return node.module or ""
    parts = [part for part in package.split(".") if part]
    anchor = parts[: max(len(parts) - (node.level - 1), 0)]
    return ".".join([*anchor, node.module] if node.module else anchor)


def load_module(path: Path) -> Module:
    """Read, parse and index one source file.

    Raises:
        ValueError: If the file is too large, or is not UTF-8.
        SyntaxError: If the file is not valid Python.
    """
    source = read_source(path)
    tree = ast.parse(source, filename=str(path))
    name, package = module_name(path)
    lines = tuple(source.splitlines())
    return Module(str(path), name, tree, source, lines, import_map(tree, package))


def load_project(paths: Sequence[str]) -> Project:
    """Load every Python file under `paths`, and index its functions and classes.

    Raises:
        ValueError: If a path is missing, a file is not UTF-8, or a limit is exceeded.
        SyntaxError: If a file is not valid Python.
    """
    modules = tuple(load_module(path) for path in python_files(paths))
    functions: dict[str, Function] = {}
    classes: dict[str, ClassInfo] = {}
    for module in modules:
        found, class_nodes = definitions(module)
        functions.update((function.qualname, function) for function in found)
        classes.update((name, class_info(name, node, module)) for name, node in class_nodes.items())
    lineage = {name: class_lineage(name, classes) for name in classes}
    function_at: dict[ast.AST, Function] = {
        function.node: function for function in functions.values()
    }
    project = Project(modules, functions, classes, lineage, function_at, {})
    return replace(
        project, fields={name: field_types(info, project) for name, info in classes.items()}
    )


# ---------------------------------------------------------------------------
# Walking syntax trees without recursion
# ---------------------------------------------------------------------------


def walk_scope(statements: Sequence[ast.AST]) -> list[ast.AST]:
    """These nodes and every node under them, except inside nested functions and classes.

    Raises:
        ValueError: If there are more than MAX_NODES nodes.
    """
    found: list[ast.AST] = []
    stack = list(statements)
    for _ in range(MAX_NODES):
        if not stack:
            return found
        node = stack.pop()
        found.append(node)
        if not isinstance(node, NESTED_SCOPES):
            stack.extend(ast.iter_child_nodes(node))
    raise ValueError("syntax tree too large")


def definitions(module: Module) -> tuple[list[Function], dict[str, ast.ClassDef]]:
    """Every function, method and class in a module, with fully qualified names.

    Raises:
        ValueError: If the tree has more than MAX_NODES nodes.
    """
    found: list[Function] = []
    classes: dict[str, ast.ClassDef] = {}
    stack: list[tuple[ast.AST, str, str | None]] = [(module.tree, module.name, None)]
    for _ in range(MAX_NODES):
        if not stack:
            return found, classes
        node, prefix, owner = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qualname = f"{prefix}.{child.name}"
                found.append(Function(qualname, child, module, owner))
                stack.append((child, qualname, owner))
            elif isinstance(child, ast.ClassDef):
                qualname = f"{prefix}.{child.name}"
                classes[qualname] = child
                stack.append((child, qualname, qualname))
            else:
                stack.append((child, prefix, owner))
    raise ValueError(f"{module.path}: syntax tree too large")


def sites(module: Module, project: Project) -> list[Site]:
    """Every node of a module, with its parent and the function that it is in.

    Raises:
        ValueError: If the tree has more than MAX_NODES nodes.
    """
    found: list[Site] = []
    stack: list[tuple[ast.AST, ast.AST | None, Function | None]] = [(module.tree, None, None)]
    for _ in range(MAX_NODES):
        if not stack:
            return found
        node, parent, function = stack.pop()
        found.append(Site(node, parent, function, module, project))
        inside = project.function_at.get(node, function)
        stack.extend((child, node, inside) for child in ast.iter_child_nodes(node))
    raise ValueError(f"{module.path}: syntax tree too large")


def qualified(node: ast.expr, imports: dict[str, str]) -> str:
    """The dotted name of a reference such as `itertools.count`, with imports resolved.

    Returns '' for anything that is not a plain dotted name, such as `f().x`.
    """
    attributes: list[str] = []
    current = node
    for _ in range(MAX_DEPTH):
        if isinstance(current, ast.Attribute):
            attributes.append(current.attr)
            current = current.value
        elif isinstance(current, ast.Name):
            return ".".join([imports.get(current.id, current.id), *reversed(attributes)])
        else:
            return ""
    return ""


def position(node: ast.AST) -> tuple[int, int]:
    """The 1-based line and column of a node."""
    if isinstance(
        node, ast.stmt | ast.expr | ast.excepthandler | ast.arg | ast.keyword | ast.alias
    ):
        return node.lineno, node.col_offset + 1
    return 1, 1


# ---------------------------------------------------------------------------
# Classes, names and calls
# ---------------------------------------------------------------------------


def global_name(node: ast.expr, module: Module) -> str:
    """The fully qualified name of a module-level reference such as a base class."""
    if isinstance(node, ast.Name) and node.id not in module.imports:
        return f"{module.name}.{node.id}"
    return qualified(node, module.imports)


def class_info(qualname: str, node: ast.ClassDef, module: Module) -> ClassInfo:
    """Index one class: its base classes, methods and properties."""
    bases = tuple(global_name(base, module) for base in node.bases)
    methods = [
        item for item in node.body if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    return ClassInfo(
        qualname=qualname,
        node=node,
        module=module,
        bases=bases,
        methods=frozenset(method.name for method in methods),
        properties=frozenset(method.name for method in methods if is_property(method, module)),
        is_protocol=any(base in PROTOCOLS for base in bases),
    )


def is_property(node: FunctionNode, module: Module) -> bool:
    """True for a method that is read like an attribute (@property and friends)."""
    names = [qualified(decorator, module.imports) for decorator in node.decorator_list]
    return any(
        name in PROPERTY_DECORATORS or name.rpartition(".")[2] in ACCESSOR_DECORATORS
        for name in names
    )


def class_lineage(name: str, classes: dict[str, ClassInfo]) -> tuple[str, ...]:
    """A class, then its base classes in the checked code, nearest first."""
    require(name in classes, f"unknown class {name}")
    order = [name]
    for index in range(len(classes)):  # each class joins `order` at most once
        if index >= len(order):
            break
        for base in classes[order[index]].bases:
            if base in classes and base not in order:
                order.append(base)
    return tuple(order)


def lookup(cls: str, name: str, project: Project, *, skip_own: bool = False) -> str:
    """The method that `cls().name` finds by inheritance, or ''."""
    require(cls in project.lineage, f"unknown class {cls}")
    lineage = project.lineage[cls]
    for klass in lineage[1:] if skip_own else lineage:
        if name in project.classes[klass].methods:
            return f"{klass}.{name}"
    return ""


def dispatch(cls: str, name: str, project: Project) -> set[str]:
    """Every method that `obj.name()` may run when `obj` is a `cls` or one of its subclasses."""
    targets = {
        f"{klass}.{name}"
        for klass, lineage in project.lineage.items()
        if cls in lineage and name in project.classes[klass].methods
    }
    inherited = lookup(cls, name, project)
    if inherited:
        targets.add(inherited)
    info = project.classes.get(cls)
    if info is not None and info.is_protocol:  # any class with the method may stand in
        targets.update(
            f"{klass}.{name}" for klass, other in project.classes.items() if name in other.methods
        )
    return targets


def resolve_name(name: str, function: Function | None, module: Module, project: Project) -> str:
    """The checked-code function or class that a plain name means, or ''.

    Like Python, it looks in the enclosing functions, then the module, then the
    imports. Class bodies are skipped, because Python skips them too.
    """
    scope = function.qualname if function is not None else module.name
    for _ in range(MAX_DEPTH):
        candidate = f"{scope}.{name}"
        if scope not in project.classes and (
            candidate in project.functions or candidate in project.classes
        ):
            return candidate
        if scope == module.name or not scope:
            break
        scope = scope.rpartition(".")[0]
    imported = module.imports.get(name, "")
    return imported if imported in project.functions or imported in project.classes else ""


def resolve(node: ast.expr, function: Function | None, module: Module, project: Project) -> str:
    """The fully qualified name of `name` or `name.attr`, or '' for other expressions.

    The first name is looked up the way Python does (see resolve_name), so a
    method of a class in the same module, such as `Greeter.hello`, is found too.
    """
    dotted = qualified(node, {})
    if not dotted:
        return ""
    head, _, rest = dotted.partition(".")
    base = resolve_name(head, function, module, project) or module.imports.get(head, head)
    return f"{base}.{rest}" if rest else base


def annotation_class(annotation: ast.expr, module: Module, project: Project) -> str:
    """The one checked-code class that a type annotation names, such as `Store | None`, or ''.

    A container such as `list[Store]` does not count: its methods are the list's.
    """
    known: set[str] = set()
    stack = [annotation]
    for _ in range(MAX_DEPTH):
        if not stack:
            break
        node = stack.pop()
        if isinstance(node, ast.BinOp):  # `A | B`
            stack.extend((node.left, node.right))
        elif isinstance(node, ast.Name | ast.Attribute):
            known.add(global_name(node, module))
    classes = known & project.classes.keys()
    return classes.pop() if len(classes) == 1 else ""


def arguments(node: FunctionNode) -> list[ast.arg]:
    """All parameters of a function, including *args and **kwargs."""
    spec = node.args
    extra = [argument for argument in (spec.vararg, spec.kwarg) if argument is not None]
    return [*spec.posonlyargs, *spec.args, *spec.kwonlyargs, *extra]


def parameter_types(function: Function, project: Project) -> dict[str, str]:
    """The checked-code class of each parameter whose annotation names one."""
    types: dict[str, str] = {}
    for argument in arguments(function.node):
        if argument.annotation is not None:
            known = annotation_class(argument.annotation, function.module, project)
            if known:
                types[argument.arg] = known
    return types


def value_class(
    value: ast.expr, types: dict[str, str], function: Function, project: Project
) -> str:
    """The checked-code class of an expression's value, when it is plain to see, or ''."""
    match value:
        case ast.Name(id=name):
            return types.get(name, "")
        case ast.Call(func=func):
            target = resolve(func, function, function.module, project)
            return target if target in project.classes else ""
        case _:
            return ""


def field_types(info: ClassInfo, project: Project) -> dict[str, str]:
    """The class of each `self.<field>` of a class, where the code makes it plain."""
    types: dict[str, str] = {}
    for statement in info.node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            known = annotation_class(statement.annotation, info.module, project)
            if known:
                types[statement.target.id] = known
    for name in sorted(info.methods):
        method = project.functions.get(f"{info.qualname}.{name}")
        if method is not None:
            types.update(assigned_fields(method, project))
    return types


def assigned_fields(method: Function, project: Project) -> dict[str, str]:
    """The `self.<field> = value` assignments in a method whose value has a known class."""
    parameters = parameter_types(method, project)
    types: dict[str, str] = {}
    for node in walk_scope(method.node.body):
        match node:
            case (
                ast.Assign(
                    targets=[ast.Attribute(value=ast.Name(id="self"), attr=attr)], value=value
                )
                | ast.AnnAssign(
                    target=ast.Attribute(value=ast.Name(id="self"), attr=attr), value=value
                )
            ):
                known = value_class(value, parameters, method, project) if value else ""
                if known:
                    types[attr] = known
            case _:
                pass
    return types


def local_types(function: Function, project: Project) -> dict[str, str]:
    """The known classes of a function's parameters, local variables and `self` fields."""
    types = parameter_types(function, project)
    for klass in reversed(project.lineage.get(function.owner or "", ())):
        fields = project.fields.get(klass, {})
        types.update({f"self.{name}": known for name, known in fields.items()})
    for node in walk_scope(function.node.body):
        match node:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.withitem(context_expr=value, optional_vars=ast.Name(id=name))
            ):
                known = value_class(value, types, function, project)
                if known:
                    types[name] = known
            case _:
                pass
    return types


def receiver(node: ast.expr) -> str:
    """The key for an object in `local_types`: `name` or `self.field`, or ''."""
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=ast.Name(id="self"), attr=attr):
            return f"self.{attr}"
        case _:
            return ""


def receiver_class(
    value: ast.expr, types: dict[str, str], function: Function, project: Project
) -> str:
    """The checked-code class of `obj` in a call `obj.method()`, or ''."""
    key = receiver(value)
    if key:
        return types.get(key, "")
    return value_class(value, types, function, project)


def call_targets(
    func: ast.expr, function: Function, types: dict[str, str], project: Project
) -> set[str]:
    """The checked-code functions that a call to `func` may run."""
    if not isinstance(func, ast.Attribute):
        return function_or_constructor(resolve(func, function, function.module, project), project)
    owner = function.owner or ""
    match func.value:
        case ast.Name(id="self" | "cls") if owner:
            return dispatch(owner, func.attr, project)
        case ast.Call(func=ast.Name(id="super")) if owner:
            inherited = lookup(owner, func.attr, project, skip_own=True)
            return {inherited} if inherited else set()
        case _:
            klass = receiver_class(func.value, types, function, project)
            if klass:
                return dispatch(klass, func.attr, project)
            return function_or_constructor(
                resolve(func, function, function.module, project), project
            )


def function_or_constructor(name: str, project: Project) -> set[str]:
    """A called function, or the __init__ and __post_init__ that creating a class runs."""
    if name in project.functions:
        return {name}
    if name not in project.classes:
        return set()
    found = {lookup(name, "__init__", project), lookup(name, "__post_init__", project)}
    return found - {""}


def call_graph(project: Project) -> dict[str, set[str]]:
    """For every function, the checked-code functions it may call."""
    graph: dict[str, set[str]] = {}
    for name, function in project.functions.items():
        types = local_types(function, project)
        graph[name] = {
            target
            for node in walk_scope(function.node.body)
            if isinstance(node, ast.Call)
            for target in call_targets(node.func, function, types, project)
        }
    return graph


# ---------------------------------------------------------------------------
# Rules checked one syntax-tree node at a time
# ---------------------------------------------------------------------------


def node_violations(module: Module, project: Project) -> list[Violation]:
    """Rules 2 to 9, for every node of one module."""
    found: list[Violation] = []
    for site in sites(module, project):
        line, column = position(site.node)
        found.extend(
            Violation(module.path, line, column, rule, message)
            for rule, message in node_problems(site)
        )
    return found


def node_problems(site: Site) -> list[Problem]:
    """The rules that one node breaks."""
    node = site.node
    if isinstance(node, ast.stmt):
        return statement_problems(node, site)
    if isinstance(node, ast.expr):
        return expression_problems(node, site)
    if isinstance(node, ast.ExceptHandler) and all(is_no_op(item) for item in node.body):
        return [("R7", "the error is silently ignored: handle it, or let it propagate")]
    return []


def statement_problems(node: ast.stmt, site: Site) -> list[Problem]:
    """Rules 2, 4, 5, 6, 8 and 9 for one statement."""
    problems: list[Problem] = []
    match node:
        case ast.While():
            problems = [("R2", "`while` loop: loop with `for` over something of fixed size")]
        case ast.Global() | ast.Nonlocal():
            problems = [("R6", "`global`/`nonlocal`: pass values in and return them instead")]
        case ast.Assert():
            problems = [("R5", "`assert` is removed by `python -O`: call require() instead")]
        case ast.Import() | ast.ImportFrom():
            problems = import_problems(node)
        case ast.ClassDef(keywords=keywords) if any(k.arg == "metaclass" for k in keywords):
            problems = [("R8", "metaclass: keep classes plain")]
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            problems = function_problems(node, site.module)
        case ast.Assign() | ast.AnnAssign() | ast.AugAssign():
            problems = assignment_problems(node, site)
        case _:
            pass
    return problems


def expression_problems(node: ast.expr, site: Site) -> list[Problem]:
    """Rules 2, 3, 5, 7, 8 and 9 for one expression."""
    match node:
        case ast.Lambda():
            return [("R9", "lambda: write a named function, and call it directly")]
        case ast.Call():
            return call_problems(node, site.module)
        case ast.Attribute(attr=attr, value=value) if DUNDER.fullmatch(attr) and not (
            is_super_call(value)
        ):
            return [("R8", f"`.{attr}`: no reflection through dunder attributes")]
        case ast.Name(ctx=ast.Load()) | ast.Attribute(ctx=ast.Load()):
            return reference_problems(node, site)
        case _:
            return []


def is_super_call(node: ast.expr) -> bool:
    """True for `super()`, so that `super().__init__(...)` stays allowed."""
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "super"
    )


def is_no_op(statement: ast.stmt) -> bool:
    """True for `pass` and for a bare `...`."""
    if isinstance(statement, ast.Pass):
        return True
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


def import_problems(node: ast.Import | ast.ImportFrom) -> list[Problem]:
    """Rule 8: no modules that load or build code at run time."""
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    else:
        names = [node.module or ""]
    return [
        ("R8", f"`import {name}`: no code loaded or built at run time")
        for name in names
        if name.partition(".")[0] in BANNED_MODULES
    ]


def call_problems(node: ast.Call, module: Module) -> list[Problem]:
    """Rules 2, 3, 5, 7 and 8 for one function call."""
    target = qualified(node.func, module.imports)
    return [
        *loop_problems(target, node),
        *memory_problems(target, node),
        *check_problems(target, node),
        *reflection_problems(target, node),
    ]


def loop_problems(target: str, node: ast.Call) -> list[Problem]:
    """Rule 2: iterators that never end on their own."""
    repeats_forever = target == "itertools.repeat" and len(node.args) <= 1 and not node.keywords
    if target in UNBOUNDED_ITERATORS or repeats_forever:
        return [("R2", f"`{target}()` never ends: give the loop a fixed bound")]
    if target == "iter" and len(node.args) == ITER_SENTINEL_ARGS:
        return [("R2", "`iter(callable, sentinel)` has no fixed bound")]
    return []


def memory_problems(target: str, node: ast.Call) -> list[Problem]:
    """Rule 3: reads that hold an unknown amount of data in memory."""
    method = node.func.attr if isinstance(node.func, ast.Attribute) else ""
    problems: list[Problem] = []
    if method in SIZED_READS and not node.args and not node.keywords:
        problems.append(("R3", f"`.{method}()` without a size: read at most a fixed amount"))
    if method in WHOLE_READS:
        problems.append(("R3", f"`.{method}()` reads everything: read at most a fixed amount"))
    reader = target.rpartition(".")[2]
    if reader in ROW_READERS and all(keyword.arg != "nrows" for keyword in node.keywords):
        problems.append(("R3", f"`{reader}()` without `nrows`: cap the number of rows"))
    return problems


def check_problems(target: str, node: ast.Call) -> list[Problem]:
    """Rules 5 and 7: checks without side effects, and no silenced errors."""
    if target.rpartition(".")[2] in CHECK_FUNCTIONS and any(
        isinstance(inner, SIDE_EFFECTS) for inner in ast.walk(node)
    ):
        return [("R5", "a check must not change anything: no `:=`, `await` or `yield` in it")]
    if target in SILENCERS:
        return [("R7", f"`{target}()` hides errors: handle them, or let them propagate")]
    return []


def reflection_problems(target: str, node: ast.Call) -> list[Problem]:
    """Rule 8: no reflection, and no code or classes built at run time."""
    if target in BANNED_CALLS:
        return [("R8", f"`{target}()`: no reflection or code built at run time")]
    if target == "type" and len(node.args) == DYNAMIC_TYPE_ARGS:
        return [("R8", "`type(name, bases, namespace)`: no classes built at run time")]
    return []


def function_problems(node: FunctionNode, module: Module) -> list[Problem]:
    """Rules 4 and 9 for one function definition."""
    problems: list[Problem] = []
    length = code_lines(node, module)
    if length > MAX_FUNCTION_LINES:
        message = f"`{node.name}` has {length} lines of code, more than {MAX_FUNCTION_LINES}"
        problems.append(("R4", f"{message}: split it"))
    annotations = [argument.annotation for argument in arguments(node)]
    if any(holds_function(annotation) for annotation in [*annotations, node.returns]):
        problems.append(("R9", f"`{node.name}` takes or returns a function: use an object"))
    return problems


def holds_function(annotation: ast.expr | None) -> bool:
    """True for a type annotation such as `Callable[[int], str]`."""
    return annotation is not None and "Callable" in ast.unparse(annotation)


def code_lines(node: FunctionNode, module: Module) -> int:
    """Lines of code in a function, not counting its docstring, comments or blank lines."""
    first, last = node.lineno, node.end_lineno or node.lineno
    require(0 < first <= last <= len(module.lines), f"{module.path}: line {last} out of range")
    skip = docstring_lines(node)
    lines = module.lines[first - 1 : last]
    return sum(
        1
        for number, text in enumerate(lines, first)
        if number not in skip and text.strip() and not text.strip().startswith("#")
    )


def docstring_lines(node: FunctionNode) -> set[int]:
    """The line numbers of a function's docstring, if it has one."""
    first = node.body[0]
    match first:
        case ast.Expr(value=ast.Constant(value=str())):
            return set(range(first.lineno, (first.end_lineno or first.lineno) + 1))
        case _:
            return set()


def assignment_problems(
    node: ast.Assign | ast.AnnAssign | ast.AugAssign, site: Site
) -> list[Problem]:
    """Rules 6 and 9: no mutable state shared by the whole program, no stored functions."""
    problems: list[Problem] = []
    if isinstance(node, ast.AnnAssign) and holds_function(node.annotation):
        problems.append(("R9", "a variable that holds a function: call functions directly"))
    shared = site.function is None  # at module level or in a class body
    if shared and (isinstance(node, ast.AugAssign) or is_mutable(node.value, site.module)):
        problems.append(("R6", "mutable module or class state: use a constant, or a function"))
    return problems


def is_mutable(value: ast.expr | None, module: Module) -> bool:
    """True for a list, dict or set, written out or built by a call such as `list()`."""
    if isinstance(value, MUTABLE_DISPLAYS):
        return True
    return (
        isinstance(value, ast.Call) and qualified(value.func, module.imports) in MUTABLE_FACTORIES
    )


def reference_problems(node: ast.Name | ast.Attribute, site: Site) -> list[Problem]:
    """Rule 9: a function used as a value, instead of being called."""
    parent = site.parent
    if isinstance(parent, ast.Call) and parent.func is node:
        return []
    if isinstance(parent, DECORATED) and any(node is item for item in parent.decorator_list):
        return []
    target = referenced_function(node, site)
    if not target:
        return []
    name = target.rpartition(".")[2]
    return [("R9", f"`{name}` is used as a value: call it, or pass an object instead")]


def referenced_function(node: ast.Name | ast.Attribute, site: Site) -> str:
    """The checked-code function or method that a name refers to, or ''."""
    project = site.project
    owner = site.function.owner if site.function is not None else None
    match node:
        case ast.Attribute(value=ast.Name(id="self" | "cls"), attr=attr) if owner:
            found = lookup(owner, attr, project)
            klass, _, method = found.rpartition(".")
            return found if found and method not in project.classes[klass].properties else ""
        case _:
            found = resolve(node, site.function, site.module, project)
    return found if found in project.functions else ""


# ---------------------------------------------------------------------------
# Rules checked over the whole program
# ---------------------------------------------------------------------------


def recursion_violations(project: Project) -> list[Violation]:
    """Rule 1: no function may call itself, directly or through other functions."""
    graph = call_graph(project)
    names = sorted(graph)
    index = {name: number for number, name in enumerate(names)}
    called = set().union(*graph.values())
    require(
        called <= index.keys(), f"the call graph names unknown functions: {called - index.keys()}"
    )
    reach = [sum(1 << index[target] for target in graph[name]) for name in names]
    for middle in range(len(names)):  # Warshall's algorithm: add the paths through `middle`
        bit = 1 << middle
        for start in range(len(names)):
            if reach[start] & bit:
                reach[start] |= reach[middle]
    found: list[Violation] = []
    for number, name in enumerate(names):
        if reach[number] >> number & 1:
            partner = cycle_partner(number, reach, names)
            found.append(recursion_violation(project.functions[name], partner))
    return found


def cycle_partner(number: int, reach: list[int], names: list[str]) -> str:
    """Another function on the same call cycle, or '' if the function calls only itself."""
    require(reach[number] >> number & 1 == 1, "only a recursive function has a cycle")
    for other, name in enumerate(names):
        if other != number and reach[number] >> other & 1 and reach[other] >> number & 1:
            return name
    return ""


def recursion_violation(function: Function, partner: str) -> Violation:
    """The report for one recursive function."""
    short = function.qualname.removeprefix(f"{function.module.name}.")
    how = f"through `{partner}`" if partner else "directly"
    line, column = position(function.node)
    message = f"`{short}` calls itself {how}: use a loop with a fixed bound"
    return Violation(function.module.path, line, column, "R1", message)


def is_stub(node: FunctionNode) -> bool:
    """True for a function with no code, such as a protocol method: only a docstring or `...`."""
    body = node.body[1:] if docstring_lines(node) else node.body
    return all(is_no_op(statement) for statement in body)


def is_check(node: ast.AST, module: Module) -> bool:
    """True for a `raise` statement, or a call to require() or assert_never()."""
    if isinstance(node, ast.Raise):
        return True
    return isinstance(node, ast.Call) and (
        qualified(node.func, module.imports).rpartition(".")[2] in CHECK_FUNCTIONS
    )


def assertion_density(project: Project) -> tuple[int, int]:
    """Rule 5: the number of checks, and the number of functions that are not stubs."""
    checks = 0
    counted = 0
    for function in project.functions.values():
        if not is_stub(function.node):
            counted += 1
            nodes = walk_scope(function.node.body)
            checks += sum(1 for node in nodes if is_check(node, function.module))
    return checks, counted


def density_violations(project: Project) -> list[Violation]:
    """Rule 5: on average, every function should check what it relies on."""
    checks, counted = assertion_density(project)
    if not counted or checks / counted >= MIN_ASSERTION_DENSITY:
        return []
    message = (
        f"{checks} checks in {counted} functions is {checks / counted:.2f} per function, "
        f"below {MIN_ASSERTION_DENSITY}: check inputs and results with require()"
    )
    return [Violation(ALL_FILES, 0, 0, "R5", message)]


def is_unexplained(comment: str) -> bool:
    """True if a comment silences a tool (noqa, type: ignore) without saying why."""
    segments = comment.split("#")[1:]
    for index, segment in enumerate(segments):
        match = SUPPRESSION.match(segment)
        if match is None:
            continue
        rest = match.group("rest")
        following = segments[index + 1] if index + 1 < len(segments) else ""
        explained_here = REASON.match(rest) is not None
        explained_after = not rest.strip() and bool(following.strip())
        if not (explained_here or (explained_after and SUPPRESSION.match(following) is None)):
            return True
    return False


def suppression_violations(module: Module) -> list[Violation]:
    """Rule 10: a comment that silences a warning must give the reason."""
    tokens = tokenize.generate_tokens(io.StringIO(module.source).readline)
    return [
        Violation(module.path, token.start[0], token.start[1] + 1, "R10", REASON_MESSAGE)
        for token in tokens
        if token.type == tokenize.COMMENT and is_unexplained(token.string)
    ]


# ---------------------------------------------------------------------------
# Running the checker
# ---------------------------------------------------------------------------


def check(project: Project) -> list[Violation]:
    """Every rule broken anywhere in the project, sorted by place."""
    found: list[Violation] = []
    for module in project.modules:
        found.extend(node_violations(module, project))
        found.extend(suppression_violations(module))
    found.extend(recursion_violations(project))
    found.extend(density_violations(project))
    return sorted(found)


def plural(count: int, noun: str) -> str:
    """'1 file', '2 files'."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def summary(project: Project, violations: Sequence[Violation]) -> str:
    """One line with what was checked and what was found."""
    checks, counted = assertion_density(project)
    density = checks / counted if counted else 0.0
    return (
        f"Power of Ten: {plural(len(project.modules), 'file')}, {plural(counted, 'function')}, "
        f"{density:.2f} checks per function, {plural(len(violations), 'problem')}."
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Check the files and folders named on the command line.

    Returns:
        0 when every rule holds, 1 when a rule is broken, 2 when the input is bad.
    """
    paths = list(sys.argv[1:] if argv is None else argv)
    if not paths:
        print("usage: python -m tools.power_of_ten PATH [PATH ...]", file=sys.stderr)
        return EXIT_BAD_INPUT
    try:
        project = load_project(paths)
        violations = check(project)
    except (OSError, SyntaxError, ValueError) as error:
        print(f"power_of_ten: {error}", file=sys.stderr)
        return EXIT_BAD_INPUT
    for violation in violations:
        print(violation)
    print(summary(project, violations))
    return EXIT_PROBLEMS if violations else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
