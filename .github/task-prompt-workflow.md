# タスクプロンプト運用ルール

**最終更新**: 2026-06-03  
**関連ファイル**: [CLAUDE.md](../CLAUDE.md), [task_intake_template.md](./prompts/templates/task_intake_template.md)

## 目的

GitHub Issues をタスク管理の正本とし、`.github/prompts/active/` 配下の prompt ファイルを Claude へのセッション briefing として使う運用を定義する。

- **GitHub Issue** = タスクの定義・進捗コメント・完了記録（永続）
- **prompt ファイル** = Claude へのセッション briefing（完了後に削除）

prompt ファイルは completed フォルダに蓄積せず、active に少数のファイルのみが存在する状態を維持する。

---

## 基本方針

- タスクの定義・背景・成果物・完了記録はすべて GitHub Issue に記載する
- prompt ファイルは Issue へのポインタと、セッション固有の一時補足のみを記載する
- タスクが完了したら、コミット後に Issue を close して prompt ファイルを削除する
- `completed/` フォルダには新規ファイルを追加しない（過去の資産はそのまま残す）

---

## 標準ワークフロー

### 1. タスク作成

**① intake ファイルを記入する**

`.github/prompts/templates/task_intake_template.md` の内容を `active/_intake_{slug}.md` にコピーし、VSCode で記入する。`{slug}` はタスク内容を表す短い英語スネークケース。

```
例: .github/prompts/active/_intake_building_gis.md
```

並行して複数タスクを起票する場合も slug が異なるためファイル名が衝突しない。

**② Claude に渡す**

`_intake_{slug}.md` を開いた状態で Claude に「このタスクを Issue にして」と伝える。

Claude がプロジェクト文脈からラベルとマイルストーンを推測し、Issue 本文を下書きする。内容を確認して承認すると、以下を Claude が自動実行する。

```powershell
# Issue 作成
gh issue create --title "タスク名" --label "data-prep" --milestone "Phase1: データ準備" --body "..."

# プロジェクトに追加・ステータス（未着手）・優先度を設定
gh project item-add 1 --owner HitsujiNeko --url https://github.com/HitsujiNeko/MasterResearch/issues/{番号}
# ステータス: 未着手、優先度: intake の指定値 を GraphQL で設定
```

**③ 開始日を設定する**（ユーザが行う）

実際に着手するタイミングで [修士研究タスク管理](https://github.com/users/HitsujiNeko/projects/1) の UI から開始日を設定する。

**④ `_intake_{slug}.md` を削除する**（ユーザが行う）

Issue 作成後、intake ファイルは不要なので削除する。

### 2. prompt ファイル作成

Issue 作成直後に Claude が `active/` に自動生成する。Issue 作成と prompt ファイル生成はセットで行う（生成漏れに注意）。

**命名規則**: `{Issue番号}_{task_name}.prompt.md`（`task_name` は英語スネークケース）

```
例: 1_consider_building_gisdata.prompt.md
```

**中身**:

```markdown
---
agent: agent
---
# #{Issue番号} {タスク名}

> Issue: https://github.com/HitsujiNeko/MasterResearch/issues/{番号}
> （詳細・完了記録はすべて Issue に記載する）

## このセッション固有の追加指示
（Issue に書けない一時的な補足。不要なら削除）

---
共通ルールは CLAUDE.md を参照
```

### 3. タスク実行

**セッション開始時**に Claude は `gh issue view {番号}` で Issue を確認し、現在のステータスに応じて以下のように対応する。

| 現在のステータス | Claude の対応 |
|---|---|
| 未着手 | 「進行中」に自動更新して作業開始 |
| 保留 | 「再開しますか？」と確認してから「進行中」に更新 |
| 進行中 | 変更なし（複数セッション対応） |

**保留にする場合**は、Claude が以下を実行する。

```powershell
gh issue comment {番号} --body "保留理由: ...\n再開条件: ..."
```

ステータスを「保留」に更新し、理由と再開条件を必ずコメントに残す。

**キャンセルにする場合**は、Claude が以下を実行する。

```powershell
gh issue close {番号} --reason "not planned" --comment "キャンセル理由: ..."
# プロジェクトのステータスを「キャンセル」に GraphQL で更新

# prompt ファイルを削除（active/ は git 未追跡のため rm で削除、コミット不要）
Remove-Item .github/prompts/active/{ファイル名}
```

### 4. タスク完了

**① 完了条件を確認し、コミットメッセージを生成する**（Claude が行う）

以下の共通完了条件と Issue 本文の `## 完了条件` をすべて満たしているか確認する。  
確認後、**コミットメッセージをユーザーに提示する**（ユーザーが別途依頼しなくてよいようにする）。

**共通完了条件**:
- Issue で要求された成果物が作成・更新されている
- 関連ドキュメントの更新が完了している
- コードを含む場合は `docs/02_methods/CodingRule.md` の実装前後チェックリストを完了している
- コミット対象が整理されている

**コミットメッセージの形式**（Claude が生成して提示）:

```
{type}: {変更内容の要約} (#{Issue番号})

{変更の詳細・背景（必要な場合）}
```

**② コミットする**（ユーザが行う）

提示されたコミットメッセージを使い、`#{番号}` が含まれていることを確認してからコミットする。

```powershell
git add {成果物}
git commit -m "{Claudeが生成したメッセージ}"
```

**③ 「コミットしました」と Claude に伝える**

コミット完了後、Claude に伝える。コミット前に close は行わない（成果物と完了状態の乖離を防ぐため）。

**④ Issue close・prompt 削除・完了日設定**（Claude が行う）

```powershell
# Issue を close
gh issue close {番号} --comment "完了。成果物: ..."

# プロジェクトのステータスを「完了」・完了日（当日）を GraphQL で更新

# prompt ファイルを削除（active/ は git 未追跡のため rm で削除）
Remove-Item .github/prompts/active/{ファイル名}
```

---

## Claude とユーザの役割分担

| 工程 | Claude | ユーザ |
|---|---|---|
| intake 記入 | — | `_intake_{slug}.md` を記入 |
| Issue 作成 | 下書き・`gh issue create` | 内容を確認して承認 |
| プロジェクト追加・ステータス（未着手）・優先度設定 | `gh project item-add` + GraphQL | — |
| 開始日設定 | — | GitHub UI で設定 |
| `_intake_{slug}.md` 削除 | — | 削除 |
| prompt ファイル生成 | `active/` に自動生成 | — |
| ステータス「進行中」に変更 | セッション開始時（条件付き）に GraphQL で更新 | — |
| タスク実行 | Issue を読んで作業 | — |
| 保留時のコメント記録 | `gh issue comment` + ステータス「保留」 | — |
| 完了条件の確認 | 共通条件 + Issue 固有条件を確認 | — |
| コミット | — | `git commit` → 「コミットしました」と伝える |
| Issue close・prompt 削除・完了日設定 | コミット確認後に `gh issue close` + `Remove-Item` + GraphQL | — |

---

## ラベル一覧

| ラベル | 用途 |
|---|---|
| `analysis` | 統計解析・可視化 |
| `data-prep` | データ取得・前処理・変換 |
| `docs` | ドキュメント・論文執筆 |
| `refactoring` | スクリプトの整理・改善 |
| `workflow` | 運用改善・ツール導入 |
| `literature` | 文献調査 |
| `bug` | スクリプトのバグ修正 |

## マイルストーン一覧

| マイルストーン | 内容 |
|---|---|
| Phase1: データ準備 | データ収集・前処理・評価 |
| Phase2: RQ1 分析 | LST と説明変数の関係分析 |
| Phase3: RQ2-3 分析 | スケール・シナリオ別分析 |
| Phase4: 論文執筆 | 論文・発表資料作成 |
| その他 | フェーズに属さないタスク |

## プロジェクトステータス一覧

| ステータス | 意味 |
|---|---|
| 未着手 | 作業未開始 |
| 進行中 | 作業中 |
| 保留 | 外部要因等で一時停止中（理由を Issue にコメント必須） |
| 完了 | 成果物コミット済み・Issue close 済み |
| キャンセル | 中止（理由を Issue にコメント必須） |

---

## 命名規則

### intake ファイル（一時）

```
.github/prompts/active/_intake_{slug}.md
```

Issue 作成後に削除する。`_` 始まりで active prompt と区別する。`{slug}` は英語スネークケース。

### active prompt

```
{Issue番号}_{task_name}.prompt.md
```

例:
```
1_consider_building_gisdata.prompt.md
```

### completed（新規追加なし）

`completed/` フォルダには今後ファイルを追加しない。過去の資産はそのまま保持する。

---

## 移行について

2026-06-02 以前に作成された `completed/` 配下のファイルは旧運用のアーカイブとして残す。  
新規タスクはすべて本ルールに従い GitHub Issues で管理する。
