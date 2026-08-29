"""src/common/analysis_dataset.py（分析用データセット読込・フィルタ・サンプリング・
フィルタ脱落の診断集計）のテスト。"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis.urban_params.tables import write_attribute_table
from src.common.analysis_dataset import (
    filter_valid_rows,
    load_analysis_dataset,
    sample_dataset,
    summarize_filter_dropout,
)


class TestLoadAnalysisDataset:
    """load_analysis_dataset のテスト。"""

    def test_reads_attribute_only_table(self, tmp_path: Path) -> None:
        """build_dataset.pyが生成する、ジオメトリを持たない属性テーブルを読み込める。

        `write_attribute_table` は `src.analysis.build_dataset` が実際に使う
        書き出し関数であり、実データセットと同じ「cell_id をキーとする属性のみの
        GeoPackage」を作る（ジオメトリ列は持たない）。
        """
        table = pd.DataFrame(
            {
                "cell_id": [1, 2],
                "lon": [105.8, 105.9],
                "lat": [21.0, 21.1],
                "NDVI": [0.4, 0.5],
            }
        )
        dataset_path = tmp_path / "dataset.gpkg"
        write_attribute_table(table, dataset_path, layer_name="dataset")

        result = load_analysis_dataset(dataset_path)

        assert "geometry" not in result.columns
        assert list(result["cell_id"]) == [1, 2]
        assert isinstance(result, pd.DataFrame)

    def test_reads_only_requested_columns(self, tmp_path: Path) -> None:
        """columnsを指定すると、その列だけを読み込む（不要な列の読込を避ける）。"""
        table = pd.DataFrame(
            {
                "cell_id": [1, 2],
                "lon": [105.8, 105.9],
                "lat": [21.0, 21.1],
                "NDVI": [0.4, 0.5],
            }
        )
        dataset_path = tmp_path / "dataset.gpkg"
        write_attribute_table(table, dataset_path, layer_name="dataset")

        result = load_analysis_dataset(dataset_path, columns=["cell_id", "NDVI"])

        # 列の並び順はストレージ側の格納順に依存するため、集合で比較する。
        assert set(result.columns) == {"cell_id", "NDVI"}
        assert list(result["cell_id"]) == [1, 2]


def _sample_dataframe() -> pd.DataFrame:
    """フィルタ条件の各分岐を1件ずつ含む合成データ。

    行1: 全条件を満たす（残るべき）
    行2: NDVIがNaN（除外されるべき）
    行3: IN_ANALYSIS_AREA=0（除外されるべき）
    行4: LST_VALID_RATIOがしきい値未満（除外されるべき）
    行5: LSTがNaN（除外されるべき）
    """
    return pd.DataFrame(
        {
            "cell_id": [1, 2, 3, 4, 5],
            "IN_ANALYSIS_AREA": [1, 1, 0, 1, 1],
            "NDVI": [0.4, np.nan, 0.3, 0.5, 0.2],
            "NDBI": [-0.1, 0.0, -0.2, -0.1, 0.1],
            "NDWI": [0.2, 0.1, 0.0, 0.2, 0.3],
            "LST": [35.0, 34.0, 33.0, 36.0, np.nan],
            "LST_VALID_RATIO": [0.9, 0.9, 0.9, 0.3, 0.9],
        }
    )


class TestFilterValidRows:
    """filter_valid_rows のテスト。"""

    def test_keeps_rows_satisfying_all_conditions(self) -> None:
        """全条件を満たす行のみが残る。"""
        dataframe = _sample_dataframe()

        result = filter_valid_rows(
            dataframe,
            feature_columns=["NDVI", "NDBI", "NDWI"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
        )

        assert list(result["cell_id"]) == [1]

    def test_excludes_rows_outside_analysis_area(self) -> None:
        """IN_ANALYSIS_AREA=0の行は除外される。"""
        dataframe = _sample_dataframe()

        result = filter_valid_rows(
            dataframe,
            feature_columns=["NDVI", "NDBI", "NDWI"],
            target_column="LST",
            lst_valid_ratio_threshold=0.0,
        )

        assert 3 not in list(result["cell_id"])

    def test_excludes_rows_with_null_feature(self) -> None:
        """説明変数がNULLの行は除外される。"""
        dataframe = _sample_dataframe()

        result = filter_valid_rows(
            dataframe,
            feature_columns=["NDVI", "NDBI", "NDWI"],
            target_column="LST",
            lst_valid_ratio_threshold=0.0,
        )

        assert 2 not in list(result["cell_id"])

    def test_excludes_rows_with_null_target(self) -> None:
        """目的変数（LST）がNULLの行は除外される。"""
        dataframe = _sample_dataframe()

        result = filter_valid_rows(
            dataframe,
            feature_columns=["NDVI", "NDBI", "NDWI"],
            target_column="LST",
            lst_valid_ratio_threshold=0.0,
        )

        assert 5 not in list(result["cell_id"])

    def test_excludes_rows_below_lst_valid_ratio_threshold(self) -> None:
        """LST_VALID_RATIOがしきい値未満の行は除外される。"""
        dataframe = _sample_dataframe()

        result = filter_valid_rows(
            dataframe,
            feature_columns=["NDVI", "NDBI", "NDWI"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
        )

        assert 4 not in list(result["cell_id"])

    def test_keeps_row_at_lst_valid_ratio_threshold_boundary(self) -> None:
        """LST_VALID_RATIOがしきい値と完全一致する行は残る（>=境界）。

        `>=` が `>` に書き換わるオフバイワン回帰を検出するため、しきい値未満の
        行が除外されることだけでなく、しきい値ちょうどの行が残ることも検証する。
        """
        dataframe = pd.DataFrame(
            {
                "cell_id": [1],
                "IN_ANALYSIS_AREA": [1],
                "NDVI": [0.4],
                "NDBI": [-0.1],
                "NDWI": [0.2],
                "LST": [35.0],
                "LST_VALID_RATIO": [0.5],
            }
        )

        result = filter_valid_rows(
            dataframe,
            feature_columns=["NDVI", "NDBI", "NDWI"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
        )

        assert list(result["cell_id"]) == [1]

    def test_excludes_rows_failing_additional_required_mask_column(self) -> None:
        """required_mask_columnsに追加した列が0の行は、他の条件を満たしていても除外される。

        Limited/FullシナリオでVALID_GIS_MASK等の追加の品質軸を課す場合を想定する。
        """
        dataframe = pd.DataFrame(
            {
                "cell_id": [1, 2],
                "IN_ANALYSIS_AREA": [1, 1],
                "NDVI": [0.4, 0.4],
                "NDBI": [-0.1, -0.1],
                "NDWI": [0.2, 0.2],
                "LST": [35.0, 35.0],
                "LST_VALID_RATIO": [0.9, 0.9],
                "VALID_GIS_MASK": [1, 0],  # cell_id=2のみVALID_GIS_MASK=0
            }
        )

        result = filter_valid_rows(
            dataframe,
            feature_columns=["NDVI", "NDBI", "NDWI"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            required_mask_columns=["IN_ANALYSIS_AREA", "VALID_GIS_MASK"],
        )

        assert list(result["cell_id"]) == [1]

    def test_resets_index(self) -> None:
        """フィルタ後のインデックスは0始まりに振り直される。"""
        dataframe = _sample_dataframe()

        result = filter_valid_rows(
            dataframe,
            feature_columns=["NDVI", "NDBI", "NDWI"],
            target_column="LST",
            lst_valid_ratio_threshold=0.0,
        )

        assert list(result.index) == list(range(len(result)))

    def test_matches_previous_behavior_with_nullable_extension_dtype_mask_column(self) -> None:
        """nullable拡張dtype（Int64）の品質列を渡しても、通常のint64列と同じ結果になる。

        内部実装をマスク構築ヘルパーへ分解した際（段階別マスクの累積AND）に、
        列の評価順が変わっている。ANDは結合順によらないため結果は変わらない
        はずだが、nullable拡張dtypeは`pd.NA`を伴うため通常のbool配列と挙動が
        異なりうる。このケースで旧実装と同じ結果になることを回帰として固定する。
        """
        dataframe = pd.DataFrame(
            {
                "cell_id": [1, 2],
                "IN_ANALYSIS_AREA": [1, 1],
                "NDVI": [0.4, 0.4],
                "NDBI": [-0.1, -0.1],
                "NDWI": [0.2, 0.2],
                "LST": [35.0, 35.0],
                "LST_VALID_RATIO": [0.9, 0.9],
                "VALID_GIS_MASK": pd.array([1, 0], dtype="Int64"),
            }
        )

        result = filter_valid_rows(
            dataframe,
            feature_columns=["NDVI", "NDBI", "NDWI"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            required_mask_columns=["IN_ANALYSIS_AREA", "VALID_GIS_MASK"],
        )

        assert list(result["cell_id"]) == [1]


class TestSampleDataset:
    """sample_dataset のテスト。"""

    def test_returns_all_rows_when_sample_size_is_zero(self) -> None:
        """sample_size=0は全件使用（サンプリングしない）を意味する。"""
        dataframe = pd.DataFrame({"value": range(100)})

        result = sample_dataset(dataframe, sample_size=0, random_state=42)

        assert len(result) == 100

    def test_samples_requested_number_of_rows(self) -> None:
        """指定した件数だけ抽出される。"""
        dataframe = pd.DataFrame({"value": range(1000)})

        result = sample_dataset(dataframe, sample_size=100, random_state=42)

        assert len(result) == 100

    def test_returns_all_rows_when_sample_size_exceeds_available_rows(self) -> None:
        """sample_sizeが元の行数を超える場合は全件を返す（エラーにしない）。"""
        dataframe = pd.DataFrame({"value": range(10)})

        result = sample_dataset(dataframe, sample_size=100, random_state=42)

        assert len(result) == 10

    def test_same_random_state_is_reproducible(self) -> None:
        """同じrandom_stateなら同じサンプルが得られる。"""
        dataframe = pd.DataFrame({"value": range(1000)})

        result_1 = sample_dataset(dataframe, sample_size=100, random_state=42)
        result_2 = sample_dataset(dataframe, sample_size=100, random_state=42)

        pd.testing.assert_frame_equal(result_1, result_2)

    def test_raises_when_sample_size_is_negative(self) -> None:
        """sample_sizeが負の場合は例外にする。"""
        dataframe = pd.DataFrame({"value": range(10)})

        with pytest.raises(ValueError, match="0以上"):
            sample_dataset(dataframe, sample_size=-1, random_state=42)


def _dropout_dataframe() -> pd.DataFrame:
    """summarize_filter_dropout の主要な分岐を1つのデータで再現する合成データ。

    段階別フィルタ列は feature_columns=["H_MEAN", "H_MAX", "POP", "NDVI"]、
    しきい値 lst_valid_ratio_threshold=0.5 を前提に設計する。

    行0: 全条件を満たす（feature_complete まで残る、母数1）
    行1: H_MEAN・H_MAX が同時にNULL（列単位のexclusiveは両方0になるが、
         column_groupsのbuilding_heightではexclusiveとして拾える）
    行2: POPのみNULL（column単位・group単位ともexclusive）
    行3: H_MEAN・H_MAX・POPが同時にNULL（列・グループいずれもexclusiveにならない）
    行4: IN_ANALYSIS_AREA=0（mask_passedで除外）
    行5: LSTがNULL（target_availableで除外）
    行6: LST_VALID_RATIOがしきい値未満（target_availableで除外）
    行7: NDVIのみNULL（column単位・group単位ともexclusive）
    """
    return pd.DataFrame(
        {
            "cell_id": [1, 2, 3, 4, 5, 6, 7, 8],
            "IN_ANALYSIS_AREA": [1, 1, 1, 1, 0, 1, 1, 1],
            "LST": [30.0, 31.0, 32.0, 33.0, 34.0, np.nan, 35.0, 36.0],
            "LST_VALID_RATIO": [0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.3, 0.9],
            "H_MEAN": [10.0, np.nan, 12.0, np.nan, 14.0, 15.0, 16.0, 14.0],
            "H_MAX": [20.0, np.nan, 22.0, np.nan, 24.0, 25.0, 26.0, 24.0],
            "POP": [100.0, 110.0, np.nan, np.nan, 130.0, 140.0, 150.0, 120.0],
            "NDVI": [0.5, 0.4, 0.3, 0.2, 0.1, 0.1, 0.1, np.nan],
        }
    )


_DROPOUT_FEATURE_COLUMNS = ["H_MEAN", "H_MAX", "POP", "NDVI"]
_DROPOUT_COLUMN_GROUPS = {
    "building_height": ["H_MEAN", "H_MAX"],
    "population": ["POP"],
    "other": ["NDVI"],
}


class TestSummarizeFilterDropout:
    """summarize_filter_dropout のテスト。"""

    def test_computes_stage_counts(self) -> None:
        """段階別母数（mask_passed→target_available→feature_complete→sampled）を集計する。"""
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=_DROPOUT_FEATURE_COLUMNS,
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=_DROPOUT_FEATURE_COLUMNS,
            column_groups=_DROPOUT_COLUMN_GROUPS,
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=1,
        )

        # mask_passed: 行4（IN_ANALYSIS_AREA=0）のみ除外 → 7件
        # target_available: 行5（LST NaN）・行6（RATIO未満）も除外 → 5件
        # （行0,1,2,3,7が対象）
        # feature_complete: H_MEAN/H_MAX/POP/NDVIが1つでもNULLの行1,2,3,7を除外 → 1件
        assert result["stages"] == {
            "dataset_row_count": 8,
            "mask_passed": 7,
            "target_available": 5,
            "feature_complete": 1,
            "sampled": 1,
        }
        assert result["base_stage"] == "target_available"

    def test_dropped_count_and_ratio(self) -> None:
        """基準段階（target_available）からの脱落数・比率を求める。"""
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=_DROPOUT_FEATURE_COLUMNS,
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=_DROPOUT_FEATURE_COLUMNS,
            column_groups=_DROPOUT_COLUMN_GROUPS,
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=1,
        )

        # target_available=5、feature_complete=1 → 脱落4件（行1,2,3,7）
        assert result["dropped_count"] == 4
        assert result["dropped_ratio"] == pytest.approx(4 / 5)

    def test_column_null_counts_are_duplicated_and_exclusive_excludes_shared_nulls(self) -> None:
        """columns.null_countは重複計上、exclusive_null_countは同時NULLの列対で0になる。"""
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=_DROPOUT_FEATURE_COLUMNS,
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=_DROPOUT_FEATURE_COLUMNS,
            column_groups=_DROPOUT_COLUMN_GROUPS,
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=1,
        )
        columns = result["columns"]

        # H_MEAN・H_MAXは行1・行3で同時にNULLになるため、両列とも
        # null_count=2だが、単独理由の行が無くexclusive_null_count=0。
        assert columns["H_MEAN"] == {
            "null_count": 2,
            "exclusive_null_count": 0,
            "target_mean": pytest.approx((31.0 + 33.0) / 2),
        }
        assert columns["H_MAX"] == {
            "null_count": 2,
            "exclusive_null_count": 0,
            "target_mean": pytest.approx((31.0 + 33.0) / 2),
        }
        # POPは行2（単独理由）・行3（H_MEAN/H_MAXとも重複）でNULL。
        # 単独理由の行2の分だけexclusive_null_count=1になる。
        assert columns["POP"] == {
            "null_count": 2,
            "exclusive_null_count": 1,
            "target_mean": pytest.approx((32.0 + 33.0) / 2),
        }
        # NDVIは行7のみNULLで、他列はすべて非NULL → 単独理由。
        assert columns["NDVI"] == {
            "null_count": 1,
            "exclusive_null_count": 1,
            "target_mean": pytest.approx(36.0),
        }
        # 列ごとのnull_countの和（2+2+2+1=7）は、行1,2,3,7の脱落数4を上回る
        # （重複計上のため）。
        assert sum(columns[c]["null_count"] for c in columns) > result["dropped_count"]

    def test_column_groups_capture_shared_null_pair_that_columns_hides(self) -> None:
        """列単位ではexclusive=0になる同時NULLペアも、グループ単位では拾える。"""
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=_DROPOUT_FEATURE_COLUMNS,
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=_DROPOUT_FEATURE_COLUMNS,
            column_groups=_DROPOUT_COLUMN_GROUPS,
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=1,
        )
        column_groups = result["column_groups"]

        # building_height（H_MEAN+H_MAX）は行1・行3でNULLだが、行1は
        # グループ外（POP・NDVI）が全て非NULLのため単独理由（exclusive）。
        # 行3はPOPも同時にNULLのため単独理由にならない → exclusive_null_count=1。
        assert column_groups["building_height"] == {
            "null_count": 2,
            "exclusive_null_count": 1,
            "target_mean": pytest.approx((31.0 + 33.0) / 2),
        }
        # population（POP）: 行2は単独理由、行3はbuilding_heightと重複。
        assert column_groups["population"] == {
            "null_count": 2,
            "exclusive_null_count": 1,
            "target_mean": pytest.approx((32.0 + 33.0) / 2),
        }
        # other（NDVI）: 行7のみで単独理由。
        assert column_groups["other"] == {
            "null_count": 1,
            "exclusive_null_count": 1,
            "target_mean": pytest.approx(36.0),
        }

    def test_raises_when_summary_column_not_in_any_group(self) -> None:
        """summary_columnsの列がcolumn_groupsのいずれにも属さない場合は例外にする。"""
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        with pytest.raises(ValueError, match="NDVI"):
            summarize_filter_dropout(
                dataframe,
                feature_columns=_DROPOUT_FEATURE_COLUMNS,
                target_column="LST",
                lst_valid_ratio_threshold=0.5,
                summary_columns=_DROPOUT_FEATURE_COLUMNS,
                column_groups={"building_height": ["H_MEAN", "H_MAX"], "population": ["POP"]},
                block_id=block_id,
                block_size_m=2_700,
                sampled_row_count=1,
            )

    def test_missing_summary_columns_are_skipped_and_recorded(self) -> None:
        """データフレームに存在しない要約対象列は例外にせず、missing_summary_columnsへ記録する。"""
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=_DROPOUT_FEATURE_COLUMNS,
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=[*_DROPOUT_FEATURE_COLUMNS, "MISSING_COLUMN"],
            column_groups={
                "building_height": ["H_MEAN", "H_MAX"],
                "population": ["POP"],
                "other": ["NDVI", "MISSING_COLUMN"],
            },
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=1,
        )

        assert result["missing_summary_columns"] == ["MISSING_COLUMN"]
        assert "MISSING_COLUMN" not in result["columns"]
        # otherグループは存在する列（NDVI）のみで集計され、欠落列があっても
        # 例外にはならない。
        assert result["column_groups"]["other"]["null_count"] == 1

    def test_dropped_summary_compares_dropped_and_final_populations(self) -> None:
        """dropped_summaryは脱落セルと最終母数を列ごとの平均・非NULL件数で対比する。"""
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=_DROPOUT_FEATURE_COLUMNS,
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=_DROPOUT_FEATURE_COLUMNS,
            column_groups=_DROPOUT_COLUMN_GROUPS,
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=1,
        )
        dropped_summary = result["dropped_summary"]

        # 脱落セル（行1,2,3,7）のNDVI: [0.4, 0.3, 0.2, NaN] → 非NULL3件、平均0.3。
        assert dropped_summary["NDVI"]["dropped"] == {
            "mean": pytest.approx(0.3),
            "non_null_count": 3,
        }
        # 最終母数（行0のみ）のNDVI: [0.5] → 非NULL1件、平均0.5。
        assert dropped_summary["NDVI"]["final"] == {
            "mean": pytest.approx(0.5),
            "non_null_count": 1,
        }
        # 脱落セルのPOP: [110.0, NaN, NaN, 120.0] → 非NULL2件、平均115.0。
        assert dropped_summary["POP"]["dropped"] == {
            "mean": pytest.approx(115.0),
            "non_null_count": 2,
        }

    def test_target_distribution_before_and_after(self) -> None:
        """target_distributionは「前」=target_available、「後」=feature_completeの分布を返す。"""
        dataframe = pd.DataFrame(
            {
                "cell_id": [1, 2, 3, 4, 5],
                "IN_ANALYSIS_AREA": [1, 1, 1, 1, 1],
                "LST": [10.0, 20.0, 30.0, 40.0, 50.0],
                "LST_VALID_RATIO": [0.9, 0.9, 0.9, 0.9, 0.9],
                # 行5（cell_id=5）だけFがNULL → feature_completeから脱落する。
                "F": [1.0, 1.0, 1.0, 1.0, np.nan],
            }
        )
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=["F"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=["F"],
            column_groups={"other": ["F"]},
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=4,
        )
        before = result["target_distribution"]["before"]
        after = result["target_distribution"]["after"]

        # before（target_available、5件: 10,20,30,40,50）
        assert before["count"] == 5
        assert before["mean"] == pytest.approx(30.0)
        assert before["std"] == pytest.approx(math.sqrt(250.0))
        assert before["min"] == pytest.approx(10.0)
        assert before["max"] == pytest.approx(50.0)
        assert before["p25"] == pytest.approx(20.0)
        assert before["p50"] == pytest.approx(30.0)
        assert before["p75"] == pytest.approx(40.0)

        # after（feature_complete、4件: 10,20,30,40）
        assert after["count"] == 4
        assert after["mean"] == pytest.approx(25.0)
        assert after["std"] == pytest.approx(math.sqrt(500.0 / 3.0))
        assert after["min"] == pytest.approx(10.0)
        assert after["max"] == pytest.approx(40.0)
        assert after["p50"] == pytest.approx(25.0)

    def test_spatial_blocks_dropout_distribution(self) -> None:
        """spatial_blocksはブロック別脱落率の分布とn_blocksを集計する。"""
        dataframe = pd.DataFrame(
            {
                "cell_id": [1, 2, 3, 4, 5, 6],
                "IN_ANALYSIS_AREA": [1, 1, 1, 1, 1, 1],
                "LST": [30.0] * 6,
                "LST_VALID_RATIO": [0.9] * 6,
                # ブロックA（行0,1）: 1/2脱落=50% / ブロックB（行2,3）: 0/2脱落=0%
                # ブロックC（行4,5）: 2/2脱落=100%
                "F": [1.0, np.nan, 1.0, 1.0, np.nan, np.nan],
            }
        )
        block_id = np.array([100, 100, 200, 200, 300, 300])

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=["F"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=["F"],
            column_groups={"other": ["F"]},
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=3,
        )
        spatial_blocks = result["spatial_blocks"]

        assert spatial_blocks["n_blocks"] == 3
        assert spatial_blocks["block_size_m"] == 2_700
        # ratio>50%はブロックC（100%）のみ。ブロックA（50%ちょうど）は含まない。
        assert spatial_blocks["blocks_over_50pct"] == 1
        assert spatial_blocks["dropped_ratio"]["median"] == pytest.approx(0.5)
        assert spatial_blocks["dropped_ratio"]["p90"] == pytest.approx(0.9)
        assert spatial_blocks["dropped_ratio"]["p99"] == pytest.approx(0.99)
        assert spatial_blocks["dropped_ratio"]["max"] == pytest.approx(1.0)

    def test_handles_empty_target_available_population(self) -> None:
        """target_availableが0件でも例外にせず、分布・ブロック集計はNoneで埋める。"""
        dataframe = pd.DataFrame(
            {
                "cell_id": [1],
                "IN_ANALYSIS_AREA": [0],  # mask_passedで除外 → target_available=0件
                "LST": [30.0],
                "LST_VALID_RATIO": [0.9],
                "F": [1.0],
            }
        )
        block_id = np.array([1])

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=["F"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=["F"],
            column_groups={"other": ["F"]},
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=0,
        )

        assert result["stages"]["target_available"] == 0
        assert result["dropped_ratio"] is None
        assert result["target_distribution"]["before"] == {
            "count": 0,
            "mean": None,
            "std": None,
            "min": None,
            "p1": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p99": None,
            "max": None,
        }
        assert result["spatial_blocks"] == {
            "n_blocks": 0,
            "block_size_m": 2_700,
            "dropped_ratio": {"median": None, "p90": None, "p99": None, "max": None},
            "blocks_over_50pct": 0,
        }
        assert result["columns"]["F"]["target_mean"] is None

    def test_raises_when_block_id_length_mismatches_dataframe(self) -> None:
        """block_idの長さがdataframeの行数と一致しない場合は例外にする。"""
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe) - 1, dtype=np.int64)  # 1件足りない

        with pytest.raises(ValueError, match="block_id"):
            summarize_filter_dropout(
                dataframe,
                feature_columns=_DROPOUT_FEATURE_COLUMNS,
                target_column="LST",
                lst_valid_ratio_threshold=0.5,
                summary_columns=_DROPOUT_FEATURE_COLUMNS,
                column_groups=_DROPOUT_COLUMN_GROUPS,
                block_id=block_id,
                block_size_m=2_700,
                sampled_row_count=1,
            )

    def test_sampled_row_count_is_recorded_as_given(self) -> None:
        """stages.sampledはsummarize_filter_dropout自身のサンプリング結果ではなく、
        引数でもらった値をそのまま記録する。"""
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=_DROPOUT_FEATURE_COLUMNS,
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=_DROPOUT_FEATURE_COLUMNS,
            column_groups=_DROPOUT_COLUMN_GROUPS,
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=42,
        )

        assert result["stages"]["sampled"] == 42

    def test_raises_when_column_group_references_column_not_in_summary_columns(self) -> None:
        """column_groupsの列がsummary_columnsに含まれない場合は例外にする。

        summary_columns側への割り当て漏れ（例: H_MAXをcolumn_groupsに残したまま
        summary_columnsから外す）は、逆方向検証が無いと無言で集計から抜け落ち、
        グループ単位の脱落数が過小に出る。片方向だけでなく両方向を検証する。
        """
        dataframe = _dropout_dataframe()
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        with pytest.raises(ValueError, match="H_MAX"):
            summarize_filter_dropout(
                dataframe,
                feature_columns=_DROPOUT_FEATURE_COLUMNS,
                target_column="LST",
                lst_valid_ratio_threshold=0.5,
                # H_MAXをsummary_columnsから外すが、column_groupsには残す。
                summary_columns=["H_MEAN", "POP", "NDVI"],
                column_groups=_DROPOUT_COLUMN_GROUPS,
                block_id=block_id,
                block_size_m=2_700,
                sampled_row_count=1,
            )

    def test_distribution_stats_sanitize_infinite_min_max_and_quantiles(self) -> None:
        """target_distributionのmin/max/分位点も、meanやstdと同様にInfをNoneへ変換する。

        `_none_if_nan` はmean/stdだけでなくmin/max/p1〜p99にも適用する必要がある。
        対象列にInf（NaNではない）が混入していても`count`には含まれるため、
        素のfloat()変換だけだとInfがそのまま返り、`save_summary`
        （allow_nan=False）で例外になりうる。
        """
        dataframe = pd.DataFrame(
            {
                "cell_id": [1, 2, 3],
                "IN_ANALYSIS_AREA": [1, 1, 1],
                "LST": [10.0, 20.0, np.inf],
                "LST_VALID_RATIO": [0.9, 0.9, 0.9],
                "F": [1.0, 1.0, 1.0],
            }
        )
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=["F"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=["F"],
            column_groups={"other": ["F"]},
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=3,
        )
        before = result["target_distribution"]["before"]

        # Infを含む列のmean/stdは元々Infではなくmath.isfinite=Falseになるため
        # Noneに変換される。ここで検証したいのはmax（Inf自身が最大値になる
        # ケース）がNoneへ変換されることと、mean/stdも連動してNoneになること。
        assert before["max"] is None
        assert before["mean"] is None
        assert before["std"] is None
        # min・p1・p25はInfの影響を受けない値のはずで、有限のまま返る。
        assert before["min"] == pytest.approx(10.0)
        assert before["p1"] == pytest.approx(10.2)
        assert before["p25"] == pytest.approx(15.0)

    def test_handles_nullable_extension_dtype_mask_column_with_missing_value(self) -> None:
        """required_mask_columnsにpd.NAを含むnullable拡張dtype列を渡しても例外にならない。

        nullable拡張dtype（Int64等）で実際に欠損（pd.NA）を含む列を渡すと、
        `_build_filter_masks` が返すマスクが一時的にnullable booleanになりうる。
        `.fillna(False)` で確定させずに`.to_numpy()`すると`object`dtype配列に
        化け、`block_id_array[...]`のブールインデックス参照が
        `IndexError: arrays used as indices must be of integer (or boolean) type`
        で壊れる（現状のbuild_dataset.pyはこの品質列をint8で生成しており欠損は
        乗らないため実害は無いが、防御的にfillna(False)で確定させて防ぐ）。
        """
        dataframe = pd.DataFrame(
            {
                "cell_id": [1, 2, 3],
                "IN_ANALYSIS_AREA": [1, 1, 1],
                "VALID_GIS_MASK": pd.array([1, pd.NA, 1], dtype="Int64"),
                "LST": [10.0, 20.0, 30.0],
                "LST_VALID_RATIO": [0.9, 0.9, 0.9],
                "F": [1.0, 1.0, 1.0],
            }
        )
        block_id = np.zeros(len(dataframe), dtype=np.int64)

        result = summarize_filter_dropout(
            dataframe,
            feature_columns=["F"],
            target_column="LST",
            lst_valid_ratio_threshold=0.5,
            summary_columns=["F"],
            column_groups={"other": ["F"]},
            block_id=block_id,
            block_size_m=2_700,
            sampled_row_count=2,
            required_mask_columns=["IN_ANALYSIS_AREA", "VALID_GIS_MASK"],
        )

        # VALID_GIS_MASKがpd.NAの行（cell_id=2）は、filter_valid_rowsが
        # `.loc[]`で除外するのと同じくmask_passedを通過しない扱いになる
        # （NAを「条件を満たさない」側として確定させる）。
        assert result["stages"]["mask_passed"] == 2
        assert result["stages"]["target_available"] == 2
