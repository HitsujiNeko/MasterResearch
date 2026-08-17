"""src/common/analysis_dataset.py（分析用データセット読込・フィルタ・サンプリング）のテスト。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analysis.urban_params.tables import write_attribute_table
from src.common.analysis_dataset import filter_valid_rows, load_analysis_dataset, sample_dataset


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
