"""extract_geofabrik_roads_hanoi.py（Geofabrik の OSM PBF から道路を抽出するスクリプト）のテスト。

`ogr2ogr` / `ogrinfo` の実行（外部コマンド）は差し替え、コマンドの組み立て・既存出力の扱い・
件数の読み取り・サマリー JSON の保存を確かめる。サマリーの保存は共通モジュール
（`src.common.summary`）を使うので、NaN を含むときに保存前に止まることも確かめる。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from src.common import config, summary
from src.preprocessing import extract_geofabrik_roads_hanoi as target


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """一時ディレクトリをプロジェクトルートとみなし、入出力パスを用意する。"""
    monkeypatch.setattr(target, "PROJECT_ROOT", tmp_path)
    input_pbf = tmp_path / "raw" / "vietnam.osm.pbf"
    roi_path = tmp_path / "roi.shp"
    input_pbf.parent.mkdir(parents=True)
    input_pbf.write_bytes(b"pbf")
    roi_path.write_bytes(b"shp")
    return {
        "input_pbf": input_pbf,
        "roi_path": roi_path,
        "output_path": tmp_path / "roads" / "roads.gpkg",
        "summary_path": tmp_path / "out" / "summary.json",
    }


def _patch_gdal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, feature_count: int) -> list:
    """GDAL の探索・抽出・件数取得を差し替える。

    抽出の差し替えは、コマンドに含まれる出力パスへ中身のあるファイルを書き出す。

    Args:
        monkeypatch: pytest の monkeypatch。
        tmp_path: GDAL_DATA に見立てるディレクトリの親。
        feature_count: 件数取得が返す値。

    Returns:
        実行された抽出コマンドを記録するリスト。
    """
    executed: list[list[str]] = []

    def fake_run_extract_command(command: list[str], environment: dict[str, str]) -> None:
        executed.append(command)
        output_path = Path(command[command.index("GPKG") + 1])
        output_path.write_bytes(b"x" * 1024)

    monkeypatch.setattr(
        target,
        "find_gdal_toolset",
        lambda: (Path("ogr2ogr"), Path("ogrinfo"), tmp_path / "gdal_data"),
    )
    monkeypatch.setattr(target, "run_extract_command", fake_run_extract_command)
    monkeypatch.setattr(target, "extract_feature_count", lambda *args: feature_count)
    return executed


def _run(paths: dict[str, Path], overwrite: bool = False) -> None:
    """テスト用の引数で `run` を呼ぶ。"""
    target.run(
        input_pbf=paths["input_pbf"],
        roi_path=paths["roi_path"],
        output_path=paths["output_path"],
        summary_path=paths["summary_path"],
        layer_name="roads",
        overwrite=overwrite,
    )


class TestCommonModuleUsage:
    """共通モジュールの関数・定数を使っていることの確認。"""

    def test_uses_common_save_summary(self) -> None:
        assert target.save_summary is summary.save_summary

    def test_default_roi_path_is_common(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["extract_geofabrik_roads_hanoi.py"])
        assert target.parse_arguments().roi_path == config.DEFAULT_HANOI_ROI_PATH


class TestBuildExtractCommand:
    """ogr2ogr コマンドの組み立て。"""

    def test_filters_highway_and_clips_to_roi(self, tmp_path: Path) -> None:
        command = target.build_extract_command(
            ogr2ogr_path=Path("ogr2ogr"),
            input_pbf=tmp_path / "in.osm.pbf",
            roi_path=tmp_path / "roi.shp",
            output_path=tmp_path / "out.gpkg",
            layer_name="roads",
        )
        assert command[command.index("-where") + 1] == "highway IS NOT NULL"
        assert command[command.index("-clipsrc") + 1] == str(tmp_path / "roi.shp")
        assert command[command.index("-nln") + 1] == "roads"
        assert command[command.index("GPKG") + 1] == str(tmp_path / "out.gpkg")
        assert "lines" in command


class TestRemoveExistingOutput:
    """既存の出力ファイルの扱い。"""

    def test_does_nothing_when_absent(self, tmp_path: Path) -> None:
        target.remove_existing_output(tmp_path / "missing.gpkg", overwrite=False)

    def test_refuses_without_overwrite(self, tmp_path: Path) -> None:
        output_path = tmp_path / "out.gpkg"
        output_path.write_bytes(b"x")
        with pytest.raises(FileExistsError):
            target.remove_existing_output(output_path, overwrite=False)
        assert output_path.exists()

    def test_deletes_with_overwrite(self, tmp_path: Path) -> None:
        output_path = tmp_path / "out.gpkg"
        output_path.write_bytes(b"x")
        target.remove_existing_output(output_path, overwrite=True)
        assert not output_path.exists()


class TestExtractFeatureCount:
    """ogrinfo の出力からの件数の読み取り。"""

    def _patch_ogrinfo(self, monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
        """ogrinfo の実行を、指定した標準出力を返すものに差し替える。"""

        def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        monkeypatch.setattr(target.subprocess, "run", fake_run)

    def test_reads_feature_count(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self._patch_ogrinfo(monkeypatch, "Layer name: roads\nFeature Count: 123\n")
        count = target.extract_feature_count(Path("ogrinfo"), tmp_path / "out.gpkg", "roads", {})
        assert count == 123

    def test_raises_without_feature_count(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._patch_ogrinfo(monkeypatch, "Layer name: roads\n")
        with pytest.raises(ValueError, match="Feature Count"):
            target.extract_feature_count(Path("ogrinfo"), tmp_path / "out.gpkg", "roads", {})


class TestRun:
    """抽出処理全体（外部コマンドを差し替えて実行）。"""

    def test_writes_summary(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        executed = _patch_gdal(monkeypatch, tmp_path, feature_count=42)

        _run(paths)

        assert len(executed) == 1
        saved = json.loads(paths["summary_path"].read_text(encoding="utf-8"))
        # パスはプロジェクトルートからの相対パス（区切り文字は OS に従う）
        assert saved == {
            "input_pbf": str(Path("raw/vietnam.osm.pbf")),
            "roi_path": "roi.shp",
            "output_path": str(Path("roads/roads.gpkg")),
            "summary_path": str(Path("out/summary.json")),
            "layer_name": "roads",
            "feature_count": 42,
            "file_size_mb": 0.0,
        }

    def test_missing_input_stops_before_extract(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        executed = _patch_gdal(monkeypatch, tmp_path, feature_count=42)
        paths["input_pbf"].unlink()

        with pytest.raises(FileNotFoundError, match="OSM PBF"):
            _run(paths)
        assert executed == []

    def test_nan_in_summary_stops_without_saving(
        self, paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_gdal(monkeypatch, tmp_path, feature_count=42)
        monkeypatch.setattr(
            target, "build_summary", lambda **kwargs: {"file_size_mb": float("nan")}
        )

        with pytest.raises(ValueError, match="NaN"):
            _run(paths)
        assert not paths["summary_path"].exists()
