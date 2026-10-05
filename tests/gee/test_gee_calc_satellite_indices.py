"""gee_calc_satellite_indices.py（正規化差分指標の定義と算出）のテスト。

GEEへの接続を伴わずに検証するため、`ee.Image` の演算を数値で模した
偽オブジェクトを用いて `add_indices` の計算式とマスクを確認する。
"""

from __future__ import annotations

import numpy as np
import pytest

import src.gee.gee_calc_satellite_indices as indices


class FakeBand:
    """`ee.Image` の単バンド演算を数値配列で模した偽オブジェクト。"""

    def __init__(self, values: np.ndarray, name: str = "", mask: np.ndarray | None = None):
        self.values = np.asarray(values, dtype=float)
        self.name = name
        self.mask = np.ones(self.values.shape, dtype=bool) if mask is None else mask

    def _unwrap(self, other: object) -> np.ndarray | float:
        """演算相手の値を取り出す（偽バンドまたは偽数値）。"""
        if isinstance(other, FakeBand):
            return other.values
        return float(other)

    def add(self, other: object) -> FakeBand:
        """加算。"""
        return FakeBand(self.values + self._unwrap(other), self.name, self.mask)

    def subtract(self, other: object) -> FakeBand:
        """減算。"""
        return FakeBand(self.values - self._unwrap(other), self.name, self.mask)

    def divide(self, other: object) -> FakeBand:
        """除算（ゼロ除算の警告は抑止し、マスクで扱う）。"""
        with np.errstate(divide="ignore", invalid="ignore"):
            return FakeBand(self.values / self._unwrap(other), self.name, self.mask)

    def abs(self) -> FakeBand:
        """絶対値。"""
        return FakeBand(np.abs(self.values), self.name, self.mask)

    def gt(self, other: object) -> FakeBand:
        """大なり比較（真偽を0/1で持つ）。"""
        return FakeBand(self.values > self._unwrap(other), self.name, self.mask)

    def updateMask(self, mask: FakeBand) -> FakeBand:  # noqa: N802 （ee APIの名称に合わせる）
        """マスクの更新（既存マスクとの論理積）。"""
        return FakeBand(self.values, self.name, self.mask & mask.values.astype(bool))

    def rename(self, name: str) -> FakeBand:
        """バンド名の変更。"""
        return FakeBand(self.values, name, self.mask)


class FakeOpticalImage:
    """スケーリング済み光学バンドを保持する偽画像。"""

    def __init__(self, bands: dict[str, np.ndarray]):
        self.bands = bands

    def select(self, band_name: str) -> FakeBand:
        """指定バンドを取り出す。"""
        return FakeBand(self.bands[band_name], band_name)


class FakeSourceImage:
    """`add_indices` の入力画像。追加されたバンドを記録する。"""

    def __init__(self) -> None:
        self.added_bands: list[FakeBand] = []

    def addBands(self, bands: list[FakeBand]) -> FakeSourceImage:  # noqa: N802 （ee APIの名称に合わせる）
        """追加バンドを記録して自身を返す。"""
        self.added_bands = list(bands)
        return self


@pytest.fixture
def optical_bands() -> dict[str, np.ndarray]:
    """反射率の模擬値。末尾の画素は GREEN + SWIR1 = 0 となる分母ゼロの例。

    末尾の SWIR1 = -0.2 は分母ゼロを作るための人工値である。実データでは有効DN範囲の
    マスクにより反射率の下限は約 7.5e-6 となり、分母が閾値 1e-6 を下回ることはない。
    """
    return {
        "SR_B3": np.array([0.10, 0.05, 0.30, 0.2]),
        "SR_B4": np.array([0.08, 0.04, 0.10, 0.1]),
        "SR_B5": np.array([0.30, 0.02, 0.40, 0.3]),
        "SR_B6": np.array([0.20, 0.01, 0.10, -0.2]),
    }


@pytest.fixture
def added_bands(
    monkeypatch: pytest.MonkeyPatch, optical_bands: dict[str, np.ndarray]
) -> dict[str, FakeBand]:
    """偽画像に対して `add_indices` を実行し、追加バンドを名前で引ける形で返す。"""
    monkeypatch.setattr(
        indices, "get_scaled_optical_bands", lambda image: FakeOpticalImage(optical_bands)
    )
    monkeypatch.setattr(indices.ee, "Number", float)

    result = indices.add_indices(FakeSourceImage())

    return {band.name: band for band in result.added_bands}


def test_definitions_fix_band_pairs() -> None:
    """各指標のバンドの組（A, B）が定義式どおりである。"""
    assert indices.NORMALIZED_DIFFERENCE_DEFINITIONS == {
        "NDVI": ("SR_B5", "SR_B4"),
        "NDBI": ("SR_B6", "SR_B5"),
        "NDWI": ("SR_B3", "SR_B5"),
        "MNDWI": ("SR_B3", "SR_B6"),
    }


def test_definitions_use_only_scaled_optical_bands() -> None:
    """定義表のバンドはすべてスケーリング対象の光学バンド（SR_B3〜SR_B6）に含まれる。"""
    scaled_bands = {"SR_B3", "SR_B4", "SR_B5", "SR_B6"}
    used_bands = {
        band for pair in indices.NORMALIZED_DIFFERENCE_DEFINITIONS.values() for band in pair
    }

    assert used_bands <= scaled_bands


def test_target_band_names_keep_existing_order_and_append_mndwi() -> None:
    """既存3指標の順序を保ったまま、MNDWI が末尾に加わる。"""
    assert indices.get_target_band_names() == ["NDVI", "NDBI", "NDWI", "MNDWI"]


def test_target_band_names_returns_copy() -> None:
    """戻り値を変更しても定数側に影響しない。"""
    band_names = indices.get_target_band_names()
    band_names.append("DUMMY")

    assert indices.BASE_INDEX_BANDS == ["NDVI", "NDBI", "NDWI", "MNDWI"]


def test_add_indices_adds_bands_in_definition_order(added_bands: dict[str, FakeBand]) -> None:
    """追加バンドの名前と順序が定義表と一致する。"""
    assert list(added_bands) == ["NDVI", "NDBI", "NDWI", "MNDWI"]


@pytest.mark.parametrize(
    ("index_name", "band_a", "band_b"),
    [
        ("NDVI", "SR_B5", "SR_B4"),
        ("NDBI", "SR_B6", "SR_B5"),
        ("NDWI", "SR_B3", "SR_B5"),
        ("MNDWI", "SR_B3", "SR_B6"),
    ],
)
def test_add_indices_computes_normalized_difference(
    added_bands: dict[str, FakeBand],
    optical_bands: dict[str, np.ndarray],
    index_name: str,
    band_a: str,
    band_b: str,
) -> None:
    """各指標が (A - B) / (A + B) で計算される（有効画素のみ比較）。"""
    band = added_bands[index_name]
    value_a = optical_bands[band_a]
    value_b = optical_bands[band_b]
    with np.errstate(divide="ignore", invalid="ignore"):
        expected = (value_a - value_b) / (value_a + value_b)

    np.testing.assert_allclose(band.values[band.mask], expected[band.mask])


def test_add_indices_masks_zero_denominator(added_bands: dict[str, FakeBand]) -> None:
    """分母がゼロ近傍の画素は、その指標だけがマスクされる。"""
    # 末尾画素は GREEN + SWIR1 = 0.2 + (-0.2) = 0 で、MNDWI のみ未定義となる。
    assert added_bands["MNDWI"].mask.tolist() == [True, True, True, False]
    for index_name in ("NDVI", "NDBI", "NDWI"):
        assert added_bands[index_name].mask.all()


def test_add_indices_mndwi_stays_within_unit_range(added_bands: dict[str, FakeBand]) -> None:
    """非負の反射率に対し、MNDWI は -1〜1 に収まる。"""
    band = added_bands["MNDWI"]
    valid_values = band.values[band.mask]

    assert np.all(valid_values >= -1.0)
    assert np.all(valid_values <= 1.0)
