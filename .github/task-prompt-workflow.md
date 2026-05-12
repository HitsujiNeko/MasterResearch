# タスクプロンプト運用ルール

**最終更新**: 2026-05-13  
**関連ファイル**: [copilot-instructions.md](./copilot-instructions.md), [.github/prompts/templates/task_prompt_template.prompt.md](./prompts/templates/task_prompt_template.prompt.md)

## 目的

`.github/prompts/` 配下のタスク prompt を、着手中・完了済みの状態と対応づけて管理するための運用ルールを定義する。  
このファイルは、タスクの開始から完了後の保管までの流れを明文化し、タスク完了条件と成果物の追跡を明確にすることを目的とする。

## 管理対象

- `active`: 現在進行中のタスク prompt
- `completed`: 完了済みのタスク prompt
- `templates`: 新規 task prompt 作成時の雛形

## 基本方針

- 1つの task prompt は、1つの作業単位として扱う
- タスクの指示内容、成果物、関連文書は task prompt を起点に追跡できる状態にする
- active にある prompt は、未完了タスクとして扱う
- completed にある prompt は、完了済みタスクとして扱う
- Codex は task prompt を参照して作業するが、完了確定や prompt の移動はユーザ判断を優先する

## 正式ルール

- active prompt を completed に移す前に、**必ず** prompt 本文へ `完了記録` を追記する
- `完了記録` には、少なくとも `実施内容` `成果物` `確認内容` を含める
- completed に移す prompt は、**必ず** `YYYYMMDD_<task_name>.prompt.md` 形式で命名する
- 上記2点を満たしていない prompt は completed に移さない

## 標準ワークフロー

### 1. タスク作成

- 新規タスクは `.github/prompts/active/` 配下に `.prompt.md` として作成する
- 新規作成時は、可能な限り `.github/prompts/templates/` 配下のテンプレートをベースにする
- prompt には、少なくとも次を記載する
  - タスク名
  - 背景または目的
  - 入力データまたは参照ファイル
  - 期待する出力
  - 制約や注意事項

### 2. タスク着手

- Codex は、会話で指定された task prompt を起点に作業する
- prompt に明示された関連ファイル、入力データ、出力先、関連文書を先に確認する
- active に複数 prompt があっても、会話で対象が特定されていない他タスクを完了扱いしない

### 3. タスク実行

- 実装、分析、文書修正は task prompt の要件に沿って行う
- 必要に応じて成果物、関連スクリプト、関連文書を更新する
- 仕様未確定事項がある場合は、推測で埋めずに仮定または要確認事項として扱う

### 4. 完了確認

タスク完了は、少なくとも次を満たしたときに判断する。

- prompt が要求する成果物が作成または更新されている
- 必要な関連文書更新が完了している
- 変更対象と変更理由を説明できる
- active prompt に `完了記録` が追記されている
- コミット対象に、成果物と対応する prompt を含められる状態になっている

### 5. 完了後の保管

- active prompt を completed に移す前に、prompt 末尾の `完了記録` を更新する
- `完了記録` には、実施内容、成果物パス、確認内容、必要なら未完了事項を記載する
- task 完了後、**ユーザが** active prompt を `.github/prompts/completed/` に移動する
- completed へ移す際は、ファイル名の先頭に完了日を `YYYYMMDD_` 形式で付与する
- completed の命名規則は以下で固定する

```text
YYYYMMDD_<task_name>.prompt.md
```

例:

```text
20260421_revise_doc_analyze_method.prompt.md
```

### 6. コミット

- タスク完了時は、成果物と完了済み prompt を同じ変更単位でコミットする
- prompt だけ、または成果物だけが先にコミットされる状態は避ける

## Codex とユーザの役割分担

### Codex が行うこと

- active prompt を読み、要件に沿って作業する
- 関連ファイル、成果物、関連文書の整合を確認する
- タスクが完了状態に近いかをユーザに説明する
- 完了に不足している項目があれば明示する

### ユーザが行うこと

- task prompt の作成
- active / completed の最終的な状態管理
- completed への移動時の命名
- タスク完了の最終判断
- 成果物と prompt のコミット

## 命名規則

### active

- 必須規則は `.prompt.md` 拡張子のみとする
- 日付は必須にしない
- タスク内容がわかる英小文字スネークケースを推奨する

例:

```text
convert_elevation_to_csv.prompt.md
```

### completed

- `YYYYMMDD_<task_name>.prompt.md` を必須とする
- `<task_name>` は active 時の内容が分かる名前を維持する

例:

```text
20260512_convert_elevation_to_csv.prompt.md
```

## 完了条件チェック

- 成果物が task prompt の要件を満たしている
- 追加・更新した関連文書に矛盾がない
- 変更ファイルを説明できる
- prompt に `完了記録` を追記済みである
- prompt が completed に移せる状態になっている
- 成果物と prompt をまとめてコミットできる

## 運用上の注意

- 既存の completed prompt には旧命名規則のファイルが含まれていてもよい
- 過去ファイルを一括リネームするかどうかは別判断とする
- 明示的な依頼がない限り、Codex は prompt ファイルの移動や完了処理を自動実施しない
- prompt の内容と実際の成果物がずれた場合は、成果物だけでなく prompt 側も見直す

## 将来の拡張候補

- `blocked/` ディレクトリの導入
- task prompt への完了日、関連コミット、成果物一覧の明記
- prompt テンプレートの統一強化
