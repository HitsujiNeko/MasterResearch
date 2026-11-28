"""tests/helpers.py（テスト全体で共有するヘルパー）のテスト。

ほかのテストの前提になる補助関数のうち、取り違えると気づきにくいもの（スクリプトの
読み込み・テスト用ラスタの書き出し）を確かめる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from tests.helpers import (
    load_script_module,
    write_test_raster,
)


class TestLoadScriptModule:
    """load_script_module のテスト。"""

    def test_loads_script_and_registers_module(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """パス指定でスクリプトを読み込み、指定した名前で sys.modules に登録する。"""
        script = tmp_path / "some_script.py"
        script.write_text("ANSWER = 7\n", encoding="utf-8")
        monkeypatch.delitem(sys.modules, "loaded_for_test", raising=False)

        module = load_script_module(script, "loaded_for_test")

        assert module.ANSWER == 7
        assert sys.modules["loaded_for_test"] is module
        sys.modules.pop("loaded_for_test", None)


class TestWriteTestRaster:
    """write_test_raster のテスト。"""

    def test_writes_multiband_raster_with_metadata(self, tmp_path: Path) -> None:
        """3 次元の配列を複数バンドとして、CRS・変換行列・nodata・説明つきで書き出す。"""
        values = np.arange(12, dtype=np.float64).reshape(2, 2, 3)
        transform = from_origin(105.0, 21.0, 0.5, 0.5)

        path = write_test_raster(
            tmp_path / "sub" / "r.tif",
            values,
            transform=transform,
            crs="EPSG:4326",
            nodata=-1.0,
            dtype="float32",
            band_names=("first", "second"),
        )

        with rasterio.open(path) as dataset:
            assert dataset.count == 2
            assert (dataset.height, dataset.width) == (2, 3)
            assert dataset.dtypes == ("float32", "float32")
            assert dataset.crs.to_epsg() == 4326
            assert dataset.transform == transform
            assert dataset.nodata == -1.0
            assert dataset.descriptions == ("first", "second")
            np.testing.assert_array_equal(dataset.read(), values.astype(np.float32))

    def test_keeps_input_dtype_and_omits_nodata_by_default(self, tmp_path: Path) -> None:
        """型を指定しなければ入力の型で書き、nodata を指定しなければタグを付けない。"""
        path = write_test_raster(
            tmp_path / "r.tif",
            np.ones((2, 2), dtype=np.uint8),
            transform=from_origin(0.0, 20.0, 10.0, 10.0),
            crs="EPSG:3857",
        )

        with rasterio.open(path) as dataset:
            assert dataset.dtypes == ("uint8",)
            assert dataset.nodata is None

    def test_rejects_band_names_that_do_not_match_band_count(self, tmp_path: Path) -> None:
        """バンドの説明の数がバンド数と違えば、書き出さずに例外にする。"""
        with pytest.raises(ValueError, match="バンド数"):
            write_test_raster(
                tmp_path / "r.tif",
                np.ones((2, 2), dtype=np.float32),
                transform=from_origin(0.0, 20.0, 10.0, 10.0),
                band_names=("first", "second"),
            )
        assert not (tmp_path / "r.tif").exists()
