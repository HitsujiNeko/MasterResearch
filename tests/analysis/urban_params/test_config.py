"""config.py（レイヤ構成・出力レイアウトの定義）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.analysis.urban_params.config import (
    CITY_CONFIG,
    PARAM_SETS,
    PARAMS_OUTPUT_PARTS,
    POPULATION_BASE_COLUMNS,
    PROJECT_ROOT,
    SCENARIO_TABLES,
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
    """接尾辞を使うモジュールでは列名が衝突せず、列名は基底名＋接尾辞になる。

    **特定のモジュール名を例外として書かない。** 「人口だけが接尾辞を持つ」と固定すると、
    同時結合が要る別ソースを他のパラメータへ追加したとき（設定のコメントは GHS-POP 等の
    追加を想定している）に、規約違反ではないのにテストが落ちる。

    固定するのは規約そのもの、すなわち次の不変条件である。

    - 接尾辞を1つでも宣言するモジュール（同時結合を想定するモジュール）では、接尾辞なしの
      セットは高々1つ（基準版）に限る。2つ以上あると、それらの列名が衝突して同時に結合
      できず、片方だけが列名衝突を免れる半端な状態になる。基準版を許すのは、既存の分析が
      参照する列名を変えずに別版を足せるようにするためである（解析対象域フラグの
      ``mask_roi`` に対する ``mask_survey`` がこれに当たる）
    - 接尾辞を宣言しないモジュール（差し替え関係）は、接尾辞なしのセットが複数あってよい
    - いずれのモジュールでも、接尾辞を外せば同一の基底名になる。崩れると ``run.py`` の
      ``apply_column_suffix()`` が組み立てる列名と宣言列が食い違う

    人口のように全セットへ接尾辞が要るモジュールで1つだけ宣言し忘れる誤りは、上記では
    基準版と区別できない。これは人口専用の
    ``test_population_columns_follow_source_suffix_rule()`` が検知する。
    """
    sets_by_module: dict[str, list[tuple[str, ParamSet]]] = {}
    for name, param_set in PARAM_SETS.items():
        sets_by_module.setdefault(param_set.module_name, []).append((name, param_set))

    for module_name, entries in sets_by_module.items():
        suffixed = [name for name, param_set in entries if param_set.column_suffix]
        unsuffixed = [name for name, param_set in entries if not param_set.column_suffix]
        if suffixed:
            assert len(unsuffixed) <= 1, (
                f"{module_name} は接尾辞を使うのに、接尾辞なしのセットが複数あります"
                f"（{sorted(unsuffixed)}）。同時に結合すると列名が衝突します"
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


def test_layer_param_sets_reference_declared_layer_input() -> None:
    """ベクタ入力のパラメータセットは、都市設定に実在する ``layers`` キーを指す。

    ラスタ入力と同じく、キー名の打ち間違いをパラメータセット追加の時点で検知する。
    """
    declared_keys = set(CITY_CONFIG[CITY_KEY]["layers"])
    missing = {
        name: param_set.input_key
        for name, param_set in PARAM_SETS.items()
        if param_set.input_kind == "layer" and param_set.input_key not in declared_keys
    }
    assert not missing, f"CITY_CONFIG['{CITY_KEY}']['layers'] に無い入力キーです: {missing}"


def test_mask_survey_declares_suffixed_column_on_survey_extent() -> None:
    """測量GISの有効域フラグは survey_extent を入力とし、接尾辞つきの列名を持つ。

    ``mask_roi`` の ``IN_ANALYSIS_AREA`` と同じ列名だと、両方を同一データセットへ
    結合したときに ``join_tables()`` が列名衝突として拒否する。
    """
    mask_survey = PARAM_SETS["mask_survey"]

    assert mask_survey.module_name == PARAM_SETS["mask_roi"].module_name
    assert mask_survey.input_key == "survey_extent"
    assert mask_survey.column_suffix == "SURVEY"
    assert mask_survey.columns == ("IN_ANALYSIS_AREA_SURVEY",)
    assert not set(mask_survey.columns) & set(PARAM_SETS["mask_roi"].columns)


def test_survey_extent_layer_matches_generator_output() -> None:
    """survey_extent の設定は、有効域を生成するスクリプトの出力先・レイヤ名と一致する。

    生成側と参照側でパス・レイヤ名を別々に持つため、片方だけを変えると
    パラメータ算出が「ファイルが見つからない」で止まる。CRS は生成元（CS）と揃える。
    """
    from src.preprocessing.build_survey_extent_hanoi import (
        DEFAULT_OUTPUT_PATH,
        OUTPUT_LAYER_NAME,
    )

    layers = CITY_CONFIG[CITY_KEY]["layers"]
    survey_extent = layers["survey_extent"]

    assert PROJECT_ROOT / survey_extent["path"] == DEFAULT_OUTPUT_PATH
    assert survey_extent["layer"] == OUTPUT_LAYER_NAME
    assert survey_extent["crs_epsg"] == layers["cs"]["crs_epsg"]


def test_full_scenario_joins_both_masks() -> None:
    """full シナリオは ROI と測量GISの両方の有効域フラグを結合する。"""
    assert {"mask_roi", "mask_survey"} <= set(SCENARIO_TABLES["full"])


@pytest.mark.parametrize("scenario", sorted(SCENARIO_TABLES))
def test_scenario_tables_declare_no_column_collisions(scenario: str) -> None:
    """各シナリオが結合するテーブルの宣言列は互いに重複しない。

    重複があると ``build_dataset.py`` の ``join_tables()`` が結合を拒否し、
    シナリオ名だけを指定したデータセット生成が実行時に失敗する。
    """
    owner_of_column: dict[str, str] = {}
    for table_name in SCENARIO_TABLES[scenario]:
        for column in PARAM_SETS[table_name].columns:
            previous = owner_of_column.get(column)
            assert previous is None, (
                f"{scenario} で列名が重複しています: {column}（{previous} と {table_name}）"
            )
            owner_of_column[column] = table_name
