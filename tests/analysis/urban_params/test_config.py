"""config.py（レイヤ構成・出力レイアウトの定義）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.analysis.urban_params.config import (
    CITY_CONFIG,
    PARAM_SETS,
    PARAMS_OUTPUT_PARTS,
    POPULATION_BASE_COLUMNS,
    ParamSet,
    grid_layer_name,
    resolve_table_path,
)

CITY_KEY = "hanoi"


@pytest.mark.parametrize(
    ("table_names", "label"),
    [
        (("build_gba", "build_dc"), "建物"),
        (("road_osm", "road_gt"), "道路"),
        (("ntl_viirs2023", "ntl_bm2023"), "夜間光"),
        (("lulc_glc2022", "lulc_esri2022"), "土地被覆"),
    ],
)
def test_param_sets_of_same_module_declare_identical_columns(
    table_names: tuple[str, ...], label: str
) -> None:
    """同じモジュールを使う別ソース版は、同じ列名を宣言する。

    感度分析で結合先を差し替えられるという設計の狙いは、この一致に依存する。
    片方の ``columns`` だけを変えても ``validate_computed_columns()`` は個別には
    通るため、列が揃わないことに気づくのは結合フェーズまで遅れる。
    """
    columns = {name: PARAM_SETS[name].columns for name in table_names}
    modules = {PARAM_SETS[name].module_name for name in table_names}

    assert len(modules) == 1, f"{label}の別ソース版が異なるモジュールを指しています: {modules}"
    assert len(set(columns.values())) == 1, f"{label}の別ソース版で列が揃っていません: {columns}"


def _population_param_sets() -> dict[str, object]:
    """人口モジュールを使うパラメータセットを抜き出す。"""
    return {
        name: param_set
        for name, param_set in PARAM_SETS.items()
        if param_set.module_name == "population"
    }


def test_population_param_sets_declare_distinct_columns() -> None:
    """人口の別ソース版は、互いに異なる列名を宣言する。

    建物・道路・夜間光の別ソース版は同一概念の「差し替え候補」であり同名でよい。
    一方、人口の3版は概念（居住人口 / 実効人口）も観測年も異なる**別変数**であり、
    説明力の差が概念差によるものか年差によるものかを分離するには、同一データセットへ
    同時に結合する必要がある。列名が重なると ``build_dataset.py`` の ``join_tables()``
    が衝突として結合を拒否し、この分離ができなくなる。
    """
    population_sets = _population_param_sets()
    assert len(population_sets) >= 2, "人口のパラメータセットが揃っていません"

    owner_of_column: dict[str, str] = {}
    for name, param_set in population_sets.items():
        for column in param_set.columns:
            previous = owner_of_column.get(column)
            assert previous is None, (
                f"人口の別ソース版で列名が重複しています: {column}（{previous} と {name}）"
            )
            owner_of_column[column] = name


def test_population_columns_follow_source_suffix_rule() -> None:
    """人口の宣言列は、基底名へデータソース接尾辞を付けた形になる。

    接尾辞の付与は ``run.py`` の ``apply_column_suffix()`` が行うため、宣言と付与規則が
    食い違うと ``validate_computed_columns()`` が実行時まで検知できない。
    """
    for name, param_set in _population_param_sets().items():
        assert param_set.column_suffix, f"{name} に接尾辞が宣言されていません"
        expected = tuple(f"{base}_{param_set.column_suffix}" for base in POPULATION_BASE_COLUMNS)
        assert param_set.columns == expected, f"{name} の列名が接尾辞規則と一致しません"


def test_column_suffix_is_declared_consistently_within_each_module() -> None:
    """接尾辞の宣言はモジュール単位で揃い、列名は基底名＋接尾辞になる。

    **特定のモジュール名を例外として書かない。** 「人口だけが接尾辞を持つ」と固定すると、
    同時結合が要る別ソースを他のパラメータへ追加したとき（設定のコメントは GHS-POP 等の
    追加を想定している）に、規約違反ではないのにテストが落ちる。逆に、人口モジュールへ
    接尾辞を宣言し忘れたセットを足しても、例外側に落ちるため検知できない。

    固定するのは規約そのもの、すなわち「同じモジュールの別ソース版は接尾辞の有無が揃い、
    接尾辞を外せば同一の基底名になる」という不変条件である。これが崩れると、片方だけが
    列名衝突を免れる半端な状態や、``run.py`` の ``apply_column_suffix()`` が組み立てる
    列名と宣言列の食い違いが生じる。
    """
    sets_by_module: dict[str, list[tuple[str, ParamSet]]] = {}
    for name, param_set in PARAM_SETS.items():
        sets_by_module.setdefault(param_set.module_name, []).append((name, param_set))

    for module_name, entries in sets_by_module.items():
        suffixed = [name for name, param_set in entries if param_set.column_suffix]
        assert len(suffixed) in (0, len(entries)), (
            f"{module_name} で接尾辞の有無が揃っていません（宣言あり: {sorted(suffixed)}）"
        )

        base_columns: set[tuple[str, ...]] = set()
        for name, param_set in entries:
            if not param_set.column_suffix:
                base_columns.add(param_set.columns)
                continue
            tail = f"_{param_set.column_suffix}"
            for column in param_set.columns:
                assert column.endswith(tail), (
                    f"{name} の列 {column} が接尾辞 {tail} で終わっていません"
                )
            base_columns.add(tuple(column[: -len(tail)] for column in param_set.columns))

        assert len(base_columns) == 1, (
            f"{module_name} の別ソース版で基底の列名が揃っていません: {sorted(base_columns)}"
        )


def test_grid_layer_name_matches_canonical_grid_naming() -> None:
    """レイヤ名は canonical_grid が書き出す grid_{scale}m 形式になる。"""
    assert grid_layer_name(30) == "grid_30m"
    assert grid_layer_name(300) == "grid_300m"


def test_resolve_table_path_uses_scale_directory(tmp_path: Path) -> None:
    """出力先は {city}/{scale}m/{テーブル名}.gpkg の階層になる。"""
    path = resolve_table_path("hanoi", 90, "build_gba", base_dir=tmp_path)

    assert path == tmp_path / "hanoi" / "90m" / "build_gba.gpkg"


def test_resolve_table_path_default_root_is_project_relative() -> None:
    """既定の出力ルートは data/output/params 配下（プロジェクトルート基準）になる。"""
    path = resolve_table_path("hanoi", 30, "road_osm")

    assert path.parts[-4:] == ("params", "hanoi", "30m", "road_osm.gpkg")
    assert path.is_absolute()
    assert PARAMS_OUTPUT_PARTS == ("data", "output", "params")


def test_resolve_table_path_separates_sources_by_table_name(tmp_path: Path) -> None:
    """同じ列を持つ別ソースのテーブルが別ファイルへ分かれる。"""
    gba_path = resolve_table_path("hanoi", 30, "build_gba", base_dir=tmp_path)
    dc_path = resolve_table_path("hanoi", 30, "build_dc", base_dir=tmp_path)

    assert gba_path != dc_path
    assert gba_path.parent == dc_path.parent


def test_city_config_declares_analysis_epsg() -> None:
    """都市設定は面積・距離計算に使う投影EPSGを持つ。"""
    assert CITY_CONFIG[CITY_KEY]["analysis_epsg"] == 5897


def test_raster_param_sets_reference_declared_raster_input() -> None:
    """ラスタ入力のパラメータセットは、都市設定に実在する ``rasters`` キーを指す。

    キー名を打ち間違えても、失敗するのは入力解決に到達した実行時である。
    パラメータセットを追加した時点で気づけるよう、宣言どうしの対応を検査する。
    """
    declared_keys = set(CITY_CONFIG[CITY_KEY]["rasters"])
    referenced = {
        name: param_set.input_key
        for name, param_set in PARAM_SETS.items()
        if param_set.input_kind == "raster"
    }

    missing = {name: key for name, key in referenced.items() if key not in declared_keys}
    assert not missing, f"CITY_CONFIG['{CITY_KEY}']['rasters'] に無い入力キーです: {missing}"


def test_raster_param_sets_declare_band_index() -> None:
    """``rasters`` の各エントリはバンド番号を明示する。

    人口ラスタはカウント（band 1）と密度（band 2）を1ファイルに持つため、
    バンド番号の省略は既定値1＝カウントの黙った採用につながる。
    """
    for key, entry in CITY_CONFIG[CITY_KEY]["rasters"].items():
        assert "band" in entry, f"バンド番号が未指定です: {key}"
        assert isinstance(entry["band"], int) and entry["band"] >= 1, (
            f"バンド番号は1以上の整数である必要があります: {key}={entry['band']}"
        )


def test_lulc_param_sets_declare_known_class_scheme() -> None:
    """``lulc`` モジュールを参照する ParamSet のラスタ設定は、既知の class_scheme を宣言する。

    ``params/lulc.py: validate_resource()`` は実行時チェックであり、CLI を実際に
    回すまで宣言漏れに気づけない。画素値の分布から分類体系を推定する経路は
    採れない（値 10・11 が GLC/Esri の両体系に存在するが意味が異なるため）ため、
    設定漏れは黙って誤った写像表を適用する結果につながる。CLI実行前に静的に
    弾けるよう、``test_raster_param_sets_declare_band_index()`` と同じ形で検査する。
    """
    from src.common.lulc_classes import CLASS_SCHEMES

    lulc_raster_keys = {
        param_set.input_key
        for param_set in PARAM_SETS.values()
        if param_set.module_name == "lulc" and param_set.input_kind == "raster"
    }
    assert lulc_raster_keys, "lulc を参照する ParamSet が見つかりません"

    for key in lulc_raster_keys:
        entry = CITY_CONFIG[CITY_KEY]["rasters"][key]
        scheme = entry.get("class_scheme", "")
        assert scheme in CLASS_SCHEMES, (
            f"rasters['{key}'] の class_scheme が未知です（値: '{scheme}'）。"
            f" CLASS_SCHEMES のいずれか（{sorted(CLASS_SCHEMES)}）を指定してください。"
        )
