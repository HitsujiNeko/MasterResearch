"""Black Marble 取得 CLI（`fetch_black_marble_hanoi`）のテスト。

処理本体（`run` / `run_inspection`）は差し替え、引数がキーワード名どおりに
渡ることだけを確かめる。差し替えた関数は任意の引数を受け取るため、受け取った
引数は本物の関数のシグネチャと照合する。処理本体の挙動は
`tests/preprocessing/black_marble/` で扱う。
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from src.preprocessing import fetch_black_marble_hanoi as target
from src.preprocessing.black_marble import pipeline


def run_main_with_fake_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str]
) -> dict[str, Any]:
    """run を差し替えて main を実行し、run が受け取った引数を返す。

    Args:
        monkeypatch: pytest の monkeypatch。
        tmp_path: 差し替えた run が返す出力先の置き場所。
        argv: スクリプト名を除くコマンドライン引数。

    Returns:
        run が受け取ったキーワード引数。
    """
    received: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> tuple[Path, Path]:
        received.update(kwargs)
        return tmp_path / "out.tif", tmp_path / "summary.json"

    def fail_inspection(**kwargs: Any) -> None:
        raise AssertionError("--inspect なしで run_inspection が呼ばれた")

    monkeypatch.setattr(target, "run", fake_run)
    monkeypatch.setattr(target, "run_inspection", fail_inspection)
    monkeypatch.setattr("sys.argv", ["fetch_black_marble_hanoi.py", *argv])

    target.main()

    # 本物の run と引数名が合わない、または必須引数が足りなければ TypeError になる
    inspect.signature(pipeline.run).bind(**received)
    return received


def test_main_passes_arguments_to_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """通常実行では全引数が run へ渡り、出力先が表示される。"""
    received = run_main_with_fake_run(
        monkeypatch,
        tmp_path,
        [
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


def test_main_passes_defaults_to_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """引数なしでは CLI の既定値が run へ渡る。"""
    received = run_main_with_fake_run(monkeypatch, tmp_path, [])

    assert received == {
        "year": target.LANDSAT_OBSERVATION_YEAR,
        "roi_path": target.DEFAULT_HANOI_ROI_PATH,
        "bbox": None,
        "output_path": None,
        "summary_path": None,
        "cache_dir": target.DEFAULT_CACHE_DIR,
        "token_file": None,
        "overwrite": False,
    }


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
    # 本物の run_inspection と引数名が合わない、または必須引数が足りなければ TypeError になる
    inspect.signature(pipeline.run_inspection).bind(**received)
