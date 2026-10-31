"""処理全体の実行（`black_marble.pipeline`）のテスト。

一覧取得・トークン解決・ダウンロードは差し替え、合成タイルで変換以降を通す。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
import rasterio

from src.preprocessing.black_marble import (
    listing,
    product,
    tile_grid,
)
from src.preprocessing.black_marble import pipeline as target
from tests.helpers import HANOI_ROI_BOUNDS, make_fake_build_target_area
from tests.preprocessing.black_marble.fake_tile import write_fake_tile


class TestValidateYear:
    """validate_year のテスト。"""

    def test_accepts_landsat_observation_year(self) -> None:
        """本研究の観測年は通す。"""
        target.validate_year(2023)

    def test_rejects_year_before_first_available(self) -> None:
        """提供開始年より前は弾く。"""
        with pytest.raises(ValueError, match="2012 年から"):
            target.validate_year(2011)

    def test_rejects_future_year(self) -> None:
        """未来の年は弾く。"""
        with pytest.raises(ValueError, match="未来の年"):
            target.validate_year(2999)


class TestResolveOutputPaths:
    """resolve_output_paths のテスト。"""

    def test_builds_default_paths_from_year(self) -> None:
        """既定では年つきのファイル名になる。"""
        output_path, summary_path = target.resolve_output_paths(2023, None, None)

        assert output_path.parent.name == "black_marble"
        assert output_path.name == "black_marble_vnp46a4_hanoi_2023.tif"
        assert summary_path.name == (
            "nighttime_lights_black_marble_vnp46a4_hanoi_2023_summary.json"
        )

    def test_trial_run_gets_distinct_filename(self) -> None:
        """試行実行では ROI 全域の成果物を上書きしないよう _trial を付ける。"""
        production_path, _ = target.resolve_output_paths(2023, None, None, is_trial=False)
        trial_path, _ = target.resolve_output_paths(2023, None, None, is_trial=True)

        assert trial_path.name == "black_marble_vnp46a4_hanoi_2023_trial.tif"
        assert trial_path != production_path


class TestRunGuards:
    """run の事前チェックのテスト（ネットワークへ出る前に止まること）。"""

    def test_rejects_unavailable_year_before_token_lookup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """提供年外の指定は、トークン解決より前に弾く。"""

        def fail_if_called(*args: Any, **kwargs: Any) -> str:
            """呼ばれた時点で失敗させる（提供年の検証は前段で終わる）。

            Raises:
                AssertionError: 呼ばれた場合。
            """
            raise AssertionError("提供年外の指定でトークン解決まで進んではいけない")

        monkeypatch.setattr(target, "resolve_earthdata_token", fail_if_called)

        with pytest.raises(ValueError, match="2012 年から"):
            target.run(
                year=2010,
                roi_path=tmp_path / "roi.shp",
                bbox=None,
                output_path=tmp_path / "out.tif",
                summary_path=tmp_path / "summary.json",
                cache_dir=tmp_path,
                token_file=None,
                overwrite=True,
            )

    def test_refuses_to_overwrite_existing_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """既存の出力があり --overwrite が無ければ、取得を始める前に止める。"""
        existing_output = tmp_path / "existing.tif"
        existing_output.write_bytes(b"IMPORTANT")
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area(HANOI_ROI_BOUNDS)
        )

        def fail_if_called(*args: Any, **kwargs: Any) -> str:
            """呼ばれた時点で失敗させる（上書き拒否は前段で終わる）。

            Raises:
                AssertionError: 呼ばれた場合。
            """
            raise AssertionError("既存ファイルがある場合はトークン解決まで進んではいけない")

        monkeypatch.setattr(target, "resolve_earthdata_token", fail_if_called)

        with pytest.raises(FileExistsError, match="--overwrite"):
            target.run(
                year=2023,
                roi_path=tmp_path / "roi.shp",
                bbox=None,
                output_path=existing_output,
                summary_path=tmp_path / "summary.json",
                cache_dir=tmp_path,
                token_file=None,
                overwrite=False,
            )

        assert existing_output.read_bytes() == b"IMPORTANT"

    def test_stops_when_multiple_tiles_are_required(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """複数タイルが要る範囲では、部分的な成果物を作らず明示的に止める。"""
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area((99.0, 19.0, 111.0, 31.0))
        )

        def fail_if_called(*args: Any, **kwargs: Any) -> str:
            """呼ばれた時点で失敗させる（複数タイル判定は前段で終わる）。

            Raises:
                AssertionError: 呼ばれた場合。
            """
            raise AssertionError("タイル結合が必要な場合はトークン解決まで進んではいけない")

        monkeypatch.setattr(target, "resolve_earthdata_token", fail_if_called)

        with pytest.raises(NotImplementedError, match="複数タイルの結合"):
            target.run(
                year=2023,
                roi_path=tmp_path / "roi.shp",
                bbox=None,
                output_path=tmp_path / "out.tif",
                summary_path=tmp_path / "summary.json",
                cache_dir=tmp_path,
                token_file=None,
                overwrite=True,
            )


class TestRunEndToEnd:
    """run の統合テスト（ネットワーク・HDF5 の取得はモックする）。

    `write_tile_geotiff` → `clip_multiband_to_area` →
    `build_multiband_pixel_statistics` → `build_summary` → `save_summary` →
    `log_results` の接合部を一度通す。とくに `log_results` は `save_summary` の
    後に走るため、ここが壊れていると 100MB 超のダウンロードと全処理を終えた
    あとで初めて失敗する。
    """

    # h28v06（経度 100-110E・緯度 20-30N）に収まり、合成タイルで複数画素になる範囲
    AREA_BOUNDS = (105.0, 21.0, 107.0, 23.0)

    def _install_fakes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        extra_fill_positions: tuple[tuple[int, int], ...] = (),
    ) -> None:
        """範囲組み立て・認証・一覧・ダウンロードを差し替える。

        Args:
            monkeypatch: pytest の monkeypatch フィクスチャ。
            extra_fill_positions: 合成タイルで追加の欠測にする画素の (行, 列)。
        """
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area(self.AREA_BOUNDS)
        )
        monkeypatch.setattr(target, "resolve_earthdata_token", lambda token_file=None: "t")

        file_name = "VNP46A4.A2023001.h28v06.002.2025162082259.h5"
        monkeypatch.setattr(
            target,
            "fetch_tile_listing",
            lambda year, headers: {
                "content": [
                    {
                        "name": file_name,
                        "downloadsLink": f"https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/{file_name}",
                        "size": 119818130,
                    }
                ]
            },
        )

        def fake_download(
            tile_file: listing.TileFile, destination_path: Path, headers: dict[str, str]
        ) -> Path:
            """配布物の代わりに合成 HDF5 タイルを置く。"""
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            write_fake_tile(
                destination_path,
                tile_grid.TileIndex(28, 6),
                extra_fill_positions=extra_fill_positions,
            )
            return destination_path

        monkeypatch.setattr(target, "download_tile", fake_download)

    def test_writes_raster_and_summary(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """取得から保存までを通しで実行し、GeoTIFF とサマリーが揃う。"""
        cache_dir = tmp_path / "cache"
        self._install_fakes(monkeypatch)

        output_path, summary_path = target.run(
            year=2023,
            roi_path=tmp_path / "roi.shp",
            bbox=None,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out_summary.json",
            cache_dir=cache_dir,
            token_file=None,
            overwrite=True,
        )

        with rasterio.open(output_path) as raster:
            assert raster.count == len(product.BAND_DEFINITIONS)
            assert raster.crs.to_epsg() == 4326
            assert raster.descriptions == tuple(
                band.output_name for band in product.BAND_DEFINITIONS
            )
            assert raster.nodata == product.OUTPUT_NODATA

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["dataset_key"] == "black_marble_vnp46a4"
        assert summary["year"] == 2023
        assert summary["tiles"] == ["h28v06"]
        assert summary["pixel_stats"]["covers_requested_area"] is True

    def test_summary_records_saturation_for_radiance_bands(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """飽和指標が放射輝度バンドにだけ入る（log_results が参照するキーの担保）。

        log_results は save_summary の後に走るため、参照キーがずれていると
        全処理を終えた後に KeyError で落ちる。ここで実際に通しておく。
        """
        self._install_fakes(monkeypatch)

        _, summary_path = target.run(
            year=2023,
            roi_path=tmp_path / "roi.shp",
            bbox=None,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out_summary.json",
            cache_dir=tmp_path / "cache",
            token_file=None,
            overwrite=True,
        )

        saturation = json.loads(summary_path.read_text(encoding="utf-8"))["pixel_stats"][
            "saturation"
        ]
        expected = {
            band.output_name for band in product.BAND_DEFINITIONS if band.is_saturation_target
        }
        assert set(saturation) == expected
        for indicators in saturation.values():
            # log_results が参照するキーが揃っていること
            assert {
                "p99_to_max_ratio",
                "pixels_at_max",
                "pixels_near_max",
                "ratio_near_max",
            } <= set(indicators)

    def test_applies_scale_factor_from_the_tile(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """タイル属性のスケール係数が最終出力まで反映される。"""
        self._install_fakes(monkeypatch)

        output_path, _ = target.run(
            year=2023,
            roi_path=tmp_path / "roi.shp",
            bbox=None,
            output_path=tmp_path / "out.tif",
            summary_path=tmp_path / "out_summary.json",
            cache_dir=tmp_path / "cache",
            token_file=None,
            overwrite=True,
        )

        with rasterio.open(output_path) as raster:
            # 合成タイルは第1バンドを 10 で埋めており、scale_factor は 1.0
            values = raster.read(1)
            assert values[values != product.OUTPUT_NODATA].max() == pytest.approx(10.0)

    def test_missing_pixels_inside_area_lower_the_valid_ratio(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """範囲内に欠測があれば有効画素率が 1 を下回り、警告も出る。

        実データ（Hanoi ROI 2023）は有効画素率 1.0000 だったため、この経路は
        実行時に一度も踏んでいない。有効域を ROI 全体と同一視しないための
        指標が欠測時にも正しく動くことを、ここで固定する。

        合成タイルは 20×20（1 画素 0.5°）で、(行 15, 列 11) の画素中心は
        経度 105.75 / 緯度 22.25 にあたり、対象範囲の内側に入る。
        """
        self._install_fakes(monkeypatch, extra_fill_positions=((15, 11),))

        with caplog.at_level(logging.WARNING):
            _, summary_path = target.run(
                year=2023,
                roi_path=tmp_path / "roi.shp",
                bbox=None,
                output_path=tmp_path / "out.tif",
                summary_path=tmp_path / "out_summary.json",
                cache_dir=tmp_path / "cache",
                token_file=None,
                overwrite=True,
            )

        pixel_stats = json.loads(summary_path.read_text(encoding="utf-8"))["pixel_stats"]
        assert pixel_stats["valid_pixels"] == pixel_stats["roi_pixels"] - 1
        assert pixel_stats["valid_pixel_ratio"] < 1.0
        # 範囲は覆えているが値が欠けている、という区別が付くこと
        assert pixel_stats["covers_requested_area"] is True
        assert "無効画素" in caplog.text

    def test_trial_run_marks_summary_and_uses_distinct_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """BBOX 指定時は試行実行として記録され、既定パスに _trial が付く。"""
        self._install_fakes(monkeypatch)
        monkeypatch.setattr(target, "DEFAULT_OUTPUT_ROOT", tmp_path / "gis" / "black_marble")

        output_path, summary_path = target.run(
            year=2023,
            roi_path=tmp_path / "roi.shp",
            bbox=[105.0, 21.0, 106.0, 22.0],
            output_path=None,
            summary_path=tmp_path / "trial_summary.json",
            cache_dir=tmp_path / "cache",
            token_file=None,
            overwrite=True,
        )

        assert output_path.name == "black_marble_vnp46a4_hanoi_2023_trial.tif"
        assert output_path.is_relative_to(tmp_path)
        assert json.loads(summary_path.read_text(encoding="utf-8"))["is_trial_run"] is True


class TestRunInspection:
    """run_inspection のテスト。"""

    def test_finds_cached_tile_by_actual_file_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """glob パターンが実際の配布ファイル名に一致する。

        実名は `VNP46A4.A2023001.h28v06.002.2025162082259.h5` で、生成日時部分は
        事前に分からない。パターンがずれるとキャッシュ済みでも「無い」と言われる。
        """
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area(HANOI_ROI_BOUNDS)
        )
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        tile_path = cache_dir / "VNP46A4.A2023001.h28v06.002.2025162082259.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6))

        target.run_inspection(
            year=2023, cache_dir=cache_dir, roi_path=tmp_path / "roi.shp", bbox=None
        )

        printed = json.loads(capsys.readouterr().out)
        assert "NearNadir_Composite_Snow_Free" in printed["datasets"]

    def test_raises_with_search_pattern_when_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """見つからない場合は、探索したパターンを添えて例外にする。"""
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area(HANOI_ROI_BOUNDS)
        )

        with pytest.raises(FileNotFoundError, match="h28v06"):
            target.run_inspection(
                year=2023, cache_dir=tmp_path, roi_path=tmp_path / "roi.shp", bbox=None
            )

    def test_warns_when_multiple_tiles_are_required(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """複数タイルが要る範囲では、先頭だけを見ることを明示する。

        取得側は同じ状況を NotImplementedError で止めるため、検査側だけ黙って
        絞ると挙動が食い違う。
        """
        monkeypatch.setattr(
            target, "build_target_area", make_fake_build_target_area((99.0, 19.0, 111.0, 31.0))
        )

        with caplog.at_level(logging.WARNING):
            with pytest.raises(FileNotFoundError):
                target.run_inspection(
                    year=2023, cache_dir=tmp_path, roi_path=tmp_path / "roi.shp", bbox=None
                )

        assert "先頭" in caplog.text
