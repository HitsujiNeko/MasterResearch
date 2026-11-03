"""scripts/make_thesis_bib.py（文献 DB → 論文用 .bib の生成）のテスト。

対象は ``src`` パッケージ外のスクリプトのため、ファイルパスを指定して読み込む。
整合検査・エスケープ・エントリ整形・書き出しは一時ファイルで検証し、最後にリポジトリの
実データ（文献 DB と引用用書誌）が整合していることを確かめる。pandoc での読み込みと
参考文献リストの書式は tests/scripts/test_build_thesis.py で検証する。
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "make_thesis_bib.py"


def _load_target() -> ModuleType:
    """対象スクリプトをモジュールとして読み込む。"""
    spec = importlib.util.spec_from_file_location("make_thesis_bib", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


target = _load_target()


def _db_row(paper_id: str = "S1", **overrides: str) -> dict[str, str]:
    """文献 DB の 1 行（検査に使う列のみ）を作る。"""
    row = {
        "ID": paper_id,
        "年": "2020",
        "タイトル": "Google Earth Engine open-source code for LST",
        "掲載誌": "Remote Sensing",
        "DOI_URL": "https://doi.org/10.3390/rs12091471",
    }
    row.update(overrides)
    return row


def _bib_row(paper_id: str = "S1", **overrides: str) -> dict[str, str]:
    """引用用書誌の 1 行を作る。"""
    row = {
        "ID": paper_id,
        "文献種別": "article",
        "著者": "Ermida, Sofia L. and Trigo, Isabel F.",
        "題名": "Google Earth Engine Open-Source Code for LST",
        "誌名": "Remote Sensing",
        "年": "2020",
        "巻": "12",
        "号": "9",
        "ページ": "1471",
        "DOI": "10.3390/rs12091471",
        "照合元": "Crossref; PDF",
        "照合日": "2026-11-03",
    }
    row.update(overrides)
    return row


def _problems(db_rows: list[dict], bib_rows: list[dict]) -> list[str]:
    """整合検査の問題一覧を返す（問題が無ければ空）。"""
    try:
        target.check_consistency(db_rows, bib_rows)
    except target.BibliographyError as exc:
        return exc.problems
    return []


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """行を UTF-8（BOM なし）の CSV に書く。"""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# 正規化・エスケープ
# ---------------------------------------------------------------------------
def test_normalize_text_ignores_case_symbols_and_spaces():
    """大文字小文字・記号・空白の差は照合で無視する。"""
    left = target.normalize_text("Da Nang City, Vietnam,  Using Cloud-Computing")
    right = target.normalize_text("da nang city vietnam using cloud computing")
    assert left == right


def test_normalize_text_keeps_non_ascii_letters():
    """アクセント付き文字は除去しない（別の語への衝突を防ぐ）。"""
    assert target.normalize_text("Göttsche") == "göttsche"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://doi.org/10.1016/j.uclim.2023.101787", "10.1016/j.uclim.2023.101787"),
        ("10.1111/j.2041-210X.2009.00001.x", "10.1111/j.2041-210X.2009.00001.x"),
        ("https://www.mdpi.com/2072-4292/12/9/1471", None),
        ("記載なし", None),
        ("", None),
    ],
)
def test_extract_doi(value, expected):
    """DOI を含む URL から DOI を取り出し、含まない値は None にする。"""
    assert target.extract_doi(value) == expected


def test_escape_bibtex_escapes_special_characters():
    """LaTeX の特殊文字をエスケープし、バックスラッシュの二重置換を起こさない。"""
    escaped = target.escape_bibtex(r"A & B 50% {x} $1 #2 a_b ~ ^ \ ")
    assert escaped == (
        r"A \& B 50\% \{x\} \$1 \#2 a\_b \textasciitilde{} \textasciicircum{}"
        r" \textbackslash{} "
    )


def test_escape_bibtex_keeps_non_ascii_text():
    """非 ASCII 文字（アクセント・漢字）はそのまま残す。"""
    assert target.escape_bibtex("Toloşi 益田晴恵") == "Toloşi 益田晴恵"


# ---------------------------------------------------------------------------
# エントリの整形
# ---------------------------------------------------------------------------
def test_format_entry_uses_id_as_key_and_protects_title():
    """引用キーは S 番号、題名は二重の波括弧で大文字小文字を保護する。"""
    entry = target.format_entry("S1", _bib_row())
    assert entry.startswith("@article{S1,\n")
    assert "  title = {{Google Earth Engine Open-Source Code for LST}},\n" in entry
    assert "  journal = {Remote Sensing},\n" in entry
    assert "  pages = {1471},\n" in entry
    assert "  doi = {10.3390/rs12091471},\n" in entry
    assert entry.endswith("\n}")


def test_format_entry_omits_empty_fields():
    """空の欄（号・DOI 等）は出力しない。"""
    entry = target.format_entry("S5", _bib_row("S5", 号="", DOI=""))
    assert "number" not in entry
    assert "doi" not in entry


def test_format_entry_escapes_container_title():
    """誌名の「&」はエスケープする（BibTeX では特殊文字のため）。"""
    entry = target.format_entry("S18", _bib_row("S18", 誌名="Landscape & Environment"))
    assert "  journal = {Landscape \\& Environment},\n" in entry


def test_format_entry_inproceedings_uses_booktitle():
    """会議録の掲載先は booktitle に書く。"""
    entry = target.format_entry("S1", _bib_row(文献種別="inproceedings"))
    assert entry.startswith("@inproceedings{S1,")
    assert "  booktitle = {Remote Sensing}," in entry


# ---------------------------------------------------------------------------
# 整合検査
# ---------------------------------------------------------------------------
def test_check_consistency_accepts_matching_rows():
    """題名の大文字小文字の差だけなら整合とみなし、ID → 行を返す。"""
    result = target.check_consistency([_db_row()], [_bib_row()])
    assert list(result) == ["S1"]


def test_check_consistency_accepts_db_without_doi():
    """文献 DB に DOI が無い（URL・記載なし）場合は DOI を突合しない。"""
    db = _db_row(DOI_URL="記載なし")
    assert _problems([db], [_bib_row(DOI="")]) == []


def test_check_consistency_reports_missing_and_extra_ids():
    """DB にあって書誌に無い ID、書誌にあって DB に無い ID を報告する。"""
    problems = _problems([_db_row("S1"), _db_row("S2")], [_bib_row("S1"), _bib_row("S3")])
    assert "S2: 引用用書誌に行がありません" in problems
    assert "S3: 文献 DB に無い ID です" in problems


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"年": "2019"}, "年が文献 DB と違います"),
        ({"年": "2020年"}, "年の書式が不正です"),
        ({"題名": "A different paper"}, "題名が文献 DB のタイトルと違います"),
        ({"誌名": "Sensors"}, "誌名が文献 DB の掲載誌と違います"),
        ({"DOI": "10.3390/rs00000000"}, "DOI が文献 DB と違います"),
        ({"DOI": "https://doi.org/10.3390/rs12091471"}, "DOI の書式が不正です"),
        ({"文献種別": "book"}, "文献種別が不正です"),
        ({"ページ": "80–90"}, "ページの書式が不正です"),
        ({"著者": ""}, "「著者」が空です"),
    ],
)
def test_check_consistency_reports_entry_problems(overrides, fragment):
    """1 件分の書式違反・DB との不一致を報告する。"""
    problems = _problems([_db_row()], [_bib_row(**overrides)])
    assert any(fragment in problem for problem in problems), problems


def test_check_consistency_reports_duplicate_and_malformed_ids():
    """ID の重複・書式違反を報告する。"""
    problems = _problems([_db_row(), _db_row()], [_bib_row(), _bib_row("X1")])
    assert "文献 DB: ID が重複しています: S1" in problems
    assert "引用用書誌: ID の書式が不正です（S+番号）: 'X1'" in problems


def test_check_consistency_collects_all_problems():
    """問題は最初の 1 件で止めず、まとめて報告する。"""
    problems = _problems(
        [_db_row("S1"), _db_row("S2")],
        [_bib_row("S1", 年="2019"), _bib_row("S2", 著者="")],
    )
    assert len(problems) == 2


# ---------------------------------------------------------------------------
# CSV の読み込み
# ---------------------------------------------------------------------------
def test_load_rows_rejects_missing_columns(tmp_path):
    """列名の誤り（「ページ」→「頁」）は、欄が黙って空になる前に失敗させる。"""
    row = _bib_row()
    row["頁"] = row.pop("ページ")
    path = tmp_path / "bib.csv"
    _write_csv(path, [row])
    with pytest.raises(target.BibliographyError) as info:
        target.load_rows(path, target.BIBLIOGRAPHY_COLUMNS)
    assert info.value.problems == ["bib.csv: 列がありません: ページ"]


def test_load_rows_reports_row_with_extra_values(tmp_path):
    """列数がヘッダーより多い行（引用符漏れ）は、行番号つきで報告する（例外で止まらない）。"""
    path = tmp_path / "db.csv"
    path.write_text(
        "ID,年,タイトル,掲載誌,DOI_URL\nS1,2020,A, B and C,Remote Sensing,\n",
        encoding="utf-8",
    )
    with pytest.raises(target.BibliographyError) as info:
        target.load_rows(path, target.DATABASE_COLUMNS)
    assert info.value.problems[0].startswith("db.csv: 2 行目の列数がヘッダーより多い")


def test_load_rows_rejects_header_only_csv(tmp_path):
    """データの行が無い CSV は失敗させる（空の .bib を黙って作らない）。"""
    path = tmp_path / "db.csv"
    path.write_text("ID,年,タイトル,掲載誌,DOI_URL\n", encoding="utf-8")
    with pytest.raises(target.BibliographyError, match="データの行がありません"):
        target.load_rows(path, target.DATABASE_COLUMNS)


def test_load_rows_strips_values_and_fills_short_rows(tmp_path):
    """値の前後の空白を除き、列が足りない行の欠けた値は空文字にする。"""
    path = tmp_path / "db.csv"
    path.write_text("ID,年,タイトル,掲載誌,DOI_URL\n S1 ,2020,T\n", encoding="utf-8")
    rows = target.load_rows(path, target.DATABASE_COLUMNS)
    assert rows == [{"ID": "S1", "年": "2020", "タイトル": "T", "掲載誌": "", "DOI_URL": ""}]


# ---------------------------------------------------------------------------
# .bib の生成・書き出し
# ---------------------------------------------------------------------------
def test_build_bibtex_orders_entries_by_id_number():
    """エントリは S 番号の数値順（S2 → S10）に並べる。"""
    db_rows = [_db_row("S10"), _db_row("S2")]
    bib_rows = [_bib_row("S10"), _bib_row("S2")]
    text = target.build_bibtex(db_rows, bib_rows)
    assert text.index("@article{S2,") < text.index("@article{S10,")
    assert text.startswith("% 自動生成ファイル")


def test_write_bibtex_writes_file(tmp_path):
    """CSV（BOM 付きも可）から .bib を書き出し、件数を返す。"""
    database = tmp_path / "db.csv"
    bibliography = tmp_path / "bib.csv"
    _write_csv(database, [_db_row()])
    bibliography.write_text("\ufeff", encoding="utf-8")
    with bibliography.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(_bib_row()))
        writer.writeheader()
        writer.writerow(_bib_row())
    output = tmp_path / "out" / "references.bib"
    assert target.write_bibtex(output, database, bibliography) == 1
    assert "@article{S1," in output.read_text(encoding="utf-8")


def test_write_bibtex_does_not_write_on_inconsistency(tmp_path):
    """不整合があれば .bib を書き出さない（古い内容で上書きもしない）。"""
    database = tmp_path / "db.csv"
    bibliography = tmp_path / "bib.csv"
    _write_csv(database, [_db_row()])
    _write_csv(bibliography, [_bib_row(年="2019")])
    output = tmp_path / "references.bib"
    with pytest.raises(target.BibliographyError):
        target.write_bibtex(output, database, bibliography)
    assert not output.exists()


def test_main_reports_problems_and_returns_error(tmp_path, capsys):
    """不整合は標準エラーに一覧し、終了コード 2 を返す。"""
    database = tmp_path / "db.csv"
    bibliography = tmp_path / "bib.csv"
    _write_csv(database, [_db_row()])
    _write_csv(bibliography, [_bib_row(年="2019")])
    argv = [
        "--output",
        str(tmp_path / "references.bib"),
        "--database",
        str(database),
        "--bibliography",
        str(bibliography),
    ]
    assert target.main(argv) == target.EXIT_ERROR
    err = capsys.readouterr().err
    assert "問題があります" in err
    assert "S1: 年が文献 DB と違います" in err


def test_main_reports_missing_file(tmp_path, capsys):
    """CSV が無ければ終了コード 2 を返す。"""
    argv = ["--database", str(tmp_path / "none.csv"), "--output", str(tmp_path / "x.bib")]
    assert target.main(argv) == target.EXIT_ERROR
    assert "ファイルがありません" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# リポジトリの実データ
# ---------------------------------------------------------------------------
def test_repository_bibliography_is_consistent_with_database():
    """文献 DB の全論文に引用用書誌があり、年・題名・誌名・DOI が一致する。

    文献 DB に論文を追加したときは、引用用書誌（papers_bibliography.csv）にも原典で
    照合した行を足す必要がある。このテストが落ちたら不足・不一致の行を直す。
    """
    db_rows = target.load_rows(target.DATABASE_FILE, target.DATABASE_COLUMNS)
    bib_rows = target.load_rows(target.BIBLIOGRAPHY_FILE, target.BIBLIOGRAPHY_COLUMNS)
    assert _problems(db_rows, bib_rows) == []
    assert len(bib_rows) == len(db_rows)
