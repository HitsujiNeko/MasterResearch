"""Black Marble 取得 CLI（`fetch_black_marble_hanoi`）のテスト。

処理本体（`run` / `run_inspection`）は差し替え、引数がキーワード名どおりに
渡ることだけを確かめる。処理本体の挙動は `tests/preprocessing/black_marble/` で扱う。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.preprocessing import fetch_black_marble_hanoi as target


def test_main_passes_arguments_to_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """通常実行では全引数が run へ渡り、出力先が表示される。"""
    received: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> tuple[Path, Path]:
        received.update(kwargs)
        return tmp_path / "out.tif", tmp_path / "summary.json"

    def fail_inspection(**kwargs: Any) -> None:
        raise AssertionError("--inspect なしで run_inspection が呼ばれた")

    monkeypatch.setattr(target, "run", fake_run)
    monkeypatch.setattr(target, "run_inspection", fail_inspection)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fetch_black_marble_hanoi.py",
            "--year",
            "2022",
            "--bbox",
            "105.8",
            "21.0",
            "105.9",
            "21.1",
            "--output-path",
            str(tmp_path / "out.tif"),
            "--summary-path",
            str(tmp_path / "summary.json"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--token-file",
            str(tmp_path / "token.txt"),
            "--overwrite",
        ],
    )

    target.main()

    assert received == {
        "year": 2022,
        "roi_path": target.DEFAULT_HANOI_ROI_PATH,
        "bbox": [105.8, 21.0, 105.9, 21.1],
        "output_path": tmp_path / "out.tif",
        "summary_path": tmp_path / "summary.json",
        "cache_dir": tmp_path / "cache",
        "token_file": tmp_path / "token.txt",
        "overwrite": True,
    }
    captured = capsys.readouterr().out
    assert str(tmp_path / "out.tif") in captured
    assert str(tmp_path / "summary.json") in captured


def test_main_inspect_calls_run_inspection_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--inspect では run_inspection だけが呼ばれ、run は呼ばれない。"""
    received: dict[str, Any] = {}

    def fake_inspection(**kwargs: Any) -> None:
        received.update(kwargs)

    def fail_run(**kwargs: Any) -> None:
        raise AssertionError("--inspect で run が呼ばれた")

    monkeypatch.setattr(target, "run", fail_run)
    monkeypatch.setattr(target, "run_inspection", fake_inspection)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fetch_black_marble_hanoi.py",
            "--inspect",
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
    )

    target.main()

    assert received == {
        "year": target.LANDSAT_OBSERVATION_YEAR,
        "cache_dir": tmp_path / "cache",
        "roi_path": target.DEFAULT_HANOI_ROI_PATH,
        "bbox": None,
    }
