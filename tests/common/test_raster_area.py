"""raster_area.py（取得対象範囲の組み立てと被覆判定）のテスト。

ネットワークアクセスは伴わせず、BBOX の妥当性検証・ROI/試行実行の分岐・
被覆判定を対象とする。
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from src.common import raster_area as target
from tests.conftest import HANOI_ROI_BOUNDS


class TestValidateBbox:
    """validate_bbox のテスト。"""

    def test_accepts_valid_bbox(self) -> None:
        """正しい BBOX は通す。"""
        target.validate_bbox([105.8, 21.0, 105.9, 21.06])

    def test_rejects_reversed_longitude(self) -> None:
        """経度の min > max は空の結果になるため弾く。"""
        with pytest.raises(ValueError, match="最小値は最大値より小さい"):
            target.validate_bbox([105.9, 21.0, 105.8, 21.06])

    def test_rejects_reversed_latitude(self) -> None:
        """緯度の min > max も同様に弾く。"""
        with pytest.raises(ValueError, match="最小値は最大値より小さい"):
            target.validate_bbox([105.8, 21.06, 105.9, 21.0])

    def test_rejects_zero_extent(self) -> None:
        """幅または高さが 0 の BBOX も弾く。"""
        with pytest.raises(ValueError, match="最小値は最大値より小さい"):
            target.validate_bbox([105.8, 21.0, 105.8, 21.06])

    def test_rejects_out_of_range_coordinates(self) -> None:
        """経緯度の値域を外れる指定を弾く。"""
        with pytest.raises(ValueError, match="値域"):
            target.validate_bbox([105.8, 21.0, 185.0, 21.06])

    def test_rejects_wrong_length(self) -> None:
        """要素数が 4 でない場合は弾く。"""
        with pytest.raises(ValueError, match="4 要素"):
            target.validate_bbox([105.8, 21.0, 105.9])


class TestBuildTargetArea:
    """build_target_area のテスト。"""

    def test_bbox_produces_trial_area(self, tmp_path: Path) -> None:
        """BBOX 指定時は試行実行フラグが立つ。"""
        roi_path = tmp_path / "dummy.shp"
        roi_path.write_bytes(b"")

        area_gdf, is_trial, _ = target.build_target_area(roi_path, [105.8, 21.0, 105.9, 21.06])

        assert is_trial is True
        assert area_gdf.crs.to_string() == "EPSG:4326"
        assert tuple(area_gdf.total_bounds) == (105.8, 21.0, 105.9, 21.06)

    def test_returns_resolved_roi_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """記録用に、読み込みへ使ったのと同じ解決済みパスを返す。

        生の引数を記録すると、プロジェクトルート以外から相対パスで実行したときに
        「読み込みは成功したのに記録されたパスは別物」という状態になる。
        """
        roi_gdf = gpd.GeoDataFrame(geometry=[box(*HANOI_ROI_BOUNDS)], crs="EPSG:4326")
        monkeypatch.setattr(
            target, "load_roi_geometry", lambda path: (roi_gdf, roi_gdf.geometry.iloc[0])
        )
        # 検証対象はパス解決だけで、読み込みはモックしている。実 ROI（Git 管理外）に
        # 依存させないため、リポジトリに常在する追跡ファイルを相対パスとして使う
        relative_path = Path("pyproject.toml")

        _, _, resolved_roi_path = target.build_target_area(relative_path, None)

        assert resolved_roi_path.is_absolute()
        assert resolved_roi_path.name == "pyproject.toml"

    def test_roi_path_is_used_when_bbox_is_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """BBOX 未指定なら ROI を読み込み、試行実行フラグは立たない。"""
        roi_gdf = gpd.GeoDataFrame(geometry=[box(*HANOI_ROI_BOUNDS)], crs="EPSG:4326")
        monkeypatch.setattr(
            target, "load_roi_geometry", lambda path: (roi_gdf, roi_gdf.geometry.iloc[0])
        )
        roi_path = tmp_path / "roi.shp"
        roi_path.write_bytes(b"")

        area_gdf, is_trial, _ = target.build_target_area(roi_path, None)

        assert is_trial is False
        assert tuple(area_gdf.total_bounds) == pytest.approx(HANOI_ROI_BOUNDS)

    def test_missing_roi_file_raises_before_any_download(self, tmp_path: Path) -> None:
        """存在しない ROI パスは読み込み前に検知する（cwd 依存の取り違えを防ぐ）。"""
        with pytest.raises(FileNotFoundError):
            target.build_target_area(tmp_path / "does_not_exist.shp", None)


class TestCoversRequestedArea:
    """covers_requested_area のテスト。"""

    def test_returns_true_when_raster_contains_requested_bounds(self) -> None:
        """要求範囲を完全に含んでいれば True。"""
        assert target.covers_requested_area(
            raster_bounds=(105.0, 20.0, 106.0, 21.0),
            requested_bounds=(105.1, 20.1, 105.9, 20.9),
        )

    def test_returns_false_when_raster_is_short_on_one_side(self) -> None:
        """1 辺でも覆えていなければ False（欠測が有効率に現れないため別途検知する）。"""
        assert not target.covers_requested_area(
            raster_bounds=(105.5, 20.0, 106.0, 21.0),
            requested_bounds=(105.0, 20.0, 106.0, 21.0),
        )

    def test_rejects_one_pixel_shortfall(self) -> None:
        """1 画素分の未被覆は実際の欠損なので False にする。"""
        pixel_size = 0.001
        assert not target.covers_requested_area(
            raster_bounds=(105.0 + pixel_size, 20.0, 106.0, 21.0),
            requested_bounds=(105.0, 20.0, 106.0, 21.0),
        )

    def test_rejects_half_pixel_shortfall(self) -> None:
        """半画素の未被覆も見逃さない。"""
        assert not target.covers_requested_area(
            raster_bounds=(105.0, 20.0, 106.0 - 0.0005, 21.0),
            requested_bounds=(105.0, 20.0, 106.0, 21.0),
        )

    def test_allows_only_floating_point_error(self) -> None:
        """座標計算の浮動小数点誤差のみを許容する。"""
        epsilon = 1e-12
        assert target.covers_requested_area(
            raster_bounds=(105.0 + epsilon, 20.0 + epsilon, 106.0 - epsilon, 21.0 - epsilon),
            requested_bounds=(105.0, 20.0, 106.0, 21.0),
        )


def _write_source_raster(
    path: Path,
    band_count: int = 2,
    dtype: str = "float32",
    nodata: float | None = None,
    width: int = 10,
    height: int = 10,
) -> None:
    """テスト用のソースラスタを書き出す。

    第 n バンドを一律 `n * 100` で埋める（バンドの取り違えを検出できるようにする）。

    Args:
        path: 出力パス。
        band_count: バンド数。
        dtype: 画素の型。
        nodata: ソース側の無効値。
        width: 列数。
        height: 行数。
    """
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": band_count,
        "dtype": dtype,
        "crs": CRS.from_epsg(4326),
        "transform": from_origin(105.0, 21.1, 0.01, 0.01),
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as destination:
        for index in range(1, band_count + 1):
            destination.write(np.full((height, width), index * 100, dtype=dtype), index)


class TestClipMultibandToArea:
    """clip_multiband_to_area のテスト。"""

    @staticmethod
    def _full_area() -> gpd.GeoDataFrame:
        """ソース全体を覆う範囲を作る。"""
        return gpd.GeoDataFrame(geometry=[box(105.0, 21.0, 105.1, 21.1)], crs="EPSG:4326")

    def test_writes_all_bands_with_descriptions(self, tmp_path: Path) -> None:
        """バンド名を説明として書き出し、CRS と nodata を宣言どおりにする。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=2)

        result = target.clip_multiband_to_area(
            source_path, self._full_area(), tmp_path / "out.tif", ["a", "b"]
        )

        with rasterio.open(tmp_path / "out.tif") as raster:
            assert raster.count == 2
            assert raster.descriptions == ("a", "b")
            assert raster.crs.to_epsg() == 4326
            assert raster.nodata == target.DEFAULT_RASTER_NODATA
            assert raster.dtypes[0] == "float32"
        assert result.raster_profile["band_count"] == 2

    def test_band_order_is_preserved(self, tmp_path: Path) -> None:
        """ソースのバンド順がそのまま出力名へ対応する。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=3)

        result = target.clip_multiband_to_area(
            source_path, self._full_area(), tmp_path / "out.tif", ["a", "b", "c"]
        )

        assert result.band_arrays["a"].max() == pytest.approx(100.0)
        assert result.band_arrays["b"].max() == pytest.approx(200.0)
        assert result.band_arrays["c"].max() == pytest.approx(300.0)

    def test_fills_padding_with_declared_nodata_for_integer_source(self, tmp_path: Path) -> None:
        """整数 dtype のソースでも、余白は宣言どおりの nodata で埋まる。

        `mask()` に nodata を渡すとソースの dtype のまま埋めるため、uint16 へ
        -9999 を渡すと 55537 に環り込む。宣言した無効値がファイル内に存在しなくなり、
        下流は余白を実データとして読んでしまう。統計は範囲マスクで絞るため
        valid_pixel_ratio は 1.0 のままで、サマリーからは気づけない。
        """
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=1, dtype="uint16")
        # ソースの一部だけを覆う三角形（必ず余白が生じる形）
        triangle = gpd.GeoDataFrame(
            geometry=[Polygon([(105.0, 21.0), (105.1, 21.0), (105.0, 21.1)])], crs="EPSG:4326"
        )

        result = target.clip_multiband_to_area(source_path, triangle, tmp_path / "out.tif", ["a"])

        unique_values = set(np.unique(result.band_arrays["a"]).tolist())
        assert 55537.0 not in unique_values, "dtype の環り込みで別の値になっている"
        assert target.DEFAULT_RASTER_NODATA in unique_values
        assert unique_values == {target.DEFAULT_RASTER_NODATA, 100.0}

    def test_translates_source_nodata_to_output_nodata(self, tmp_path: Path) -> None:
        """ソース自身の無効値も出力の nodata へ統一する。"""
        source_path = tmp_path / "source.tif"
        # 全画素を 100 で埋めたうえで、ソースの nodata を 100 と宣言する
        _write_source_raster(source_path, band_count=1, dtype="uint16", nodata=100)

        result = target.clip_multiband_to_area(
            source_path, self._full_area(), tmp_path / "out.tif", ["a"]
        )

        assert set(np.unique(result.band_arrays["a"]).tolist()) == {target.DEFAULT_RASTER_NODATA}

    def test_rejects_band_count_mismatch(self, tmp_path: Path) -> None:
        """バンド数が合わなければ、名前の割り当てがずれるため止める。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=3)

        with pytest.raises(ValueError, match="バンド数が想定と異なります"):
            target.clip_multiband_to_area(
                source_path, self._full_area(), tmp_path / "out.tif", ["a", "b"]
            )

    def test_rejects_duplicated_band_names(self, tmp_path: Path) -> None:
        """バンド名が重複していれば止める（辞書化で後勝ちになり取り違えるため）。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=3)

        with pytest.raises(ValueError, match="重複しています"):
            target.clip_multiband_to_area(
                source_path, self._full_area(), tmp_path / "out.tif", ["a", "b", "a"]
            )

    def test_rejects_source_without_crs(self, tmp_path: Path) -> None:
        """CRS 未定義のソースは、範囲の変換ができないため止める。"""
        source_path = tmp_path / "source.tif"
        with rasterio.open(
            source_path,
            "w",
            driver="GTiff",
            height=10,
            width=10,
            count=1,
            dtype="float32",
            transform=from_origin(105.0, 21.1, 0.01, 0.01),
        ) as destination:
            destination.write(np.ones((10, 10), dtype="float32"), 1)

        with pytest.raises(ValueError, match="CRS が未定義"):
            target.clip_multiband_to_area(
                source_path, self._full_area(), tmp_path / "out.tif", ["a"]
            )

    def test_area_mask_matches_clipped_grid(self, tmp_path: Path) -> None:
        """範囲マスクはソースのグリッドではなくクリップ後のグリッドに整合する。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=1, width=20, height=20)
        # ソースの一部だけを覆う範囲
        area = gpd.GeoDataFrame(geometry=[box(105.05, 21.0, 105.1, 21.05)], crs="EPSG:4326")

        result = target.clip_multiband_to_area(source_path, area, tmp_path / "out.tif", ["a"])

        assert result.area_mask.shape == result.band_arrays["a"].shape
        assert result.area_mask.shape != (20, 20)
        # 矩形の範囲なので、クリップ窓は全画素が範囲内になる
        assert result.area_mask.all()

    def test_reports_when_source_does_not_cover_area(self, tmp_path: Path) -> None:
        """ソースが要求範囲を覆っていなければ covers_area が False になる。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=1)
        # ソース（105.0-105.1）の東へはみ出す範囲
        area = gpd.GeoDataFrame(geometry=[box(105.0, 21.0, 105.3, 21.1)], crs="EPSG:4326")

        result = target.clip_multiband_to_area(source_path, area, tmp_path / "out.tif", ["a"])

        assert result.covers_area is False

    def test_reports_when_source_covers_area(self, tmp_path: Path) -> None:
        """ソースが要求範囲を覆っていれば covers_area が True になる。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=1)
        area = gpd.GeoDataFrame(geometry=[box(105.02, 21.02, 105.08, 21.08)], crs="EPSG:4326")

        result = target.clip_multiband_to_area(source_path, area, tmp_path / "out.tif", ["a"])

        assert result.covers_area is True

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        """出力先の親ディレクトリが無ければ作る。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=1)

        target.clip_multiband_to_area(
            source_path, self._full_area(), tmp_path / "sub" / "dir" / "out.tif", ["a"]
        )

        assert (tmp_path / "sub" / "dir" / "out.tif").exists()

    def test_replaces_nan_with_nodata(self, tmp_path: Path) -> None:
        """ソースの NaN も無効値へ統一する。

        NaN を残すと `x != nodata` の判定をすり抜けて有効画素に数えられ、
        統計が NaN になる。それはサマリー保存時にようやく例外になるため、
        GeoTIFF だけ書き終えた中途半端な状態で止まってしまう。
        """
        source_path = tmp_path / "source.tif"
        with rasterio.open(
            source_path,
            "w",
            driver="GTiff",
            height=10,
            width=10,
            count=1,
            dtype="float32",
            crs=CRS.from_epsg(4326),
            transform=from_origin(105.0, 21.1, 0.01, 0.01),
        ) as destination:
            values = np.full((10, 10), 100.0, dtype="float32")
            values[0, 0] = np.nan
            destination.write(values, 1)

        result = target.clip_multiband_to_area(
            source_path, self._full_area(), tmp_path / "out.tif", ["a"]
        )

        band = result.band_arrays["a"]
        assert not np.isnan(band).any()
        assert band[0, 0] == target.DEFAULT_RASTER_NODATA

    def test_output_is_compressed(self, tmp_path: Path) -> None:
        """出力を圧縮して保存する。

        ソースの profile を引き継がない方針にした結果、指定を忘れると圧縮が
        外れて研究データが不必要に大きくなる（実測で約2.3倍）。値は変えずに
        縮む設定なので既定で有効にしておく。
        """
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=2)

        target.clip_multiband_to_area(
            source_path, self._full_area(), tmp_path / "out.tif", ["a", "b"]
        )

        with rasterio.open(tmp_path / "out.tif") as raster:
            assert raster.profile["compress"] == "deflate"

    def test_does_not_inherit_source_storage_options(self, tmp_path: Path) -> None:
        """ソースのタイル設定を引き継がない（バンド数・dtype を変える出力と噛み合わない）。"""
        source_path = tmp_path / "source.tif"
        with rasterio.open(
            source_path,
            "w",
            driver="GTiff",
            height=512,
            width=512,
            count=2,
            dtype="float32",
            crs=CRS.from_epsg(4326),
            transform=from_origin(105.0, 21.1, 0.01, 0.01),
            tiled=True,
            blockxsize=256,
            blockysize=256,
        ) as destination:
            for index in (1, 2):
                destination.write(np.full((512, 512), index * 100, dtype="float32"), index)

        # ソースより十分小さい範囲でクリップする（ブロックサイズが出力寸法を超える）
        area = gpd.GeoDataFrame(geometry=[box(105.0, 21.05, 105.02, 21.1)], crs="EPSG:4326")
        target.clip_multiband_to_area(source_path, area, tmp_path / "out.tif", ["a", "b"])

        with rasterio.open(tmp_path / "out.tif") as raster:
            assert raster.width < 256
            assert raster.read(1).max() == pytest.approx(100.0)


class TestReadClippedFloatArray:
    """read_clipped_float_array のテスト（書き出しを伴わない読み取り）。"""

    def test_returns_float32_with_unified_nodata(self, tmp_path: Path) -> None:
        """整数ソースでも float32 で返し、余白は指定した無効値になる。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=1, dtype="uint16")
        triangle = gpd.GeoDataFrame(
            geometry=[Polygon([(105.0, 21.0), (105.1, 21.0), (105.0, 21.1)])], crs="EPSG:4326"
        )

        clipped = target.read_clipped_float_array(source_path, triangle)

        assert clipped.array.dtype == np.float32
        assert set(np.unique(clipped.array).tolist()) == {target.DEFAULT_RASTER_NODATA, 100.0}

    def test_does_not_write_any_file(self, tmp_path: Path) -> None:
        """読み取りのみで、ファイルは作らない（書き出しは呼び出し側の責務）。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=1)
        before = set(tmp_path.iterdir())

        target.read_clipped_float_array(
            source_path, gpd.GeoDataFrame(geometry=[box(105.0, 21.0, 105.1, 21.1)], crs="EPSG:4326")
        )

        assert set(tmp_path.iterdir()) == before

    def test_keeps_all_source_bands(self, tmp_path: Path) -> None:
        """バンド名の指定なしに、ソースの全バンドをそのまま返す。"""
        source_path = tmp_path / "source.tif"
        _write_source_raster(source_path, band_count=3)

        clipped = target.read_clipped_float_array(
            source_path, gpd.GeoDataFrame(geometry=[box(105.0, 21.0, 105.1, 21.1)], crs="EPSG:4326")
        )

        assert clipped.array.shape[0] == 3

    def test_rejects_source_without_crs(self, tmp_path: Path) -> None:
        """CRS 未定義のソースは範囲を変換できないため止める。"""
        source_path = tmp_path / "source.tif"
        with rasterio.open(
            source_path,
            "w",
            driver="GTiff",
            height=10,
            width=10,
            count=1,
            dtype="float32",
            transform=from_origin(105.0, 21.1, 0.01, 0.01),
        ) as destination:
            destination.write(np.ones((10, 10), dtype="float32"), 1)

        with pytest.raises(ValueError, match="CRS が未定義"):
            target.read_clipped_float_array(
                source_path,
                gpd.GeoDataFrame(geometry=[box(105.0, 21.0, 105.1, 21.1)], crs="EPSG:4326"),
            )


class TestWriteFloatRaster:
    """write_float_raster のテスト。"""

    def test_writes_bands_in_dict_order_with_names(self, tmp_path: Path) -> None:
        """辞書の順序がバンド順になり、名前が説明として入る。"""
        transform = from_origin(105.0, 21.1, 0.01, 0.01)
        band_arrays = {
            "first": np.full((4, 5), 1.0, dtype=np.float32),
            "second": np.full((4, 5), 2.0, dtype=np.float32),
        }

        target.write_float_raster(tmp_path / "out.tif", band_arrays, transform, CRS.from_epsg(4326))

        with rasterio.open(tmp_path / "out.tif") as raster:
            assert raster.descriptions == ("first", "second")
            assert raster.read(1).max() == pytest.approx(1.0)
            assert raster.read(2).max() == pytest.approx(2.0)
            assert raster.nodata == target.DEFAULT_RASTER_NODATA
            assert raster.profile["compress"] == "deflate"

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """出力先の親ディレクトリが無ければ作る。"""
        target.write_float_raster(
            tmp_path / "sub" / "out.tif",
            {"a": np.zeros((2, 2), dtype=np.float32)},
            from_origin(105.0, 21.1, 0.01, 0.01),
            CRS.from_epsg(4326),
        )

        assert (tmp_path / "sub" / "out.tif").exists()

    def test_rejects_empty_band_arrays(self, tmp_path: Path) -> None:
        """バンドが空なら、寸法を決められないため止める。"""
        with pytest.raises(ValueError, match="書き出すバンドがありません"):
            target.write_float_raster(
                tmp_path / "out.tif", {}, from_origin(105.0, 21.1, 0.01, 0.01), CRS.from_epsg(4326)
            )

        assert not (tmp_path / "out.tif").exists()

    def test_rejects_mismatched_band_shapes(self, tmp_path: Path) -> None:
        """バンド間で形状が違えば止める。

        先頭バンドの寸法で profile を組むため、揃っていないと書き込みが失敗するか、
        通った場合にバンドごとに意味の違う範囲を持つ成果物になる。
        """
        band_arrays = {
            "a": np.zeros((4, 5), dtype=np.float32),
            "b": np.zeros((3, 5), dtype=np.float32),
        }

        with pytest.raises(ValueError, match="形状が揃っていません"):
            target.write_float_raster(
                tmp_path / "out.tif",
                band_arrays,
                from_origin(105.0, 21.1, 0.01, 0.01),
                CRS.from_epsg(4326),
            )

        assert not (tmp_path / "out.tif").exists()
