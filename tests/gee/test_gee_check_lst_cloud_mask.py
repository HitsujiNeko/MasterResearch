"""gee_check_lst_cloud_mask.py（LST 雲マスクの QA ビット検証）のテスト。

GEE への接続を伴わない範囲のみを対象とする。マスク候補の判定は、1 画素の
QA_PIXEL / QA_RADSAT 値を持つ偽の `ee.Image` に適用して確認し、本番の
`cloud_mask`（採用した `plus_cirrus_snow`）/ `cloud_mask_sr`（`indices_equivalent`）と
同じ画素を残すことを確かめる。
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

import src.gee.gee_check_lst_cloud_mask as check
from src.gee.gee_calc_LST import cloud_mask
from src.gee.gee_calc_satellite_indices import cloud_mask_sr


class _FakePixel:
    """`ee.Image` の 1 画素を模し、整数値に対するビット演算・比較・論理積を再現する。"""

    def __init__(self, value: int) -> None:
        self.value = value

    def bitwiseAnd(self, other: int) -> "_FakePixel":
        return _FakePixel(self.value & other)

    def eq(self, other: int) -> "_FakePixel":
        return _FakePixel(int(self.value == other))

    def And(self, other: "_FakePixel") -> "_FakePixel":
        return _FakePixel(int(bool(self.value) and bool(other.value)))


class _FakeImage:
    """QA_PIXEL・QA_RADSAT を持つ 1 画素の `ee.Image` を模す。

    `updateMask` は呼ばれるたびにマスクを論理積で重ね、`kept` で画素が残るかを返す。
    """

    def __init__(self, qa_pixel: int, qa_radsat: int = 0, kept: bool = True) -> None:
        self.bands = {"QA_PIXEL": qa_pixel, "QA_RADSAT": qa_radsat}
        self.kept = kept

    def select(self, name: str) -> _FakePixel:
        return _FakePixel(self.bands[name])

    def updateMask(self, mask: _FakePixel) -> "_FakeImage":
        return _FakeImage(
            self.bands["QA_PIXEL"],
            self.bands["QA_RADSAT"],
            kept=self.kept and bool(mask.value),
        )


def _variant(name: str) -> check.MaskVariant:
    """候補名から `MaskVariant` を取り出す。"""
    return next(variant for variant in check.MASK_VARIANTS if variant.name == name)


def _kept_by_variant(name: str, qa_pixel: int, qa_radsat: int = 0) -> bool:
    """候補のマスクで 1 画素が残るかを返す。"""
    image = _FakeImage(qa_pixel, qa_radsat)
    return bool(check.build_variant_mask(image, _variant(name)).value)


# --- ビット定義・マスク候補 ---


@pytest.mark.parametrize(
    ("bits", "expected"),
    [((3, 4), 0b11000), ((0,), 1), ((1, 2, 3, 4), 0b11110), ((15,), 1 << 15)],
)
def test_build_qa_bit_mask(bits: tuple, expected: int) -> None:
    """指定したビットだけを立てたマスク値を返す。"""
    assert check.build_qa_bit_mask(bits) == expected


@pytest.mark.parametrize("bits", [(), (16,), (-1,)])
def test_build_qa_bit_mask_invalid_bits_raise(bits: tuple) -> None:
    """空の指定や 0〜15 の範囲外のビット番号は例外とする。"""
    with pytest.raises(ValueError):
        check.build_qa_bit_mask(bits)


def test_qa_pixel_bit_definitions_follow_usgs() -> None:
    """フラグと信頼度フィールドのビット位置が USGS の Landsat 8-9 定義と一致する。"""
    assert check.QA_PIXEL_FLAG_BITS == {
        "fill": 0,
        "dilated_cloud": 1,
        "cirrus": 2,
        "cloud": 3,
        "cloud_shadow": 4,
        "snow": 5,
        "clear": 6,
        "water": 7,
    }
    assert check.QA_PIXEL_CONFIDENCE_FIELDS == {
        "cloud_confidence": 8,
        "cloud_shadow_confidence": 10,
        "snow_ice_confidence": 12,
        "cirrus_confidence": 14,
    }


def test_mask_variants_are_as_planned() -> None:
    """比較する候補は 7 つで、先頭が変更前のマスク（bit 3・4）である。"""
    assert [(v.name, v.bits, v.require_radsat_zero) for v in check.MASK_VARIANTS] == [
        ("current", (3, 4), False),
        ("plus_dilated", (1, 3, 4), False),
        ("plus_cirrus", (2, 3, 4), False),
        ("plus_dilated_cirrus", (1, 2, 3, 4), False),
        ("plus_snow", (3, 4, 5), False),
        ("plus_cirrus_snow", (2, 3, 4, 5), False),
        ("indices_equivalent", (0, 1, 2, 3, 4, 5), True),
    ]
    assert check.MASK_VARIANTS[0].name == check.CURRENT_VARIANT_NAME


def test_adopted_variant_matches_production_cloud_mask_for_all_qa_values() -> None:
    """採用した `plus_cirrus_snow` は全 QA_PIXEL 値（0〜65535）で本番の `cloud_mask` と
    同じ画素を残す。"""
    mismatches = [
        qa
        for qa in range(1 << 16)
        if _kept_by_variant("plus_cirrus_snow", qa) != cloud_mask(_FakeImage(qa)).kept
    ]

    assert mismatches == []


@pytest.mark.parametrize("qa_radsat", [0, 1, 0b100000])
def test_indices_equivalent_matches_production_cloud_mask_sr(qa_radsat: int) -> None:
    """`indices_equivalent` は全 QA_PIXEL 値で衛星指標側の `cloud_mask_sr` と同じ画素を残す。"""
    mismatches = [
        qa
        for qa in range(1 << 16)
        if _kept_by_variant("indices_equivalent", qa, qa_radsat)
        != cloud_mask_sr(_FakeImage(qa, qa_radsat)).kept
    ]

    assert mismatches == []


@pytest.mark.parametrize(
    ("name", "qa_pixel", "kept"),
    [
        ("current", 1 << 1, True),
        ("plus_dilated", 1 << 1, False),
        ("plus_dilated", 1 << 2, True),
        ("plus_cirrus", 1 << 2, False),
        ("plus_cirrus", 1 << 1, True),
        ("plus_dilated_cirrus", 1 << 1, False),
        ("plus_dilated_cirrus", 1 << 2, False),
        ("plus_dilated_cirrus", 1 << 5, True),
        ("current", 1 << 5, True),
        ("plus_snow", 1 << 5, False),
        ("plus_snow", 1 << 2, True),
        ("plus_snow", 1 << 1, True),
        ("plus_cirrus_snow", 1 << 5, False),
        ("plus_cirrus_snow", 1 << 2, False),
        ("plus_cirrus_snow", 1 << 1, True),
    ],
)
def test_variants_differ_only_in_added_bits(name: str, qa_pixel: int, kept: bool) -> None:
    """各候補は追加したビットの画素だけを新たに除外する。"""
    assert _kept_by_variant(name, qa_pixel) is kept


# --- 対象シーンの選定 ---


def _results_df() -> pd.DataFrame:
    """探索結果CSVを模した小さな表。"""
    return pd.DataFrame(
        {
            "scene_index": ["LC09_A", "LC08_B", "LC08_C", "LC09_D", "LC08_E"],
            "observation_datetime_utc": [
                "2022-09-30T03:23:46",
                "2023-07-07T03:23:05",
                "2024-11-30T03:23:36",
                "2022-07-21T03:17:32",
                "2023-01-01T03:00:00",
            ],
            "lst_min_temp_c": [-102.2, 23.7, 13.5, -45.4, 10.0],
        }
    )


def _ranking_df() -> pd.DataFrame:
    """ランキングCSVを模した表（実効ROIカバー率の降順）。"""
    return pd.DataFrame({"scene_index": ["LC08_C", "LC08_B", "LC09_A", "LC08_E"]})


def test_select_target_scenes_default_union_with_reasons() -> None:
    """既定では閾値未満・ランキング上位・採用観測の和集合を、理由つき・日時順で返す。"""
    selected = check.select_target_scenes(
        _results_df(),
        _ranking_df(),
        threshold_c=-20.0,
        top_n=2,
        adopted_observations=["2023-07-07T03:23:05"],
    )

    assert selected["scene_index"].tolist() == ["LC09_D", "LC09_A", "LC08_B", "LC08_C"]
    assert selected["selection_reason"].tolist() == [
        "lst_min_below_threshold",
        "lst_min_below_threshold",
        "ranking_top2;adopted",
        "ranking_top2",
    ]


def test_select_target_scenes_threshold_is_strict() -> None:
    """閾値ちょうどの観測は対象にしない（「未満」で判定する）。"""
    selected = check.select_target_scenes(
        _results_df(), _ranking_df(), threshold_c=-45.4, top_n=0, adopted_observations=[]
    )

    assert selected["scene_index"].tolist() == ["LC09_A"]


def test_select_target_scenes_specified_overrides_default() -> None:
    """`scene_indices` を指定した場合はそれだけを対象にする。"""
    selected = check.select_target_scenes(
        _results_df(),
        _ranking_df(),
        threshold_c=-20.0,
        top_n=2,
        adopted_observations=["2023-07-07T03:23:05"],
        scene_indices=["LC09_A"],
    )

    assert selected["scene_index"].tolist() == ["LC09_A"]
    assert selected["selection_reason"].tolist() == ["specified"]


def test_select_target_scenes_unknown_scene_raises() -> None:
    """探索結果CSVに無い system:index を指定すると例外とする。"""
    with pytest.raises(ValueError, match="LC09_X"):
        check.select_target_scenes(
            _results_df(),
            _ranking_df(),
            threshold_c=-20.0,
            top_n=2,
            adopted_observations=[],
            scene_indices=["LC09_X"],
        )


def test_select_target_scenes_unknown_adopted_observation_raises() -> None:
    """探索結果CSVに無い採用観測を指定すると例外とする（黙って対象から落とさない）。"""
    with pytest.raises(ValueError, match="2099-01-01"):
        check.select_target_scenes(
            _results_df(),
            _ranking_df(),
            threshold_c=-20.0,
            top_n=2,
            adopted_observations=["2099-01-01T00:00:00"],
        )


@pytest.mark.parametrize(
    ("scene_index", "expected"),
    [("LC08_127045_20230707", "L8"), ("LC09_127045_20220930", "L9")],
)
def test_sensor_from_scene_index(scene_index: str, expected: str) -> None:
    """system:index の接頭辞からセンサ名を返す。"""
    assert check.sensor_from_scene_index(scene_index) == expected


def test_sensor_from_scene_index_unknown_raises() -> None:
    """LC08 / LC09 以外は例外とする。"""
    with pytest.raises(ValueError, match="未対応"):
        check.sensor_from_scene_index("LE07_127045_20230707")


# --- 集計結果の整形 ---


def _scene() -> dict:
    """対象シーンの情報を模した辞書。"""
    return {
        "scene_index": "LC09_127045_20220930",
        "observation_datetime_utc": "2022-09-30T03:23:46",
        "satellite": "Landsat9",
        "selection_reason": "lst_min_below_threshold",
        "scene_coverage_ratio": 0.9,
        "indices_effective_roi_coverage": 50.0,
    }


def test_build_variant_rows_computes_ratios_like_search_script() -> None:
    """有効画素率（0-100）と実効ROIカバー率（被覆率×有効画素率）を探索と同じ定義で出す。"""
    stats = {"lst__total_count": 1000}
    for index, variant in enumerate(check.MASK_VARIANTS):
        stats[f"lst__{variant.name}_count"] = 900 - index * 100
        stats[f"lst__{variant.name}_min"] = -100.0 + index
        stats[f"lst__{variant.name}_mean"] = 25.0
        stats[f"lst__{variant.name}_max"] = 40.0
        stats[f"lst__{variant.name}_stdDev"] = 5.0
        stats[f"below__{variant.name}_count"] = 10 - index

    rows = check.build_variant_rows(_scene(), stats, threshold_c=-20.0)

    assert [row["variant"] for row in rows] == [v.name for v in check.MASK_VARIANTS]
    current = rows[0]
    assert current["lst_valid_pixel_ratio"] == pytest.approx(90.0)
    assert current["lst_effective_roi_coverage"] == pytest.approx(81.0)
    # 指標側（50.0）のほうが小さいので選定キーは指標側の値になる
    assert current["effective_roi_coverage"] == pytest.approx(50.0)
    assert current["mask_bits"] == "3;4"
    assert current["below_threshold_pixels"] == 10
    assert current["lst_min_temp_c"] == pytest.approx(-100.0)
    # 最後の候補（indices_equivalent）は有効画素 300 → 30%、LST 側（27.0）が選定キーになる
    last = rows[-1]
    assert last["lst_valid_pixel_ratio"] == pytest.approx(30.0)
    assert last["effective_roi_coverage"] == pytest.approx(27.0)
    assert last["require_radsat_zero"] is True


def test_build_variant_rows_handles_missing_values() -> None:
    """有効画素が無い候補は画素数 0・統計量 NaN とし、全体画素が 0 でも割り算で落ちない。"""
    rows = check.build_variant_rows(_scene(), {"lst__total_count": None}, threshold_c=-20.0)

    assert all(row["lst_total_pixels"] == 0 for row in rows)
    assert all(row["lst_valid_pixel_ratio"] == 0.0 for row in rows)
    assert all(math.isnan(row["lst_min_temp_c"]) for row in rows)
    assert all(row["below_threshold_pixels"] == 0 for row in rows)


def test_merge_variant_results_adds_count_suffix() -> None:
    """画素数のキーに `_count` を付け、統計量と 1 つの辞書にまとめる。"""
    merged = check.merge_variant_results(
        {"lst__total": 1000, "lst__current": 900, "below__current": 5},
        {"lst__current_min": -10.0, "lst__current_mean": 25.0},
    )

    assert merged == {
        "lst__total_count": 1000,
        "lst__current_count": 900,
        "below__current_count": 5,
        "lst__current_min": -10.0,
        "lst__current_mean": 25.0,
    }


def test_anomaly_band_names() -> None:
    """フラグ 8 個・信頼度 4 フィールド × 4 段階・QA_RADSAT の計 25 列。"""
    names = check.anomaly_band_names()

    assert len(names) == 25
    assert names[:8] == list(check.QA_PIXEL_FLAG_BITS)
    assert names[8:12] == [f"cloud_confidence_{level}" for level in range(4)]
    assert names[-1] == "radsat_nonzero"


def test_build_anomaly_row() -> None:
    """集計値を整数の画素数に変換し、欠けている列は 0 とする。"""
    sums = {"anomaly_pixels": 120.0, "cloud": 3.0, "dilated_cloud": 117.4, "cirrus": None}

    row = check.build_anomaly_row(_scene(), sums, threshold_c=-20.0)

    assert row["scene_index"] == "LC09_127045_20220930"
    assert row["threshold_c"] == -20.0
    assert row["anomaly_pixels"] == 120
    assert row["cloud"] == 3
    assert row["dilated_cloud"] == 117
    assert row["cirrus"] == 0
    assert row["radsat_nonzero"] == 0
    assert list(row)[: len(check.SCENE_META_COLUMNS)] == list(check.SCENE_META_COLUMNS)


@pytest.mark.parametrize(
    ("value", "expected"), [(None, 0), (float("nan"), 0), (3.0, 3), (2.6, 3), (0, 0)]
)
def test_to_count(value: object, expected: int) -> None:
    """None・NaN は 0、小数は四捨五入した整数にする。"""
    assert check.to_count(value) == expected
