"""paper_scout.py（引用スノーボーリングによる文献候補探索）のテスト。

ネットワークアクセスは monkeypatch でモックし、DOI/タイトル正規化・
inverted-index 復元・スコアリング・突合・認証パラメータ付与・候補集約を検証する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.literature import paper_scout


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
    assert paper_scout.normalize_doi(value) == expected


def test_normalize_title_removes_symbols_and_collapses_space() -> None:
    title = "Urban Heat Island: A Multi-Scale Study (2021)!"
    assert paper_scout.normalize_title(title) == "urban heat island a multi scale study 2021"


def test_short_openalex_id() -> None:
    assert paper_scout.short_openalex_id("https://openalex.org/W123") == "W123"
    assert paper_scout.short_openalex_id("https://openalex.org/W456/") == "W456"
    assert paper_scout.short_openalex_id(None) is None


# ---------------------------------------------------------------------------
# アブストラクト復元
# ---------------------------------------------------------------------------
def test_reconstruct_abstract_orders_by_position() -> None:
    inverted = {"urban": [1], "the": [0], "heat": [2]}
    assert paper_scout.reconstruct_abstract(inverted) == "the urban heat"


def test_reconstruct_abstract_handles_empty() -> None:
    assert paper_scout.reconstruct_abstract(None) == ""
    assert paper_scout.reconstruct_abstract({}) == ""


# ---------------------------------------------------------------------------
# スコアリング
# ---------------------------------------------------------------------------
def test_score_text_weights_title_over_abstract() -> None:
    title = "Land surface temperature in Hanoi"
    abstract = "This study analyzes thermal patterns."
    score, matched = paper_scout.score_text(title, abstract)
    # タイトルの "land surface temperature"(3.0×2) + "hanoi"(3.0×2)、
    # アブストの "thermal"(1.0×1) がマッチする
    assert "land surface temperature" in matched
    assert "hanoi" in matched
    assert "thermal" in matched
    assert score == pytest.approx(3.0 * 2 + 3.0 * 2 + 1.0)


def test_score_text_no_match_is_zero() -> None:
    score, matched = paper_scout.score_text("An unrelated economics paper", "About markets")
    assert score == 0.0
    assert matched == set()


def test_score_text_word_boundary_prevents_substring_false_positive() -> None:
    # "grid" は単語境界照合のため "gridlock" にはマッチしない
    score, matched = paper_scout.score_text("Gridlock in cities", "")
    assert "grid" not in matched
    assert score == 0.0


# ---------------------------------------------------------------------------
# 認証パラメータ
# ---------------------------------------------------------------------------
def test_auth_params_prefers_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")
    assert paper_scout._auth_params("me@example.com") == "&api_key=secret-key"


def test_auth_params_falls_back_to_mailto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    assert paper_scout._auth_params("me@example.com") == "&mailto=me@example.com"


def test_auth_params_empty_when_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    assert paper_scout._auth_params(None) == ""


def test_redact_hides_api_key() -> None:
    url = "https://api.openalex.org/works?filter=x&api_key=secret&select=id"
    assert "secret" not in paper_scout._redact(url)
    assert "api_key=***" in paper_scout._redact(url)


def test_build_url_includes_select_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "k")
    url = paper_scout._build_url("filter=doi:10.1/x", None)
    assert url.startswith(paper_scout.OPENALEX_BASE_URL)
    assert "select=" in url
    assert "api_key=k" in url


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
    dois, titles = paper_scout.load_registered(csv_path)
    assert "10.3390/rs13214256" in dois
    assert "first paper" in titles
    assert "second paper" in titles
    # S3 は DOI が非DOI形式なので DOI 集合には入らないがタイトルは入る
    assert "third paper" in titles


def test_read_starting_papers_all(csv_path: Path) -> None:
    papers = paper_scout.read_starting_papers(csv_path, None)
    assert [p[0] for p in papers] == ["S1", "S2", "S3"]
    assert papers[0][2] == "10.3390/rs13214256"
    assert papers[1][2] is None  # S2 は DOI なし


def test_read_starting_papers_filtered(csv_path: Path) -> None:
    papers = paper_scout.read_starting_papers(csv_path, ["S1", "s3"])
    assert [p[0] for p in papers] == ["S1", "S3"]


# ---------------------------------------------------------------------------
# 候補集約（突合・重複統合）
# ---------------------------------------------------------------------------
def _work(
    work_id: str,
    doi: str | None = None,
    title: str = "",
    year: int | None = 2021,
) -> dict[str, Any]:
    return {
        "id": f"https://openalex.org/{work_id}",
        "doi": doi,
        "title": title,
        "publication_year": year,
        "primary_location": {"source": {"display_name": "Some Journal"}},
        "abstract_inverted_index": None,
    }


def test_add_candidate_excludes_registered_doi() -> None:
    candidates: dict[str, paper_scout.Candidate] = {}
    work = _work("W1", doi="https://doi.org/10.3390/rs13214256", title="Registered")
    paper_scout.add_candidate(candidates, work, "S1", "前方", {"10.3390/rs13214256"}, set())
    assert candidates == {}


def test_add_candidate_excludes_registered_title() -> None:
    candidates: dict[str, paper_scout.Candidate] = {}
    work = _work("W2", doi=None, title="Already Registered Paper")
    paper_scout.add_candidate(candidates, work, "S1", "前方", set(), {"already registered paper"})
    assert candidates == {}


def test_add_candidate_merges_via_and_directions() -> None:
    candidates: dict[str, paper_scout.Candidate] = {}
    work = _work("W3", doi="https://doi.org/10.1/new", title="New Urban Heat Island Study")
    paper_scout.add_candidate(candidates, work, "S1", "前方", set(), set())
    paper_scout.add_candidate(candidates, work, "S2", "後方", set(), set())
    assert len(candidates) == 1
    cand = next(iter(candidates.values()))
    assert cand.via_papers == {"S1", "S2"}
    assert cand.directions == {"前方", "後方"}
    assert cand.score > 0  # "urban heat island" にマッチ


# ---------------------------------------------------------------------------
# scout 統合（ネットワークをモック）
# ---------------------------------------------------------------------------
def test_scout_end_to_end(monkeypatch: pytest.MonkeyPatch, csv_path: Path) -> None:
    # 起点 S1(DOI) を解決 → 前方1件・後方1件、うち後方は既登録(S3タイトル)で除外
    start_work = {
        "id": "https://openalex.org/W100",
        "doi": "https://doi.org/10.3390/rs13214256",
        "title": "First Paper",
        "publication_year": 2020,
        "primary_location": {"source": {"display_name": "J1"}},
        "referenced_works": ["https://openalex.org/W200"],
    }
    forward_work = _work(
        "W300", doi="https://doi.org/10.1/forward", title="Forward Citing LST Study"
    )
    backward_work = _work("W200", doi=None, title="Third Paper")  # 既登録タイトル

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any] | None:
        if "filter=doi:" in url:
            return {"results": [start_work]}
        if "filter=openalex_id:" in url:
            return {"results": [backward_work]}
        if "filter=cites:" in url:
            return {"results": [forward_work], "meta": {"next_cursor": None}}
        return {"results": []}

    monkeypatch.setattr(paper_scout, "_safe_fetch", fake_safe_fetch)

    candidates, skipped = paper_scout.scout(
        csv_path=csv_path,
        s_numbers=["S1"],
        mailto=None,
        timeout=5,
        max_forward=400,
    )
    assert skipped == []
    # 後方(既登録)は除外され、前方1件のみ残る
    assert len(candidates) == 1
    assert candidates[0].title == "Forward Citing LST Study"
    assert candidates[0].via_papers == {"S1"}
    assert candidates[0].directions == {"前方"}


def test_scout_records_unresolved_start(monkeypatch: pytest.MonkeyPatch, csv_path: Path) -> None:
    # 常に空 → 起点解決失敗を skipped に記録する
    monkeypatch.setattr(paper_scout, "_safe_fetch", lambda url, timeout: {"results": []})
    candidates, skipped = paper_scout.scout(
        csv_path=csv_path,
        s_numbers=["S2"],  # DOI なし → タイトル検索も空
        mailto=None,
        timeout=5,
        max_forward=400,
    )
    assert candidates == []
    assert len(skipped) == 1
    assert "S2" in skipped[0]


def test_title_similarity() -> None:
    assert paper_scout.title_similarity("Urban Heat Island Study", "Urban Heat Island Study") == 1.0
    assert paper_scout.title_similarity("Urban Heat Island", "") == 0.0
    # 無関係なタイトルは低い類似度
    assert (
        paper_scout.title_similarity(
            "Assessment of Temperature Change in Da Nang City",
            "Internet of Things is a revolutionary approach",
        )
        < 0.5
    )


def test_resolve_start_work_adopts_similar_title(monkeypatch: pytest.MonkeyPatch) -> None:
    # DOI なし・完全一致なしでも、類似度が閾値以上なら採用する
    similar = _work("W9", doi=None, title="Urban Heat Island in Hanoi Vietnam 2021")
    monkeypatch.setattr(paper_scout, "_safe_fetch", lambda url, timeout: {"results": [similar]})
    work = paper_scout.resolve_start_work(
        "Urban Heat Island in Hanoi, Vietnam (2021)", None, None, timeout=5
    )
    assert work is similar


def test_resolve_start_work_rejects_dissimilar_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 最上位候補が無関係なら採用せず None（起点スキップ）
    unrelated = _work("W8", doi=None, title="Internet of Things revolutionary review")
    monkeypatch.setattr(paper_scout, "_safe_fetch", lambda url, timeout: {"results": [unrelated]})
    work = paper_scout.resolve_start_work(
        "Assessment of Temperature Change in Da Nang City Vietnam", None, None, timeout=5
    )
    assert work is None


def test_resolve_start_work_requests_referenced_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 起点 work の取得 URL には後方引用用の referenced_works が含まれること
    captured: list[str] = []

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any]:
        captured.append(url)
        return {"results": [_work("W1", doi="https://doi.org/10.1/x", title="T")]}

    monkeypatch.setattr(paper_scout, "_safe_fetch", fake_safe_fetch)
    paper_scout.resolve_start_work("Title", "10.1/x", None, timeout=5)
    assert captured
    assert "referenced_works" in captured[0]


def _candidate(work_id: str, score: float) -> paper_scout.Candidate:
    """スコアだけを指定した候補を作るテスト用ヘルパー。"""
    return paper_scout.Candidate(
        openalex_id=work_id, title="t", year=None, venue=None, doi=None, score=score
    )


def test_filter_by_min_score_excludes_below_threshold() -> None:
    cands = [_candidate("W1", 50.0), _candidate("W2", 20.0), _candidate("W3", 0.0)]
    result = paper_scout.filter_by_min_score(cands, 20.0)
    assert [c.openalex_id for c in result] == ["W1", "W2"]


def test_filter_by_min_score_zero_returns_all() -> None:
    cands = [_candidate("W1", 0.0)]
    # 閾値 0 は除外なし（同一リストを返す）
    assert paper_scout.filter_by_min_score(cands, 0.0) == cands


def test_fetch_backward_uses_documented_filter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 後方引用取得の URL は文書化された filter=ids.openalex を使う
    captured: list[str] = []

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any]:
        captured.append(url)
        return {"results": []}

    monkeypatch.setattr(paper_scout, "_safe_fetch", fake_safe_fetch)
    work = {"referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"]}
    paper_scout.fetch_backward(work, None, timeout=5)
    assert captured
    assert "filter=ids.openalex:W1|W2" in captured[0]


def test_resolve_start_work_encodes_special_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # タイトルの & や # がクエリを壊さないよう URL エンコードされる
    captured: list[str] = []

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any]:
        captured.append(url)
        return {"results": []}

    monkeypatch.setattr(paper_scout, "_safe_fetch", fake_safe_fetch)
    paper_scout.resolve_start_work("Heat & Cities #1", None, None, timeout=5)
    assert captured
    # 生の & / # がタイトル由来でクエリに現れない（%26 / %23 にエンコード）
    assert "search=Heat%20%26%20Cities%20%231" in captured[0]


def test_format_table_escapes_pipe() -> None:
    cand = paper_scout.Candidate(
        openalex_id="W1",
        title="A|B study",
        year=2021,
        venue="J|X",
        doi="10.1/x",
        score=10.0,
    )
    table = paper_scout.format_table([cand], top=5)
    assert "A\\|B study" in table
    assert "J\\|X" in table


def test_fetch_forward_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {"results": [_work("W1")], "meta": {"next_cursor": "c2"}},
        {"results": [_work("W2")], "meta": {"next_cursor": None}},
    ]
    calls: list[str] = []

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any]:
        calls.append(url)
        return pages[len(calls) - 1]

    monkeypatch.setattr(paper_scout, "_safe_fetch", fake_safe_fetch)
    works = paper_scout.fetch_forward("W100", None, timeout=5, max_forward=400)
    assert len(works) == 2
    assert "cursor=*" in calls[0]
    assert "cursor=c2" in calls[1]


def test_fetch_forward_respects_max(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"results": [_work("W1"), _work("W2"), _work("W3")], "meta": {"next_cursor": None}}
    monkeypatch.setattr(paper_scout, "_safe_fetch", lambda url, timeout: page)
    works = paper_scout.fetch_forward("W100", None, timeout=5, max_forward=2)
    assert len(works) == 2
