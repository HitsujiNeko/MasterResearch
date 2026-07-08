# スキル運用ルール

**最終更新**: 2026-07-08
**関連ドキュメント**: [CLAUDE.md](../../CLAUDE.md), [CodingRule.md](CodingRule.md), [shared/github-project-api.md](../../.claude/skills/shared/github-project-api.md), [shared/finalize-steps.md](../../.claude/skills/shared/finalize-steps.md)

---

## 目的

Claude Code のカスタムスキル（`.claude/skills/` 配下）の作成・変更・運用に関するプロジェクト固有のルールを定義する。

スキルの書き方に関する汎用的なベストプラクティス（500行制限、段階的開示など）は Skill Creator スキルがカバーするため、本ドキュメントでは重複記載しない。

---

## 作成・変更のルール（行為ベース）

環境（Claude Desktop / デスクトップアプリ / VS Code / リモート）による禁止は設けず、**行為に対する承認**で統制する。

- スキルの新規作成・変更は、**環境を問わずユーザーの明示承認を得てから**行う（変更内容の提示 → 承認 → 実施）
- Skill Creator スキルが利用できる環境では、作成・変更に Skill Creator を使用することを推奨する
- 承認なしのスキル変更は、軽微な修正（typo 等）であっても行わない

---

## 共通リファレンス（shared/）

複数スキルが共有する手順は `.claude/skills/shared/` に一元化し、各スキルからは参照のみとする（重複記載によるドリフト防止）。

| ファイル | 内容 |
|---|---|
| `shared/github-project-api.md` | GitHub Project の GraphQL 取得クエリ・フィールド名・使用禁止コマンド・日本語処理 |
| `shared/finalize-steps.md` | ドキュメント生成系スキルの終端手順（ファクトチェック→lint→承認・コミット→push条件） |

クエリや手順を変更する場合は shared 側のみを更新し、各スキルには固有の差分だけを書く。

---

## プロジェクト固有ルール

- 日本語でのコメント・説明を基本とする（description はトリガー精度のため英語可）
- スキル内のファイルパスはスラッシュ（`/`）を使用する（Windows 環境でも統一）
