"""append_remaining_dgn.py（既存 GPKG に残りの DGN を追記する前処理）のテスト。

ogr2ogr は実行せず、`subprocess.run` を偽物に差し替えて、処理済みファイルの読み取り・
スキップ・失敗時の集計の分岐を確かめる。

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
        "src.preprocessing.append_remaining_dgn", tmp_path_factory.mktemp("import_cwd")
    )


def _make_dgn_files(directory: Path, names: list[str]) -> None:
    """空の DGN ファイルを作る。

    Args:
        directory: 作成先。
        names: ファイル名の一覧。
    """
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"")


class TestGetOgr2ogrPath:
    """get_ogr2ogr_path のテスト。"""

    @staticmethod
    def _patch(
        target: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        common_path: str | None,
        runnable: set[str],
    ) -> None:
        """ツールの探索と実行を差し替える。

        Args:
            target: 対象モジュール。
            monkeypatch: 差し替え用のフィクスチャ。
            common_path: 共通探索で見つかる ogr2ogr のパス。None なら見つからない。
            runnable: `--version` が成功する ogr2ogr のパス。
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
            return subprocess.CompletedProcess(command, 0, stdout="GDAL 3.10.0", stderr="")

        monkeypatch.setattr(target, "find_gdal_toolset", fake_find)
        monkeypatch.setattr(target.subprocess, "run", fake_run)

    def test_prefers_common_toolset(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """共通探索で見つかった ogr2ogr が動けば、それを使う。"""
        common = str(Path("qgis") / "ogr2ogr.exe")
        self._patch(target, monkeypatch, common, {common, "ogr2ogr"})

        assert target.get_ogr2ogr_path() == common

    def test_falls_back_to_path_when_common_is_missing(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """共通探索で見つからなければ、パス上の ogr2ogr を使う。"""
        self._patch(target, monkeypatch, None, {"ogr2ogr"})

        assert target.get_ogr2ogr_path() == "ogr2ogr"

    def test_exits_when_no_tool_runs(
        self, target: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """どの ogr2ogr も動かなければ終了する。"""
        self._patch(target, monkeypatch, str(Path("qgis") / "ogr2ogr.exe"), set())

        with pytest.raises(SystemExit, match="ogr2ogrが見つかりません"):
            target.get_ogr2ogr_path()


class TestGetProcessedFilesFromLog:
    """get_processed_files_from_log のテスト。"""

    def test_returns_empty_set_when_log_is_missing(
        self, target: ModuleType, tmp_path: Path
    ) -> None:
        """ログが無ければ空の集合を返す。"""
        assert target.get_processed_files_from_log(tmp_path / "missing.log") == set()

    def test_collects_files_followed_by_success_line(
        self, target: ModuleType, tmp_path: Path
    ) -> None:
        """初期化・追記の行の次が成功の行であるファイルだけを処理済みとする。"""
        log_file = tmp_path / "merge_vector_fixed.log"
        log_file.write_text(
            "\n".join(
                [
                    "2026-01-01 10:00:00,000 - INFO - 初期化: a_DC.dgn",
                    "2026-01-01 10:00:01,000 - INFO -   ✅ 初期化成功: a_DC.dgn",
                    "2026-01-01 10:00:02,000 - INFO - 追加中 (1/3): b_DC.dgn",
                    "2026-01-01 10:00:03,000 - INFO -   ✅ 追加成功",
                    "2026-01-01 10:00:04,000 - INFO - 追加中 (2/3): c_DC.dgn",
                    "2026-01-01 10:00:05,000 - WARNING -   ⚠️ 追加失敗（スキップ）: c_DC.dgn",
                    "2026-01-01 10:00:06,000 - INFO - 追加中 (3/3): d_DC.dgn",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        assert target.get_processed_files_from_log(log_file) == {"a_DC.dgn", "b_DC.dgn"}


class TestAppendRemainingFiles:
    """append_remaining_files のテスト。"""

    @staticmethod
    def _patch_run(
        target: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        failures: dict[str, BaseException] | None = None,
    ) -> list[tuple[list[str], Any]]:
        """ogr2ogr の実行を差し替え、コマンドとタイムアウト秒数を記録する。

        Args:
            target: 対象モジュール。
            monkeypatch: 差し替え用のフィクスチャ。
            failures: 入力 DGN のファイル名から、送出する例外への辞書。

        Returns:
            (コマンド, タイムアウト秒数) の記録。
        """
        calls: list[tuple[list[str], Any]] = []

        def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            """記録し、指定された入力だけ失敗させる。"""
            calls.append((command, kwargs.get("timeout")))
            name = Path(command[4]).name
            if failures and name in failures:
                raise failures[name]
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(target.subprocess, "run", fake_run)
        return calls

    def test_returns_error_when_output_is_missing(self, target: ModuleType, tmp_path: Path) -> None:
        """追記先の GPKG が無ければ error を返す。"""
        stats = target.append_remaining_files(
            tmp_path, "DC", tmp_path / "merge_DC.gpkg", "ogr2ogr", set(), set()
        )

        assert stats["status"] == "error"

    def test_complete_when_nothing_remains(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """スキップ・処理済みを除いて残りが無ければ、ogr2ogr を呼ばずに complete を返す。"""
        _make_dgn_files(tmp_path / "Vector_DC", ["a.dgn", "b.dgn"])
        output = tmp_path / "merge_DC.gpkg"
        output.write_bytes(b"gpkg")
        calls = self._patch_run(target, monkeypatch)

        stats = target.append_remaining_files(
            tmp_path / "Vector_DC", "DC", output, "ogr2ogr", {"a.dgn"}, {"b.dgn"}
        )

        assert stats == {"status": "complete", "processed": 0, "failed": 0}
        assert calls == []

    def test_appends_remaining_files_and_counts_outcomes(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """残りを追記し、成功・失敗・時間切れを分けて集計する。"""
        _make_dgn_files(tmp_path / "Vector_DC", ["a.dgn", "b.dgn", "c.dgn", "skip.dgn", "done.dgn"])
        output = tmp_path / "merge_DC.gpkg"
        output.write_bytes(b"gpkg")
        calls = self._patch_run(
            target,
            monkeypatch,
            failures={
                "b.dgn": subprocess.CalledProcessError(1, "ogr2ogr", stderr="x" * 400),
                "c.dgn": subprocess.TimeoutExpired("ogr2ogr", 60),
            },
        )

        stats = target.append_remaining_files(
            tmp_path / "Vector_DC",
            "DC",
            output,
            "ogr2ogr",
            {"skip.dgn"},
            {"done.dgn"},
            timeout_seconds=60,
        )

        assert [Path(command[4]).name for command, _ in calls] == ["a.dgn", "b.dgn", "c.dgn"]
        for command, timeout in calls:
            assert {"-update", "-append", "-makevalid", "-skipfailures"} <= set(command)
            assert command[3] == str(output)
            assert timeout == 60
        assert stats["status"] == "success"
        assert (
            stats["total_files"],
            stats["processed_files"],
            stats["failed_files"],
            stats["skipped_files"],
        ) == (3, 1, 1, 1)
        # エラー出力は先頭 300 文字に切り詰める
        assert stats["errors"] == [
            {"file": "b.dgn", "error": "x" * 300},
            {"file": "c.dgn", "error": "Timeout (60s)"},
        ]


class TestMain:
    """main のテスト。"""

    def test_returns_without_tool_search_when_input_is_missing(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """入力ディレクトリが無ければ、ツールを探さずに終える。"""

        def fail_if_called() -> str:
            """呼ばれたら失敗させる。"""
            raise AssertionError("ツールの探索に進んではいけない")

        monkeypatch.setattr(target, "get_ogr2ogr_path", fail_if_called)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "append_remaining_dgn",
                "DC",
                "--input-dir",
                str(tmp_path / "missing"),
                "--output",
                str(tmp_path / "merge_DC.gpkg"),
            ],
        )

        target.main()

    def test_merges_skip_lists_and_passes_processed_files(
        self, target: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """既定のスキップ一覧と --skip を合わせ、ログの処理済みファイルとともに渡す。"""
        input_dir = tmp_path / "Vector_DC"
        input_dir.mkdir()
        output = tmp_path / "merge_DC.gpkg"
        output.write_bytes(b"gpkg")
        log_file = tmp_path / "merge.log"
        log_file.write_text("x - INFO - 追加中 (1/1): done.dgn\n✅ 追加成功\n", encoding="utf-8")
        received: dict[str, Any] = {}

        def fake_append(*args: Any) -> dict[str, Any]:
            """受け取った引数を記録する。"""
            received["args"] = args
            return {
                "status": "success",
                "total_files": 0,
                "processed_files": 0,
                "failed_files": 0,
                "skipped_files": 0,
                "errors": [],
            }

        monkeypatch.setattr(target, "get_ogr2ogr_path", lambda: "ogr2ogr")
        monkeypatch.setattr(target, "append_remaining_files", fake_append)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "append_remaining_dgn",
                "DC",
                "--input-dir",
                str(input_dir),
                "--output",
                str(output),
                "--log-file",
                str(log_file),
                "--skip",
                "extra.dgn",
                "--timeout",
                "30",
            ],
        )

        target.main()

        args = received["args"]
        assert args[:4] == (input_dir, "DC", output, "ogr2ogr")
        assert args[4] == set(target.DEFAULT_SKIP_FILES) | {"extra.dgn"}
        assert args[5] == {"done.dgn"}
        assert args[6] == 30
