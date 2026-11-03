"""文献データベースから修士論文の参考文献用の BibTeX（.bib）を生成する。

``docs/04_archive/01_metadata/papers_database.csv``（文献 DB。収録する論文と S 番号の正本）と
``docs/04_archive/01_metadata/papers_bibliography.csv``（引用用書誌。全著者・原典表記の題名・
巻・号・ページ。Crossref と原典 PDF で照合済み）を突き合わせ、引用キーを S 番号（``S1`` 等）
とする .bib を書き出す。本文では ``[@S1]`` のように引用する。

生成前に 2 つの CSV を検査し、1 件でも問題があれば .bib を書かずに失敗する。

- 必要な列がそろい、列数がヘッダーより多い行（題名の引用符漏れ等）が無く、行が 1 件以上ある
- 文献 DB の全 ID に引用用書誌の行があり、引用用書誌に DB に無い ID が無い
- 年が一致し、題名・誌名が大文字小文字・記号・空白の差を除いて一致する
- 文献 DB に DOI が書かれている場合は DOI が一致する（大文字小文字は区別しない）
- 必須欄（著者・題名・誌名・年）が空でなく、文献種別（article／inproceedings）と年・ページ・
  DOI の書式が正しい

使い方:
    python scripts/make_thesis_bib.py
    python scripts/make_thesis_bib.py --output path/to/references.bib

``scripts/build_thesis.py`` はビルドのたびに本スクリプトの処理で、出力する docx と同じ
ディレクトリ（既定は ``thesis/build/``）に ``references.bib`` を生成する（生成物はコミットしない）。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
METADATA_DIR = REPO_ROOT / "docs" / "04_archive" / "01_metadata"
DATABASE_FILE = METADATA_DIR / "papers_database.csv"
BIBLIOGRAPHY_FILE = METADATA_DIR / "papers_bibliography.csv"
DEFAULT_OUTPUT = REPO_ROOT / "thesis" / "build" / "references.bib"

# 引用用書誌の文献種別 → BibTeX のエントリ型と、誌名（掲載先）を書く欄
ENTRY_TYPES = {
    "article": ("article", "journal"),
    "inproceedings": ("inproceedings", "booktitle"),
}

# 読み込みに必要な列（列名の誤りで欄が黙って空になるのを防ぐため、ヘッダーで検査する）
DATABASE_COLUMNS = ("ID", "年", "タイトル", "掲載誌", "DOI_URL")
BIBLIOGRAPHY_COLUMNS = ("ID", "文献種別", "著者", "題名", "誌名", "年", "巻", "号", "ページ", "DOI")
# 引用用書誌で値が空であってはならない列
REQUIRED_VALUES = ("著者", "題名", "誌名", "年")

ID_PATTERN = re.compile(r"^S(\d+)$")
YEAR_PATTERN = re.compile(r"^\d{4}$")
# ページ範囲（80-90）または論文番号（1471）。英字を含む番号（e0123 等）も許す
PAGES_PATTERN = re.compile(r"^[0-9A-Za-z]+(-[0-9A-Za-z]+)?$")
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"'<>{}%\\]+")

# BibTeX（LaTeX）で特別な意味を持つ文字のエスケープ。置換結果に含まれる「\」「{}」を
# 再びエスケープしないよう、1 回の走査で置換する
_BIBTEX_ESCAPES = (
    ("\\", r"\textbackslash{}"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
)
_BIBTEX_ESCAPE_MAP = dict(_BIBTEX_ESCAPES)
_BIBTEX_SPECIALS = re.compile("[" + re.escape("".join(_BIBTEX_ESCAPE_MAP)) + "]")

# 終了コード
EXIT_OK = 0
EXIT_ERROR = 2


class BibliographyError(ValueError):
    """文献 DB・引用用書誌の問題（メッセージの一覧を持つ）。"""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def load_rows(path: Path, columns: Sequence[str]) -> list[dict[str, str]]:
    """CSV を読み、各行を列名 → 値（前後の空白を除いたもの）の辞書で返す。

    Args:
        path: CSV のパス（UTF-8。BOM の有無は問わない）。
        columns: ヘッダーに必要な列名。

    Returns:
        行の一覧。

    Raises:
        FileNotFoundError: ファイルが無い場合。
        BibliographyError: 必要な列が無い・列数がヘッダーより多い行がある・行が無い場合。
    """
    if not path.is_file():
        raise FileNotFoundError(f"ファイルがありません: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames or []
        missing = [column for column in columns if column not in header]
        if missing:
            raise BibliographyError([f"{path.name}: 列がありません: {'、'.join(missing)}"])
        rows: list[dict[str, str]] = []
        problems: list[str] = []
        for row in reader:
            # 列数がヘッダーより多い行は、余りの値が None キーに入る
            if None in row:
                problems.append(
                    f"{path.name}: {reader.line_num} 行目の列数がヘッダーより多い"
                    "（カンマを含む値を引用符で囲んでいない可能性）"
                )
                continue
            rows.append({key: (value or "").strip() for key, value in row.items()})
    if not rows and not problems:
        problems.append(f"{path.name}: データの行がありません")
    if problems:
        raise BibliographyError(problems)
    return rows


def normalize_text(value: str) -> str:
    """照合用に正規化する（小文字化・記号を空白へ・空白の圧縮）。"""
    text = re.sub(r"[^\w\s]", " ", value.lower())
    return re.sub(r"\s+", " ", text).strip()


def extract_doi(value: str) -> str | None:
    """文字列（DOI または DOI を含む URL）から DOI を取り出す。無ければ None。"""
    match = DOI_PATTERN.search(value)
    return match.group(0).rstrip(".,;") if match else None


def index_by_id(
    rows: Sequence[dict[str, str]], label: str
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """行を ID で引ける辞書にし、ID の書式違反・重複を問題として返す。

    Args:
        rows: CSV の行。
        label: 問題のメッセージに付ける CSV の呼び名。

    Returns:
        ID → 行の辞書と、問題のメッセージの一覧。
    """
    indexed: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    for row in rows:
        paper_id = row.get("ID", "")
        if not ID_PATTERN.match(paper_id):
            problems.append(f"{label}: ID の書式が不正です（S+番号）: {paper_id!r}")
        elif paper_id in indexed:
            problems.append(f"{label}: ID が重複しています: {paper_id}")
        else:
            indexed[paper_id] = row
    return indexed, problems


def check_entry(paper_id: str, db_row: dict[str, str], bib_row: dict[str, str]) -> list[str]:
    """1 件分の引用用書誌を、書式と文献 DB との一致の観点で検査する。

    Args:
        paper_id: S 番号。
        db_row: 文献 DB の行。
        bib_row: 引用用書誌の行。

    Returns:
        問題のメッセージの一覧（問題が無ければ空）。
    """
    problems = [
        f"{paper_id}: 引用用書誌の「{column}」が空です"
        for column in REQUIRED_VALUES
        if not bib_row.get(column)
    ]
    if bib_row.get("文献種別") not in ENTRY_TYPES:
        allowed = "／".join(ENTRY_TYPES)
        problems.append(f"{paper_id}: 文献種別が不正です（{allowed}）: {bib_row.get('文献種別')!r}")
    year = bib_row.get("年", "")
    if year and not YEAR_PATTERN.match(year):
        problems.append(f"{paper_id}: 年の書式が不正です: {year!r}")
    elif year and year != db_row.get("年"):
        problems.append(f"{paper_id}: 年が文献 DB と違います（DB {db_row.get('年')!r}）: {year!r}")
    pages = bib_row.get("ページ", "")
    if pages and not PAGES_PATTERN.match(pages):
        problems.append(f"{paper_id}: ページの書式が不正です（80-90 または 1471）: {pages!r}")
    for bib_column, db_column in (("題名", "タイトル"), ("誌名", "掲載誌")):
        value = bib_row.get(bib_column, "")
        if value and normalize_text(value) != normalize_text(db_row.get(db_column, "")):
            problems.append(
                f"{paper_id}: {bib_column}が文献 DB の{db_column}と違います"
                f"（DB {db_row.get(db_column)!r}）: {value!r}"
            )
    doi = bib_row.get("DOI", "")
    if doi and extract_doi(doi) != doi:
        problems.append(f"{paper_id}: DOI の書式が不正です（10.xxxx/... のみ）: {doi!r}")
    db_doi = extract_doi(db_row.get("DOI_URL", ""))
    if db_doi and db_doi.lower() != doi.lower():
        problems.append(f"{paper_id}: DOI が文献 DB と違います（DB {db_doi!r}）: {doi!r}")
    return problems


def check_consistency(
    db_rows: Sequence[dict[str, str]], bib_rows: Sequence[dict[str, str]]
) -> dict[str, dict[str, str]]:
    """文献 DB と引用用書誌の整合を検査し、ID → 引用用書誌の行を返す。

    Args:
        db_rows: 文献 DB の行。
        bib_rows: 引用用書誌の行。

    Returns:
        ID → 引用用書誌の行の辞書。

    Raises:
        BibliographyError: 不整合が 1 件以上ある場合（全件をまとめて報告する）。
    """
    db_index, problems = index_by_id(db_rows, "文献 DB")
    bib_index, bib_problems = index_by_id(bib_rows, "引用用書誌")
    problems.extend(bib_problems)
    for paper_id in sorted(db_index.keys() - bib_index.keys(), key=_id_number):
        problems.append(f"{paper_id}: 引用用書誌に行がありません")
    for paper_id in sorted(bib_index.keys() - db_index.keys(), key=_id_number):
        problems.append(f"{paper_id}: 文献 DB に無い ID です")
    for paper_id in sorted(db_index.keys() & bib_index.keys(), key=_id_number):
        problems.extend(check_entry(paper_id, db_index[paper_id], bib_index[paper_id]))
    if problems:
        raise BibliographyError(problems)
    return bib_index


def _id_number(paper_id: str) -> int:
    """S 番号の数値部分（並べ替え用）。"""
    return int(ID_PATTERN.match(paper_id).group(1))


def escape_bibtex(text: str) -> str:
    """BibTeX の値として安全になるよう特殊文字をエスケープする。"""
    return _BIBTEX_SPECIALS.sub(lambda match: _BIBTEX_ESCAPE_MAP[match.group(0)], text)


def format_entry(paper_id: str, row: dict[str, str]) -> str:
    """引用用書誌の 1 行を BibTeX の 1 エントリにする。

    題名は二重の波括弧で囲み、大文字小文字の変換（文頭のみ大文字化等）を防ぐ。
    DOI は検査済みの書式（空白・引用符・波括弧・「%」・バックスラッシュを含まない）で、
    pandoc がそのまま読めるためエスケープしない。

    Args:
        paper_id: 引用キーにする S 番号。
        row: 検査済みの引用用書誌の行。

    Returns:
        BibTeX のエントリ（末尾の改行なし）。
    """
    entry_type, container_field = ENTRY_TYPES[row["文献種別"]]
    fields = [
        ("author", escape_bibtex(row["著者"])),
        ("title", "{" + escape_bibtex(row["題名"]) + "}"),
        (container_field, escape_bibtex(row["誌名"])),
        ("year", row["年"]),
        ("volume", escape_bibtex(row["巻"])),
        ("number", escape_bibtex(row["号"])),
        ("pages", row["ページ"]),
        ("doi", row["DOI"]),
    ]
    lines = [f"@{entry_type}{{{paper_id},"]
    lines.extend(f"  {name} = {{{value}}}," for name, value in fields if value)
    lines.append("}")
    return "\n".join(lines)


def build_bibtex(db_rows: Sequence[dict[str, str]], bib_rows: Sequence[dict[str, str]]) -> str:
    """整合を検査したうえで、S 番号順に並べた .bib の本文を返す。

    Args:
        db_rows: 文献 DB の行。
        bib_rows: 引用用書誌の行。

    Returns:
        .bib の本文。

    Raises:
        BibliographyError: 不整合がある場合。
    """
    bib_index = check_consistency(db_rows, bib_rows)
    header = (
        "% 自動生成ファイル（scripts/make_thesis_bib.py）。手で編集しない。\n"
        "% 生成元: docs/04_archive/01_metadata/papers_database.csv,"
        " papers_bibliography.csv\n"
    )
    entries = [
        format_entry(paper_id, bib_index[paper_id])
        for paper_id in sorted(bib_index, key=_id_number)
    ]
    return header + "\n" + "\n\n".join(entries) + "\n"


def write_bibtex(
    output: Path,
    database_file: Path = DATABASE_FILE,
    bibliography_file: Path = BIBLIOGRAPHY_FILE,
) -> int:
    """2 つの CSV から .bib を生成して書き出し、エントリ数を返す。

    Args:
        output: 出力する .bib（既存のファイルは上書きする）。
        database_file: 文献 DB の CSV。
        bibliography_file: 引用用書誌の CSV。

    Returns:
        書き出したエントリ数。

    Raises:
        FileNotFoundError: CSV が無い場合。
        BibliographyError: CSV の形式の問題・不整合がある場合（.bib は書き出さない）。
    """
    db_rows = load_rows(database_file, DATABASE_COLUMNS)
    bib_rows = load_rows(bibliography_file, BIBLIOGRAPHY_COLUMNS)
    text = build_bibtex(db_rows, bib_rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    return len(bib_rows)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(description="文献データベースから論文用の .bib を生成する")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="出力する .bib（既定: thesis/build/references.bib）",
    )
    parser.add_argument("--database", type=Path, default=DATABASE_FILE, help="文献 DB の CSV")
    parser.add_argument(
        "--bibliography", type=Path, default=BIBLIOGRAPHY_FILE, help="引用用書誌の CSV"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """.bib を生成する。終了コードを返す（0: 成功、2: 失敗）。"""
    args = parse_args(argv)
    try:
        count = write_bibtex(args.output, args.database, args.bibliography)
    except FileNotFoundError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except BibliographyError as exc:
        print("エラー: 文献 DB と引用用書誌に問題があります", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_ERROR
    print(f".bib を生成しました（{count} 件）: {args.output}")
    return EXIT_OK


def _configure_utf8_output() -> None:
    """標準出力・標準エラーを UTF-8 にする（Windows で cp932 になり文字化けするのを防ぐ）。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    _configure_utf8_output()
    sys.exit(main())
