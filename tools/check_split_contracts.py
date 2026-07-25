"""Verify split mixin names and signatures against their IDE base classes."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_START = "    # BEGIN GENERATED MIXIN CONTRACTS"
GENERATED_END = "    # END GENERATED MIXIN CONTRACTS"


@dataclass(frozen=True)
class ContractSpec:
    split_directory: str
    base_filename: str
    base_class: str
    base_only_methods: frozenset[str]
    signature_exceptions: frozenset[str]


CONTRACTS = (
    ContractSpec(
        "src/runtime/services_split",
        "service_base.py",
        "BluraySubtitleServiceBase",
        frozenset({"__init_subclass__"}),
        frozenset({"__init__"}),
    ),
    ContractSpec(
        "src/runtime/gui_runtime_split",
        "gui_base.py",
        "BluraySubtitleGuiBase",
        frozenset({"__init_subclass__"}),
        frozenset({"__init__"}),
    ),
)


def _class_methods(
    module_path: Path,
    class_name: str,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    class_node = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name),
        None,
    )
    if class_node is None:
        raise ValueError(f"Class {class_name!r} was not found in {module_path}")
    return {
        node.name: node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _mixin_methods(
    split_directory: Path,
    base_filename: str,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for module_path in sorted(split_directory.glob("*.py")):
        if module_path.name in {"__init__.py", base_filename}:
            continue
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef) or not class_node.name.endswith("Mixin"):
                continue
            methods.update(
                {
                    node.name: node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            )
    return methods


def _method_contract(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, tuple[str, ...]]:
    return_annotation = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    signature = f"({ast.unparse(node.args)}){return_annotation}"
    decorators = tuple(ast.unparse(decorator) for decorator in node.decorator_list)
    return signature, decorators


def _generated_declarations(
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> str:
    lines = [GENERATED_START]
    for method_name, node in sorted(methods.items()):
        lines.extend(f"    @{ast.unparse(decorator)}" for decorator in node.decorator_list)
        async_prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        return_annotation = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        lines.extend(
            (
                f"    {async_prefix}def {method_name}({ast.unparse(node.args)}){return_annotation}:",
                "        raise NotImplementedError",
                "",
            )
        )
    lines.append(GENERATED_END)
    return "\n".join(lines)


def synchronize_contracts(project_root: Path = PROJECT_ROOT, write: bool = False) -> list[str]:
    """Generate or verify both IDE base declaration blocks from their split mixins."""
    errors: list[str] = []
    for spec in CONTRACTS:
        split_directory = project_root / spec.split_directory
        base_path = split_directory / spec.base_filename
        source = base_path.read_text(encoding="utf-8-sig")
        start = source.find(GENERATED_START)
        end = source.find(GENERATED_END)
        if start < 0 or end < start:
            errors.append(f"{spec.base_filename}: generated declaration markers are missing")
            continue
        end += len(GENERATED_END)
        mixin_methods = _mixin_methods(split_directory, spec.base_filename)
        generated = _generated_declarations(
            {
                name: node
                for name, node in mixin_methods.items()
                if name not in spec.signature_exceptions
            }
        )
        if source[start:end] == generated:
            continue
        if not write:
            errors.append(
                f"{spec.base_filename}: generated declarations are stale; "
                "run python tools/check_split_contracts.py --write"
            )
            continue
        updated = source[:start] + generated + source[end:]
        base_path.write_bytes(updated.replace("\n", "\r\n").encode("utf-8"))
    return errors


def contract_errors(project_root: Path = PROJECT_ROOT) -> list[str]:
    """Return missing or stale base declarations without importing PyQt or application code."""
    errors = synchronize_contracts(project_root)
    for spec in CONTRACTS:
        split_directory = project_root / spec.split_directory
        mixin_methods = _mixin_methods(split_directory, spec.base_filename)
        base_methods = _class_methods(split_directory / spec.base_filename, spec.base_class)
        declared_contracts = set(base_methods) - spec.base_only_methods
        missing = sorted(set(mixin_methods) - declared_contracts)
        stale = sorted(declared_contracts - set(mixin_methods))
        if missing:
            errors.append(f"{spec.base_filename}: missing declarations: {', '.join(missing)}")
        if stale:
            errors.append(f"{spec.base_filename}: stale declarations: {', '.join(stale)}")
        shared = sorted(set(mixin_methods) & declared_contracts - spec.signature_exceptions)
        for method_name in shared:
            base_contract = _method_contract(base_methods[method_name])
            mixin_contract = _method_contract(mixin_methods[method_name])
            if base_contract != mixin_contract:
                errors.append(
                    f"{spec.base_filename}: {method_name} contract differs: "
                    f"base={base_contract!r}, mixin={mixin_contract!r}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate both IDE base declaration blocks before checking them",
    )
    args = parser.parse_args()
    if args.write:
        errors = synchronize_contracts(write=True)
        if errors:
            print("Split base contract generation failed:")
            for error in errors:
                print(f"- {error}")
            return 1
    errors = contract_errors()
    if errors:
        print("Split base contract check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Split base contracts are synchronized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
