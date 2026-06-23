# タスクプロンプト運用ルール

**最終更新**: 2026-06-11  
**関連ファイル**: [CLAUDE.md](../CLAUDE.md), [task_intake_template.md](./prompts/templates/task_intake_template.md), [PULL_REQUEST_TEMPLATE.md](./PULL_REQUEST_TEMPLATE.md)

## 目的

GitHub Issues をタスク管理の正本とし、`.github/prompts/active/` 配下の prompt ファイルを Claude へのセッション briefing として使う運用を定義する。

- **GitHub Issue** = タスクの定義・進捗コメント・完了記録（永続）
- **prompt ファイル** = Claude へのセッション briefing（完了後に削除）

prompt ファイルは completed フォルダに蓄積せず、active に少数のファイルのみが存在する状態を維持する。

---

## 基本方針

- タスクの定義・背景・成果物・完了記録はすべて GitHub Issue に記載する
- prompt ファイルは Issue へのポインタと、セッション固有の一時補足のみを記載する
- タスクごとに作業ブランチを作成し、PRレビュー・squash mergeを経て `main` に統合する
  - ブランチ作成・コミット・push・PR作成: Claude
  - レビュー・動作確認・squash mergeの実行: ユーザー
- PRがsquash mergeされたら、Claudeがmainへの復帰・ローカルブランチ削除・prompt削除・完了処理を行う（Issueは `Closes #{Issue番号}` によりGitHub側で自動closeされる）
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

**③ `_intake_{slug}.md` を削除する**（ユーザが行う）

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

**段階的コミット**: コミットは意味のある単位で分割する。複数の論理的変更を一括コミットしない。コミットメッセージは `{type}: {変更内容の要約} (#{Issue番号})` の形式を維持する。

**セッション開始時の状態確認**

Claude は作業開始前に以下を実行し、作業ディレクトリ・ブランチの状態をユーザーに提示する（前回セッションが中断された場合などに、未コミットの変更や既存PRを見落とさないため）。

```powershell
git status --short
git diff --stat
git log origin/main..HEAD --oneline
gh pr list --head {Issue番号}/{タスク要約英文} --json number,url,state
```

未コミットの変更や未push のコミット、既存PRがある場合は内容を提示し、どこから作業を再開するかをユーザーに確認する。状態を推測して自動的にスキップしない。

Claude は `gh issue view {番号}` で Issue を確認し、現在のステータスに応じて以下のように対応する。

| 現在のステータス | Claude の対応 |
|---|---|
| 未着手 | 「進行中」に自動更新し、開始日（当日）を設定したうえで、`main` から作業ブランチ `{Issue番号}/{タスク要約英文}` を作成・チェックアウトして作業開始 |
| 保留 | 「再開しますか？」と確認してから「進行中」に更新し、既存の作業ブランチをチェックアウトして再開 |
| 進行中 | 変更なし（複数セッション対応） |

ブランチ命名規則は[作業ブランチ](#作業ブランチ)を参照。

**保留にする場合**は、Claude が以下を実行する。

```powershell
gh issue comment {番号} --body "保留理由: ...\n再開条件: ..."
```

ステータスを「保留」に更新し、理由と再開条件を必ずコメントに残す。作業ブランチはそのまま保持し、再開時に同じブランチで作業を継続する。

**キャンセルにする場合**は、Claude が以下を実行する。

```powershell
gh issue close {番号} --reason "not planned" --comment "キャンセル理由: ..."
# プロジェクトのステータスを「キャンセル」に GraphQL で更新

# prompt ファイルを削除（active/ は git 未追跡のため rm で削除、コミット不要）
Remove-Item .github/prompts/active/{ファイル名}

# 作業ブランチを削除する
# PRが作成済みの場合は、ブランチ削除前に PR を close する
gh pr close {PR番号}  # PRが作成済みの場合のみ
git checkout main
git branch -D {Issue番号}/{タスク要約英文}
git push origin --delete {Issue番号}/{タスク要約英文}  # リモートにpush済みの場合のみ
```

### 4. タスク完了

**① 完了条件を確認し、レビューを依頼する**（Claude が行う）

以下の共通完了条件と Issue 本文の `## 完了条件` をすべて満たしているか確認する。
確認後、確認項目をユーザーに提示し、レビュー・動作確認を依頼する。

**共通完了条件**:
- Issue で要求された成果物が作成・更新されている
- 関連ドキュメントの更新が完了している
- コードを含む場合は `docs/02_methods/CodingRule.md` の実装前後チェックリストを完了している
- コミット対象が整理されている

**② レビュー・動作確認**（ユーザが行う）

レビュー・動作確認を行う。未承認の場合は改善事項を Claude に伝え、①に戻る。

**③ コミット・push・PR作成**（Claude が行う）

承認後、Claude は以下の手順で行う。

1. `git status` でステージ対象ファイルを確認し、`.env` 等の機密情報を含むファイルが含まれていないか確認する
2. [`.github/PULL_REQUEST_TEMPLATE.md`](./PULL_REQUEST_TEMPLATE.md) を読み込み、その構成に従ってPR本文を作成する（`Closes #{Issue番号}` を含める）
3. コミットメッセージ・PR本文をユーザーに提示し、確認を得る
4. 確認後、以下を実行する

```powershell
git add {成果物}
git commit -m "{type}: {変更内容の要約} (#{Issue番号})"
git push -u origin {Issue番号}/{タスク要約英文}
gh pr create --title "{type}: {変更内容の要約} (#{Issue番号})" --head {Issue番号}/{タスク要約英文} --body-file {PR本文ファイル}
```

- コミットメッセージ・PRタイトルは `{type}: {変更内容の要約} (#{Issue番号})` の形式に統一する（[commitタイプ一覧](#commitタイプ一覧)参照）
- `gh pr create` には `--head` を必ず明示する（ツール呼び出し間で作業ディレクトリがリセットされ、意図しないブランチがheadになることを防ぐため）

**④ PRレビュー・squash merge**（ユーザが行う）

PR をレビューし、問題なければ GitHub 上で squash merge する。

> リポジトリの「Auto delete head branches」設定が有効な場合、squash merge後にリモートの作業ブランチは自動削除される。

**⑤ 「マージしました」と Claude に伝える**

**⑥ マージ後処理**（Claude が行う）

```powershell
git checkout main
git pull
git branch -D {Issue番号}/{タスク要約英文}

# prompt ファイルを削除（active/ は git 未追跡のため rm で削除）
Remove-Item .github/prompts/active/{ファイル名}

# プロジェクトのステータスを「完了」・完了日（当日）を GraphQL で更新
```

Issue自体は `Closes #{Issue番号}` により GitHub 側で自動close済みのため、`gh issue close` は不要。

---

## Claude とユーザの役割分担

| 工程 | Claude | ユーザ |
|---|---|---|
| intake 記入 | — | `_intake_{slug}.md` を記入 |
| Issue 作成 | 下書き・`gh issue create` | 内容を確認して承認 |
| プロジェクト追加・ステータス（未着手）・優先度設定 | `gh project item-add` + GraphQL | — |
| `_intake_{slug}.md` 削除 | — | 削除 |
| prompt ファイル生成 | `active/` に自動生成 | — |
| ステータス「進行中」に変更・開始日設定・作業ブランチ作成 | セッション開始時（条件付き）に GraphQL更新 + `git checkout -b` | — |
| タスク実行 | Issue を読んで作業 | — |
| 保留時のコメント記録 | `gh issue comment` + ステータス「保留」 | — |
| 完了条件の確認・レビュー依頼 | 共通条件 + Issue 固有条件を確認し提示 | — |
| レビュー・動作確認・承認 | — | レビュー・動作確認 |
| コミット・push・PR作成 | `git commit` + `git push` + `gh pr create` | — |
| PRレビュー・squash merge | — | レビュー・squash merge |
| マージ後処理（main復帰・ブランチ削除・prompt削除・完了日設定） | 「マージしました」連絡後に実行 | 「マージしました」と連絡 |

---

## commitタイプ一覧

コミットメッセージ・PRタイトルの両方で `{type}: {変更内容の要約} (#{Issue番号})` の形式に統一する。

| type | 用途 |
|---|---|
| `feat` | 新機能の追加 |
| `fix` | バグ修正 |
| `docs` | ドキュメントのみの変更 |
| `refactor` | 機能を変更しないコードの整理・改善 |
| `test` | テストの追加・修正 |
| `chore` | 上記に分類されないその他の変更（設定変更など） |

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
| 完了 | PRがsquash merge済み・Issue close 済み |
| キャンセル | 中止（理由を Issue にコメント必須） |

---

## 命名規則

### 作業ブランチ

```
{Issue番号}/{タスク要約英文}
```

`{タスク要約英文}` は英語の kebab-case。`main` から作成する。

例:
```
6/coding-rule-improvement
```

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
