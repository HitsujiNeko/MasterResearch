"""scout_report.py（文献探索の月次報告コメントの生成）のテスト。

探索本体（``paper_scout.scout``）は monkeypatch で差し替え、ネットワークにアクセスしない。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from src.literature import paper_scout, scout_report
from src.literature.openalex import Candidate


def _candidate(openalex_id: str, doi: str | None, score: float, title: str = "T") -> Candidate:
    """テスト用の候補を作る。"""
    return Candidate(
        openalex_id=f"https://openalex.org/{openalex_id}",
        title=title,
        year=2025,
        venue="Remote Sensing",
        doi=doi,
        score=score,
        via_papers={"S1"},
        directions={"前方"},
    )


class TestKeys:
    """提示済み判定キーとマーカーのテスト。"""

    def test_key_prefers_doi(self) -> None:
        """DOI があれば DOI をキーにする。"""
        cand = _candidate("W1", "10.1/abc", 50.0)
        assert scout_report.candidate_report_key(cand) == "doi:10.1/abc"

    def test_key_falls_back_to_openalex_id(self) -> None:
        """DOI が無ければ OpenAlex の短縮 ID をキーにする。"""
        cand = _candidate("W2", None, 50.0)
        assert scout_report.candidate_report_key(cand) == "openalex:W2"

    def test_key_is_none_without_identifiers(self) -> None:
        """DOI も OpenAlex ID も無ければ None。"""
        cand = Candidate(openalex_id="", title="T", year=None, venue=None, doi=None)
        assert scout_report.candidate_report_key(cand) is None

    def test_marker_round_trip(self) -> None:
        """マーカーに書いたキーを、そのまま復元できる。"""
        keys = ["doi:10.1/abc", "openalex:W2", "doi:10.2/with space>and-->arrow"]
        marker = scout_report.format_marker(keys)

        assert marker.startswith("<!--")
        assert marker.endswith("-->")
        # キーに含まれる `>` がマーカーの終端と誤認されない
        assert marker.count("-->") == 1
        assert scout_report.extract_presented_keys([marker]) == set(keys)

    def test_extracts_keys_from_multiple_comments(self) -> None:
        """複数のコメント・本文中の位置にかかわらずキーを集め、マーカーの無いコメントは無視する。"""
        bodies = [
            "## 文献候補\n表\n" + scout_report.format_marker(["doi:10.1/a"]) + "\n",
            "ふつうのコメント（マーカーなし）",
            scout_report.format_marker(["openalex:W9", "doi:10.1/b"]),
            "",
        ]
        assert scout_report.extract_presented_keys(bodies) == {
            "doi:10.1/a",
            "openalex:W9",
            "doi:10.1/b",
        }


class TestLoadCommentBodies:
    """load_comment_bodies のテスト。"""

    def test_reads_concatenated_pages(self, tmp_path: Path) -> None:
        """--paginate の連結出力（配列が複数並ぶ）を読む。"""
        path = tmp_path / "comments.json"
        page1 = json.dumps([{"body": "A"}, {"body": "B"}])
        page2 = json.dumps([{"body": "C"}])
        path.write_text(f"{page1}\n{page2}\n", encoding="utf-8")

        assert scout_report.load_comment_bodies(path) == ["A", "B", "C"]

    def test_reads_empty_array(self, tmp_path: Path) -> None:
        """コメントが無い Issue（空配列）は空のリストになる。"""
        path = tmp_path / "comments.json"
        path.write_text("[]", encoding="utf-8")

        assert scout_report.load_comment_bodies(path) == []

    def test_treats_missing_body_as_empty(self, tmp_path: Path) -> None:
        """body が null のコメントは空文字列として扱う。"""
        path = tmp_path / "comments.json"
        path.write_text(json.dumps([{"body": None}]), encoding="utf-8")

        assert scout_report.load_comment_bodies(path) == [""]

    def test_rejects_non_array(self, tmp_path: Path) -> None:
        """配列でない JSON（エラー応答など）は ValueError。"""
        path = tmp_path / "comments.json"
        path.write_text(json.dumps({"message": "Not Found"}), encoding="utf-8")

        with pytest.raises(ValueError):
            scout_report.load_comment_bodies(path)


class TestSelectNewCandidates:
    """select_new_candidates のテスト。"""

    def test_excludes_presented_and_limits_count(self) -> None:
        """提示済みを除いて上位から選び、新規候補の総数も返す。"""
        candidates = [
            _candidate("W1", "10.1/a", 90.0),
            _candidate("W2", None, 80.0),
            _candidate("W3", "10.1/c", 70.0),
            _candidate("W4", "10.1/d", 60.0),
        ]
        presented = {"doi:10.1/a", "openalex:W2"}

        selected, total_new, presented_count = scout_report.select_new_candidates(
            candidates, presented, top=1
        )

        assert [cand.doi for cand in selected] == ["10.1/c"]
        assert total_new == 2
        assert presented_count == 2

    def test_returns_empty_when_all_presented(self) -> None:
        """全件提示済みなら空。"""
        candidates = [_candidate("W1", "10.1/a", 90.0)]

        selected, total_new, presented_count = scout_report.select_new_candidates(
            candidates, {"doi:10.1/a"}, top=10
        )

        assert selected == []
        assert total_new == 0
        assert presented_count == 1

    def test_skips_keyless_candidates_without_counting_as_presented(self) -> None:
        """判定キーを作れない候補は掲載せず、提示済みの件数にも数えない。"""
        keyless = Candidate(openalex_id="", title="T", year=None, venue=None, doi=None, score=99.0)
        candidates = [keyless, _candidate("W1", "10.1/a", 90.0)]

        selected, total_new, presented_count = scout_report.select_new_candidates(
            candidates, set(), top=10
        )

        assert [cand.doi for cand in selected] == ["10.1/a"]
        assert total_new == 1
        assert presented_count == 0


class TestFormatReportComment:
    """format_report_comment のテスト。"""

    def test_contains_table_summary_and_marker_of_listed_only(self) -> None:
        """表・件数の要約・掲載した候補だけのマーカーを含む。"""
        selected = [_candidate("W1", "10.1/a", 90.0, title="Urban | heat")]

        body = scout_report.format_report_comment(
            selected,
            total_new=5,
            excluded_count=2,
            min_score=30.0,
            run_date=dt.date(2026, 11, 1),
            skipped=[],
        )

        assert body.startswith("## 文献候補 2026-11（2026-11-01 実行）")
        assert "新規候補 5 件のうち上位 1 件を掲載" in body
        assert "提示済みの 2 件を除外" in body
        assert "Urban \\| heat" in body
        assert "解決できなかった起点" not in body
        assert scout_report.extract_presented_keys([body]) == {"doi:10.1/a"}

    def test_lists_skipped_starts(self) -> None:
        """解決できなかった起点があれば折りたたみで併記する。"""
        body = scout_report.format_report_comment(
            [_candidate("W1", "10.1/a", 90.0)],
            total_new=1,
            excluded_count=0,
            min_score=30.0,
            run_date=dt.date(2026, 11, 1),
            skipped=["S2: 起点をOpenAlexで解決できませんでした"],
        )

        assert "<summary>解決できなかった起点</summary>" in body
        assert "- S2: 起点をOpenAlexで解決できませんでした" in body


class TestMain:
    """main の統合テスト（探索本体は差し替える）。"""

    @pytest.fixture()
    def papers_csv(self, tmp_path: Path) -> Path:
        """起点 CSV のダミー（scout を差し替えるため中身は使わない）。"""
        path = tmp_path / "papers_database.csv"
        path.write_text("ID\nS1\n", encoding="utf-8")
        return path

    def _patch_scout(
        self,
        monkeypatch: pytest.MonkeyPatch,
        candidates: list[Candidate],
        skipped: list[str] | None = None,
    ) -> None:
        """paper_scout.scout を固定の結果に差し替える。"""
        monkeypatch.setattr(
            paper_scout, "scout", lambda **kwargs: (list(candidates), list(skipped or []))
        )

    def test_second_run_excludes_first_run_candidates(
        self, tmp_path: Path, papers_csv: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """1回目に掲載した候補は、そのコメントを読んだ2回目では掲載しない。"""
        candidates = [
            _candidate("W1", "10.1/a", 90.0),
            _candidate("W2", None, 80.0),
            _candidate("W3", "10.1/c", 70.0),
            _candidate("W4", "10.1/d", 10.0),
        ]
        self._patch_scout(monkeypatch, candidates)
        comments_path = tmp_path / "comments.json"
        comments_path.write_text("[]", encoding="utf-8")
        first_output = tmp_path / "first.md"
        common_args = ["--csv", str(papers_csv), "--top", "2", "--min-score", "30"]

        first_code = scout_report.main(
            ["--comments-json", str(comments_path), "--output", str(first_output), *common_args]
        )
        assert first_code == 0
        first_body = first_output.read_text(encoding="utf-8")
        assert scout_report.extract_presented_keys([first_body]) == {"doi:10.1/a", "openalex:W2"}

        comments_path.write_text(json.dumps([{"body": first_body}]), encoding="utf-8")
        second_output = tmp_path / "second.md"
        second_code = scout_report.main(
            ["--comments-json", str(comments_path), "--output", str(second_output), *common_args]
        )

        assert second_code == 0
        second_body = second_output.read_text(encoding="utf-8")
        # スコア 30 未満の W4 は足切りされ、W3 だけが新規として残る
        assert scout_report.extract_presented_keys([second_body]) == {"doi:10.1/c"}
        assert "提示済みの 2 件を除外" in second_body

    def test_no_new_candidates_writes_nothing(
        self, tmp_path: Path, papers_csv: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """新規候補が無ければ専用の終了コードを返し、ファイルを作らない。"""
        self._patch_scout(monkeypatch, [_candidate("W1", "10.1/a", 90.0)])
        comments_path = tmp_path / "comments.json"
        marker = scout_report.format_marker(["doi:10.1/a"])
        comments_path.write_text(json.dumps([{"body": marker}]), encoding="utf-8")
        output = tmp_path / "out.md"

        code = scout_report.main(
            [
                "--comments-json",
                str(comments_path),
                "--output",
                str(output),
                "--csv",
                str(papers_csv),
            ]
        )

        assert code == scout_report.EXIT_NO_NEW_CANDIDATES
        assert not output.exists()

    def test_partially_resolved_starts_still_post(
        self, tmp_path: Path, papers_csv: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """一部の起点を解決できなくても候補があれば 0 を返し、解決できなかった起点を併記する。"""
        self._patch_scout(
            monkeypatch,
            [_candidate("W1", "10.1/a", 90.0)],
            skipped=["S2: 起点をOpenAlexで解決できませんでした"],
        )
        comments_path = tmp_path / "comments.json"
        comments_path.write_text("[]", encoding="utf-8")
        output = tmp_path / "out.md"

        code = scout_report.main(
            [
                "--comments-json",
                str(comments_path),
                "--output",
                str(output),
                "--csv",
                str(papers_csv),
            ]
        )

        assert code == 0
        assert "- S2: 起点をOpenAlexで解決できませんでした" in output.read_text(encoding="utf-8")

    def test_empty_result_without_skipped_starts_returns_one(
        self, tmp_path: Path, papers_csv: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """起点は解決できても候補が1件も取れなければ（取得の全滅）、新規なしではなく失敗とする。"""
        self._patch_scout(monkeypatch, [])
        comments_path = tmp_path / "comments.json"
        comments_path.write_text("[]", encoding="utf-8")
        output = tmp_path / "out.md"

        code = scout_report.main(
            [
                "--comments-json",
                str(comments_path),
                "--output",
                str(output),
                "--csv",
                str(papers_csv),
            ]
        )

        assert code == 1
        assert not output.exists()

    @pytest.mark.parametrize("top", ["0", "-1", "x"])
    def test_rejects_invalid_top(self, tmp_path: Path, top: str) -> None:
        """--top は 1 以上の整数のみ受け付ける。"""
        with pytest.raises(SystemExit):
            scout_report.main(
                ["--comments-json", "c.json", "--output", str(tmp_path / "o.md"), "--top", top]
            )

    def test_search_failure_returns_one(
        self, tmp_path: Path, papers_csv: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """起点を1件も解決できず候補が空なら、新規なしではなく失敗として 1 を返す。"""
        self._patch_scout(monkeypatch, [], skipped=["S1: 起点をOpenAlexで解決できませんでした"])
        comments_path = tmp_path / "comments.json"
        comments_path.write_text("[]", encoding="utf-8")
        output = tmp_path / "out.md"

        code = scout_report.main(
            [
                "--comments-json",
                str(comments_path),
                "--output",
                str(output),
                "--csv",
                str(papers_csv),
            ]
        )

        assert code == 1
        assert not output.exists()
