"""water_source_disagreement_map.py（水域データの食い違い図）のテスト。

区分・一致数・窓の切り出しはユニットテストで、描画は小さな合成マスクでの
スモークテスト（PNG が書き出されること）で確認する。図の見た目は目視で確認する。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from src.visualization import water_source_disagreement_map as target

MASK_CRS = "EPSG:5897"


def _write_masks(path: Path, center_lon: float, center_lat: float, size: int = 400) -> Path:
    """指定地点を中心とする 30m 格子の合成マスク（全バンド）を書き出す。

    左半分を水域、右下の隅を無効にする。

    Args:
        path: 出力パス。
        center_lon: 中心の経度。
        center_lat: 中心の緯度。
        size: 一辺のセル数。

    Returns:
        書き出したパス。
    """
    to_mask = Transformer.from_crs("EPSG:4326", MASK_CRS, always_xy=True)
    x, y = to_mask.transform(center_lon, center_lat)
    transform = from_origin(x - size * 15.0, y + size * 15.0, 30.0, 30.0)
    band = np.zeros((size, size), dtype=np.uint8)
    band[:, : size // 2] = target.MASK_WATER
    band[-10:, -10:] = target.MASK_NODATA
    names = sorted(set(target.OVERVIEW_KEYS) | set(target.ZOOM_PARTNERS) | {"glc"})
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=len(names),
        dtype="uint8",
        crs=MASK_CRS,
        transform=transform,
        nodata=target.MASK_NODATA,
    ) as destination:
        for index, name in enumerate(names, start=1):
            destination.write(band, index)
            destination.set_band_description(index, name)
    return path


class TestClassifyPair:
    """classify_pair のテスト。"""

    def test_five_categories(self) -> None:
        """両方非水域・両方水域・A のみ・B のみ・無効の 5 区分になる。"""
        mask_a = np.array([0, 1, 1, 0, 255, 1], dtype=np.uint8)
        mask_b = np.array([0, 1, 0, 1, 1, 255], dtype=np.uint8)

        classes = target.classify_pair(mask_a, mask_b)

        assert classes.tolist() == [
            target.PAIR_NEITHER,
            target.PAIR_BOTH,
            target.PAIR_A_ONLY,
            target.PAIR_B_ONLY,
            target.PAIR_INVALID,
            target.PAIR_INVALID,
        ]


class TestCountWaterSources:
    """count_water_sources のテスト。"""

    def test_counts_and_masks_invalid(self) -> None:
        """水域とした判定の数を数え、いずれかが無効なセルはマスクする。"""
        masks = {
            "a": np.array([1, 1, 0, 255], dtype=np.uint8),
            "b": np.array([1, 0, 0, 1], dtype=np.uint8),
        }

        counts = target.count_water_sources(masks, ("a", "b"))

        assert counts.filled(-1).tolist() == [2, 1, 0, -1]

    def test_rejects_unknown_band(self) -> None:
        """マスクに無いバンド名を指定すると停止する。"""
        with pytest.raises(KeyError, match="無いバンド"):
            target.count_water_sources({"a": np.zeros(2, dtype=np.uint8)}, ("a", "b"))


class TestWindowSlices:
    """window_slices のテスト。"""

    def test_window_is_centered_and_sized(self) -> None:
        """3km の半径は 30m セルで 100 セル分になり、中心付近で切り出される。"""
        to_mask = Transformer.from_crs("EPSG:4326", MASK_CRS, always_xy=True)
        x, y = to_mask.transform(105.83, 21.02)
        transform = from_origin(x - 6000.0, y + 6000.0, 30.0, 30.0)
        window = target.ZoomWindow("w", "w", 105.83, 21.02, 3000.0, "")

        rows, cols = target.window_slices(window, transform, MASK_CRS, (400, 400))

        assert rows.stop - rows.start == pytest.approx(200, abs=1)
        assert cols.stop - cols.start == pytest.approx(200, abs=1)
        assert rows.start == pytest.approx(100, abs=1)

    def test_window_outside_raises(self) -> None:
        """マスクと重ならない窓は停止する。"""
        to_mask = Transformer.from_crs("EPSG:4326", MASK_CRS, always_xy=True)
        x, y = to_mask.transform(105.83, 21.02)
        transform = from_origin(x, y, 30.0, 30.0)
        window = target.ZoomWindow("far", "far", 106.5, 20.0, 3000.0, "")

        with pytest.raises(ValueError, match="重なりません"):
            target.window_slices(window, transform, MASK_CRS, (100, 100))


class TestDefaultWindows:
    """既定の拡大範囲のテスト。"""

    def test_windows_do_not_overlap(self) -> None:
        """既定の拡大範囲どうしは重ならない（同じ場所を二度描かない）。"""
        to_mask = Transformer.from_crs("EPSG:4326", MASK_CRS, always_xy=True)
        boxes = []
        for window in target.DEFAULT_WINDOWS:
            x, y = to_mask.transform(window.lon, window.lat)
            size = window.half_size_m
            boxes.append((x - size, y - size, x + size, y + size))
        for index, box_a in enumerate(boxes):
            for box_b in boxes[index + 1 :]:
                overlaps = not (
                    box_a[2] <= box_b[0]
                    or box_b[2] <= box_a[0]
                    or box_a[3] <= box_b[1]
                    or box_b[3] <= box_a[1]
                )
                assert not overlaps


class TestRun:
    """run のスモークテスト。"""

    def test_writes_two_png(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """全域図と拡大図の 2 枚の PNG が書き出される。"""
        mask_path = _write_masks(tmp_path / "masks.tif", 105.83, 20.9, size=900)
        # 合成マスクの範囲に収まる小さな窓へ差し替える
        monkeypatch.setattr(
            target,
            "DEFAULT_WINDOWS",
            (target.ZoomWindow("w", "テスト地点", 105.83, 20.9, 1500.0, ""),),
        )

        overview_path, zoom_path = target.run(mask_path, tmp_path / "out", "test")

        assert overview_path.exists() and overview_path.stat().st_size > 0
        assert zoom_path.exists() and zoom_path.stat().st_size > 0

    def test_read_mask_requires_file(self, tmp_path: Path) -> None:
        """マスクが無ければ停止する。"""
        with pytest.raises(FileNotFoundError):
            target.read_mask_raster(tmp_path / "missing.tif")
