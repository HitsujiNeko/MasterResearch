"""ドキュメント整合性チェックを一括実行するエントリポイント。

CI から `python -m src.doc_checks.run_all` で呼び出す。
機械的チェック（カタログ差分・リンク切れ・メタ情報・表記揺れ・書誌整合）は
1件でも違反があれば終了コード1を返す。鮮度チェックは警告のみで、
終了コードには影響しない（更新日の乖離は違反ではなく注意情報のため）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.doc_checks.bibliography_consistency import check_bibliography_consistency
from src.doc_checks.broken_links import check_broken_links
from src.doc_checks.catalog_diff import check_catalog_diff
from src.doc_checks.freshness import check_freshness
from src.doc_checks.metadata_presence import check_metadata_presence
from src.doc_checks.terminology import check_terminology


def main(project_root: Path = PROJECT_ROOT) -> int:
    """全チェックを実行し、結果を表示したうえで終了コードを返す。

    Args:
        project_root: プロジェクトのルートディレクトリ。
    Returns:
        違反があった場合は1、すべて通過した場合は0。
    """
    has_failure = False

    catalog_result = check_catalog_diff(project_root)
    if catalog_result.has_violations:
        has_failure = True
        print("[NG] カタログ差分:")
        for path in catalog_result.missing_from_catalog:
            print(f"  - 実ファイルはあるがカタログ未掲載: {path}")
        for path in catalog_result.missing_file:
            print(f"  - カタログに記載があるが実ファイルなし: {path}")

    broken_links = check_broken_links(project_root)
    if broken_links:
        has_failure = True
        print("[NG] リンク切れ:")
        for link in broken_links:
            print(f"  - {link.source_file}: {link.target}")

    missing_metadata = check_metadata_presence(project_root)
    if missing_metadata:
        has_failure = True
        print("[NG] メタ情報欠落:")
        for item in missing_metadata:
            print(f"  - {item.file}")

    terminology_violations = check_terminology(project_root)
    if terminology_violations:
        has_failure = True
        print("[NG] 表記揺れ:")
        for v in terminology_violations:
            print(f"  - {v.file}:{v.line} [{v.category}] {v.matched_text!r}")

    bibliography_mismatches = check_bibliography_consistency(project_root)
    if bibliography_mismatches:
        has_failure = True
        print("[NG] 書誌整合:")
        for m in bibliography_mismatches:
            print(f"  - {m.paper_id} [{m.source}]: 正本={m.canonical_year!r} 記載={m.found_year!r}")

    freshness_warnings = check_freshness(project_root)
    if freshness_warnings:
        print("[WARN] 鮮度チェック（fail対象外・要確認）:")
        for w in freshness_warnings:
            print(
                f"  - {w.file}: 最終更新記載={w.metadata_date} "
                f"最終コミット={w.last_commit_date} 乖離={w.days_diff}日"
            )

    if not has_failure:
        print("[OK] 機械的チェックはすべて通過しました。")

    return 1 if has_failure else 0


if __name__ == "__main__":
    sys.exit(main())
