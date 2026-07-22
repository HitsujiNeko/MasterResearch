"""paper_watch.py（OpenAlex 新着文献ウォッチ）のテスト。

ネットワークアクセスは monkeypatch でモックし、検索式生成・日付計算・
新着取得のページング・突合（既登録の除外）・重複排除・スコア降順・
取得失敗時のスキップ・テーブル整形・CLI の動作を検証する。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from src.literature import paper_scout, paper_watch


# ---------------------------------------------------------------------------
# 語彙共有の保証
# ---------------------------------------------------------------------------
def test_core_search_terms_are_shared_vocabulary() -> None:
    # 検索の中核語はすべて paper_scout の KEYWORD_WEIGHTS に定義されている（ドリフト防止）
    for term in paper_watch.CORE_SEARCH_TERMS:
        assert term in paper_scout.KEYWORD_WEIGHTS


# ---------------------------------------------------------------------------
# 日付・検索式
# ---------------------------------------------------------------------------
def test_default_from_date_subtracts_days() -> None:
    today = dt.date(2026, 7, 22)
    assert paper_watch.default_from_date(7, today) == "2026-07-15"


def test_build_search_filter_includes_date_and_core_terms() -> None:
    filter_value = paper_watch.build_search_filter("2026-07-15")
    assert filter_value.startswith("from_publication_date:2026-07-15,")
    assert "title_and_abstract.search:" in filter_value
    assert '"land surface temperature"' in filter_value
    assert " OR " in filter_value


# ---------------------------------------------------------------------------
# 新着取得（ネットワークをモック）
# ---------------------------------------------------------------------------
def _work(
    work_id: str,
    doi: str | None = None,
    title: str = "",
    year: int | None = 2026,
) -> dict[str, Any]:
    return {
        "id": f"https://openalex.org/{work_id}",
        "doi": doi,
        "title": title,
        "publication_year": year,
        "primary_location": {"source": {"display_name": "Some Journal"}},
        "abstract_inverted_index": None,
    }


def test_fetch_recent_paginates_until_cursor_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        {"results": [_work("W1")], "meta": {"next_cursor": "c2"}},
        {"results": [_work("W2")], "meta": {"next_cursor": None}},
    ]
    calls: list[str] = []

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any] | None:
        calls.append(url)
        return pages.pop(0)

    monkeypatch.setattr(paper_scout, "_safe_fetch", fake_safe_fetch)
    works, ok = paper_watch.fetch_recent("2026-07-15", None, 5, max_results=100)
    assert ok is True
    assert [w["id"] for w in works] == [
        "https://openalex.org/W1",
        "https://openalex.org/W2",
    ]
    # 2ページ目のリクエストで cursor=c2 が使われている
    assert "cursor=c2" in calls[1]


def test_fetch_recent_respects_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any] | None:
        return {
            "results": [_work("W1"), _work("W2"), _work("W3")],
            "meta": {"next_cursor": None},
        }

    monkeypatch.setattr(paper_scout, "_safe_fetch", fake_safe_fetch)
    works, ok = paper_watch.fetch_recent("2026-07-15", None, 5, max_results=2)
    assert ok is True
    assert len(works) == 2


def test_fetch_recent_stops_on_empty_results_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # results が空でも next_cursor が非None を返し続けるケースでも1回で打ち切る
    calls: list[str] = []

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any] | None:
        calls.append(url)
        return {"results": [], "meta": {"next_cursor": "never-ends"}}

    monkeypatch.setattr(paper_scout, "_safe_fetch", fake_safe_fetch)
    works, ok = paper_watch.fetch_recent("2026-07-15", None, 5, max_results=100)
    # 取得自体は成功（=セクションはスキップせず0件扱い）だが、無限ループせず1回で止まる
    assert works == []
    assert ok is True
    assert len(calls) == 1


def test_fetch_recent_reports_failure_when_first_page_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paper_scout, "_safe_fetch", lambda url, timeout: None)
    works, ok = paper_watch.fetch_recent("2026-07-15", None, 5, max_results=100)
    assert works == []
    assert ok is False


# ---------------------------------------------------------------------------
# 候補集約（突合・重複排除・スコア降順）
# ---------------------------------------------------------------------------
def test_collect_candidates_excludes_registered_and_dedupes() -> None:
    works = [
        _work("W1", doi="https://doi.org/10.1000/known", title="Known LST Paper"),
        _work("W2", doi="https://doi.org/10.1000/new1", title="Urban Heat Island in Hanoi"),
        _work("W3", doi="https://doi.org/10.1000/new1", title="Duplicate DOI Paper"),
        _work("W4", doi=None, title="Registered By Title"),
    ]
    candidates = paper_watch.collect_candidates(
        works,
        registered_dois={"10.1000/known"},
        registered_titles={"registered by title"},
    )
    # 既登録(DOI・タイトル)は除外、重複 DOI は1件に統合 → W2 のみ残る
    assert len(candidates) == 1
    assert candidates[0].doi == "10.1000/new1"
    assert candidates[0].score > 0  # "urban heat island" + "hanoi" にマッチ


def test_collect_candidates_sorts_by_score_desc() -> None:
    works = [
        _work("W1", doi="https://doi.org/10.1000/aaa", title="Thermal note"),  # 低スコア
        _work(
            "W2",
            doi="https://doi.org/10.1000/bbb",
            title="Land Surface Temperature and Urban Structure in Vietnam",
        ),  # 高スコア
    ]
    candidates = paper_watch.collect_candidates(works, set(), set())
    assert [c.doi for c in candidates] == ["10.1000/bbb", "10.1000/aaa"]
    assert candidates[0].score > candidates[1].score


# ---------------------------------------------------------------------------
# watch 統合
# ---------------------------------------------------------------------------
_CSV_CONTENT = (
    "ID,著者,年,タイトル,掲載誌,主目的,データ種別,主要手法,対象地域,DOI_URL,"
    "PDF有無,重要度,RQ1関連,RQ2関連,RQ3関連,キーワード,メモ\n"
    "S1,A,2020,Known LST Paper,J1,,,,,https://doi.org/10.1000/known,,,,,,,\n"
)


@pytest.fixture()
def csv_path(tmp_path: Path) -> Path:
    path = tmp_path / "papers_database.csv"
    path.write_text(_CSV_CONTENT, encoding="utf-8")
    return path


def test_watch_end_to_end(monkeypatch: pytest.MonkeyPatch, csv_path: Path) -> None:
    known = _work("W1", doi="https://doi.org/10.1000/known", title="Known LST Paper")
    fresh = _work("W2", doi="https://doi.org/10.1000/fresh", title="New Urban Heat Island Study")

    def fake_safe_fetch(url: str, timeout: int) -> dict[str, Any] | None:
        assert "from_publication_date:2026-07-15" in url
        return {"results": [known, fresh], "meta": {"next_cursor": None}}

    monkeypatch.setattr(paper_scout, "_safe_fetch", fake_safe_fetch)
    candidates, from_date, ok = paper_watch.watch(
        csv_path=csv_path,
        days=7,
        mailto=None,
        timeout=5,
        max_results=100,
        today=dt.date(2026, 7, 22),
    )
    assert ok is True
    assert from_date == "2026-07-15"
    # 既登録の known は除外、fresh のみ残る
    assert [c.doi for c in candidates] == ["10.1000/fresh"]


def test_watch_returns_not_ok_on_fetch_failure(
    monkeypatch: pytest.MonkeyPatch, csv_path: Path
) -> None:
    monkeypatch.setattr(paper_scout, "_safe_fetch", lambda url, timeout: None)
    candidates, from_date, ok = paper_watch.watch(
        csv_path=csv_path,
        days=7,
        mailto=None,
        timeout=5,
        max_results=100,
        today=dt.date(2026, 7, 22),
    )
    assert candidates == []
    assert ok is False
    assert from_date == "2026-07-15"


# ---------------------------------------------------------------------------
# テーブル整形
# ---------------------------------------------------------------------------
def test_format_watch_table_escapes_pipes_and_limits_rows() -> None:
    cands = [
        paper_scout.Candidate(
            openalex_id="W1",
            title="A | B study",
            year=2026,
            venue="Jour|nal",
            doi="10.1/x",
            score=6.0,
            matched_keywords={"urban heat island", "lst"},
        ),
        paper_scout.Candidate(
            openalex_id="W2", title="Second", year=2026, venue=None, doi=None, score=1.0
        ),
    ]
    table = paper_watch.format_watch_table(cands, top=1)
    # ヘッダ2行 + データ1行（top=1 で2件目は出さない）
    assert len(table.splitlines()) == 3
    assert "A \\| B study" in table
    assert "Jour\\|nal" in table
    assert "Second" not in table
    # マッチキーワードがソートされて出力される
    assert "lst;urban heat island" in table


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_main_prints_skip_message_on_failure(
    monkeypatch: pytest.MonkeyPatch, csv_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(paper_scout, "_safe_fetch", lambda url, timeout: None)
    exit_code = paper_watch.main(["--csv", str(csv_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "スキップ" in captured.err


def test_main_writes_csv_and_table(
    monkeypatch: pytest.MonkeyPatch,
    csv_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fresh = _work(
        "W2", doi="https://doi.org/10.1000/fresh", title="New Land Surface Temperature Study"
    )
    monkeypatch.setattr(
        paper_scout,
        "_safe_fetch",
        lambda url, timeout: {"results": [fresh], "meta": {"next_cursor": None}},
    )
    output = tmp_path / "out.csv"
    exit_code = paper_watch.main(["--csv", str(csv_path), "--output", str(output), "--top", "5"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "新着の未登録候補" in captured.out
    assert output.exists()
    assert "10.1000/fresh" in output.read_text(encoding="utf-8-sig")
