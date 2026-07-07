# スキル運用ルール

**最終更新**: 2026-07-07
**関連ドキュメント**: [CLAUDE.md](../../CLAUDE.md), [CodingRule.md](CodingRule.md)

---

## 目的

Claude Code のカスタムスキル（`.claude/skills/` 配下）の作成・変更・運用に関するプロジェクト固有のルールを定義する。

スキルの書き方に関する汎用的なベストプラクティス（500行制限、段階的開示など）は Skill Creator スキルがカバーするため、本ドキュメントでは重複記載しない。

---

## 環境ルール

| 環境 | スキルの利用 | スキルの作成・変更 |
|---|---|---|
| **Claude Desktop** | 可 | 可（Skill Creator 使用） |
| **Claude Code デスクトップアプリ** | 可 | 可（Skill Creator スキルが利用可能な場合のみ） |
| **VS Code (Claude Code 拡張)** | 可 | 不可 |

- スキルの新規作成・変更は **Skill Creator スキルが利用できる環境**（Claude Desktop、または Skill Creator が有効な Claude Code デスクトップアプリ）で行う
- VS Code ではスキルの利用のみとし、SKILL.md の編集は行わない

---

## プロジェクト固有ルール

- 日本語でのコメント・説明を基本とする（description はトリガー精度のため英語可）
- スキル内のファイルパスはスラッシュ（`/`）を使用する（Windows 環境でも統一）
