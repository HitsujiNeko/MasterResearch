"""organize_dgn.py（DGN ファイルを種類別ディレクトリへ振り分ける前処理）のテスト。

実データ（測量 GIS の DGN）は使わず、一時ディレクトリに空の `.dgn` ファイルを置いて
振り分け・上書き・試行実行の分岐を確かめる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.preprocessing import organize_dgn as target


def _make_source(root: Path) -> dict[str, Path]:
    """領域フォルダ 2 つに DGN ファイルを置いたソースを作る。

    Args:
        root: ソースのルート。

    Returns:
        ファイル名から作成したパスへの辞書。
    """
    files = {
        "a_CS.dgn": root / "region_b" / "a_CS.dgn",
        "b_DC.dgn": root / "region_a" / "b_DC.dgn",
        "c_TV.dgn": root / "region_a" / "c_TV.dgn",
        # 対象外: 未知のサフィックス・拡張子違い・領域フォルダの外
        "d_XX.dgn": root / "region_a" / "d_XX.dgn",
        "e_CS.txt": root / "region_a" / "e_CS.txt",
        "f_CS.dgn": root / "f_CS.dgn",
    }
    for name, path in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"source:{name}", encoding="utf-8")
    return files


class TestFindDgnFiles:
    """find_dgn_files のテスト。"""

    def test_yields_known_suffixes_in_region_folders_only(self, tmp_path: Path) -> None:
        """領域フォルダ内の既知サフィックスの DGN だけを、サフィックスとともに返す。"""
        files = _make_source(tmp_path)

        found = sorted(target.find_dgn_files(tmp_path))

        assert found == sorted(
            [("CS", files["a_CS.dgn"]), ("DC", files["b_DC.dgn"]), ("TV", files["c_TV.dgn"])]
        )

    def test_returns_nothing_for_empty_source(self, tmp_path: Path) -> None:
        """領域フォルダが無ければ何も返さない。"""
        assert list(target.find_dgn_files(tmp_path)) == []


class TestEnsureTargets:
    """ensure_targets のテスト。"""

    def test_creates_one_directory_per_suffix(self, tmp_path: Path) -> None:
        """サフィックスごとに Vector_<サフィックス> を作り、その対応を返す。"""
        targets = target.ensure_targets(tmp_path / "out")

        assert set(targets) == set(target.SUFFIXES)
        for suffix, path in targets.items():
            assert path == tmp_path / "out" / f"Vector_{suffix}"
            assert path.is_dir()


class TestCopyFiles:
    """copy_files のテスト。"""

    def test_copies_each_file_into_its_suffix_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """各 DGN を対応する Vector_* へコピーし、件数を要約に出す。"""
        source = tmp_path / "source"
        _make_source(source)
        out = tmp_path / "out"

        target.copy_files(source, out, dry_run=False, overwrite=False, only_suffix=None)

        assert (out / "Vector_CS" / "a_CS.dgn").read_text(encoding="utf-8") == "source:a_CS.dgn"
        assert (out / "Vector_DC" / "b_DC.dgn").is_file()
        assert (out / "Vector_TV" / "c_TV.dgn").is_file()
        assert not (out / "Vector_CS" / "f_CS.dgn").exists()
        assert "total_found=3, copied=3, skipped=0" in capsys.readouterr().out

    def test_skips_existing_file_without_overwrite(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """同名ファイルがあり上書き指定が無ければ、元のファイルを残してスキップする。"""
        source = tmp_path / "source"
        _make_source(source)
        existing = tmp_path / "out" / "Vector_CS" / "a_CS.dgn"
        existing.parent.mkdir(parents=True)
        existing.write_text("existing", encoding="utf-8")

        target.copy_files(
            source, tmp_path / "out", dry_run=False, overwrite=False, only_suffix=None
        )

        assert existing.read_text(encoding="utf-8") == "existing"
        assert "total_found=3, copied=2, skipped=1" in capsys.readouterr().out

    def test_overwrites_existing_file_when_requested(self, tmp_path: Path) -> None:
        """上書き指定があれば、同名ファイルをソースの内容で置き換える。"""
        source = tmp_path / "source"
        _make_source(source)
        existing = tmp_path / "out" / "Vector_CS" / "a_CS.dgn"
        existing.parent.mkdir(parents=True)
        existing.write_text("existing", encoding="utf-8")

        target.copy_files(source, tmp_path / "out", dry_run=False, overwrite=True, only_suffix=None)

        assert existing.read_text(encoding="utf-8") == "source:a_CS.dgn"

    def test_dry_run_copies_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """試行実行ではコピーせず、予定だけを表示する。"""
        source = tmp_path / "source"
        _make_source(source)
        out = tmp_path / "out"

        target.copy_files(source, out, dry_run=True, overwrite=False, only_suffix=None)

        assert list(out.rglob("*.dgn")) == []
        captured = capsys.readouterr().out
        assert "WOULD COPY" in captured
        assert "copied=3" in captured

    def test_only_suffix_limits_the_target_kind(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """種類を指定すると、そのサフィックスの DGN だけを処理する。"""
        source = tmp_path / "source"
        _make_source(source)
        out = tmp_path / "out"

        target.copy_files(source, out, dry_run=False, overwrite=False, only_suffix="DC")

        assert [path.name for path in out.rglob("*.dgn")] == ["b_DC.dgn"]
        assert "total_found=1, copied=1" in capsys.readouterr().out


class TestMain:
    """main のテスト。"""

    def test_exits_when_source_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ソースが存在しなければ、何も作らずに終了する。"""
        out = tmp_path / "out"
        monkeypatch.setattr(
            sys,
            "argv",
            ["organize_dgn", "--source", str(tmp_path / "missing"), "--target", str(out)],
        )

        with pytest.raises(SystemExit, match="ソースが存在しません"):
            target.main()
        assert not out.exists()

    def test_passes_options_to_copy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """コマンドライン引数の値をそのまま振り分け処理へ渡す。"""
        source = tmp_path / "source"
        source.mkdir()
        calls: list[tuple] = []
        monkeypatch.setattr(target, "copy_files", lambda *args: calls.append(args))
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "organize_dgn",
                "--source",
                str(source),
                "--target",
                str(tmp_path / "out"),
                "--dry-run",
                "--overwrite",
                "--suffix",
                "GT",
            ],
        )

        target.main()

        assert calls == [(source, tmp_path / "out", True, True, "GT")]
