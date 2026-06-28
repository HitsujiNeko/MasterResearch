---
name: check-docs-consistency
description: "docs/配下のドキュメント間の整合性（リンク切れ、docs/README.mdカタログとの差分、メタ情報の有無、用語の表記揺れ）を検出し、結果をGitHub Issueとして起票する。「ドキュメントの整合性チェック」「リンク切れチェック」「docs/README.md更新もれの確認」などのリクエストで使用する。"
---

# ドキュメント整合性チェック

`docs/` 配下のドキュメント群が CLAUDE.md・docs/README.md の「Single Source of Truth」運用ルールに従っているかを検査し、問題があれば GitHub Issue として報告するスキル。

検出と報告のみを行い、ファイルの修正は行わない。

---

## チェック項目

5 つのチェックを順に実施する。各項目の判定基準・対象外ルールは `references/check_spec.md` を参照。

1. **docs/README.md カタログ差分** — カタログ掲載と実ファイルの過不足
2. **リンク切れ** — 相対パスリンクの実在確認（`src/`・`.github/` への参照も含む）
3. **メタ情報の有無** — 冒頭5行以内の「最終更新」記載の確認
4. **用語の表記揺れ** — CLAUDE.md 最小用語集との照合
5. **内容の不一致** — 同一対象（EPSGコード等）の文書間での記述差異

---

## 実行手順

1. `docs/` 配下の `.md` / `.mmd` ファイル一覧を取得する
2. `docs/README.md` を読み込み、カタログのパス一覧を抽出する
3. チェック項目 1〜5 を実施する（Grep / Glob を活用し、不要な全文 Read は避ける）
4. 結果に応じて報告する

### 問題なしの場合

Issue を作成せず、ユーザーに「問題なし」と報告して終了する。

### 問題ありの場合

`.github/ISSUE_TEMPLATE/docs-consistency-report.md` の構成に従い Issue を作成する。
日本語の文字化けを防ぐため、本文は一時ファイルに書き出して `--body-file` で渡す（Bash ツールを使用）。

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

- 対象は `docs/` 配下のみ。ルートの `README.md` や `CLAUDE.md` 自体の確認が必要な場合はユーザーに目的を確認する
