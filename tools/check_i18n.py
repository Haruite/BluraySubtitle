"""Ratchet checks for the repository's English-source and i18n rules.

The user-visible call detection is intentionally conservative. It covers common Qt
widget constructors, message boxes, text setters, and terminal output calls. The
baseline allows existing debt to decrease while rejecting new text or additional
occurrences. Moving existing code between files does not increase debt.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import tokenize
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = Path("src/core/i18n.py")
BASELINE_PATH = Path("tools/i18n_audit_baseline.json")
WIDGET_TEXT_CALLS = {"QLabel", "QPushButton", "QCheckBox", "QGroupBox"}
MESSAGE_BOX_CALLS = {"information", "warning", "critical"}
TEXT_SETTER_CALLS = {"setWindowTitle", "setText", "setLabelText"}
OUTPUT_CALLS = {"print", "print_terminal_line"}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    text: str


def _catalog(project_root: Path) -> dict[str, str]:
    path = project_root / CATALOG_PATH
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "I18N_ZH_TO_EN" for target in node.targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict):
                break
            return value
    raise ValueError(f"I18N_ZH_TO_EN was not found in {path}")


def _is_translation_call(node: ast.Call) -> bool:
    function = node.func
    return (
        isinstance(function, ast.Attribute) and function.attr == "t"
    ) or (
        isinstance(function, ast.Name) and function.id == "translate_text"
    )


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _literal_fragments(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ]
    return []


def _visible_argument_indexes(node: ast.Call) -> list[int]:
    name = _call_name(node)
    if name in WIDGET_TEXT_CALLS or name in TEXT_SETTER_CALLS:
        return [0]
    if name in MESSAGE_BOX_CALLS:
        return [1, 2]
    if name in OUTPUT_CALLS:
        return list(range(len(node.args)))
    return []


def _has_visible_text(text: str) -> bool:
    return bool(text.strip()) and any(character.isalpha() for character in text)


def audit_findings(project_root: Path = PROJECT_ROOT) -> dict[str, Counter[Finding]]:
    """Collect path/text counters for diagnostics and repository-wide debt totals."""
    catalog = _catalog(project_root)
    english_sources = set(catalog.values())
    catalog_path = project_root / CATALOG_PATH
    findings = {
        "chinese_source_strings": Counter(),
        "unmapped_translation_calls": Counter(),
        "chinese_comments": Counter(),
        "direct_user_visible_strings": Counter(),
    }
    for module_path in sorted((project_root / "src").rglob("*.py")):
        relative_path = module_path.relative_to(project_root).as_posix()
        source_text = module_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source_text, filename=str(module_path))
        for token in tokenize.generate_tokens(io.StringIO(source_text).readline):
            if token.type == tokenize.COMMENT and any(
                "\u4e00" <= character <= "\u9fff" for character in token.string
            ):
                findings["chinese_comments"][Finding(relative_path, token.string)] += 1
        for node in ast.walk(tree):
            if (
                module_path != catalog_path
                and isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and any("\u4e00" <= character <= "\u9fff" for character in node.value)
            ):
                findings["chinese_source_strings"][Finding(relative_path, node.value)] += 1
            if not isinstance(node, ast.Call) or not _is_translation_call(node) or not node.args:
                continue
            source = node.args[0]
            if isinstance(source, ast.Constant) and isinstance(source.value, str):
                if source.value not in english_sources:
                    findings["unmapped_translation_calls"][Finding(relative_path, source.value)] += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for argument_index in _visible_argument_indexes(node):
                if argument_index >= len(node.args):
                    continue
                argument = node.args[argument_index]
                if isinstance(argument, ast.Call) and _is_translation_call(argument):
                    continue
                for text in _literal_fragments(argument):
                    if _has_visible_text(text):
                        findings["direct_user_visible_strings"][Finding(relative_path, text)] += 1
    return findings


def write_baseline(project_root: Path = PROJECT_ROOT) -> Path:
    findings = audit_findings(project_root)
    payload = {
        rule: [
            {"path": finding.path, "text": finding.text, "count": count}
            for finding, count in sorted(counter.items())
        ]
        for rule, counter in sorted(findings.items())
    }
    path = project_root / BASELINE_PATH
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return path


def _load_baseline(project_root: Path) -> dict[str, Counter[Finding]]:
    path = project_root / BASELINE_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        rule: Counter(
            {
                Finding(entry["path"], entry["text"]): int(entry["count"])
                for entry in entries
            }
        )
        for rule, entries in raw.items()
    }


def audit_errors(project_root: Path = PROJECT_ROOT) -> list[str]:
    current = audit_findings(project_root)
    baseline = _load_baseline(project_root)
    errors: list[str] = []
    for rule, current_counter in current.items():
        current_by_text: Counter[str] = Counter()
        baseline_by_text: Counter[str] = Counter()
        for finding, count in current_counter.items():
            current_by_text[finding.text] += count
        for finding, count in baseline.get(rule, Counter()).items():
            baseline_by_text[finding.text] += count
        for finding_text, count in sorted((current_by_text - baseline_by_text).items()):
            paths = sorted(
                finding.path
                for finding in current_counter
                if finding.text == finding_text
            )
            errors.append(
                f"{rule}: {finding_text!r} has {count} new occurrence(s); "
                f"current paths: {', '.join(paths)}"
            )
    return errors


def baseline_metrics(project_root: Path = PROJECT_ROOT) -> dict[str, tuple[int, int]]:
    baseline = _load_baseline(project_root)
    return {
        rule: (sum(counter.values()), len(counter))
        for rule, counter in baseline.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Replace the audit baseline with the current findings.",
    )
    args = parser.parse_args()
    if args.write_baseline:
        path = write_baseline()
        print(f"Wrote i18n audit baseline: {path}")
        return 0
    errors = audit_errors()
    if errors:
        print("i18n audit failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    metrics = baseline_metrics()
    summary = ", ".join(
        f"{rule}={occurrences} occurrence(s) in {unique} path/text item(s)"
        for rule, (occurrences, unique) in sorted(metrics.items())
    )
    print(f"i18n ratchet passed ({summary}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
