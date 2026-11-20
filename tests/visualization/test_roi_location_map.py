"""roi_location_map.py（ROI 位置図のレイアウト計算・注記）のテスト。

タイル取得と描画を伴う ``build_roi_location_map`` は対象外とし、
図の体裁を決める純関数のみを検証する。
"""

from __future__ import annotations

import math

import geopandas as gpd
import matplotlib
import pytest
from shapely.geometry import box

from src.common.config import HANOI_UTM_CRS
from src.visualization import roi_location_map
from src.visualization.roi_location_map import (
    BOUNDARY_ATTRIBUTION,
    CREDIT_MAX_LINE_CHARS,
    HANOI_STATIONS_OVERLAY,
    HANOI_SURVEY_OVERLAY,
    OVERLAY_LEGEND_LABELS,
    PROJECTION_NOTE,
    MapPoint,
    StudyAreaOverlay,
    _draw_overlay,
    band_geometries,
    credit_lines,
    expand_extent,
    format_latitude,
    format_longitude,
    graticule_ticks,
    layout_rects,
    nice_scalebar_length_km,
    overlay_legend_height_mm,
    overlay_legend_keys,
)
from src.visualization.xyz_tiles import PROVIDERS

# ハノイ ROI 相当の縦横比（高さ/幅）とベトナム全図の縦横比。
HANOI_MAP_ASPECT = 1.2
VIETNAM_INSET_ASPECT = 2.14


def test_nice_scalebar_length_picks_quarter_of_width() -> None:
    """地図幅のおよそ4分の1に近い切りのよい長さを選ぶ。"""
    # 幅91kmなら目安は約25km。
    assert nice_scalebar_length_km(91.0) == 25


def test_nice_scalebar_length_scales_with_map_width() -> None:
    """地図が広いほど長いスケールバーを選ぶ。"""
    assert nice_scalebar_length_km(1000.0) > nice_scalebar_length_km(50.0)


def test_nice_scalebar_length_returns_listed_value() -> None:
    """戻り値は候補に含まれる切りのよい値である。"""
    assert nice_scalebar_length_km(7.3) in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500)


@pytest.mark.parametrize("width_km", [0.0, -10.0])
def test_nice_scalebar_length_rejects_non_positive(width_km: float) -> None:
    """幅が正でなければエラーになる。"""
    with pytest.raises(ValueError):
        nice_scalebar_length_km(width_km)


def test_graticule_ticks_are_inside_range_and_sorted() -> None:
    """目盛はすべて区間内にあり、昇順に並ぶ。"""
    ticks = graticule_ticks(105.245, 106.064)
    assert ticks == sorted(ticks)
    assert all(105.245 <= tick <= 106.064 for tick in ticks)


def test_graticule_ticks_use_constant_spacing() -> None:
    """目盛の間隔は一定である。"""
    ticks = graticule_ticks(20.515, 21.435)
    steps = [round(b - a, 6) for a, b in zip(ticks[:-1], ticks[1:], strict=True)]
    assert len(set(steps)) == 1


def test_graticule_ticks_respect_target_count() -> None:
    """目盛数は目安の前後に収まる。"""
    ticks = graticule_ticks(105.245, 106.064, target_count=4)
    assert 2 <= len(ticks) <= 7


def test_graticule_ticks_can_be_empty_for_narrow_range() -> None:
    """最小間隔より狭い区間では目盛が入らないことがある。"""
    assert graticule_ticks(105.201, 105.209) == []


@pytest.mark.parametrize(
    ("minimum", "maximum", "target"),
    [(1.0, 1.0, 4), (2.0, 1.0, 4), (1.0, 2.0, 0)],
)
def test_graticule_ticks_reject_invalid_input(minimum: float, maximum: float, target: int) -> None:
    """区間または目盛数が正でなければエラーになる。"""
    with pytest.raises(ValueError):
        graticule_ticks(minimum, maximum, target_count=target)


def test_format_longitude_marks_hemisphere() -> None:
    """東経・西経が記号で書き分けられる。"""
    assert format_longitude(105.6) == "105.6°E"
    assert format_longitude(-30.0) == "30°W"


def test_format_latitude_marks_hemisphere() -> None:
    """北緯・南緯が記号で書き分けられる。"""
    assert format_latitude(21.0) == "21°N"
    assert format_latitude(-8.5) == "8.5°S"


def test_expand_extent_adds_margin_to_each_side() -> None:
    """各辺に幅・高さの割合分の余白が加わる。"""
    assert expand_extent((0.0, 0.0, 10.0, 20.0), 0.1) == pytest.approx((-1.0, -2.0, 11.0, 22.0))


def test_expand_extent_zero_ratio_is_identity() -> None:
    """割合0なら範囲は変わらない。"""
    extent = (105.0, 20.0, 106.0, 21.0)
    assert expand_extent(extent, 0.0) == pytest.approx(extent)


@pytest.mark.parametrize(
    ("extent", "ratio"),
    [
        ((0.0, 0.0, 0.0, 1.0), 0.1),  # 幅が0
        ((0.0, 0.0, 1.0, 0.0), 0.1),  # 高さが0
        ((0.0, 0.0, 1.0, 1.0), -0.1),  # 割合が負
    ],
)
def test_expand_extent_rejects_invalid_input(
    extent: tuple[float, float, float, float], ratio: float
) -> None:
    """範囲または割合が不正ならエラーになる。"""
    with pytest.raises(ValueError):
        expand_extent(extent, ratio)


def test_layout_rects_returns_positive_figure_size() -> None:
    """図の寸法は正の値になる。"""
    width, height, _ = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    assert width > 0
    assert height > 0


def test_layout_rects_keeps_all_axes_inside_figure() -> None:
    """すべての軸が figure の内側（0-1）に収まる。"""
    _, _, rects = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    assert set(rects) == {"map", "inset", "legend", "credit"}
    for left, bottom, width, height in rects.values():
        assert 0.0 <= left and 0.0 <= bottom
        assert width > 0 and height > 0
        assert left + width <= 1.0 + 1e-9
        assert bottom + height <= 1.0 + 1e-9


def test_layout_rects_places_right_column_beside_map() -> None:
    """インセットと凡例は本図の右側に置かれる。"""
    _, _, rects = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    map_right = rects["map"][0] + rects["map"][2]
    assert rects["inset"][0] >= map_right
    assert rects["legend"][0] >= map_right


def test_layout_rects_stacks_legend_below_inset() -> None:
    """凡例はインセットの下に、重ならずに置かれる。"""
    _, _, rects = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    legend_top = rects["legend"][1] + rects["legend"][3]
    assert legend_top <= rects["inset"][1] + 1e-9


def test_layout_rects_places_credit_below_map() -> None:
    """出典表記は本図より下に置かれる。"""
    _, _, rects = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    credit_top = rects["credit"][1] + rects["credit"][3]
    assert credit_top <= rects["map"][1] + 1e-9


def test_layout_rects_widens_figure_for_wider_map() -> None:
    """本図が横長になるほど図全体も広くなる。"""
    narrow, _, _ = layout_rects(1.5, VIETNAM_INSET_ASPECT)
    wide, _, _ = layout_rects(0.8, VIETNAM_INSET_ASPECT)
    assert wide > narrow


@pytest.mark.parametrize(("map_aspect", "inset_aspect"), [(0.0, 2.0), (1.2, 0.0), (-1.0, 2.0)])
def test_layout_rects_rejects_non_positive_aspect(map_aspect: float, inset_aspect: float) -> None:
    """縦横比が正でなければエラーになる。"""
    with pytest.raises(ValueError):
        layout_rects(map_aspect, inset_aspect)


# ベースマップ配信元の出典表記の一例（OpenStreetMap タイル）。
BASEMAP_ATTRIBUTION = "Basemap: © OpenStreetMap contributors"


def test_credit_lines_keeps_required_attributions() -> None:
    """表示義務のある2つの出典表記がいずれも含まれる。"""
    joined = "\n".join(credit_lines(BASEMAP_ATTRIBUTION))
    assert BASEMAP_ATTRIBUTION in joined
    assert BOUNDARY_ATTRIBUTION in joined


def test_credit_lines_puts_licence_text_before_projection_note() -> None:
    """表示義務のある表記を先に、義務の無い投影法の注記を後に置く。"""
    lines = credit_lines(BASEMAP_ATTRIBUTION)
    assert lines == [BASEMAP_ATTRIBUTION, BOUNDARY_ATTRIBUTION, PROJECTION_NOTE]


def test_credit_lines_are_much_shorter_than_single_line_form() -> None:
    """最長の行が、1行にまとめた場合の半分より短い。

    行長が縮むぶんだけ文字を大きくできる、というのが複数行に分ける理由である。
    ここが満たせなくなるほど行が伸びたら、文字サイズの前提も見直す必要がある。
    """
    lines = credit_lines(BASEMAP_ATTRIBUTION)
    single_line_length = sum(len(line) for line in lines)
    assert max(len(line) for line in lines) < single_line_length / 2


@pytest.mark.parametrize("attribution", ["", "   "])
def test_credit_lines_rejects_empty_attribution(attribution: str) -> None:
    """出典表記が空ならエラーになる（利用条件を満たせないため）。"""
    with pytest.raises(ValueError):
        credit_lines(attribution)


@pytest.mark.parametrize("provider_name", sorted(PROVIDERS))
def test_credit_lines_fit_within_strip_for_every_provider(provider_name: str) -> None:
    """どのタイル配信元でも、出典表記の各行が表記帯の幅に収まる。

    出典表記の文字列はプロバイダごとに長さが違う。長いものを追加したときに
    帯からはみ出すのを、文字数の上限で検出する。
    """
    lines = credit_lines(PROVIDERS[provider_name].attribution)
    assert max(len(line) for line in lines) <= CREDIT_MAX_LINE_CHARS


def test_layout_rects_taller_legend_shrinks_inset_only() -> None:
    """凡例を高くすると、インセットだけが低くなり本図の大きさは変わらない。"""
    _, _, base = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    _, _, tall = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT, legend_height_mm=34.0)
    assert tall["legend"][3] > base["legend"][3]
    assert tall["inset"][3] < base["inset"][3]
    assert tall["map"][3] == pytest.approx(base["map"][3])


def test_layout_rects_widens_right_column_on_request() -> None:
    """右カラムの最小幅を広げると、図全体が広がる。"""
    narrow, _, _ = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT)
    wide, _, _ = layout_rects(HANOI_MAP_ASPECT, VIETNAM_INSET_ASPECT, right_column_min_mm=60.0)
    assert wide > narrow


@pytest.mark.parametrize(
    ("legend_height_mm", "right_column_min_mm"),
    [(0.0, 28.0), (12.0, 0.0), (90.0, 28.0)],
)
def test_layout_rects_rejects_invalid_legend_or_column(
    legend_height_mm: float, right_column_min_mm: float
) -> None:
    """凡例・右カラムの寸法が正でないとき、凡例が高すぎてインセットが置けないときは止める。"""
    with pytest.raises(ValueError):
        layout_rects(
            HANOI_MAP_ASPECT,
            VIETNAM_INSET_ASPECT,
            legend_height_mm=legend_height_mm,
            right_column_min_mm=right_column_min_mm,
        )


def test_band_geometries_have_expected_areas() -> None:
    """円板と環の面積が、投影座標系で πr² の差に一致する（多角形近似の誤差 0.1% 以内）。"""
    center = HANOI_STATIONS_OVERLAY.center
    bands = band_geometries(center, ((0.0, 5.0), (15.0, 25.0))).to_crs(HANOI_UTM_CRS)
    areas_km2 = bands.area.to_numpy() / 1.0e6
    assert areas_km2[0] == pytest.approx(math.pi * 5.0**2, rel=1e-3)
    assert areas_km2[1] == pytest.approx(math.pi * (25.0**2 - 15.0**2), rel=1e-3)
    assert bands.is_valid.all()
    assert list(bands["inner_km"]) == [0.0, 15.0]
    assert list(bands["outer_km"]) == [5.0, 25.0]


def test_band_geometries_ring_excludes_center() -> None:
    """環（内径 > 0）は中心点を含まず、円板は中心点を含む。"""
    center = MapPoint("c", lon=105.852, lat=21.028)
    bands = band_geometries(center, ((0.0, 5.0), (15.0, 25.0))).to_crs(HANOI_UTM_CRS)
    point = (
        gpd.GeoSeries.from_xy([center.lon], [center.lat], crs="EPSG:4326")
        .to_crs(HANOI_UTM_CRS)
        .iloc[0]
    )
    assert bands.geometry.iloc[0].contains(point)
    assert not bands.geometry.iloc[1].contains(point)


def test_band_geometries_are_returned_in_web_mercator() -> None:
    """重ね描きに使うため、Web メルカトルで返す。"""
    bands = band_geometries(HANOI_STATIONS_OVERLAY.center, ((0.0, 5.0),))
    assert bands.crs.to_epsg() == 3857


@pytest.mark.parametrize("bands_km", [(), ((-1.0, 5.0),), ((5.0, 5.0),), ((10.0, 5.0),)])
def test_band_geometries_reject_invalid_bands(bands_km: tuple) -> None:
    """距離帯が空・内径が負・外径が内径以下のときは止める。"""
    with pytest.raises(ValueError):
        band_geometries(HANOI_STATIONS_OVERLAY.center, bands_km)


@pytest.mark.parametrize(
    "crs_text",
    [
        "EPSG:4326",  # 地理座標系（単位は度）
        "EPSG:2263",  # 米国の州平面座標系（単位は US フィート）
    ],
)
def test_band_geometries_reject_non_metric_crs(crs_text: str) -> None:
    """投影座標系でない、または単位がメートルでない座標系では止める（半径がずれるため）。"""
    with pytest.raises(ValueError):
        band_geometries(HANOI_STATIONS_OVERLAY.center, ((0.0, 5.0),), projected_crs=crs_text)


def test_study_area_overlay_matches_source_definitions() -> None:
    """既定の重ね描きの定義が、正本の観測所座標と都心・郊外の定義と一致する。"""
    stations = {
        station.label: (station.lon, station.lat) for station in HANOI_STATIONS_OVERLAY.stations
    }
    assert stations == {"Noi Bai": (105.807, 21.221), "Ha Dong": (105.767, 20.967)}
    center = HANOI_STATIONS_OVERLAY.center
    assert (center.lon, center.lat) == (105.852, 21.028)
    assert HANOI_STATIONS_OVERLAY.bands_km == ((0.0, 5.0), (15.0, 25.0))


def test_survey_overlay_points_to_default_extent() -> None:
    """有効域の既定値は、測量 GIS の有効域のファイルだけを重ねる。"""
    assert HANOI_SURVEY_OVERLAY.survey_extent_path is not None
    assert HANOI_SURVEY_OVERLAY.survey_extent_path.name == "hanoi_survey_extent.gpkg"
    assert HANOI_SURVEY_OVERLAY.stations == ()
    assert HANOI_SURVEY_OVERLAY.center is None


def test_overlay_legend_keys_follow_given_elements() -> None:
    """凡例には指定した要素だけが、決まった順に載る。"""
    assert overlay_legend_keys(HANOI_SURVEY_OVERLAY) == ["survey"]
    assert overlay_legend_keys(HANOI_STATIONS_OVERLAY) == ["stations", "center", "bands"]
    assert set(OVERLAY_LEGEND_LABELS) == {"survey", "stations", "center", "bands"}
    assert all(label.strip() for label in OVERLAY_LEGEND_LABELS.values())


def test_overlay_legend_height_grows_with_items() -> None:
    """凡例の項目が多いほど凡例パネルを高くし、項目がなければ既定の高さになる。"""
    assert overlay_legend_height_mm(0) == pytest.approx(12.0)
    assert overlay_legend_height_mm(3) > overlay_legend_height_mm(1)
    with pytest.raises(ValueError):
        overlay_legend_height_mm(-1)


def test_study_area_overlay_rejects_empty_or_bands_without_center() -> None:
    """重ねる要素がないとき、距離帯があるのに中心点がないときは作れない。"""
    with pytest.raises(ValueError):
        StudyAreaOverlay()
    with pytest.raises(ValueError):
        StudyAreaOverlay(stations=HANOI_STATIONS_OVERLAY.stations, bands_km=((0.0, 5.0),))


@pytest.fixture
def overlay_axes():
    """ベースマップを使わない、重ね描き用の空の軸を返す。"""
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots()
    yield axes
    plt.close(fig)


def test_draw_overlay_rejects_missing_extent_file(tmp_path, overlay_axes) -> None:
    """測量 GIS の有効域のファイルが無いときは止める。"""
    overlay = StudyAreaOverlay(survey_extent_path=tmp_path / "missing.gpkg")
    with pytest.raises(FileNotFoundError):
        _draw_overlay(overlay_axes, overlay, font_pt=9.0)


def test_draw_overlay_rejects_extent_without_crs(tmp_path, overlay_axes) -> None:
    """有効域に座標系が無いときは、推測で補わずに止める（位置のずれを防ぐ）。"""
    path = tmp_path / "no_crs.gpkg"
    gpd.GeoDataFrame(geometry=[box(105.78, 20.99, 105.87, 21.09)]).to_file(path)
    with pytest.raises(ValueError, match="座標系"):
        _draw_overlay(overlay_axes, StudyAreaOverlay(survey_extent_path=path), font_pt=9.0)


def test_draw_overlay_survey_only_draws_no_points(tmp_path, overlay_axes) -> None:
    """有効域だけを指定したときは、有効域の面だけを描き、記号や注記は描かない。"""
    path = tmp_path / "extent.gpkg"
    gpd.GeoDataFrame(geometry=[box(105.78, 20.99, 105.87, 21.09)], crs="EPSG:4326").to_file(path)
    _draw_overlay(overlay_axes, StudyAreaOverlay(survey_extent_path=path), font_pt=9.0)
    assert overlay_axes.collections
    assert not overlay_axes.lines
    assert not overlay_axes.texts


def test_draw_overlay_stations_draws_points_bands_and_labels(overlay_axes) -> None:
    """観測所の既定値では、距離帯・中心点・観測所を描き、観測所名を注記する。"""
    _draw_overlay(overlay_axes, HANOI_STATIONS_OVERLAY, font_pt=9.0)
    labels = {text.get_text() for text in overlay_axes.texts}
    assert labels == {station.label for station in HANOI_STATIONS_OVERLAY.stations}
    # 中心点 1 + 観測所 2 の記号
    assert len(overlay_axes.lines) == 1 + len(HANOI_STATIONS_OVERLAY.stations)
    assert overlay_axes.collections  # 距離帯の面と線


@pytest.fixture
def captured_build(monkeypatch: pytest.MonkeyPatch) -> dict:
    """``build_roi_location_map`` を差し替え、CLI が渡した引数を記録する（描画・通信をしない）。"""
    calls: dict = {}

    def fake_build(**kwargs):
        calls.update(kwargs)
        return kwargs["output_path"]

    monkeypatch.setattr(roi_location_map, "build_roi_location_map", fake_build)
    return calls


def test_main_without_overlay_passes_none(tmp_path, captured_build) -> None:
    """``--overlay`` を付けなければ、従来どおり重ね描きなしで描く。"""
    assert roi_location_map.main(["--output", str(tmp_path / "a.png")]) == 0
    assert captured_build["overlay"] is None


def test_main_selects_overlay_preset(tmp_path, captured_build) -> None:
    """``--overlay stations`` は観測所と距離帯の既定値を渡す。"""
    roi_location_map.main(["--output", str(tmp_path / "a.png"), "--overlay", "stations"])
    assert captured_build["overlay"] == HANOI_STATIONS_OVERLAY


def test_main_replaces_survey_extent_path(tmp_path, captured_build) -> None:
    """``--overlay survey`` と ``--survey-extent`` を併せると、有効域のパスだけを差し替える。"""
    extent = tmp_path / "extent.gpkg"
    roi_location_map.main(
        ["--output", str(tmp_path / "a.png"), "--overlay", "survey", "--survey-extent", str(extent)]
    )
    assert captured_build["overlay"].survey_extent_path == extent
    assert captured_build["overlay"].stations == ()


@pytest.mark.parametrize("overlay_args", [[], ["--overlay", "stations"]])
def test_main_rejects_survey_extent_without_survey_overlay(
    tmp_path, captured_build, overlay_args: list[str]
) -> None:
    """有効域を重ねない指定で ``--survey-extent`` を渡すと、引数の誤りとして止める。"""
    with pytest.raises(SystemExit) as excinfo:
        roi_location_map.main(
            ["--output", str(tmp_path / "a.png"), *overlay_args, "--survey-extent", "x.gpkg"]
        )
    assert excinfo.value.code == 2
    assert not captured_build
