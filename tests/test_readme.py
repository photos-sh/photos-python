"""Keeps the README honest: its examples must parse, and every call they make
on a client must fit the real signature."""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import photos_sh
from photos_sh import Jobs, Photos, webhooks

README = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
BLOCKS = re.findall(r"```python\n(.*?)```", README, flags=re.DOTALL)


def calls_on_the_client(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    """Calls like ``photos.resize(...)`` and ``photos.jobs.get(...)``, by dotted name."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        names: list[str] = []
        target: ast.expr = node.func
        while isinstance(target, ast.Attribute):
            names.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name) and target.id in ("photos", "webhooks") and names:
            found.append((".".join([target.id, *reversed(names)]), node))
    return found


def test_the_examples_parse() -> None:
    assert len(BLOCKS) >= 10
    for block in BLOCKS:
        ast.parse(block)


def test_the_examples_fit_the_signatures() -> None:
    checked = set()
    for block in BLOCKS:
        for name, call in calls_on_the_client(ast.parse(block)):
            root, *path = name.split(".")
            if root == "webhooks":
                function = getattr(webhooks, path[0])
                args: list[object] = []
            else:
                owner: type = Photos
                if path[0] == "jobs":
                    owner, path = Jobs, path[1:]
                function = getattr(owner, path[0])
                args = [None]  # self
            args += [None] * len(call.args)
            keywords = {k.arg: None for k in call.keywords if k.arg is not None}
            inspect.signature(function).bind(*args, **keywords)  # raises if it does not fit
            checked.add(name)
    # Every public method has an example.
    for owner, prefix in ((Photos, "photos."), (Jobs, "photos.jobs.")):
        for method in vars(owner):
            public = not method.startswith("_") and callable(getattr(owner, method))
            if public and method != "close":
                assert prefix + method in checked, f"no README example for {prefix}{method}"
    assert "webhooks.verify" in checked
    # Results' own methods: called on the result of a call, so matched by text.
    for method in vars(photos_sh.JobItemResult):
        if not method.startswith("_") and callable(getattr(photos_sh.JobItemResult, method)):
            assert any(f").{method}()" in block for block in BLOCKS), f"no example for {method}"


def test_the_documented_signatures_are_the_real_ones() -> None:
    def shown(function: object, name: str) -> str:
        parameters = list(inspect.signature(function).parameters.values())  # type: ignore[arg-type]
        parameters = [
            p.replace(annotation=inspect.Parameter.empty) for p in parameters if p.name != "self"
        ]
        return f"{name}{inspect.Signature(parameters)}".replace("'", '"')

    assert f"`{shown(Jobs.wait, 'jobs.wait')}`" in README
    assert f"`{shown(Jobs.create, 'jobs.create')}`" in README
    assert f"`{shown(webhooks.verify, 'verify')}`" in README


def test_the_error_classes_named_exist() -> None:
    for name in set(re.findall(r"`(\w+Error)`", README)):
        if name in ("ValueError", "TypeError"):
            continue
        assert issubclass(getattr(photos_sh, name), photos_sh.PhotosError), name
