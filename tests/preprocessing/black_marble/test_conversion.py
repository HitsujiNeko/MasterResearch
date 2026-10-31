"""HDF5 の読み込みと GeoTIFF 変換（`black_marble.conversion`）のテスト。

合成した小さな `.h5` を書き出して検証する（配布物の 119.8MB タイルには依存させない）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pytest
import rasterio

from src.preprocessing.black_marble import conversion as target
from src.preprocessing.black_marble import (
    product,
    tile_grid,
)
from tests.preprocessing.black_marble.fake_tile import FAKE_TILE_PIXELS, write_fake_tile


class TestReadScaledSds:
    """read_scaled_sds のテスト。"""

    def test_applies_scale_factor_from_attributes(self, tmp_path: Path) -> None:
        """スケール係数は属性から実測して適用する（決め打ちしない）。"""
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6), scale_factor=0.25)

        with h5py.File(tile_path, "r") as h5_file:
            values, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        # 第1バンドの生値は 10、スケール 0.25 → 2.5
        assert applied["scale_factor"] == pytest.approx(0.25)
        assert values[1, 1] == pytest.approx(2.5)

    def test_applies_offset_from_attributes(self, tmp_path: Path) -> None:
        """オフセットも属性から実測し、`生値 * scale + offset` の順で適用する。

        実ファイルの offset は 0.0 のため、0 のままでは符号・適用順の取り違え
        （NASA 系にある `(生値 - offset) * scale` との混同）を検出できない。
        """
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6), scale_factor=0.5, offset=3.0)

        with h5py.File(tile_path, "r") as h5_file:
            values, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        # 第1バンドの生値は 10 → 10 * 0.5 + 3.0 = 8.0
        assert applied["offset"] == pytest.approx(3.0)
        assert applied["offset_attribute"] == "offset"
        assert values[1, 1] == pytest.approx(8.0)

    def test_falls_back_to_add_offset_attribute_name(self, tmp_path: Path) -> None:
        """CF 規約の `add_offset` しか持たない版でも読める。"""
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6), offset=2.0)
        with h5py.File(tile_path, "a") as h5_file:
            dataset = h5_file[target.SDS_GROUP_PATH]["NearNadir_Composite_Snow_Free"]
            dataset.attrs["add_offset"] = dataset.attrs["offset"]
            del dataset.attrs["offset"]

        with h5py.File(tile_path, "r") as h5_file:
            values, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert applied["offset_attribute"] == "add_offset"
        assert applied["defaulted_attributes"] == []
        assert values[1, 1] == pytest.approx(12.0)

    def test_replaces_fill_value_with_nodata(self, tmp_path: Path) -> None:
        """欠測値は共通の nodata へ置き換える（スケール適用後の値にしない）。"""
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            values, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert values[0, 0] == product.OUTPUT_NODATA
        assert applied["fill_pixels"] == 1

    def test_records_units_and_long_name(self, tmp_path: Path) -> None:
        """単位・説明の属性も記録する（サマリーへ残すため）。"""
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            _, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert applied["units"] == "nWatts/(cm^2 sr)"
        assert applied["long_name"] == "NearNadir_Composite_Snow_Free"

    def test_raises_with_available_names_when_sds_missing(self, tmp_path: Path) -> None:
        """想定した SDS が無ければ、実在する名前を添えて例外にする。"""
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            with pytest.raises(KeyError, match="NearNadir_Composite_Snow_Free"):
                target.read_scaled_sds(h5_file, "Renamed_In_A_Future_Version")


class TestWriteTileGeotiff:
    """write_tile_geotiff のテスト。"""

    def test_writes_all_bands_with_tile_georeference(self, tmp_path: Path) -> None:
        """タイル番号から組み立てたジオリファレンスで全バンドを書き出す。"""
        tile = tile_grid.TileIndex(28, 6)
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile)

        output_path, metadata = target.write_tile_geotiff(tile_path, tile, tmp_path / "tile.tif")

        with rasterio.open(output_path) as raster:
            assert raster.count == len(product.BAND_DEFINITIONS)
            assert raster.crs.to_epsg() == 4326
            assert raster.descriptions == tuple(
                band.output_name for band in product.BAND_DEFINITIONS
            )
            assert raster.bounds.left == pytest.approx(100.0)
            assert raster.bounds.top == pytest.approx(30.0)
            assert raster.bounds.right == pytest.approx(110.0)
            assert raster.bounds.bottom == pytest.approx(20.0)
        assert metadata["pixel_size_deg"] == pytest.approx(
            tile_grid.TILE_SIZE_DEG / FAKE_TILE_PIXELS
        )

    def test_band_order_matches_definitions(self, tmp_path: Path) -> None:
        """SDS の並びが定義順のまま出力バンドへ対応する（取り違えの検出）。"""
        tile = tile_grid.TileIndex(28, 6)
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile, scale_factor=1.0)

        output_path, _ = target.write_tile_geotiff(tile_path, tile, tmp_path / "tile.tif")

        with rasterio.open(output_path) as raster:
            for index in range(1, len(product.BAND_DEFINITIONS) + 1):
                values = raster.read(index)
                # 合成タイルは第 n バンドを一律 n*10 で埋めてある（欠測の 1 画素を除く）
                assert values[1, 1] == pytest.approx(index * 10)

    def test_non_square_tile_keeps_row_and_column_order(self, tmp_path: Path) -> None:
        """行数と列数が異なっても、行=緯度方向・列=経度方向の対応が崩れない。

        実ファイルは 2400×2400 の正方形のため、正方形だけで検証していると
        行と列の取り違え（経度・緯度分解能の入れ替え）が素通りする。
        """
        tile = tile_grid.TileIndex(28, 6)
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile, shape=(10, 20))

        output_path, metadata = target.write_tile_geotiff(tile_path, tile, tmp_path / "tile.tif")

        with rasterio.open(output_path) as raster:
            assert (raster.height, raster.width) == (10, 20)
            # タイルは常に 10°×10°。列 20 なら経度 0.5°/画素、行 10 なら緯度 1.0°/画素
            assert raster.transform.a == pytest.approx(0.5)
            assert raster.transform.e == pytest.approx(-1.0)
            assert raster.bounds.right == pytest.approx(110.0)
            assert raster.bounds.bottom == pytest.approx(20.0)
        assert metadata["tile_shape"] == [10, 20]

    def test_rejects_tile_whose_attributes_disagree(self, tmp_path: Path) -> None:
        """属性の境界座標がタイル番号と食い違うファイルは変換しない。"""
        tile = tile_grid.TileIndex(28, 6)
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(
            tile_path,
            tile,
            bounds_override={"west": 110.0, "east": 120.0, "north": 30.0, "south": 20.0},
        )

        with pytest.raises(ValueError, match="一致しません"):
            target.write_tile_geotiff(tile_path, tile, tmp_path / "tile.tif")


class TestDescribeHdf5Structure:
    """describe_hdf5_structure のテスト。"""

    def test_lists_datasets_and_attributes(self, tmp_path: Path) -> None:
        """SDS 名・形状・属性を読み取れる。"""
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6))

        structure = target.describe_hdf5_structure(tile_path)

        assert "NearNadir_Composite_Snow_Free" in structure["datasets"]
        entry = structure["datasets"]["NearNadir_Composite_Snow_Free"]
        assert entry["shape"] == [FAKE_TILE_PIXELS, FAKE_TILE_PIXELS]
        assert entry["attributes"]["scale_factor"] == pytest.approx(1.0)
        assert structure["root_attributes"]["WestBoundingCoord"] == pytest.approx(100.0)

    def test_result_is_json_serializable(self, tmp_path: Path) -> None:
        """HDF5 の属性型が JSON へ書ける形に変換されている。"""
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6))

        json.dumps(target.describe_hdf5_structure(tile_path), ensure_ascii=False)

    def test_raises_when_group_is_absent(self, tmp_path: Path) -> None:
        """SDS グループが無ければ、ルートのキーを添えて例外にする。"""
        tile_path = tmp_path / "empty.h5"
        with h5py.File(tile_path, "w") as h5_file:
            h5_file.create_group("Unexpected")

        with pytest.raises(KeyError, match="Unexpected"):
            target.describe_hdf5_structure(tile_path)


class TestReadScaledSdsMissingAttributes:
    """属性が欠けた SDS の扱いのテスト。

    属性名が配布バージョンで変わると、換算がずれたまま最後まで通ってしまう
    （実ファイルの `scale_factor` は 1.0 だが、これも実測して初めて分かった値で、
    事前の想定 0.1 は外れていた）。既定値で代用した事実が記録に残ることを固定する。
    """

    @staticmethod
    def _write_tile_without_attributes(path: Path, tile: tile_grid.TileIndex) -> None:
        """スケール・欠測値の属性を持たない合成タイルを書き出す。"""
        west, south, east, north = tile_grid.compute_tile_bounds(tile)
        bounds = {"west": west, "east": east, "north": north, "south": south}
        with h5py.File(path, "w") as h5_file:
            for key, attribute_name in tile_grid.BOUNDING_COORD_ATTRIBUTES.items():
                h5_file.attrs[attribute_name] = np.float64(bounds[key])
            group = h5_file.create_group(target.SDS_GROUP_PATH)
            for index, band in enumerate(product.BAND_DEFINITIONS, start=1):
                group.create_dataset(
                    band.sds_name,
                    data=np.full((FAKE_TILE_PIXELS, FAKE_TILE_PIXELS), index * 10, dtype=np.uint16),
                )

    def test_records_defaulted_attributes(self, tmp_path: Path) -> None:
        """欠けた属性名を記録に残す。"""
        tile_path = tmp_path / "tile.h5"
        self._write_tile_without_attributes(tile_path, tile_grid.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            _, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert applied["defaulted_attributes"] == ["scale_factor", "offset", "_FillValue"]

    def test_records_nothing_when_attributes_are_present(self, tmp_path: Path) -> None:
        """属性が揃っていれば記録は空になる。"""
        tile_path = tmp_path / "tile.h5"
        write_fake_tile(tile_path, tile_grid.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            _, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert applied["defaulted_attributes"] == []
        assert applied["unusable_attributes"] == []


class TestFillValueRepresentability:
    """`_FillValue` の型不一致の扱いのテスト。

    整数型は範囲外の値を例外にせず巻き戻すため（`-999.9` → `uint16` は `64537`）、
    型が食い違うと一致 0 件になるだけで警告も出ない。番兵値（`65535` 等）が実測値
    として統計へ混入する経路を塞げているかを固定する。
    """

    @pytest.mark.parametrize(
        ("fill_value", "dtype", "expected"),
        [
            (65535, np.dtype(np.uint16), True),
            (255, np.dtype(np.uint8), True),
            (-999.9, np.dtype(np.uint16), False),
            (-999.9, np.dtype(np.uint8), False),
            (70000, np.dtype(np.uint16), False),
            (-999.9, np.dtype(np.float32), True),
            ("bad", np.dtype(np.uint16), False),
            ([1, 2], np.dtype(np.uint16), False),
        ],
    )
    def test_judges_representability(self, fill_value: Any, dtype: Any, expected: bool) -> None:
        """整数型では範囲外・非整数を弾き、浮動小数点型は丸めとして許す。"""
        assert target.is_fill_value_representable(fill_value, dtype) is expected

    @staticmethod
    def _write_tile_with_mismatched_fill_value(path: Path, tile: tile_grid.TileIndex) -> None:
        """uint16 の SDS に float の _FillValue を付けた合成タイルを書き出す。"""
        west, south, east, north = tile_grid.compute_tile_bounds(tile)
        bounds = {"west": west, "east": east, "north": north, "south": south}
        with h5py.File(path, "w") as h5_file:
            for key, attribute_name in tile_grid.BOUNDING_COORD_ATTRIBUTES.items():
                h5_file.attrs[attribute_name] = np.float64(bounds[key])
            group = h5_file.create_group(target.SDS_GROUP_PATH)
            for index, band in enumerate(product.BAND_DEFINITIONS, start=1):
                dataset = group.create_dataset(
                    band.sds_name,
                    data=np.full((FAKE_TILE_PIXELS, FAKE_TILE_PIXELS), index * 10, dtype=np.uint16),
                )
                dataset.attrs["scale_factor"] = np.float64(1.0)
                dataset.attrs["offset"] = np.float64(0.0)
                # uint16 の配列に対し、表現できない値を _FillValue として与える
                dataset.attrs["_FillValue"] = np.float64(-999.9)

    def test_records_unusable_fill_value_instead_of_silently_matching_nothing(
        self, tmp_path: Path
    ) -> None:
        """型が合わない _FillValue は適用せず、記録に残す。"""
        tile_path = tmp_path / "tile.h5"
        self._write_tile_with_mismatched_fill_value(tile_path, tile_grid.TileIndex(28, 6))

        with h5py.File(tile_path, "r") as h5_file:
            _, applied = target.read_scaled_sds(h5_file, "NearNadir_Composite_Snow_Free")

        assert applied["unusable_attributes"] == ["_FillValue"]
        # 属性自体は存在するため、欠落側には入れない
        assert applied["defaulted_attributes"] == []
        assert applied["fill_pixels"] == 0
