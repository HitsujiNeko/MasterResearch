#!/usr/bin/env bash
# 危険な git/gh 操作を検査する PreToolUse hook のラッパー。
#
# 判定は同じディレクトリの dangerous_command_guard.py に委ねる。Python の探索順は
#   1. 環境変数 CLAUDE_GUARD_PYTHON
#   2. PATH 上の python3・python（Microsoft Store の仮エイリアス WindowsApps は除く）
# とし、終了コード 0（許可）・2（拒否）を返した最初の Python の結果に従う。
#
# Python が見つからない・異常終了した場合は、危険語の有無を粗く判定して拒否側に倒す
# （hook は終了コード 2 以外の失敗ではツールの実行を止めないため）。この経路のみ
# echo "git push --force" のような無害なコマンドも拒否しうる。
# PATH が壊れた環境でも粗い判定まで到達できるよう、bash の組み込み機能だけで書く。

# Windows では区切りが \ のパスで呼ばれうるため、/ と \ の両方で親ディレクトリを取る
guard_dir="${BASH_SOURCE[0]%[/\\]*}"
if [ "$guard_dir" = "${BASH_SOURCE[0]}" ]; then
  guard_dir="."
fi
guard_py="$guard_dir/dangerous_command_guard.py"

IFS= read -r -d '' input

# 指定の Python で判定する。判定できた（0 か 2 を返した）場合はその結果で終了する
try_python() {
  local message status
  [ -f "$guard_py" ] || return 1
  message="$(printf '%s' "$input" | "$1" "$guard_py" 2>&1)"
  status=$?
  if [ "$status" -eq 0 ]; then
    exit 0
  fi
  # Python 自身の起動エラー（スクリプトを開けない等）も終了コード 2 になるため、
  # 判定スクリプトの拒否文面であることも確かめる
  if [ "$status" -eq 2 ] && [[ $message == 危険操作ガード:* ]]; then
    printf '%s
' "$message" >&2
    exit 2
  fi
  return 1
}

if [ -n "${CLAUDE_GUARD_PYTHON:-}" ]; then
  try_python "$CLAUDE_GUARD_PYTHON"
fi
# CLAUDE_GUARD_PYTHON で判定できなかった場合だけ PATH を探す（Windows ではプロセス生成が重いため）
for name in python3 python; do
  while IFS= read -r path; do
    case "$path" in
      *WindowsApps*) continue ;;
    esac
    try_python "$path"
  done < <(type -aP "$name")
done

# --- Python で判定できなかった場合の粗い判定 ---
# JSON のエスケープ（\n・\t・\"）を戻してから、語の境界つきで危険語の組を探す
text="${input//\\n/ }"
text="${text//\\t/ }"
text="${text//\\\"/\"}"
shopt -s nocasematch

b='(^|[^[:alnum:]_])'
e='([^[:alnum:]_]|$)'
s='(^|[[:space:]"'"'"'=])'
end='([[:space:]"'"'"';&|)]|$)'
re_tool="${b}(git|gh)${e}"
re_push_danger="(force|delete|mirror|prune|${s}-[uvqnfd46]*[fd][uvqnfd46]*${end}|[[:space:]][+:][^[:space:]:\"])"
re_clean_danger="(force|${s}-[dfxinqe]*[dfx][dfxinqe]*${end})"

deny() {
  printf '%s\n' "危険操作ガード: $1 の可能性があるコマンドを検出しました。" \
    "判定スクリプト（Python）を実行できなかったため、安全側でブロックしました。" \
    "環境変数 CLAUDE_GUARD_PYTHON に Python の実行ファイルを設定してください。" >&2
  exit 2
}

has_word() {
  [[ $text =~ ${b}$1${e} ]]
}

if [[ $text =~ $re_tool ]]; then
  if has_word push && [[ $text =~ $re_push_danger ]]; then
    deny "git push の強制 push またはリモート削除"
  fi
  if has_word reset && [[ $text =~ hard ]]; then
    deny "git reset --hard"
  fi
  if has_word clean && [[ $text =~ $re_clean_danger ]]; then
    deny "git clean によるファイル削除"
  fi
  if has_word pr && has_word merge; then
    deny "gh pr merge"
  fi
  if has_word repo && has_word delete; then
    deny "gh repo delete"
  fi
fi
exit 0
