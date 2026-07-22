"""openalex.py（OpenAlex アクセス・文献スコアリング共有ツールキット）のテスト。

ネットワークアクセスは monkeypatch でモックし、DOI/タイトル正規化・
inverted-index 復元・スコアリング・突合・認証パラメータ付与・URL 組み立て・
足切りを検証する。
"""

from __future__ import annotations

from pathlib import Path

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
