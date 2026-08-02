"""raster_stats.py（有効画素の記述統計と飽和判定）のテスト。"""

from __future__ import annotations

import numpy as np
import pytest

from src.common import raster_stats as target


class TestBuildBandStatistics:
    """build_band_statistics のテスト。"""

    def test_returns_none_for_empty_input(self) -> None:
        """有効画素が無ければ None を返す。"""
        assert target.build_band_statistics(np.array([], dtype=np.float32)) is None

    def test_computes_descriptive_statistics(self) -> None:
        """記述統計を返す。"""
        stats = target.build_band_statistics(np.arange(1.0, 101.0, dtype=np.float32))

        assert stats is not None
        assert stats["min"] == pytest.approx(1.0)
        assert stats["max"] == pytest.approx(100.0)
        assert stats["median"] == pytest.approx(50.5)
        assert stats["p95"] == pytest.approx(95.05, rel=1e-3)

    def test_aggregates_in_float64(self) -> None:
        """float32 の丸め誤差を拾わないよう float64 で集計する。"""
        # float32 の有効桁（約7桁）を超える組み合わせ。float32 のまま累算すると
        # 小さい側が丸め落ちし、平均が理論値から相対 5e-08 ほどずれる
        values = np.array([1.0e8] + [1.0] * 1000, dtype=np.float32)

        stats = target.build_band_statistics(values)

        assert stats is not None
        assert stats["mean"] == pytest.approx((1.0e8 + 1000.0) / 1001, rel=1e-12)


class TestBuildSaturationIndicators:
    """build_saturation_indicators のテスト。"""

    def test_returns_none_for_empty_input(self) -> None:
        """有効画素が無ければ None を返す。"""
        assert target.build_saturation_indicators(np.array([], dtype=np.float32)) is None

    def test_detects_saturation_when_values_pile_up_at_max(self) -> None:
        """上位が最大値へ張り付いていれば飽和の兆候として現れる。"""
        # 100 画素中 30 画素が上限に張り付いた分布
        values = np.concatenate(
            [np.linspace(0.0, 50.0, 70), np.full(30, 100.0)],
        ).astype(np.float32)

        indicators = target.build_saturation_indicators(values)

        assert indicators is not None
        assert indicators["pixels_at_max"] == 30
        assert indicators["ratio_near_max"] == pytest.approx(0.3)
        assert indicators["p99_to_max_ratio"] == pytest.approx(1.0)

    def test_reports_low_ratio_when_max_is_isolated(self) -> None:
        """最大値が単独画素なら p99 との差が残り、飽和とは判定されない。"""
        values = np.concatenate([np.linspace(0.0, 10.0, 999), np.array([1000.0])]).astype(
            np.float32
        )

        indicators = target.build_saturation_indicators(values)

        assert indicators is not None
        assert indicators["pixels_at_max"] == 1
        assert indicators["p99_to_max_ratio"] < 0.1

    def test_handles_all_zero_values_without_dividing_by_zero(self) -> None:
        """全画素 0（完全な消灯）でもゼロ除算にならない。"""
        indicators = target.build_saturation_indicators(np.zeros(10, dtype=np.float32))

        assert indicators is not None
        assert indicators["max"] == 0.0
        # 相対幅の近傍は定義できないため比率は None にする（0 除算も NaN も出さない）
        assert indicators["p99_to_max_ratio"] is None
        assert indicators["pixels_near_max"] == 10

    def test_handles_negative_values(self) -> None:
        """負の放射輝度（背景除去後に生じうる）でも破綻しない。"""
        indicators = target.build_saturation_indicators(
            np.array([-1.0, -0.5, -0.2], dtype=np.float32)
        )

        assert indicators is not None
        assert indicators["max"] == pytest.approx(-0.2)
        assert indicators["p99_to_max_ratio"] is None

    def test_neighborhood_ratio_is_configurable(self) -> None:
        """近傍幅を広げると、その分だけ最大値近傍の画素が増える。"""
        values = np.array([50.0, 90.0, 95.0, 100.0], dtype=np.float32)

        narrow = target.build_saturation_indicators(values, neighborhood_ratio=0.01)
        wide = target.build_saturation_indicators(values, neighborhood_ratio=0.2)

        assert narrow is not None and wide is not None
        assert narrow["pixels_near_max"] == 1
        assert wide["pixels_near_max"] == 3


class TestBuildMultibandPixelStatistics:
    """build_multiband_pixel_statistics のテスト。"""

    NODATA = -9999.0

    @staticmethod
    def _band_arrays(height: int = 2, width: int = 3) -> dict[str, np.ndarray]:
        """非正方形の入力一式を作る（行・列の取り違えを検出するため）。"""
        return {
            name: np.arange(height * width, dtype=np.float32).reshape(height, width)
            for name in ("primary", "secondary", "flag")
        }

    def test_handles_non_square_rasters(self) -> None:
        """行数と列数が異なっても集計できる。"""
        stats = target.build_multiband_pixel_statistics(
            band_arrays=self._band_arrays(height=2, width=3),
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
            primary_band="primary",
            nodata=self.NODATA,
        )

        assert stats["total_pixels"] == 6
        assert stats["roi_pixels"] == 6
        assert stats["valid_pixels"] == 6
        assert stats["valid_pixel_ratio"] == pytest.approx(1.0)

    def test_counts_valid_pixels_per_band(self) -> None:
        """バンドごとに別々の有効画素数を数える。

        一部バンドだけ欠測になるデータセット（背景マスク・品質フラグ）で、
        他バンドの統計まで母集団が痩せるのを避ける。
        """
        band_arrays = self._band_arrays(height=2, width=3)
        band_arrays["secondary"][0, :] = self.NODATA

        stats = target.build_multiband_pixel_statistics(
            band_arrays=band_arrays,
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
            primary_band="primary",
            nodata=self.NODATA,
        )

        assert stats["valid_pixel_ratio"] == pytest.approx(1.0)
        assert stats["primary"]["valid_pixels"] == 6
        assert stats["secondary"]["valid_pixels"] == 3
        assert stats["secondary"]["valid_pixel_ratio"] == pytest.approx(0.5)
        # 他バンドの nodata が主バンドの最小値へ混ざっていないこと
        assert stats["primary"]["min"] == pytest.approx(0.0)

    def test_primary_band_drives_coverage_ratio(self) -> None:
        """主バンドの欠測は被覆率へ反映される。"""
        band_arrays = self._band_arrays(height=2, width=3)
        band_arrays["primary"][0, :] = self.NODATA

        stats = target.build_multiband_pixel_statistics(
            band_arrays=band_arrays,
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
            primary_band="primary",
            nodata=self.NODATA,
        )

        assert stats["valid_pixels"] == 3
        assert stats["valid_pixel_ratio"] == pytest.approx(0.5)
        assert stats["primary_band"] == "primary"

    def test_excludes_pixels_outside_area(self) -> None:
        """範囲外の画素は有効画素にも分母にも入らない。"""
        stats = target.build_multiband_pixel_statistics(
            band_arrays=self._band_arrays(height=2, width=3),
            area_mask=np.array([[True, True, True], [False, False, False]]),
            covers_area=True,
            primary_band="primary",
            nodata=self.NODATA,
        )

        assert stats["roi_pixels"] == 3
        assert stats["outside_roi_pixels"] == 3
        assert stats["valid_pixels"] == 3
        assert stats["primary"]["max"] == pytest.approx(2.0)

    def test_ratio_is_zero_when_area_is_empty(self) -> None:
        """範囲内画素が 0 でもゼロ除算にならない。"""
        stats = target.build_multiband_pixel_statistics(
            band_arrays=self._band_arrays(),
            area_mask=np.zeros((2, 3), dtype=bool),
            covers_area=True,
            primary_band="primary",
            nodata=self.NODATA,
        )

        assert stats["roi_pixels"] == 0
        assert stats["valid_pixel_ratio"] == 0.0
        # 統計は空でも件数のキーは残す（サマリーの形を安定させるため）
        assert stats["primary"]["valid_pixels"] == 0
        assert "min" not in stats["primary"]

    def test_saturation_is_computed_only_for_named_bands(self) -> None:
        """飽和指標は指定したバンドにのみ付く（フラグ値には意味がないため）。"""
        stats = target.build_multiband_pixel_statistics(
            band_arrays=self._band_arrays(),
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
            primary_band="primary",
            nodata=self.NODATA,
            saturation_bands=["primary", "secondary"],
        )

        assert set(stats["saturation"]) == {"primary", "secondary"}
        assert "flag" not in stats["saturation"]

    def test_saturation_is_empty_by_default(self) -> None:
        """指定しなければ飽和指標は算出しない。"""
        stats = target.build_multiband_pixel_statistics(
            band_arrays=self._band_arrays(),
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
            primary_band="primary",
            nodata=self.NODATA,
        )

        assert stats["saturation"] == {}

    def test_records_coverage_flag(self) -> None:
        """カバレッジ判定の結果をそのまま保持する。"""
        stats = target.build_multiband_pixel_statistics(
            band_arrays=self._band_arrays(),
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=False,
            primary_band="primary",
            nodata=self.NODATA,
        )

        assert stats["covers_requested_area"] is False

    def test_raises_when_primary_band_is_absent(self) -> None:
        """主バンドが無ければ、被覆率を誤って別バンドで代表させず止める。"""
        with pytest.raises(KeyError, match="主バンド"):
            target.build_multiband_pixel_statistics(
                band_arrays=self._band_arrays(),
                area_mask=np.ones((2, 3), dtype=bool),
                covers_area=True,
                primary_band="absent",
                nodata=self.NODATA,
            )

    def test_raises_when_saturation_band_is_absent(self) -> None:
        """飽和指標の対象バンドが無ければ、黙って省略せず止める。"""
        with pytest.raises(KeyError, match="飽和指標"):
            target.build_multiband_pixel_statistics(
                band_arrays=self._band_arrays(),
                area_mask=np.ones((2, 3), dtype=bool),
                covers_area=True,
                primary_band="primary",
                nodata=self.NODATA,
                saturation_bands=["absent"],
            )

    @pytest.mark.parametrize("reserved_name", ["valid_pixels", "saturation", "primary_band"])
    def test_raises_when_band_name_collides_with_reserved_key(self, reserved_name: str) -> None:
        """予約キーと同名のバンドは、集計値を静かに上書きする前に止める。

        バンド別統計は集計値と同じ階層に置くため、名前が衝突すると例外にならず
        サマリー JSON の値だけが壊れる。
        """
        band_arrays = {
            "primary": np.zeros((2, 3), dtype=np.float32),
            reserved_name: np.zeros((2, 3), dtype=np.float32),
        }

        with pytest.raises(ValueError, match="予約キーと衝突"):
            target.build_multiband_pixel_statistics(
                band_arrays=band_arrays,
                area_mask=np.ones((2, 3), dtype=bool),
                covers_area=True,
                primary_band="primary",
                nodata=self.NODATA,
            )

    def test_accepts_band_names_that_do_not_collide(self) -> None:
        """予約キー以外のバンド名は、これまでどおり受け付ける（過剰な拒否をしない）。"""
        statistics = target.build_multiband_pixel_statistics(
            band_arrays=self._band_arrays(),
            area_mask=np.ones((2, 3), dtype=bool),
            covers_area=True,
            primary_band="primary",
            nodata=self.NODATA,
        )

        assert "primary" in statistics

    def test_raises_when_band_shapes_differ(self) -> None:
        """バンド間で形状が違えば、numpy の不可解なエラーになる前に止める。"""
        band_arrays = {
            "primary": np.zeros((2, 3), dtype=np.float32),
            "secondary": np.zeros((1, 3), dtype=np.float32),
        }

        with pytest.raises(ValueError, match="形状が揃っていません"):
            target.build_multiband_pixel_statistics(
                band_arrays=band_arrays,
                area_mask=np.ones((2, 3), dtype=bool),
                covers_area=True,
                primary_band="primary",
                nodata=self.NODATA,
            )

    def test_raises_when_area_mask_shape_differs(self) -> None:
        """範囲マスクの形状がバンドと合わなければ止める。"""
        with pytest.raises(ValueError, match="area_mask の形状"):
            target.build_multiband_pixel_statistics(
                band_arrays=self._band_arrays(height=2, width=3),
                area_mask=np.ones((3, 2), dtype=bool),
                covers_area=True,
                primary_band="primary",
                nodata=self.NODATA,
            )
