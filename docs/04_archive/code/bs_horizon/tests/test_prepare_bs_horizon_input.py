"""prepare_bs_horizon_input.py（BSHorizon入力CSV生成）のテスト。"""

from __future__ import annotations

from pathlib import Path

from src.preprocessing.prepare_bs_horizon_input import strip_header


def test_strip_header_removes_first_line_only(tmp_path: Path) -> None:
    """先頭のヘッダー行のみが除かれ、データ行はそのまま出力される。"""
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_text(
        "id,x,y,elevation\n0,581302.1,2333408.8,10.86\n1,581337.0,2333402.9,11.07\n",
        encoding="utf-8",
    )

    written_count = strip_header(input_path, output_path)

    assert written_count == 2
    assert output_path.read_text(encoding="utf-8") == (
        "0,581302.1,2333408.8,10.86\n1,581337.0,2333402.9,11.07\n"
    )


def test_strip_header_empty_data_yields_empty_output(tmp_path: Path) -> None:
    """ヘッダーのみのCSVからは空の出力を生成する。"""
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_text("id,x,y,elevation\n", encoding="utf-8")

    written_count = strip_header(input_path, output_path)

    assert written_count == 0
    assert output_path.read_text(encoding="utf-8") == ""


def test_strip_header_preserves_crlf_line_endings(tmp_path: Path) -> None:
    """入力がCRLF改行の場合、出力もCRLF改行のまま保持する。"""
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_bytes(b"id,x,y,elevation\r\n0,581302.1,2333408.8,10.86\r\n")

    strip_header(input_path, output_path)

    assert output_path.read_bytes() == b"0,581302.1,2333408.8,10.86\r\n"
