"""terminology.py（用語の表記揺れ検出）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.doc_checks.terminology import _code_block_mask, check_terminology


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_no_violations_for_canonical_terms(tmp_path: Path) -> None:
    """規約表記どおりであれば違反は検出しない。"""
    content = (
        "LSTは30°Cである。\n"
        "分析シナリオは衛星データのみ／衛星＋公開GISデータ。\n"
        "英語表記は Satellite only / Satellite + open GIS。\n"
        "GBAを衛星＋公開GISデータのシナリオの建物主ソースとする。\n"
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
    """Satellite Onlyの大文字小文字の揺れを旧呼び名として検出する。"""
    _write(tmp_path / "docs" / "a.md", "satellite only シナリオで分析する。\n")

    result = check_terminology(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].category == "シナリオ名（旧呼び名）"
    assert result[0].matched_text == "satellite only"


def test_detects_limited_lowercase_before_scenario_word(tmp_path: Path) -> None:
    """「シナリオ」直前のLimited/Fullの大文字小文字の揺れを旧呼び名として検出する。"""
    _write(tmp_path / "docs" / "a.md", "limitedシナリオで採用する。\n")

    result = check_terminology(project_root=tmp_path)

    assert len(result) == 1
    assert result[0].category == "シナリオ名（旧呼び名）"
    assert result[0].matched_text == "limited"


def test_detects_old_scenario_names_in_prose(tmp_path: Path) -> None:
    """本文に残った旧呼び名（Satellite Only・Limited シナリオ・Fullシナリオ）を検出する。"""
    content = "Satellite Only と比べる。\nLimited シナリオで採用する。\nFullシナリオは未実施。\n"
    _write(tmp_path / "docs" / "a.md", content)

    result = check_terminology(project_root=tmp_path)

    assert [(v.line, v.category, v.matched_text) for v in result] == [
        (1, "シナリオ名（旧呼び名）", "Satellite Only"),
        (2, "シナリオ名（旧呼び名）", "Limited"),
        (3, "シナリオ名（旧呼び名）", "Full"),
    ]


def test_does_not_flag_new_english_scenario_name(tmp_path: Path) -> None:
    """新しい英語表記「Satellite only」は大文字小文字を区別して許容する。"""
    _write(tmp_path / "docs" / "a.md", "英語表記は Satellite only とする。\n")

    result = check_terminology(project_root=tmp_path)

    assert result == []


def test_does_not_flag_old_scenario_names_inside_inline_code(tmp_path: Path) -> None:
    """インラインコード内（出力値の引用・識別子）の旧呼び名は検出しない。"""
    content = (
        '結果 JSON の `"scenario": "Satellite Only"` と `Limited − Satellite Only` を引用する。\n'
        "テーマ ``Full`` シナリオ表示の切り替え。\n"
    )
    _write(tmp_path / "docs" / "a.md", content)

    result = check_terminology(project_root=tmp_path)

    assert result == []


def test_detects_old_scenario_name_outside_inline_code_on_same_line(tmp_path: Path) -> None:
    """同じ行にインラインコードがあっても、その外側の旧呼び名は検出する。"""
    _write(tmp_path / "docs" / "a.md", "`limited` を指す Satellite Only の記述。\n")

    result = check_terminology(project_root=tmp_path)

    assert [v.matched_text for v in result] == ["Satellite Only"]


def test_excludes_submitted_gis_ideas_documents_only_for_scenario_names(tmp_path: Path) -> None:
    """提出済み資料（GIS_IDEAS_*）ではシナリオ名だけを対象外とし、他の用語は検出する。"""
    poster = tmp_path / "docs" / "03_results" / "GIS_IDEAS_poster.md"
    _write(poster, "Satellite Only と Limited シナリオ。30℃\n")

    result = check_terminology(project_root=tmp_path)

    assert [(v.category, v.matched_text) for v in result] == [("LST単位", "℃")]


def test_does_not_flag_old_scenario_names_inside_fenced_code_block(tmp_path: Path) -> None:
    """フェンス付きコードブロック内の旧呼び名は検出せず、ブロックの外は検出する。"""
    content = (
        "```json\n"
        '{"scenario": "Satellite Only"}\n'
        "Limited シナリオ\n"
        "```\n"
        "~~~\n"
        "Full シナリオ\n"
        "~~~\n"
        "Satellite Only の記述。\n"
    )
    _write(tmp_path / "docs" / "a.md", content)

    result = check_terminology(project_root=tmp_path)

    assert [(v.line, v.matched_text) for v in result] == [(8, "Satellite Only")]


def test_code_block_closes_only_with_same_fence_char_and_length(tmp_path: Path) -> None:
    """閉じフェンスは開始と同じ記号・同じ長さ以上・info string なしの行だけとする。"""
    content = (
        "```\n"  # 1: 開始（```）
        "~~~\n"  # 2: 記号が違うので閉じない
        "````md\n"  # 3: info string 付きなので閉じない
        "Limited シナリオ\n"  # 4: ブロック内
        "```\n"  # 5: 閉じる
        "Full シナリオ\n"  # 6: ブロック外
        "````md\n"  # 7: 開始（````）
        "```\n"  # 8: 短いので閉じない
        "Limited シナリオ\n"  # 9: ブロック内
        "````\n"  # 10: 閉じる
        "Satellite Only\n"  # 11: ブロック外
    )
    _write(tmp_path / "docs" / "a.md", content)

    result = check_terminology(project_root=tmp_path)

    assert [(v.line, v.matched_text) for v in result] == [(6, "Full"), (11, "Satellite Only")]


def test_code_block_mask_follows_commonmark_boundaries() -> None:
    """フェンス判定の境界（info string・タブ字下げ・閉じフェンスの字下げと空白）を確認する。"""
    cases = {
        # バッククォートの開始フェンスは info string にバッククォートを含むとフェンスでない
        "backtick_info_with_backtick": (["``` a`b", "x"], [False, False]),
        # ~~~ の info string はバッククォートを含んでもフェンスとみなす
        "tilde_info_with_backtick": (["~~~ a`b", "x", "~~~", "y"], [True, True, True, False]),
        # タブ字下げはフェンスではない
        "tab_indent": (["\t```", "x"], [False, False]),
        # 閉じフェンスは字下げ3文字まで・後ろの半角空白とタブを許す
        "close_indented_with_trailing_ws": (
            ["```", "x", "   ``` \t", "y"],
            [True, True, True, False],
        ),
        # 長い ~~~~ でも閉じる
        "longer_tilde_close": (["~~~", "x", "~~~~", "y"], [True, True, True, False]),
        # 全角空白が続く行は閉じフェンスではない
        "fullwidth_space_does_not_close": (["```", "```　", "x"], [True, True, True]),
    }
    for name, (lines, expected) in cases.items():
        assert _code_block_mask(lines) == expected, name


def test_indented_four_spaces_is_not_a_fence(tmp_path: Path) -> None:
    """字下げ4文字以上の ``` はフェンスとみなさず、後続の本文を検査する。"""
    _write(tmp_path / "docs" / "a.md", "    ```\nFull シナリオ\n")

    result = check_terminology(project_root=tmp_path)

    assert [(v.line, v.matched_text) for v in result] == [(2, "Full")]


def test_unclosed_fence_continues_to_end_of_document(tmp_path: Path) -> None:
    """閉じていないコードブロックは CommonMark どおり文書末まで続くとみなす（仕様）。"""
    _write(tmp_path / "docs" / "a.md", "Full シナリオ\n```\nコード\n\nLimited シナリオ\n")

    result = check_terminology(project_root=tmp_path)

    assert [(v.line, v.matched_text) for v in result] == [(1, "Full")]


def test_fenced_code_block_does_not_hide_other_categories(tmp_path: Path) -> None:
    """コードブロック内でも、シナリオ名以外の用語は従来どおり検査する。"""
    _write(tmp_path / "docs" / "a.md", "```text\n30℃\n```\n")

    result = check_terminology(project_root=tmp_path)

    assert [(v.category, v.matched_text) for v in result] == [("LST単位", "℃")]


def test_detects_old_scenario_name_after_unclosed_backtick(tmp_path: Path) -> None:
    """閉じていないバックティックはインラインコードとみなさず、その後ろも検査する。"""
    _write(tmp_path / "docs" / "a.md", "`limited の説明として Satellite Only を使う。\n")

    result = check_terminology(project_root=tmp_path)

    assert [v.matched_text for v in result] == ["Satellite Only"]


def test_backtick_runs_of_different_length_are_not_inline_code(tmp_path: Path) -> None:
    """開始と終了のバックティック列の長さが違う場合はインラインコードとみなさず検査する。"""
    content = "本文 ``Satellite Only``` を比較する。\n本文 ```Limited シナリオ`` を比較する。\n"
    _write(tmp_path / "docs" / "a.md", content)

    result = check_terminology(project_root=tmp_path)

    assert [v.matched_text for v in result] == ["Satellite Only", "Limited"]


def test_inline_code_may_contain_backtick_run_of_other_length(tmp_path: Path) -> None:
    """長さの違うバックティックを中に含むインラインコードは、全体を対象外とする。"""
    _write(tmp_path / "docs" / "a.md", "``Satellite Only ` Full シナリオ`` を引用する。\n")

    result = check_terminology(project_root=tmp_path)

    assert result == []


def test_detects_both_names_in_juxtaposed_scenario_phrase(tmp_path: Path) -> None:
    """「Limited・Full シナリオ」のような並記では両方の旧呼び名を検出する。"""
    _write(tmp_path / "docs" / "a.md", "Limited・Full シナリオに含める。Limited / Fullシナリオ。\n")

    result = check_terminology(project_root=tmp_path)

    assert [v.matched_text for v in result] == ["Limited", "Full", "Limited", "Full"]


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
