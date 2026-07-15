"""papers_database.csv を正本として、先行研究の発表年の整合性を検証する。

`docs/04_archive/01_metadata/papers_database.csv` の ID・年を正本とし、
以下の3箇所に記載された同一IDの発表年が正本と一致するかを突合する。

- `docs/README.md` の「先行研究一覧（S1-S8）」箇条書き
- `docs/04_archive/previous_studies_report.md` の「先行研究一覧」表
- `docs/04_archive/02_structured_summaries/S{ID}_*.md` のファイル名末尾の年、
  および本文表の「**発表年**」行

正本の年が「年不明」等パース不能な値であっても、他箇所が具体的な年を
記載していれば不一致として検出する（S2の発表年分裂と同種の問題を
恒久的に検出するため）。
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT

_PAPERS_DB_PATH = "docs/04_archive/01_metadata/papers_database.csv"
_README_PATH = "docs/README.md"
_REPORT_PATH = "docs/04_archive/previous_studies_report.md"
_SUMMARIES_DIR = "docs/04_archive/02_structured_summaries"

_README_BULLET_PATTERN = re.compile(r"-\s*\*\*(S\d+)\*\*:[^(]*\(([^)]*)\)")
_REPORT_ROW_PATTERN = re.compile(r"\|\s*(S\d+)\s*\|[^|(]*\(([^)]*)\)[^|]*\|")
_SUMMARY_FILENAME_PATTERN = re.compile(r"^(S\d+)_.*?(\d{4})\.md$")
_SUMMARY_HEADER_YEAR_PATTERN = re.compile(r"\*\*発表年\*\*\s*\|\s*([^\|]+?)\s*\|")


@dataclass(frozen=True)
class BibliographyMismatch:
    """papers_database.csv の発表年と他箇所の記載が一致しない1件。"""

    paper_id: str
    source: str
    canonical_year: str
    found_year: str


def check_bibliography_consistency(
    project_root: Path = PROJECT_ROOT,
) -> list[BibliographyMismatch]:
    """papers_database.csv を正本に、他3箇所の発表年記載を突合する。"""
    canonical_years = _load_canonical_years(project_root)

    mismatches: list[BibliographyMismatch] = []
    mismatches.extend(
        _check_source(
            project_root / _README_PATH,
            "docs/README.md",
            canonical_years,
            _extract_readme_years,
        )
    )
    mismatches.extend(
        _check_source(
            project_root / _REPORT_PATH,
            "docs/04_archive/previous_studies_report.md",
            canonical_years,
            _extract_report_years,
        )
    )
    mismatches.extend(_check_summaries(project_root, canonical_years))
    return mismatches


def _load_canonical_years(project_root: Path) -> dict[str, str]:
    csv_path = project_root / _PAPERS_DB_PATH
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return {row["ID"].strip(): row["年"].strip() for row in reader if row.get("ID")}


def _check_source(
    file_path: Path,
    source_label: str,
    canonical_years: dict[str, str],
    extractor: Callable[[str], list[tuple[str, str]]],
) -> list[BibliographyMismatch]:
    if not file_path.exists():
        return []
    text = file_path.read_text(encoding="utf-8")
    mismatches: list[BibliographyMismatch] = []
    for paper_id, found_year in extractor(text):
        canonical = canonical_years.get(paper_id)
        if canonical is not None and found_year != canonical:
            mismatches.append(
                BibliographyMismatch(
                    paper_id=paper_id,
                    source=source_label,
                    canonical_year=canonical,
                    found_year=found_year,
                )
            )
    return mismatches


def _extract_readme_years(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2).strip()) for m in _README_BULLET_PATTERN.finditer(text)]


def _extract_report_years(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2).strip()) for m in _REPORT_ROW_PATTERN.finditer(text)]


def _check_summaries(
    project_root: Path, canonical_years: dict[str, str]
) -> list[BibliographyMismatch]:
    summaries_dir = project_root / _SUMMARIES_DIR
    if not summaries_dir.exists():
        return []

    mismatches: list[BibliographyMismatch] = []
    for summary_path in sorted(summaries_dir.glob("S*.md")):
        filename_match = _SUMMARY_FILENAME_PATTERN.match(summary_path.name)
        if filename_match is None:
            continue
        paper_id, filename_year = filename_match.group(1), filename_match.group(2)
        canonical = canonical_years.get(paper_id)
        if canonical is not None and filename_year != canonical:
            mismatches.append(
                BibliographyMismatch(
                    paper_id=paper_id,
                    source=f"{_SUMMARIES_DIR}/{summary_path.name}（ファイル名）",
                    canonical_year=canonical,
                    found_year=filename_year,
                )
            )

        text = summary_path.read_text(encoding="utf-8")
        header_match = _SUMMARY_HEADER_YEAR_PATTERN.search(text)
        if header_match is not None and canonical is not None:
            header_year = header_match.group(1).strip()
            if header_year != canonical:
                mismatches.append(
                    BibliographyMismatch(
                        paper_id=paper_id,
                        source=f"{_SUMMARIES_DIR}/{summary_path.name}（ヘッダー）",
                        canonical_year=canonical,
                        found_year=header_year,
                    )
                )
    return mismatches
