"""merge_vector_fixed.py（DGN を種類別の GeoPackage に統合する前処理）のテスト。

ogr2ogr / ogrinfo は実行せず、`subprocess.run` を偽物に差し替えて、ツールの選び方・
コマンドの組み立て・失敗時の集計の分岐を確かめる。

対象モジュールは import した時点で作業ディレクトリに `data/output/` を作り、ログの
設定を行う。リポジトリ直下を汚さないよう、一時ディレクトリで import する。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.helpers import import_with_contained_side_effects


@pytest.fixture(scope="module")
def target(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    """import 時の副作用を一時ディレクトリに閉じ込めて対象モジュールを読み込む。"""
    return import_with_contained_side_effects(
        "src.preprocessing.merge_vector_fixed", tmp_path_factory.mktemp("import_cwd")
    )


def _completed(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """成功した `subprocess.run` の戻り値を作る。"""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _make_dgn_files(directory: Path, names: list[str]) -> list[Path]:
    """空の DGN ファイルを作る。

    Args:
        directory: 作成先。
        names: ファイル名の一覧。

    Returns:
        作成したパスの一覧。
    """
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / name for name in names]
    for path in paths:
        path.write_bytes(b"")
    return paths


class TestGetOgrinfoPath:
    """get_ogrinfo_path のテスト。"""

    def test_uses_sibling_ogrinfo_exe_when_present(
        self, target: ModuleType, tmp_path: Path
    ) -> None:
        """ogr2ogr.exe と同じ場所に ogrinfo.exe があれば、それを使う。"""
        (tmp_path / "ogrinfo.exe").write_bytes(b"")

        result = target.get_ogrinfo_path(str(tmp_path / "ogr2ogr.exe"))

        assert result == str(tmp_path / "ogrinfo.exe")

    def test_falls_back_to_name_replacement_without_sibling(
        self, target: ModuleType, tmp_path: Path
    ) -> None:
        """同じ場所に ogrinfo.exe が無ければ、パスの ogr2ogr を ogrinfo に置き換える。"""
        result = target.get_ogrinfo_path(str(tmp_path / "ogr2ogr.exe"))

        assert result == str(tmp_path / "ogrinfo.exe")

    def test_bare_command_name_maps_to_ogrinfo(self, target: ModuleType) -> None:
        """パスの無いコマンド名 ogr2ogr には ogrinfo を対応させる。"""
        assert target.get_ogrinfo_path("ogr2ogr") == "ogrinfo"


class TestHasDgnv8Support:
    """has_dgnv8_support のテスト。"""

    def test_true_when_formats_list_dgnv8(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ogrinfo --formats の出力に DGNv8 があれば True を返す。"""
        monkeypatch.setattr(
            target.subprocess, "run", lambda *args, **kwargs: _completed("  DGNV8 -vector-")
        )

        assert target.has_dgnv8_support("ogrinfo") is True

    def test_false_when_formats_lack_dgnv8(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """出力に DGNv8 が無ければ False を返す。"""
        monkeypatch.setattr(
            target.subprocess, "run", lambda *args, **kwargs: _completed("  DGN -vector-")
        )

        assert target.has_dgnv8_support("ogrinfo") is False

    def test_false_when_ogrinfo_fails(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ogrinfo を実行できなければ False を返す。"""

        def failing(*args: Any, **kwargs: Any) -> None:
            """実行ファイルが無いときの例外を送出する。"""
            raise FileNotFoundError("ogrinfo")

        monkeypatch.setattr(target.subprocess, "run", failing)

        assert target.has_dgnv8_support("ogrinfo") is False


class TestGetOgr2ogrPath:
    """get_ogr2ogr_path のテスト。"""

    @staticmethod
    def _patch_tools(
        target: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        common_path: str | None,
        runnable: set[str],
        dgnv8_capable: set[str],
    ) -> None:
        """ツールの探索・実行・DGNv8 判定を差し替える。

        Args:
            target: 対象モジュール。
            monkeypatch: 差し替え用のフィクスチャ。
            common_path: 共通探索で見つかる ogr2ogr のパス。None なら見つからない。
            runnable: `--version` が成功する ogr2ogr のパス。
            dgnv8_capable: DGNv8 に対応する ogrinfo のパス。
        """

        def fake_find() -> tuple[Path, Path, Path]:
            """共通探索の結果を返す。"""
            if common_path is None:
                raise FileNotFoundError("QGIS が見つかりません")
            return Path(common_path), Path("gdalwarp"), Path("gdal_translate")

        def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            """登録した実行ファイルだけ成功させる。"""
            if command[0] not in runnable:
                raise FileNotFoundError(command[0])
            return _completed("GDAL 3.10.0")

        monkeypatch.setattr(target, "find_gdal_toolset", fake_find)
        monkeypatch.setattr(target.subprocess, "run", fake_run)
        monkeypatch.setattr(target, "get_ogrinfo_path", lambda path: f"{path}:ogrinfo")
        monkeypatch.setattr(target, "has_dgnv8_support", lambda path: path in dgnv8_capable)

    def test_prefers_common_toolset_with_dgnv8(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """共通探索で見つかった ogr2ogr が DGNv8 に対応していれば、それを使う。"""
        common = str(Path("qgis") / "ogr2ogr.exe")
        self._patch_tools(target, monkeypatch, common, {common, "ogr2ogr"}, {f"{common}:ogrinfo"})

        assert target.get_ogr2ogr_path() == common

    def test_falls_back_to_path_when_common_lacks_dgnv8(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """共通探索の ogr2ogr が DGNv8 非対応なら、パス上の ogr2ogr を使う。"""
        common = str(Path("qgis") / "ogr2ogr.exe")
        self._patch_tools(target, monkeypatch, common, {common, "ogr2ogr"}, {"ogr2ogr:ogrinfo"})

        assert target.get_ogr2ogr_path() == "ogr2ogr"

    def test_accepts_tool_without_dgnv8_when_not_required(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DGNv8 を必須としなければ、非対応の ogr2ogr でも使う。"""
        common = str(Path("qgis") / "ogr2ogr.exe")
        self._patch_tools(target, monkeypatch, common, {common}, set())

        assert target.get_ogr2ogr_path(require_dgnv8=False) == common

    def test_exits_when_no_dgnv8_tool(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DGNv8 対応の ogr2ogr が無ければ、その旨を示して終了する。"""
        self._patch_tools(target, monkeypatch, None, {"ogr2ogr"}, set())

        with pytest.raises(SystemExit, match="DGNv8"):
            target.get_ogr2ogr_path()

    def test_exits_when_no_tool_at_all(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ogr2ogr がどこにも無ければ、GDAL の確認を促して終了する。"""
        self._patch_tools(target, monkeypatch, None, set(), set())

        with pytest.raises(SystemExit, match="GDALのインストール確認"):
            target.get_ogr2ogr_path(require_dgnv8=False)


class TestMergeToGeopackage:
    """merge_to_geopackage のテスト。"""

    @staticmethod
    def _patch_run(
        target: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        failures: dict[str, BaseException] | None = None,
        create_output: bool = True,
    ) -> list[list[str]]:
        """ogr2ogr の実行を差し替え、受け取ったコマンドを記録する。

        Args:
            target: 対象モジュール。
            monkeypatch: 差し替え用のフィクスチャ。
            failures: 入力 DGN のファイル名から、送出する例外への辞書。
            create_output: 初期化のコマンドで出力 GPKG を作るか。

        Returns:
            受け取ったコマンドの記録。
        """
        commands: list[list[str]] = []

        def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            """記録し、指定された入力だけ失敗させる。"""
            commands.append(command)
            name = Path(command[4]).name
            if failures and name in failures:
                raise failures[name]
            if create_output and "-update" not in command:
                Path(command[3]).write_bytes(b"gpkg")
            return _completed()

        monkeypatch.setattr(target.subprocess, "run", fake_run)
        return commands

    def test_returns_no_files_when_directory_is_empty(
        self, target: ModuleType, tmp_path: Path
    ) -> None:
        """DGN が 1 つも無ければ、何もせず no_files を返す。"""
        (tmp_path / "Vector_DC").mkdir()

        stats = target.merge_to_geopackage(tmp_path / "Vector_DC", "DC", tmp_path, "ogr2ogr")

        assert stats == {"status": "no_files", "file_count": 0}

    def test_skips_existing_output_when_requested(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """既存 GPKG のスキップを指定すると、ogr2ogr を呼ばずに skipped を返す。"""
        _make_dgn_files(tmp_path / "Vector_DC", ["a.dgn", "b.dgn"])
        (tmp_path / "merge_DC.gpkg").write_bytes(b"old")
        commands = self._patch_run(target, monkeypatch)

        stats = target.merge_to_geopackage(
            tmp_path / "Vector_DC", "DC", tmp_path, "ogr2ogr", skip_existing=True
        )

        assert stats == {"status": "skipped", "file_count": 2}
        assert commands == []
        assert (tmp_path / "merge_DC.gpkg").read_bytes() == b"old"

    def test_initializes_with_first_file_and_appends_the_rest(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """名前順の先頭で GPKG を作り、残りを修復つきで追記して success を返す。"""
        _make_dgn_files(tmp_path / "Vector_DC", ["b.dgn", "a.dgn", "c.dgn"])
        (tmp_path / "merge_DC.gpkg").write_bytes(b"old")
        commands = self._patch_run(target, monkeypatch)

        stats = target.merge_to_geopackage(tmp_path / "Vector_DC", "DC", tmp_path, "ogr2ogr")

        assert [Path(command[4]).name for command in commands] == ["a.dgn", "b.dgn", "c.dgn"]
        assert "-update" not in commands[0]
        assert {"-makevalid", "-skipfailures"} <= set(commands[0])
        for command in commands[1:]:
            assert {"-update", "-append", "-makevalid", "-skipfailures"} <= set(command)
        assert stats["status"] == "success"
        assert (stats["total_files"], stats["processed_files"], stats["failed_files"]) == (3, 3, 0)
        assert stats["output_file"] == "merge_DC.gpkg"
        # 既存の GPKG は消してから作り直す
        assert (tmp_path / "merge_DC.gpkg").read_bytes() == b"gpkg"

    def test_append_failures_give_partial_success(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """追記の失敗・時間切れは記録して続け、partial_success を返す。"""
        _make_dgn_files(tmp_path / "Vector_DC", ["a.dgn", "b.dgn", "c.dgn"])
        self._patch_run(
            target,
            monkeypatch,
            failures={
                "b.dgn": subprocess.CalledProcessError(1, "ogr2ogr", stderr="broken geometry"),
                "c.dgn": subprocess.TimeoutExpired("ogr2ogr", 300),
            },
        )

        stats = target.merge_to_geopackage(tmp_path / "Vector_DC", "DC", tmp_path, "ogr2ogr")

        assert stats["status"] == "partial_success"
        assert (stats["processed_files"], stats["failed_files"]) == (1, 2)
        assert stats["errors"] == [
            {"file": "b.dgn", "error": "broken geometry"},
            {"file": "c.dgn", "error": "Timeout (300s)"},
        ]

    def test_stops_when_initialization_fails(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """先頭ファイルでの初期化に失敗したら、追記に進まず failed を返す。"""
        _make_dgn_files(tmp_path / "Vector_DC", ["a.dgn", "b.dgn"])
        commands = self._patch_run(
            target,
            monkeypatch,
            failures={"a.dgn": subprocess.CalledProcessError(1, "ogr2ogr", stderr="no driver")},
        )

        stats = target.merge_to_geopackage(tmp_path / "Vector_DC", "DC", tmp_path, "ogr2ogr")

        assert stats["status"] == "failed"
        assert stats["errors"] == [{"file": "a.dgn", "error": "no driver"}]
        assert len(commands) == 1

    def test_failed_when_output_is_not_created(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """コマンドが成功しても GPKG ができていなければ failed を返す。"""
        _make_dgn_files(tmp_path / "Vector_DC", ["a.dgn"])
        self._patch_run(target, monkeypatch, create_output=False)

        stats = target.merge_to_geopackage(tmp_path / "Vector_DC", "DC", tmp_path, "ogr2ogr")

        assert stats["status"] == "failed"


class TestMain:
    """main のテスト。"""

    @staticmethod
    def _run_main(
        target: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: list[str]
    ) -> tuple[list[bool], list[str]]:
        """ツール探索と統合処理を差し替えて main を実行する。

        Args:
            target: 対象モジュール。
            monkeypatch: 差し替え用のフィクスチャ。
            tmp_path: 入出力のルート。
            extra: 追加のコマンドライン引数。

        Returns:
            (ツール探索に渡した DGNv8 必須の指定, 統合処理に渡した種類) の記録。
        """
        required: list[bool] = []
        merged: list[str] = []

        def fake_get_path(require_dgnv8: bool = True) -> str:
            """DGNv8 必須の指定を記録する。"""
            required.append(require_dgnv8)
            return "ogr2ogr"

        def fake_merge(
            in_dir: Path, suffix: str, output: Path, ogr2ogr: str, skip: bool
        ) -> dict[str, Any]:
            """統合した種類を記録する。"""
            merged.append(suffix)
            return {"status": "skipped", "file_count": 0}

        monkeypatch.setattr(target, "get_ogr2ogr_path", fake_get_path)
        monkeypatch.setattr(target, "merge_to_geopackage", fake_merge)
        argv = ["merge_vector_fixed", "--root", str(tmp_path), "--output", str(tmp_path / "out")]
        monkeypatch.setattr(sys, "argv", argv + extra)
        target.main()
        return required, merged

    def test_all_suffixes_require_dgnv8_and_skip_missing_directories(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全種類を処理するときは TV を含むため DGNv8 を必須とし、無い種類は飛ばす。"""
        (tmp_path / "Vector_DC").mkdir()
        (tmp_path / "Vector_TV").mkdir()

        required, merged = self._run_main(target, monkeypatch, tmp_path, [])

        assert required == [True]
        assert merged == ["DC", "TV"]
        assert (tmp_path / "out").is_dir()

    def test_single_non_tv_suffix_does_not_require_dgnv8(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TV 以外の 1 種類だけを処理するときは DGNv8 を必須としない。"""
        (tmp_path / "Vector_DC").mkdir()

        required, merged = self._run_main(target, monkeypatch, tmp_path, ["--suffix", "DC"])

        assert required == [False]
        assert merged == ["DC"]
