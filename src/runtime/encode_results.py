"""Encode row results, retained failure artifacts, and batch summaries."""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.core.i18n import translate_text


class EncodeTaskFailure(RuntimeError):
    """A row-local execution failure with task-owned artifacts to retain."""

    def __init__(
            self,
            stage: str,
            message: str,
            artifact_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.stage = str(stage or 'Encode row execution')
        self.artifact_paths = tuple(dict.fromkeys(
            os.path.abspath(os.path.normpath(path))
            for path in artifact_paths
            if str(path or '').strip()
        ))


@dataclass(frozen=True)
class EncodeRowResult:
    """Terminal result for one visible main or SP Encode row."""

    row_type: str
    source_path: str
    output_path: str
    status: str
    message: str = ''
    report_path: str = ''
    artifact_paths: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EncodeBatchResult:
    """Ordered results for every selected row in one Encode request."""

    rows: tuple[EncodeRowResult, ...]

    @property
    def failed_rows(self) -> tuple[EncodeRowResult, ...]:
        return tuple(row for row in self.rows if row.status.startswith('failed'))

    @property
    def completed_rows(self) -> tuple[EncodeRowResult, ...]:
        return tuple(row for row in self.rows if row.status == 'completed')

    @property
    def warning_rows(self) -> tuple[EncodeRowResult, ...]:
        return tuple(row for row in self.rows if row.status == 'completed_with_warnings')


def write_encode_row_error_report(
        row_type: str,
        source_path: str,
        output_path: str,
        stage: str,
        error: BaseException,
        artifact_paths: tuple[str, ...],
) -> str:
    """Write a new row-owned report without replacing an existing report."""
    normalized_output = os.path.abspath(os.path.normpath(output_path))
    output_folder = os.path.dirname(normalized_output)
    os.makedirs(output_folder, exist_ok=True)
    output_stem = os.path.splitext(os.path.basename(normalized_output))[0]
    report_base = os.path.join(output_folder, f'{output_stem}.encode-error')
    lines = [
        translate_text('Encode row failed; later rows continued.'),
        translate_text('Row type: {row_type}').format(row_type=translate_text(row_type)),
        translate_text('Source: {path}').format(
            path=os.path.abspath(os.path.normpath(source_path))
        ),
        translate_text('Planned output: {path}').format(path=normalized_output),
        translate_text('Stage: {stage}').format(stage=translate_text(stage)),
        translate_text('Error: {error}').format(error=str(error)),
        translate_text('Preserved artifacts:'),
    ]
    if artifact_paths:
        lines.extend(f'- {path}' for path in artifact_paths)
    else:
        lines.append(f'- {translate_text("None")}')

    suffix = 1
    while True:
        report_path = (
            f'{report_base}.txt'
            if suffix == 1
            else f'{report_base}.{suffix}.txt'
        )
        try:
            with open(report_path, 'x', encoding='utf-8', newline='') as report:
                report.write('\r\n'.join(lines) + '\r\n')
        except FileExistsError:
            suffix += 1
            continue
        return report_path


def format_encode_batch_error_summary(
        result: EncodeBatchResult,
        messages: tuple[str, ...],
) -> str:
    """Format the one post-worker summary shown for a batch with row failures."""
    lines = [
        translate_text('Encode batch completed with errors.'),
        translate_text('Completed rows: {count}').format(
            count=len(result.completed_rows)
        ),
        translate_text('Completed with warnings: {count}').format(
            count=len(result.warning_rows)
        ),
        translate_text('Failed rows: {count}').format(count=len(result.failed_rows)),
    ]
    report_paths = tuple(
        row.report_path for row in result.failed_rows if row.report_path
    )
    if report_paths:
        lines.extend(('', translate_text('Error reports:')))
        lines.extend(f'- {path}' for path in report_paths)
    artifact_paths = tuple(dict.fromkeys(
        path
        for row in result.failed_rows
        for path in row.artifact_paths
    ))
    if artifact_paths:
        lines.extend(('', translate_text('Preserved artifacts:')))
        lines.extend(f'- {path}' for path in artifact_paths)
    if messages:
        lines.extend(('', translate_text('Warnings and errors:')))
        lines.extend(f'- {message}' for message in messages)
    return '\n'.join(lines)


__all__ = [
    'EncodeBatchResult',
    'EncodeRowResult',
    'EncodeTaskFailure',
    'format_encode_batch_error_summary',
    'write_encode_row_error_report',
]
