"""terminology.py（用語の表記揺れ検出）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.doc_checks.terminology import check_terminology


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_no_violations_for_canonical_terms(tmp_path: Path) -> None:
    """規約表記どおりであれば違反は検出しない。"""
    content = (
        "LSTは30°Cである。\n"
        "分析シナリオは Satellite Only / Limited / Full の3種類。\n"
        "GBAをLimitedシナリオの建物主ソースとする。\n"
        "CRSはEPSG:4326、WGS84、VN-2000を使用する。\n"
        "RQ1とRQ2とRQ3を検証する。\n"
    )
    _write(tmp_path / "docs" / "a.md", content)

    result = check_terminology(project_root=tmp_path)

    assert result == []


def test_detects_celsius_variants(tmp_path: Path) -> None:
    """℃・度C・数値付きケルビンをLST単位の表記揺れとして検出する。"""
    _write(tmp_path / "docs" / "a.md", "30℃、30度C、30ケルビン\n")

    result = check_terminology(project_root=tmp_path)

    categories = {v.category for v in result}
    matched = {v.matched_text for v in result}
    assert categories == {"LST単位"}
    assert matched == {"℃", "度C", "30ケルビン"}


def test_does_not_flag_bare_kelvin_mention_without_number(tmp_path: Path) -> None:
    """数値を伴わない「ケルビン」への言及（他システムの単位説明等）は検出しない。"""
    content = "原典実装のLSTバンドはケルビンだが、本研究では摂氏に変換して出力する。\n"
    _write(tmp_path / "docs" / "a.md", content)

    result = check_terminology(project_root=tmp_path)

    assert result == []


def test_does_not_flag_rq_or_epsg_inside_snake_case_identifiers(tmp_path: Path) -> None:
    """スネークケースのファイル名・識別子に含まれるrq3・EPSG4326は検出しない。"""
    content = (
        "- `src/analysis/analysis_rq3_satellite_only.py`\n"
        "`data/gis/boundaries/hanoi/hanoi_ROI_EPSG4326.shp`\n"
        "`rq1_variable_importance.md`: RQ1結果\n"
    )
    _write(tmp_path / "docs" / "a.md", content)

    result = check_terminology(project_root=tmp_path)

    assert result == []


def test_detects_satellite_only_case_variant(tmp_path: Path) -> None:
    """Satellite Onlyの大文字小文字の揺れを検出する。"""
    _write(tmp_path / "docs" / "a.md", "satellite only シナリオで分析する。\n")

    result = check_terminology(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].category == "シナリオ名"
    assert result[0].matched_text == "satellite only"


def test_detects_limited_lowercase_before_scenario_word(tmp_path: Path) -> None:
    """「シナリオ」直前のLimited/Fullの大文字小文字の揺れを検出する。"""
    _write(tmp_path / "docs" / "a.md", "limitedシナリオで採用する。\n")

    result = check_terminology(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].category == "シナリオ名"
    assert result[0].matched_text == "limited"


def test_does_not_flag_full_or_limited_outside_scenario_context(tmp_path: Path) -> None:
    """「シナリオ」に続かないLimited/Fullは通常の英単語として扱い検出しない。"""
    _write(tmp_path / "docs" / "a.md", "This is a full stack limited example.\n")

    result = check_terminology(project_root=tmp_path)

    assert result == []


def test_detects_epsg_space_variant(tmp_path: Path) -> None:
    """EPSG:NNNN形式からの逸脱（空白区切り等）を検出する。"""
    _write(tmp_path / "docs" / "a.md", "CRSはEPSG 4326を使用する。\n")

    result = check_terminology(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].category == "座標系"
    assert result[0].matched_text == "EPSG 4326"


def test_detects_wgs84_space_variant(tmp_path: Path) -> None:
    """WGS84の空白混入を検出する。"""
    _write(tmp_path / "docs" / "a.md", "座標系はWGS 84を使用する。\n")

    result = check_terminology(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].category == "座標系"
    assert result[0].matched_text == "WGS 84"


def test_detects_vn2000_missing_hyphen(tmp_path: Path) -> None:
    """VN-2000のハイフン欠落を検出する。"""
    _write(tmp_path / "docs" / "a.md", "測量データはVN2000を使用する。\n")

    result = check_terminology(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].category == "座標系"
    assert result[0].matched_text == "VN2000"


def test_detects_rq_space_variant(tmp_path: Path) -> None:
    """RQ表記の半角スペース混入を検出する。"""
    _write(tmp_path / "docs" / "a.md", "RQ 1について検証する。\n")

    result = check_terminology(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].category == "RQ表記"
    assert result[0].matched_text == "RQ 1"


def test_excludes_archive_directory(tmp_path: Path) -> None:
    """04_archive/配下は先行研究の引用文脈のため対象外。"""
    _write(tmp_path / "docs" / "04_archive" / "S1.md", "30℃、RQ 1、EPSG 4326\n")

    result = check_terminology(project_root=tmp_path)

    assert result == []


def test_reports_correct_line_number(tmp_path: Path) -> None:
    """検出行の行番号を正しく報告する。"""
    _write(tmp_path / "docs" / "a.md", "1行目\n2行目\n30℃を検出\n")

    result = check_terminology(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].line == 3
