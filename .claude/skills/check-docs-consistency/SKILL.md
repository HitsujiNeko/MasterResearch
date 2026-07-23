---
name: check-docs-consistency
description: "docs/配下のドキュメントの意味的な整合性（同一対象の記述差異等）を検出し、機械的チェック（CI実行結果）と合わせて結果をGitHub Issueとして起票する。「ドキュメントの整合性チェック」「内容の不一致確認」などのリクエストで使用する。"
---

# ドキュメント整合性チェック

`docs/` 配下のドキュメント群が CLAUDE.md・docs/README.md の「Single Source of Truth」運用ルールに従っているかを検査し、問題があれば GitHub Issue として報告するスキル。

検出と報告のみを行い、ファイルの修正は行わない。

機械的に判定可能な項目（カタログ差分・リンク切れ・メタ情報の有無・用語の表記揺れ・書誌整合・鮮度）は `src/doc_checks/` にスクリプト化され、PRごとにCIジョブ `doc-consistency` として実行される。本スキルはその実行結果の確認と、意味的判断を要するチェックを担う。

---

## チェック項目

1. **機械的チェック（CI結果の確認）** — `python -m src.doc_checks.run_all` を実行し、カタログ差分・リンク切れ・メタ情報・表記揺れ・書誌整合・鮮度の検出結果を取得する
2. **事実レジストリの逐件照合** — `references/check_spec.md` の事実レジストリ**全件**を、正本と写しで行（箇所）単位に照合する。照合対象の項目・レジストリ・判定基準はすべて `references/check_spec.md` を正本とする（項目一覧を本ファイルに再掲しない）
3. **結果数値の再突合** — `docs/03_results/` の各文書の数値を、生成元データ（各文書本文の出力ファイル節が指す JSON/CSV）と再照合する。手順は `references/check_spec.md` を参照

---

## 実行手順

1. `python -m src.doc_checks.run_all` を実行する
2. 事実レジストリの逐件照合を実施する（`references/check_spec.md` の 1 章。Grep / Glob を活用し、不要な全文 Read は避ける）
3. 結果数値の再突合を実施する（`references/check_spec.md` の 2 章）
4. すべての結果を統合して報告する

### 問題なしの場合

Issue を作成せず、ユーザーに「問題なし」と報告して終了する。

### 問題ありの場合

`.github/ISSUE_TEMPLATE/docs-consistency-report.md` の構成に従い Issue を作成する。
本文は [../shared/github-project-api.md](../shared/github-project-api.md) の「日本語テキストの安全な処理」に従い、一時ファイル経由の `--body-file` で渡す。

```bash
gh issue create --repo HitsujiNeko/MasterResearch \
  --title "docs: ドキュメント整合性チェック報告 (YYYY-MM-DD)" \
  --label "docs" \
  --body-file {一時ファイルパス}
```

末尾に以下のフッタを追加する:

```markdown
---
🤖 このIssueは /check-docs-consistency スキルにより作成されました。
```

この Issue はチェック結果の報告を目的とするため、優先度のユーザー確認・プロジェクトへの追加は行わない。

### 次のアクション

- **対話セッション**: 「このまま修正に着手しますか？」と確認する
- **自動実行**（ルーチンからの呼び出し）: Issue 起票で完了とする

---

## 注意事項

- 検査対象の中心は `docs/` 配下だが、事実レジストリの照合では正本・写しとして
  ルート `README.md` と `CLAUDE.md`（最小用語集が複数事実の正本）も**読み取り対象に含む**（読み取りのみ・修正はしない）。
  レジストリ照合以外の目的でルートファイル自体を検査する場合は、ユーザーに目的を確認する
