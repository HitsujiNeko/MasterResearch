"""openalex.py（OpenAlex アクセス・文献スコアリング共有ツールキット）のテスト。

ネットワークアクセスは monkeypatch でモックし、DOI/タイトル正規化・
inverted-index 復元・スコアリング・突合・認証パラメータ付与・URL 組み立て・
足切りを検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from src.literature import openalex


# ---------------------------------------------------------------------------
# 正規化
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://doi.org/10.3390/rs13214256", "10.3390/rs13214256"),
        ("http://dx.doi.org/10.1016/j.rse.2020.111888", "10.1016/j.rse.2020.111888"),
        ("doi:10.3390/rs13214256", "10.3390/rs13214256"),
        ("  10.3390/RS13214256 ", "10.3390/rs13214256"),
        ("https://www.mdpi.com/2072-4292/12/9/1471", None),
        ("掲載なし", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_doi(value: str | None, expected: str | None) -> None:
    assert openalex.normalize_doi(value) == expected


def test_normalize_title_removes_symbols_and_collapses_space() -> None:
    title = "Urban Heat Island: A Multi-Scale Study (2021)!"
    assert openalex.normalize_title(title) == "urban heat island a multi scale study 2021"


def test_normalize_title_preserves_non_ascii_letters() -> None:
    # アクセント付き・非ラテン文字は除去せず保持する（記号のみ空白化）
    assert openalex.normalize_title("Zürich café, São Paulo!") == "zürich café são paulo"
    assert openalex.normalize_title("都市の熱環境 2021") == "都市の熱環境 2021"


# ---------------------------------------------------------------------------
# アブストラクト復元
# ---------------------------------------------------------------------------
def test_reconstruct_abstract_orders_by_position() -> None:
    inverted = {"urban": [1], "the": [0], "heat": [2]}
    assert openalex.reconstruct_abstract(inverted) == "the urban heat"


def test_reconstruct_abstract_handles_empty() -> None:
    assert openalex.reconstruct_abstract(None) == ""
    assert openalex.reconstruct_abstract({}) == ""


# ---------------------------------------------------------------------------
# スコアリング
# ---------------------------------------------------------------------------
def test_score_text_weights_title_over_abstract() -> None:
    title = "Land surface temperature in Hanoi"
    abstract = "This study analyzes thermal patterns."
    score, matched = openalex.score_text(title, abstract)
    # タイトルの "land surface temperature"(3.0×2) + "hanoi"(3.0×2)、
    # アブストの "thermal"(1.0×1) がマッチする
    assert "land surface temperature" in matched
    assert "hanoi" in matched
    assert "thermal" in matched
    assert score == pytest.approx(3.0 * 2 + 3.0 * 2 + 1.0)


def test_score_text_no_match_is_zero() -> None:
    score, matched = openalex.score_text("An unrelated economics paper", "About markets")
    assert score == 0.0
    assert matched == set()


def test_score_text_word_boundary_prevents_substring_false_positive() -> None:
    # "grid" は単語境界照合のため "gridlock" にはマッチしない
    score, matched = openalex.score_text("Gridlock in cities", "")
    assert "grid" not in matched
    assert score == 0.0


# ---------------------------------------------------------------------------
# 認証パラメータ・URL 組み立て
# ---------------------------------------------------------------------------
def test_auth_params_prefers_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")
    assert openalex._auth_params("me@example.com") == "&api_key=secret-key"


def test_auth_params_falls_back_to_mailto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    # @ は %40 にエンコードされる（サーバ側でデコードされ polite pool として機能）
    assert openalex._auth_params("me@example.com") == "&mailto=me%40example.com"


def test_auth_params_empty_when_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    assert openalex._auth_params(None) == ""


def test_auth_params_url_encodes_values(monkeypatch: pytest.MonkeyPatch) -> None:
    # api_key / mailto の特殊文字（+ など）がエンコードされる
    monkeypatch.setenv("OPENALEX_API_KEY", "a+b/c")
    assert openalex._auth_params(None) == "&api_key=a%2Bb%2Fc"
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    assert openalex._auth_params("me+tag@example.com") == "&mailto=me%2Btag%40example.com"


def test_redact_hides_api_key() -> None:
    url = "https://api.openalex.org/works?filter=x&api_key=secret&select=id"
    assert "secret" not in openalex._redact(url)
    assert "api_key=***" in openalex._redact(url)


def test_build_url_includes_select_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "k")
    url = openalex.build_url("filter=doi:10.1/x", None)
    assert url.startswith(openalex.OPENALEX_BASE_URL)
    assert "select=" in url
    assert "api_key=k" in url


def test_safe_fetch_returns_payload_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"results": [{"id": "W1"}]}
    monkeypatch.setattr(openalex, "fetch_json_with_retry", lambda url, **kwargs: payload)
    assert openalex.safe_fetch("https://example.org", 5) is payload


@pytest.mark.parametrize("exc", [RuntimeError("429"), ValueError("bad json")])
def test_safe_fetch_returns_none_on_error(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    # fetch_json_with_retry が失敗（429 のリトライ超過・JSON 破損）しても例外を握り、None を返す
    def raising(url: str, **kwargs: Any) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr(openalex, "fetch_json_with_retry", raising)
    assert openalex.safe_fetch("https://example.org", 5) is None


# テスト用の並び順（実装と同じく一意なキーで終える）
_SORT = "cited_by_count:desc,ids.openalex"


def _page_of(start: int, count: int, total: int | None = None) -> dict[str, Any]:
    """ID が start から連番の work を count 件含むページを返す。

    total を指定した場合は、OpenAlex と同じく ``meta.count`` に総件数を入れる。
    """
    page: dict[str, Any] = {"results": [{"id": f"W{start + offset}"} for offset in range(count)]}
    if total is not None:
        page["meta"] = {"count": total}
    return page


def _fake_pages(monkeypatch: pytest.MonkeyPatch, pages: list[dict[str, Any] | None]) -> list[str]:
    """safe_fetch を pages を順に返すモックに差し替え、呼び出し URL の記録先を返す。"""
    calls: list[str] = []

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any] | None:
        calls.append(url)
        return pages.pop(0)

    monkeypatch.setattr(openalex, "safe_fetch", fake_safe_fetch)
    return calls


def test_fetch_paged_uses_page_numbers_not_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    # 満杯のページが続く間はページ番号を増やし、件数が per_page 未満のページで終わる
    calls = _fake_pages(monkeypatch, [_page_of(1, 2), _page_of(3, 2), _page_of(5, 1)])
    works, ok = openalex.fetch_paged(
        "filter=cites:W1", None, 5, max_results=100, sort=_SORT, per_page=2
    )
    assert ok is True
    assert [w["id"] for w in works] == ["W1", "W2", "W3", "W4", "W5"]
    assert len(calls) == 3
    for page, url in enumerate(calls, start=1):
        assert f"&per-page=2&page={page}&" in url
        # 並び順を毎ページ指定し、ページの境目を安定させている
        assert f"&sort={_SORT}&" in url
        assert "cursor" not in url


def test_fetch_paged_stops_at_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    # 上限に達したら次のページを取りに行かず、上限件数に切り詰める
    calls = _fake_pages(monkeypatch, [_page_of(1, 2), _page_of(3, 2), _page_of(5, 2)])
    works, ok = openalex.fetch_paged(
        "filter=cites:W1", None, 5, max_results=3, sort=_SORT, per_page=2
    )
    assert ok is True
    assert [w["id"] for w in works] == ["W1", "W2", "W3"]
    assert len(calls) == 2


def test_fetch_paged_stops_on_empty_page(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_pages(monkeypatch, [_page_of(1, 2), {"results": []}])
    works, ok = openalex.fetch_paged(
        "filter=cites:W1", None, 5, max_results=100, sort=_SORT, per_page=2
    )
    assert ok is True
    assert len(works) == 2
    assert len(calls) == 2


def test_fetch_paged_keeps_partial_results_when_later_page_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 2ページ目が失敗（None）しても、取得済みの1ページ目は返す
    _fake_pages(monkeypatch, [_page_of(1, 2), None])
    works, ok = openalex.fetch_paged(
        "filter=cites:W1", None, 5, max_results=100, sort=_SORT, per_page=2
    )
    assert ok is True
    assert [w["id"] for w in works] == ["W1", "W2"]


def test_fetch_paged_reports_failure_when_first_page_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_pages(monkeypatch, [None])
    works, ok = openalex.fetch_paged(
        "filter=cites:W1", None, 5, max_results=100, sort=_SORT, per_page=2
    )
    assert works == []
    assert ok is False


def test_fetch_paged_stops_at_basic_paging_limit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # basic paging の上限（先頭 BASIC_PAGING_LIMIT 件）を超えるページは要求しない
    monkeypatch.setattr(openalex, "BASIC_PAGING_LIMIT", 4)
    pages = [_page_of(1, 2), _page_of(3, 2), _page_of(5, 2)]
    calls = _fake_pages(monkeypatch, pages)
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        works, ok = openalex.fetch_paged(
            "filter=cites:W1", None, 5, max_results=100, sort=_SORT, per_page=2
        )
    assert ok is True
    assert len(works) == 4
    assert len(calls) == 2
    assert "basic paging の上限" in caplog.text


def test_fetch_paged_does_not_warn_when_max_results_reached_at_limit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # 上限件数ちょうどで終わった場合は basic paging の上限による打ち切りではない
    monkeypatch.setattr(openalex, "BASIC_PAGING_LIMIT", 4)
    _fake_pages(monkeypatch, [_page_of(1, 2), _page_of(3, 2)])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        works, _ = openalex.fetch_paged(
            "filter=cites:W1", None, 5, max_results=4, sort=_SORT, per_page=2
        )
    assert len(works) == 4
    assert "basic paging の上限" not in caplog.text


def test_fetch_paged_does_not_warn_when_total_equals_basic_paging_limit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # 総件数がちょうど上限件数の場合、最終ページが満杯でも取りこぼしはない
    monkeypatch.setattr(openalex, "BASIC_PAGING_LIMIT", 4)
    _fake_pages(monkeypatch, [_page_of(1, 2, total=4), _page_of(3, 2, total=4)])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        works, _ = openalex.fetch_paged(
            "filter=cites:W1", None, 5, max_results=100, sort=_SORT, per_page=2
        )
    assert len(works) == 4
    assert caplog.text == ""


def test_fetch_paged_warns_basic_paging_limit_with_total(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # 総件数が basic paging の上限を超える場合は、総件数を添えて警告する
    monkeypatch.setattr(openalex, "BASIC_PAGING_LIMIT", 4)
    _fake_pages(monkeypatch, [_page_of(1, 2, total=5), _page_of(3, 2, total=5)])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        openalex.fetch_paged("filter=cites:W1", None, 5, max_results=100, sort=_SORT, per_page=2)
    assert "basic paging の上限" in caplog.text
    assert "総件数: 5 件" in caplog.text


@pytest.mark.parametrize(
    ("pages", "max_results", "expected_phrases"),
    [
        # 総件数が上限を超える（ページ途中で上限に達した）
        (
            [_page_of(1, 2, total=10), _page_of(3, 2, total=10)],
            3,
            ["打ち切りました", "総件数: 10 件"],
        ),
        # 総件数が上限を超える（ページの境目で上限ちょうどに達した）
        (
            [_page_of(1, 2, total=10), _page_of(3, 2, total=10)],
            4,
            ["打ち切りました", "総件数: 10 件"],
        ),
        # 1ページ目の総件数が古く、実際には上限を超えて取得していた（取得件数を優先する）
        (
            [_page_of(1, 2, total=3), _page_of(3, 2, total=3)],
            3,
            ["打ち切りました", "総件数: 3 件"],
        ),
        # 総件数が不明で、上限を超えて取得していた（切り捨ては確実）
        ([_page_of(1, 2), _page_of(3, 2)], 3, ["打ち切りました", "総件数: 不明"]),
        # 総件数が不明で、最後のページが満杯（続きがありうるが断定しない）
        (
            [_page_of(1, 2), _page_of(3, 2)],
            4,
            ["取得を止めました", "総件数: 不明", "続きがある可能性"],
        ),
    ],
)
def test_fetch_paged_warns_when_truncated_by_max_results(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    pages: list[dict[str, Any]],
    max_results: int,
    expected_phrases: list[str],
) -> None:
    _fake_pages(monkeypatch, pages)
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        works, _ = openalex.fetch_paged(
            "filter=cites:W1", None, 5, max_results=max_results, sort=_SORT, per_page=2
        )
    assert len(works) == max_results
    assert f"取得上限 {max_results} 件に達したため" in caplog.text
    for phrase in expected_phrases:
        assert phrase in caplog.text
    # どの並び順の先頭を残したか・どの問い合わせかが分かる
    assert _SORT in caplog.text
    assert "filter=cites:W1" in caplog.text
    # 警告は1件のみ（basic paging 上限の警告と重ならない）
    assert len(caplog.records) == 1


def test_fetch_paged_warns_only_paging_limit_when_max_results_exceeds_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # 取得上限が basic paging の上限より大きく、総件数がその間にある場合は basic paging の警告のみ
    monkeypatch.setattr(openalex, "BASIC_PAGING_LIMIT", 4)
    _fake_pages(monkeypatch, [_page_of(1, 2, total=6), _page_of(3, 2, total=6)])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        works, _ = openalex.fetch_paged(
            "filter=cites:W1", None, 5, max_results=10, sort=_SORT, per_page=2
        )
    assert len(works) == 4
    assert "basic paging の上限" in caplog.text
    assert "取得上限" not in caplog.text
    assert len(caplog.records) == 1


def test_fetch_paged_warns_only_max_results_when_equal_to_paging_limit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # 取得上限が basic paging の上限と等しく、総件数がそれを超える場合は取得上限の警告のみ
    monkeypatch.setattr(openalex, "BASIC_PAGING_LIMIT", 4)
    _fake_pages(monkeypatch, [_page_of(1, 2, total=6), _page_of(3, 2, total=6)])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        works, _ = openalex.fetch_paged(
            "filter=cites:W1", None, 5, max_results=4, sort=_SORT, per_page=2
        )
    assert len(works) == 4
    assert "取得上限 4 件に達したため打ち切りました" in caplog.text
    assert "basic paging の上限" not in caplog.text
    assert len(caplog.records) == 1


def test_fetch_paged_warns_paging_limit_when_per_page_does_not_divide_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # per_page が上限を割り切らないと取得できるのは上限より少ないため、総件数＝上限でも警告する
    monkeypatch.setattr(openalex, "BASIC_PAGING_LIMIT", 5)
    _fake_pages(monkeypatch, [_page_of(1, 2, total=5), _page_of(3, 2, total=5)])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        works, _ = openalex.fetch_paged(
            "filter=cites:W1", None, 5, max_results=100, sort=_SORT, per_page=2
        )
    assert len(works) == 4
    assert "basic paging の上限" in caplog.text
    assert "総件数: 5 件" in caplog.text


def test_fetch_paged_warns_paging_limit_as_possible_when_total_unknown(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # 総件数が不明な場合は、basic paging の上限でも続きの有無を断定しない
    monkeypatch.setattr(openalex, "BASIC_PAGING_LIMIT", 4)
    _fake_pages(monkeypatch, [_page_of(1, 2), _page_of(3, 2)])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        openalex.fetch_paged("filter=cites:W1", None, 5, max_results=100, sort=_SORT, per_page=2)
    assert "basic paging の上限" in caplog.text
    assert "続きがある可能性" in caplog.text


@pytest.mark.parametrize("max_results", [0, -1])
def test_fetch_paged_returns_empty_without_warning_for_non_positive_max(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, max_results: int
) -> None:
    # 上限が 0 以下なら1件も要求せず、打ち切りの警告も出さない
    calls = _fake_pages(monkeypatch, [_page_of(1, 2, total=10)])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        works, ok = openalex.fetch_paged(
            "filter=cites:W1", None, 5, max_results=max_results, sort=_SORT, per_page=2
        )
    assert works == []
    assert ok is False
    assert calls == []
    assert caplog.text == ""


@pytest.mark.parametrize(
    ("pages", "max_results"),
    [
        # 総件数がちょうど上限件数（最終ページが満杯のまま上限に達した）
        ([_page_of(1, 2, total=4), _page_of(3, 2, total=4)], 4),
        # 総件数が上限より少ない
        ([_page_of(1, 2, total=3), _page_of(3, 1, total=3)], 4),
        # 総件数が不明でも、満杯でない最終ページで上限ちょうどに達した
        ([_page_of(1, 2), _page_of(3, 1)], 3),
        # 上限に達する前に最終ページで終わった
        ([_page_of(1, 2), _page_of(3, 1)], 100),
    ],
)
def test_fetch_paged_does_not_warn_when_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    pages: list[dict[str, Any]],
    max_results: int,
) -> None:
    _fake_pages(monkeypatch, pages)
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        openalex.fetch_paged(
            "filter=cites:W1", None, 5, max_results=max_results, sort=_SORT, per_page=2
        )
    assert caplog.text == ""


def test_fetch_paged_does_not_warn_truncation_when_later_page_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # 取得失敗で止まった場合は上限による打ち切りではない（失敗は safe_fetch が別途警告する）
    _fake_pages(monkeypatch, [_page_of(1, 2, total=10), None])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        openalex.fetch_paged("filter=cites:W1", None, 5, max_results=3, sort=_SORT, per_page=2)
    assert "取得上限" not in caplog.text


def test_fetch_paged_truncation_warning_hides_api_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # API キーを設定していても、打ち切りのログにキーの値は出ない
    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")
    calls = _fake_pages(monkeypatch, [_page_of(1, 2, total=10), _page_of(3, 2, total=10)])
    with caplog.at_level("WARNING", logger=openalex.logger.name):
        openalex.fetch_paged("filter=cites:W1", None, 5, max_results=3, sort=_SORT, per_page=2)
    # 前提: リクエスト URL にはキーが付いている
    assert "secret-key" in calls[0]
    assert "取得上限" in caplog.text
    assert "secret-key" not in caplog.text


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"meta": {"count": 12}, "results": []}, 12),
        ({"results": []}, None),
        ({"meta": None, "results": []}, None),
        ({"meta": {"count": "12"}, "results": []}, None),
        ({"meta": {"count": True}, "results": []}, None),
    ],
)
def test_total_count_reads_meta_count(result: dict[str, Any], expected: int | None) -> None:
    assert openalex._total_count(result) == expected


class _RaisingReconfigure:
    """reconfigure が例外を投げるダミーストリーム。"""

    def reconfigure(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("reconfigure unsupported")


class _NoReconfigure:
    """reconfigure 属性を持たないダミーストリーム。"""


def test_force_utf8_output_swallows_stream_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # reconfigure が ValueError/AttributeError を投げても握り潰して継続する
    monkeypatch.setattr(sys, "stdout", _RaisingReconfigure())
    monkeypatch.setattr(sys, "stderr", _NoReconfigure())
    openalex.force_utf8_output()  # 例外を送出しないこと


# ---------------------------------------------------------------------------
# CSV 読み込み
# ---------------------------------------------------------------------------
_CSV_CONTENT = (
    "ID,著者,年,タイトル,掲載誌,主目的,データ種別,主要手法,対象地域,DOI_URL,"
    "PDF有無,重要度,RQ1関連,RQ2関連,RQ3関連,キーワード,メモ\n"
    "S1,A,2020,First Paper,J1,,,,,https://doi.org/10.3390/rs13214256,,,,,,,\n"
    "S2,B,2021,Second Paper,J2,,,,,掲載なし,,,,,,,\n"
    "S3,C,2022,Third Paper,J3,,,,,https://www.mdpi.com/2072-4292/12/9/1471,,,,,,,\n"
)


@pytest.fixture()
def csv_path(tmp_path: Path) -> Path:
    path = tmp_path / "papers_database.csv"
    path.write_text(_CSV_CONTENT, encoding="utf-8")
    return path


def test_load_registered(csv_path: Path) -> None:
    dois, titles = openalex.load_registered(csv_path)
    assert "10.3390/rs13214256" in dois
    assert "first paper" in titles
    assert "second paper" in titles
    # S3 は DOI が非DOI形式なので DOI 集合には入らないがタイトルは入る
    assert "third paper" in titles


# ---------------------------------------------------------------------------
# 候補キー・足切り
# ---------------------------------------------------------------------------
def test_candidate_key_prefers_doi() -> None:
    work = {"doi": "https://doi.org/10.3390/rs13214256", "title": "Some Title"}
    assert openalex.candidate_key(work) == "doi:10.3390/rs13214256"


def test_candidate_key_falls_back_to_title() -> None:
    work = {"doi": None, "title": "Urban Heat Island Study"}
    assert openalex.candidate_key(work) == "title:urban heat island study"


# ---------------------------------------------------------------------------
# CSV 数式インジェクション対策
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+1", "'+1"),
        ("-1", "'-1"),
        ("@cmd", "'@cmd"),
        ("10.3390/rs13214256", "10.3390/rs13214256"),
        ("Normal Title", "Normal Title"),
        ("", ""),
        (None, ""),
        (2026, "2026"),
    ],
)
def test_sanitize_csv_cell(value: object, expected: str) -> None:
    assert openalex.sanitize_csv_cell(value) == expected


def test_write_candidates_csv_sanitizes_and_writes_header(tmp_path: Path) -> None:
    cand = openalex.Candidate(
        openalex_id="W1",
        title="=HYPERLINK(evil)",
        year=2026,
        venue="Journal",
        doi="10.1000/x",
        score=6.0,
        matched_keywords={"lst"},
        via_papers={"S1"},
        directions={"前方"},
    )
    output = tmp_path / "scout.csv"
    openalex.write_candidates_csv([cand], output)
    text = output.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0] == "スコア,タイトル,年,掲載誌,DOI,経由,方向,マッチKW"
    # 数式起点のタイトルは先頭に ' が付与されて無害化される
    assert "'=HYPERLINK(evil)" in text


def _candidate(work_id: str, score: float) -> openalex.Candidate:
    """スコアだけを指定した候補を作るテスト用ヘルパー。"""
    return openalex.Candidate(
        openalex_id=work_id, title="t", year=None, venue=None, doi=None, score=score
    )


def test_filter_by_min_score_excludes_below_threshold() -> None:
    cands = [_candidate("W1", 50.0), _candidate("W2", 20.0), _candidate("W3", 0.0)]
    result = openalex.filter_by_min_score(cands, 20.0)
    assert [c.openalex_id for c in result] == ["W1", "W2"]


def test_filter_by_min_score_zero_returns_all() -> None:
    cands = [_candidate("W1", 0.0)]
    # 閾値 0 は除外なし（同一リストを返す）
    assert openalex.filter_by_min_score(cands, 0.0) == cands
