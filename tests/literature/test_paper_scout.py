"""paper_scout.py（引用スノーボーリングによる文献候補探索）のテスト。

OpenAlex アクセス・正規化・スコアリング等の共有処理のテストは test_openalex.py にあり、
本ファイルはスノーボーリング固有部（起点解決・引用取得・候補集約・scout 統合）を検証する。
ネットワークアクセスは monkeypatch で共有ツールキット ``openalex.safe_fetch`` をモックする。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.literature import openalex, paper_scout


def test_short_openalex_id() -> None:
    assert paper_scout.short_openalex_id("https://openalex.org/W123") == "W123"
    assert paper_scout.short_openalex_id("https://openalex.org/W456/") == "W456"
    assert paper_scout.short_openalex_id(None) is None


# ---------------------------------------------------------------------------
# papers_database.csv の読み込み（起点）
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
    work = _work("W3", doi="https://doi.org/10.1000/new", title="New Urban Heat Island Study")
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
        "W300", doi="https://doi.org/10.1000/forward", title="Forward Citing LST Study"
    )
    backward_work = _work("W200", doi=None, title="Third Paper")  # 既登録タイトル

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any] | None:
        if "filter=doi:" in url:
            return {"results": [start_work]}
        if "filter=ids.openalex:" in url:
            return {"results": [backward_work]}
        if "filter=cites:" in url:
            return {"results": [forward_work], "meta": {"next_cursor": None}}
        return {"results": []}

    monkeypatch.setattr(openalex, "safe_fetch", fake_safe_fetch)

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
    monkeypatch.setattr(openalex, "safe_fetch", lambda url, timeout: {"results": []})
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


# ---------------------------------------------------------------------------
# 起点解決
# ---------------------------------------------------------------------------
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
    monkeypatch.setattr(openalex, "safe_fetch", lambda url, timeout: {"results": [similar]})
    work = paper_scout.resolve_start_work(
        "Urban Heat Island in Hanoi, Vietnam (2021)", None, None, timeout=5
    )
    assert work is similar


def test_resolve_start_work_rejects_dissimilar_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 最上位候補が無関係なら採用せず None（起点スキップ）
    unrelated = _work("W8", doi=None, title="Internet of Things revolutionary review")
    monkeypatch.setattr(openalex, "safe_fetch", lambda url, timeout: {"results": [unrelated]})
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
        return {"results": [_work("W1", doi="https://doi.org/10.1000/x", title="T")]}

    monkeypatch.setattr(openalex, "safe_fetch", fake_safe_fetch)
    paper_scout.resolve_start_work("Title", "10.1000/x", None, timeout=5)
    assert captured
    assert "referenced_works" in captured[0]


def test_resolve_start_work_encodes_special_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # タイトルの & や # がクエリを壊さないよう URL エンコードされる
    captured: list[str] = []

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any]:
        captured.append(url)
        return {"results": []}

    monkeypatch.setattr(openalex, "safe_fetch", fake_safe_fetch)
    paper_scout.resolve_start_work("Heat & Cities #1", None, None, timeout=5)
    assert captured
    # 生の & / # がタイトル由来でクエリに現れない（%26 / %23 にエンコード）
    assert "search=Heat%20%26%20Cities%20%231" in captured[0]


def test_fetch_backward_uses_documented_filter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 後方引用取得の URL は文書化された filter=ids.openalex を使う
    captured: list[str] = []

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any]:
        captured.append(url)
        return {"results": []}

    monkeypatch.setattr(openalex, "safe_fetch", fake_safe_fetch)
    work = {"referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"]}
    paper_scout.fetch_backward(work, None, timeout=5)
    assert captured
    assert "filter=ids.openalex:W1|W2" in captured[0]
