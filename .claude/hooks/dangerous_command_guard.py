"""危険な git/gh 操作を実行前に検査する PreToolUse hook の判定ロジック。

Claude Code の Bash / PowerShell ツールが実行しようとするコマンド文字列を字句解析し、
force push・リモートブランチ削除・``git reset --hard``・``git clean``・``gh pr merge``・
``gh repo delete`` を検出したら拒否する。``permissions.deny`` の前方一致では防げない
サブシェル・``git -C``・変数展開などの形も対象とする。

入出力は Claude Code の hook 仕様に従う。

- 入力: 標準入力の JSON（``tool_name`` と ``tool_input.command``）
- 出力: 許可は終了コード 0、拒否は終了コード 2 と標準エラーへの理由

静的に判定できない形（変数展開・``eval``・インタプリタのコード文字列など）は、
コマンド全体に危険語が含まれる場合に限り安全側（拒否）に倒す。
標準ライブラリのみで動作させる（CI の test ジョブと hook の実行環境を揃えるため）。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
from dataclasses import dataclass, field

# 終了コード（Claude Code の hook 仕様。2 は JSON の allow でも覆せない拒否）
EXIT_ALLOW = 0
EXIT_DENY = 2

# 入れ子（bash -c・eval・$(…) 等）を再帰検査する深さの上限
MAX_DEPTH = 8


class ParseError(Exception):
    """クォートや括弧が閉じていない等、字句解析できない入力。"""


@dataclass(frozen=True)
class Dialect:
    """シェルごとの字句規則。"""

    name: str
    escape: str
    single_quote: bool
    backtick_subst: bool
    dollar: bool
    percent_vars: bool
    separators: frozenset[str]
    braces_always: bool


BASH = Dialect(
    name="bash",
    escape="\\",
    single_quote=True,
    backtick_subst=True,
    dollar=True,
    percent_vars=False,
    separators=frozenset(";&|()"),
    braces_always=False,
)
POWERSHELL = Dialect(
    name="powershell",
    escape="`",
    single_quote=True,
    backtick_subst=False,
    dollar=True,
    percent_vars=False,
    separators=frozenset(";&|(){}"),
    braces_always=True,
)
CMD = Dialect(
    name="cmd",
    escape="^",
    single_quote=False,
    backtick_subst=False,
    dollar=False,
    percent_vars=True,
    separators=frozenset("&|()"),
    braces_always=False,
)

# ツール名 → 字句規則
TOOL_DIALECTS = {"Bash": BASH, "PowerShell": POWERSHELL}

# 区切りを表す内部トークン
SEP = object()


@dataclass
class Word:
    """1 語。

    ``text`` はクォート・エスケープを解いた値で、変数展開・コマンド置換の部分は
    元の表記（``$VAR`` 等）のまま残す。``heredoc`` はヒアドキュメントの本文を表す。
    """

    text: str
    quoted: bool = False
    has_expansion: bool = False
    heredoc: bool = False


@dataclass
class ScanState:
    """1 回の検査全体で共有する状態。"""

    # 変数展開・eval 等により静的に判定できない箇所があったか
    dynamic: bool = False
    # 実行するコマンド名そのものが変数で決まる箇所があったか
    dynamic_head: bool = False
    # 安全側の判定で危険語を探す対象に加える文字列（復号した -EncodedCommand 等）
    extra_texts: list[str] = field(default_factory=list)


# --- 字句解析 ---------------------------------------------------------------

_BASH_SPECIAL_VARS = set("@*#?$!-0123456789")
_NAME_CHARS = re.compile(r"[A-Za-z0-9_]")
_PS_VAR_CHARS = re.compile(r"[A-Za-z0-9_:?^$]")
_ANSI_C_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}


_HEREDOC_START = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([^\s;&|()<>]+))")


def _match_heredoc(s: str, i: int) -> re.Match[str] | None:
    """位置 ``i`` が bash のヒアドキュメント開始（``<<EOF`` 等）ならその一致を返す。"""
    if s.startswith("<<<", i):
        return None
    return _HEREDOC_START.match(s, i)


def _heredoc_spec(m: re.Match[str]) -> tuple[str, bool, bool]:
    """ヒアドキュメント開始の一致から (終端語, 本文を展開しないか, 先頭タブを除くか) を返す。"""
    delim = m.group(2) if m.group(2) is not None else m.group(3)
    literal = delim is not None or m.group(0).lstrip("<-").lstrip(" \t").startswith("\\")
    if delim is None:
        delim = m.group(4)
    return delim, literal, m.group(1) == "-"


def _read_heredoc_body(s: str, newline: int, delim: str, strip_tabs: bool) -> tuple[str, int]:
    """改行位置 ``newline`` の次の行から終端語の行までを読み、(本文, 終端行の改行位置) を返す。

    終端語が見つからない場合は末尾までを本文とする（bash も同様に扱う）。
    """
    lines = []
    pos = newline + 1
    while pos <= len(s):
        end = s.find("\n", pos)
        if end == -1:
            end = len(s)
        line = s[pos:end].rstrip("\r")
        if (line.lstrip("\t") if strip_tabs else line) == delim:
            return "\n".join(lines), end
        lines.append(line)
        pos = end + 1
    return "\n".join(lines), len(s)


def _find_closing_paren(s: str, start: int, dialect: Dialect) -> int:
    """``start`` の直後から対応する ``)`` の位置を返す。

    クォート・括弧の入れ子・ヒアドキュメントの本文を考慮する。
    """
    depth = 1
    i = start
    n = len(s)
    pending: list[tuple[str, bool, bool]] = []
    while i < n:
        c = s[i]
        if dialect is BASH and c == "<":
            m = _match_heredoc(s, i)
            if m:
                pending.append(_heredoc_spec(m))
                i = m.end()
                continue
        if c == "\n" and pending:
            for delim, _literal, strip_tabs in pending:
                _body, i = _read_heredoc_body(s, i, delim, strip_tabs)
            pending = []
            continue
        if c == dialect.escape:
            i += 2
            continue
        if c == "'" and dialect.single_quote:
            j = s.find("'", i + 1)
            if j == -1:
                raise ParseError("引用符が閉じていない")
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == dialect.escape else 1
            if j >= n:
                raise ParseError("引用符が閉じていない")
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ParseError("括弧が閉じていない")


def _find_closing_brace(s: str, start: int) -> int:
    """``start`` の直後から対応する ``}`` の位置を返す（入れ子のみ考慮）。"""
    depth = 1
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ParseError("波括弧が閉じていない")


def _decode_ansi_c(s: str, start: int) -> tuple[str, int]:
    """bash の ``$'…'`` の中身を復号し、(値, 閉じ引用符の次の位置) を返す。"""
    out = []
    i = start
    n = len(s)
    while i < n:
        c = s[i]
        if c == "'":
            return "".join(out), i + 1
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in _ANSI_C_ESCAPES:
                out.append(_ANSI_C_ESCAPES[nxt])
                i += 2
                continue
            m = None
            if nxt == "x":
                m = re.match(r"[0-9A-Fa-f]{1,2}", s[i + 2 :])
                base = 16
            elif nxt in "uU":
                m = re.match(r"[0-9A-Fa-f]{1,8}", s[i + 2 :])
                base = 16
            if m:
                out.append(chr(int(m.group(0), base)))
                i += 2 + len(m.group(0))
                continue
            m = re.match(r"[0-7]{1,3}", s[i + 1 :])
            if m:
                out.append(chr(int(m.group(0), 8)))
                i += 1 + len(m.group(0))
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    raise ParseError("引用符が閉じていない")


class _Tokenizer:
    """コマンド文字列を語と区切りの列に分割する。

    ``$(…)``・バッククォート・``${…}`` の内側は、独立したコマンド文字列として
    ``nested`` に集める（呼び出し側が再帰的に検査する）。
    """

    def __init__(self, s: str, dialect: Dialect) -> None:
        self.s = s
        self.d = dialect
        self.items: list[object] = []
        self.nested: list[tuple[str, Dialect]] = []
        self._chars: list[str] = []
        self._in_word = False
        self._quoted = False
        self._expansion = False
        self._pending_heredocs: list[tuple[str, bool, bool]] = []

    # 語の組み立て
    def _add(self, text: str, quoted: bool = False) -> None:
        self._chars.append(text)
        self._in_word = True
        self._quoted = self._quoted or quoted

    def _add_expansion(self, raw: str) -> None:
        """展開部分を元の表記のまま語に加え、展開ありと記録する。"""
        self._add(raw)
        self._expansion = True

    def _flush(self) -> None:
        if self._in_word:
            self.items.append(Word("".join(self._chars), self._quoted, self._expansion))
        self._chars = []
        self._in_word = False
        self._quoted = False
        self._expansion = False

    def _sep(self) -> None:
        self._flush()
        self.items.append(SEP)

    def _is_boundary(self, i: int) -> bool:
        """位置 ``i`` が語の境界（空白・区切り・末尾）か。"""
        return i >= len(self.s) or self.s[i] in " \t\r\n" or self.s[i] in self.d.separators

    # 展開
    def _dollar(self, i: int) -> int:
        """``$`` で始まる展開を処理し、次に読む位置を返す。"""
        s = self.s
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if nxt == "(":
            end = _find_closing_paren(s, i + 2, self.d)
            self.nested.append((s[i + 2 : end], self.d))
            self._add_expansion(s[i : end + 1])
            return end + 1
        if nxt == "{":
            end = _find_closing_brace(s, i + 2)
            self.nested.append((s[i + 2 : end], self.d))
            self._add_expansion(s[i : end + 1])
            return end + 1
        if self.d is BASH:
            if nxt == "'":
                value, end = _decode_ansi_c(s, i + 2)
                self._add(value, quoted=True)
                return end
            if nxt == '"':
                return self._double_quote(i + 1)
            if nxt and nxt in _BASH_SPECIAL_VARS:
                self._add_expansion(s[i : i + 2])
                return i + 2
            pattern = _NAME_CHARS
        else:
            pattern = _PS_VAR_CHARS
        j = i + 1
        while j < len(s) and pattern.match(s[j]):
            j += 1
        if j == i + 1:
            self._add("$")
            return i + 1
        self._add_expansion(s[i:j])
        return j

    def _backtick(self, i: int) -> int:
        """bash のバッククォートによるコマンド置換を処理する。"""
        j = i + 1
        while j < len(self.s) and self.s[j] != "`":
            j += 2 if self.s[j] == "\\" else 1
        if j >= len(self.s):
            raise ParseError("バッククォートが閉じていない")
        self.nested.append((self.s[i + 1 : j], self.d))
        self._add_expansion(self.s[i : j + 1])
        return j + 1

    def _percent(self, i: int) -> int:
        """cmd の ``%VAR%`` を展開として扱う。"""
        m = re.match(r"%[^%\s]+%", self.s[i:])
        if m:
            self._add_expansion(m.group(0))
            return i + len(m.group(0))
        self._add("%")
        return i + 1

    # 引用符
    def _single_quote(self, i: int) -> int:
        s = self.s
        out = []
        j = i + 1
        while True:
            k = s.find("'", j)
            if k == -1:
                raise ParseError("引用符が閉じていない")
            out.append(s[j:k])
            # PowerShell では '' が 1 文字の ' を表す
            if self.d is POWERSHELL and s[k + 1 : k + 2] == "'":
                out.append("'")
                j = k + 2
                continue
            self._add("".join(out), quoted=True)
            return k + 1

    def _double_quote(self, i: int) -> int:
        s = self.s
        d = self.d
        j = i + 1
        self._add("", quoted=True)
        while j < len(s):
            c = s[j]
            if c == '"':
                if d is POWERSHELL and s[j + 1 : j + 2] == '"':
                    self._add('"')
                    j += 2
                    continue
                return j + 1
            if c == d.escape and d is not CMD and j + 1 < len(s):
                nxt = s[j + 1]
                if d is BASH and nxt not in '$`"\\\n':
                    self._add(c)
                    j += 1
                    continue
                if nxt != "\n":
                    self._add(nxt)
                j += 2
                continue
            if c == "$" and d.dollar:
                j = self._dollar(j)
                continue
            if c == "`" and d.backtick_subst:
                j = self._backtick(j)
                continue
            if c == "%" and d.percent_vars:
                j = self._percent(j)
                continue
            self._add(c)
            j += 1
        raise ParseError("引用符が閉じていない")

    def _expandable_body(self, body: str) -> None:
        """展開される本文（ヒアドキュメント等）からコマンド置換を集める。"""
        escaped = body.replace(self.d.escape, self.d.escape * 2).replace('"', self.d.escape + '"')
        inner = _Tokenizer('"' + escaped + '"', self.d)
        inner.run()
        self.nested.extend(inner.nested)

    def _here_string(self, i: int) -> int:
        """PowerShell のヒア文字列 ``@'…'@`` / ``@"…"@`` を処理する。"""
        s = self.s
        quote = s[i + 1]
        end = s.find("\n" + quote + "@", i + 2)
        if end == -1:
            raise ParseError("ヒア文字列が閉じていない")
        body = s[s.index("\n", i) + 1 : end]
        if quote == '"':
            self._expandable_body(body)
        self._add(body, quoted=True)
        return end + 3

    def _heredoc_bodies(self, newline: int) -> int:
        """改行位置で、保留中のヒアドキュメント本文を読み取り、次に読む位置を返す。"""
        pos = newline
        for delim, literal, strip_tabs in self._pending_heredocs:
            body, pos = _read_heredoc_body(self.s, pos, delim, strip_tabs)
            if not literal:
                self._expandable_body(body)
            self.items.append(Word(body, quoted=True, heredoc=True))
        self._pending_heredocs = []
        return pos

    def run(self) -> None:
        s = self.s
        d = self.d
        i = 0
        n = len(s)
        while i < n:
            c = s[i]
            if c in " \t\r":
                self._flush()
                i += 1
            elif c == "\n":
                self._flush()
                if self._pending_heredocs:
                    i = self._heredoc_bodies(i)
                self.items.append(SEP)
                i += 1
            elif d is BASH and c == "<" and _match_heredoc(s, i):
                m = _match_heredoc(s, i)
                self._flush()
                self._pending_heredocs.append(_heredoc_spec(m))
                i = m.end()
            elif c == d.escape:
                # 行継続（エスケープ＋改行）は空白と同じに扱う
                if s[i + 1 : i + 2] == "\n" or s[i + 1 : i + 3] == "\r\n":
                    self._flush()
                    i += 2 if s[i + 1] == "\n" else 3
                elif i + 1 < n:
                    self._add(s[i + 1], quoted=True)
                    i += 2
                else:
                    i += 1
            elif c == "'" and d.single_quote:
                i = self._single_quote(i)
            elif c == '"':
                i = self._double_quote(i)
            elif c == "$" and d.dollar:
                i = self._dollar(i)
            elif c == "`" and d.backtick_subst:
                i = self._backtick(i)
            elif c == "%" and d.percent_vars:
                i = self._percent(i)
            elif d is POWERSHELL and c == "@" and re.match(r"@['\"][ \t]*\r?\n", s[i:]):
                i = self._here_string(i)
            elif d is POWERSHELL and c == "@" and _NAME_CHARS.match(s[i + 1 : i + 2] or " "):
                # スプラッティング（@args）
                j = i + 1
                while j < n and _NAME_CHARS.match(s[j]):
                    j += 1
                self._add_expansion(s[i:j])
                i = j
            elif c in d.separators:
                self._sep()
                i += 1
            elif c in "{}" and not d.braces_always:
                # bash の { } は単独の語のときだけ複合コマンドの区切りになる
                if not self._in_word and self._is_boundary(i + 1):
                    self._sep()
                else:
                    # 語中の { はブレース展開になりうる
                    self._add(c)
                    self._expansion = self._expansion or (c == "{" and d is BASH)
                i += 1
            else:
                self._add(c)
                if d is BASH and c in "*?":
                    # グロブは実行時のファイル名に依存する
                    self._expansion = True
                i += 1
        self._flush()
        if self._pending_heredocs:
            self._heredoc_bodies(n)


def tokenize(command: str, dialect: Dialect) -> tuple[list[list[Word]], list[tuple[str, Dialect]]]:
    """コマンド文字列を単純コマンド（語のリスト）の列と、入れ子のコマンド文字列に分ける。"""
    tok = _Tokenizer(command, dialect)
    tok.run()
    commands: list[list[Word]] = [[]]
    for item in tok.items:
        if item is SEP:
            commands.append([])
        else:
            commands[-1].append(item)
    return [c for c in commands if c], tok.nested


# --- コマンド名の正規化と分類 ------------------------------------------------

_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".com")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
_PS_ASSIGNMENT_OPERATOR = re.compile(r"^[-+*/%]?=$|^\?\?=$")

# 先頭にあっても実行対象を変えない語（シェルの予約語）
_BASH_KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}"}
# 後続の引数のどこかで別のコマンドを実行しうる語（後続を全位置で検査する）
_WRAPPERS = {
    "command",
    "builtin",
    "exec",
    "env",
    "sudo",
    "doas",
    "time",
    "nohup",
    "xargs",
    "timeout",
    "nice",
    "ionice",
    "setsid",
    "stdbuf",
    "watch",
    "find",
    "parallel",
    "wsl",
    "start",
}
_SCRIPT_SUFFIXES = (".sh", ".bash", ".ps1", ".py", ".bat", ".cmd")
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ash", "busybox"}
_POWERSHELLS = {"powershell", "pwsh", "powershell_ise"}
_INTERPRETERS = re.compile(
    r"^(python[0-9.]*|pythonw|py|node|nodejs|perl|ruby|php|deno|bun|rscript|lua|osascript)$"
)


def normalize_name(text: str) -> str:
    """実行ファイル名をパス・拡張子を除いた小文字の名前にする。"""
    name = text.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in _EXECUTABLE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _short_letters(arg: str, value_letters: str) -> str:
    """結合された短縮オプション（``-fdx``）の文字列を返す。値を取る文字以降は除く。"""
    letters = []
    for ch in arg[1:]:
        if ch in value_letters:
            break
        letters.append(ch)
    return "".join(letters)


def _long_name(arg: str) -> str:
    """``--name=value`` から ``name`` を取り出す。"""
    return arg[2:].split("=", 1)[0]


def _abbrev_of(name: str, *targets: str) -> bool:
    """git の長いオプションの省略形（一意な前方一致）として ``targets`` のいずれかに当たるか。"""
    return bool(name) and any(t.startswith(name) for t in targets)


# --- git / gh の判定 ---------------------------------------------------------

# 値を別の語で受け取る git のグローバルオプション
_GIT_GLOBAL_VALUE_OPTIONS = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--config-env",
    "--list-cmds",
}


def _check_push(args: list[Word]) -> str | None:
    """git push の引数から force・リモート削除を検出する。"""
    options_ended = False
    for w in args:
        t = w.text
        if not options_ended and t == "--":
            options_ended = True
            continue
        if not options_ended and t.startswith("--"):
            name = _long_name(t)
            if _abbrev_of(name, "force", "force-with-lease"):
                return f"git push の強制 push（{t}）"
            if _abbrev_of(name, "delete", "mirror", "prune"):
                return f"git push によるリモート ref の削除（{t}）"
            continue
        if not options_ended and t.startswith("-") and len(t) > 1:
            letters = _short_letters(t, value_letters="o")
            if "f" in letters:
                return f"git push の強制 push（{t}）"
            if "d" in letters:
                return f"git push によるリモートブランチの削除（{t}）"
            continue
        if t.startswith("+") and len(t) > 1:
            return f"git push の強制 push（refspec {t}）"
        if t.startswith(":") and len(t) > 1:
            return f"git push によるリモートブランチの削除（refspec {t}）"
    return None


def _check_reset(args: list[Word]) -> str | None:
    """git reset --hard を検出する。"""
    for w in args:
        t = w.text
        if t == "--":
            break
        if t.startswith("--") and _abbrev_of(_long_name(t), "hard"):
            return f"git reset --hard（{t}）"
    return None


def _check_clean(args: list[Word]) -> str | None:
    """git clean の実削除を検出する（-n / --dry-run を含む場合は許可）。"""
    dangerous = None
    for w in args:
        t = w.text
        if t == "--":
            break
        if t.startswith("--"):
            name = _long_name(t)
            if _abbrev_of(name, "dry-run"):
                return None
            if _abbrev_of(name, "force"):
                dangerous = dangerous or t
        elif t.startswith("-") and len(t) > 1:
            letters = _short_letters(t, value_letters="e")
            if "n" in letters:
                return None
            if set(letters) & set("fxXd"):
                dangerous = dangerous or t
    return f"git clean によるファイル削除（{dangerous}）" if dangerous else None


_GIT_SUBCOMMAND_CHECKS = {"push": _check_push, "reset": _check_reset, "clean": _check_clean}


def _check_git(args: list[Word], state: ScanState) -> str | None:
    """git の呼び出しを検査する。"""
    i = 0
    while i < len(args):
        t = args[i].text
        if t in _GIT_GLOBAL_VALUE_OPTIONS:
            i += 2
        elif t.startswith("-") and t != "-":
            i += 1
        else:
            break
    if i >= len(args):
        return None
    check = _GIT_SUBCOMMAND_CHECKS.get(args[i].text)
    # サブコマンド自体、または検査対象のサブコマンドの引数が変数で決まる場合は静的に判定できない
    # （commit -m "$(…)" 等の無関係な展開は対象外とし、メッセージ中の語での誤検知を避ける）
    if args[i].has_expansion or (check and any(w.has_expansion for w in args[i + 1 :])):
        state.dynamic = True
    return check(args[i + 1 :]) if check else None


def _check_gh(args: list[Word], state: ScanState) -> str | None:
    """gh の呼び出しを検査する（-R/--repo の位置を問わない）。"""
    positional: list[Word] = []
    skip_next = False
    for w in args:
        t = w.text
        if skip_next:
            skip_next = False
            continue
        if t in ("-R", "--repo"):
            skip_next = True
            continue
        if t.startswith("-"):
            continue
        positional.append(w)
    # サブコマンドが変数で決まる場合は静的に判定できない（--body "$(…)" 等の値は対象外）
    if any(w.has_expansion for w in positional[:2]):
        state.dynamic = True
    subcommand = [w.text for w in positional[:2]]
    if subcommand == ["pr", "merge"]:
        return "gh pr merge（マージはユーザーの専権）"
    if subcommand == ["repo", "delete"]:
        return "gh repo delete"
    return None


# --- 入れ子のコマンド文字列 --------------------------------------------------


def _join(words: list[Word]) -> str:
    """語を空白で連結してコマンド文字列に戻す。"""
    return " ".join(w.text for w in words)


def _check_shell(args: list[Word], stdin: list[str], state: ScanState, depth: int) -> str | None:
    """``bash -c "…"`` の文字列、またはヒアドキュメントで渡したスクリプトを検査する。"""
    for k, w in enumerate(args):
        t = w.text
        if t.startswith("-") and not t.startswith("--") and "c" in t[1:]:
            rest = [a for a in args[k + 1 :] if not a.text.startswith("-")]
            return _scan(rest[0].text, BASH, state, depth + 1) if rest else None
    if stdin:
        return _scan("\n".join(stdin), BASH, state, depth + 1)
    # スクリプトファイル・パイプから読む場合は内容を静的に判定できない
    state.dynamic = True
    return None


def _check_powershell(args: list[Word], state: ScanState, depth: int) -> str | None:
    """``powershell -Command "…"`` / ``-EncodedCommand`` の文字列を検査する。"""
    value_options = (
        "executionpolicy",
        "ep",
        "ex",
        "windowstyle",
        "w",
        "configurationname",
        "workingdirectory",
        "wd",
        "settingsfile",
        "outputformat",
        "of",
        "o",
        "inputformat",
        "if",
        "i",
        "version",
        "v",
        "psconsolefile",
        "custompipename",
        "configurationfile",
    )
    k = 0
    while k < len(args):
        t = args[k].text
        if t.startswith(("-", "/")) and len(t) > 1:
            name = t.lstrip("-/").lower()
            if name in ("e", "ec") or (len(name) >= 3 and "encodedcommand".startswith(name)):
                if k + 1 >= len(args):
                    return None
                try:
                    decoded = base64.b64decode(args[k + 1].text, validate=True).decode("utf-16-le")
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    state.dynamic = True
                    return None
                state.extra_texts.append(decoded)
                return _scan(decoded, POWERSHELL, state, depth + 1)
            if "command".startswith(name):
                body = _join(args[k + 1 :])
                if body.strip() in ("", "-"):
                    state.dynamic = True
                return _scan(body, POWERSHELL, state, depth + 1)
            if _abbrev_of(name, "file"):
                state.dynamic = True
                return None
            k += 2 if name in value_options else 1
            continue
        # 位置引数以降はコマンドとして解釈される（powershell.exe の既定）
        return _scan(_join(args[k:]), POWERSHELL, state, depth + 1)
    # 引数なしは標準入力から読むため静的に判定できない
    state.dynamic = True
    return None


def _check_cmd(args: list[Word], state: ScanState, depth: int) -> str | None:
    """``cmd /c "…"`` の文字列を検査する。"""
    for k, w in enumerate(args):
        t = w.text.lower()
        if t.startswith(("/c", "/k")):
            head = w.text[2:]
            body = " ".join(([head] if head else []) + [a.text for a in args[k + 1 :]])
            return _scan(body, CMD, state, depth + 1)
    state.dynamic = True
    return None


def _check_invoke_expression(args: list[Word], state: ScanState, depth: int) -> str | None:
    """``Invoke-Expression "…"`` の文字列を検査する。"""
    # -Command パラメータ名そのものは除く
    words = [
        w for w in args if not (w.text.startswith("-") and "command".startswith(w.text[1:].lower()))
    ]
    if any(w.has_expansion for w in words):
        state.dynamic = True
    return _scan(_join(words), POWERSHELL, state, depth + 1)


# 値を別の語で受け取る Start-Process のパラメータ（FilePath・ArgumentList 以外）
_START_PROCESS_VALUE_OPTIONS = (
    "workingdirectory",
    "verb",
    "windowstyle",
    "credential",
    "environment",
    "redirectstandarderror",
    "redirectstandardinput",
    "redirectstandardoutput",
)


def _check_start_process(args: list[Word], state: ScanState, depth: int) -> str | None:
    """``Start-Process git -ArgumentList …`` を実行ファイル＋引数として検査する。"""
    file_path = None
    arg_list: list[str] = []
    positional: list[str] = []
    k = 0
    while k < len(args):
        t = args[k].text
        name = t.lstrip("-").lower() if t.startswith("-") else ""
        if name and _abbrev_of(name, "filepath"):
            file_path = args[k + 1].text if k + 1 < len(args) else None
            k += 2
        elif name and (_abbrev_of(name, "argumentlist") or name == "args"):
            arg_list.extend(a.text for a in args[k + 1 : k + 2])
            k += 2
        elif name:
            k += 2 if _abbrev_of(name, *_START_PROCESS_VALUE_OPTIONS) else 1
        else:
            positional.append(t)
            k += 1
    if file_path is None and positional:
        file_path = positional.pop(0)
    if not arg_list and positional:
        arg_list = positional
    if file_path is None:
        return None
    # 配列指定（'push','-f'）はカンマ区切りを空白に置き換える
    body = file_path + " " + " ".join(a.replace(",", " ") for a in arg_list)
    if re.search(r"\s", file_path):
        body = '"' + file_path + '" ' + " ".join(a.replace(",", " ") for a in arg_list)
    return _scan(body, POWERSHELL, state, depth + 1)


# --- 単純コマンドの検査 ------------------------------------------------------


def _check_simple(words: list[Word], dialect: Dialect, state: ScanState, depth: int) -> str | None:
    """1 つの単純コマンドを検査し、拒否理由（なければ None）を返す。"""
    heredocs = [w for w in words if w.heredoc]
    words = [w for w in words if not w.heredoc]
    stdin = [w.text for w in heredocs]
    i = 0
    while i < len(words):
        t = words[i].text
        if dialect is not POWERSHELL and not words[i].quoted and _ASSIGNMENT.match(t):
            i += 1
        elif dialect is BASH and not words[i].quoted and t in _BASH_KEYWORDS:
            i += 1
        elif dialect is POWERSHELL and t == ".":
            i += 1
        elif (
            dialect is POWERSHELL
            and words[i].has_expansion
            and i + 1 < len(words)
            and _PS_ASSIGNMENT_OPERATOR.match(words[i + 1].text)
        ):
            # 代入文（$x = …）は右辺をコマンドとして検査する
            i += 2
        else:
            break
    if i >= len(words):
        return None
    head = words[i]
    args = words[i + 1 :]
    if head.has_expansion:
        # 実行するコマンド自体が変数で決まる
        state.dynamic = True
        state.dynamic_head = True
        return None
    name = normalize_name(head.text)

    if name == "git":
        return _check_git(args, state)
    if name == "gh":
        return _check_gh(args, state)
    if name in _SHELLS:
        return _check_shell(args, stdin, state, depth)
    if name in _POWERSHELLS:
        if stdin:
            reason = _scan("\n".join(stdin), POWERSHELL, state, depth + 1)
            if reason:
                return reason
        return _check_powershell(args, state, depth)
    if name == "cmd":
        return _check_cmd(args, state, depth)
    if name in ("invoke-expression", "iex"):
        return _check_invoke_expression(args, state, depth)
    if name in ("start-process", "saps") or (name == "start" and dialect is POWERSHELL):
        return _check_start_process(args, state, depth)
    if name == "eval":
        if any(w.has_expansion for w in args):
            state.dynamic = True
        return _scan(_join(args), dialect, state, depth + 1)
    if name == "alias" and dialect is BASH:
        for w in args:
            if "=" in w.text:
                reason = _scan(w.text.split("=", 1)[1], BASH, state, depth + 1)
                if reason:
                    return reason
        return None
    if name == "trap" and dialect is BASH and args:
        return _scan(args[0].text, BASH, state, depth + 1)
    if (
        _INTERPRETERS.match(name)
        or name == "source"
        or (name == "." and dialect is BASH)
        or head.text.lower().endswith(_SCRIPT_SUFFIXES)
    ):
        # インタプリタのコード・スクリプトファイルの内容は静的に判定できない
        state.dynamic = True
        return None
    if name in _WRAPPERS:
        for k in range(len(args)):
            reason = _check_simple(args[k:] + heredocs, dialect, state, depth + 1)
            if reason:
                return reason
    return None


def _scan(command: str, dialect: Dialect, state: ScanState, depth: int) -> str | None:
    """コマンド文字列を（入れ子も含めて）検査し、拒否理由を返す。"""
    if depth > MAX_DEPTH:
        state.dynamic = True
        return None
    commands, nested = tokenize(command, dialect)
    for inner, inner_dialect in nested:
        reason = _scan(inner, inner_dialect, state, depth + 1)
        if reason:
            return reason
    for words in commands:
        reason = _check_simple(words, dialect, state, depth)
        if reason:
            return reason
    return None


# --- 静的に判定できない形の安全側判定 ----------------------------------------

_TOOL_WORD = re.compile(r"\b(git|gh)\b", re.IGNORECASE)
_WORD_START = r"(?:^|(?<=[\s'\"=]))"
_WORD_END = r"(?=$|[\s'\";&|)])"
_COARSE_RULES = (
    (
        re.compile(r"\bpush\b"),
        re.compile(
            r"force|delete|mirror|prune"
            + rf"|{_WORD_START}-[uvqn46]*[fd][uvqnfd46]*{_WORD_END}"
            + rf"|{_WORD_START}[+:][^\s:]"
        ),
        "git push の強制 push またはリモート削除",
    ),
    (re.compile(r"\breset\b"), re.compile(r"hard"), "git reset --hard"),
    (
        re.compile(r"\bclean\b"),
        re.compile(rf"force|{_WORD_START}-[dfxXinqe]*[dfxX][dfxXinqe]*{_WORD_END}"),
        "git clean によるファイル削除",
    ),
    (re.compile(r"\bpr\b"), re.compile(r"\bmerge\b"), "gh pr merge"),
    (re.compile(r"\brepo\b"), re.compile(r"\bdelete\b"), "gh repo delete"),
)


def coarse_danger(text: str, require_tool: bool = True) -> str | None:
    """コマンド全体に危険語の組が含まれるかを粗く判定し、該当した操作名を返す。"""
    if require_tool and not _TOOL_WORD.search(text):
        return None
    for trigger, danger, label in _COARSE_RULES:
        if trigger.search(text) and danger.search(text):
            return label
    return None


# --- 公開関数と CLI ----------------------------------------------------------


def inspect_command(command: str, tool_name: str = "Bash") -> str | None:
    """コマンド文字列を検査し、拒否する場合はその理由を、許可する場合は None を返す。"""
    dialect = TOOL_DIALECTS.get(tool_name)
    if dialect is None or not command.strip():
        return None
    state = ScanState()
    try:
        reason = _scan(command, dialect, state, depth=0)
    except Exception:  # noqa: BLE001 - 解析できない入力・内部エラーは危険語の有無で判定する
        label = coarse_danger(command)
        return f"{label}（構文を解析できないため安全側で判定）" if label else None
    if reason:
        return reason
    if state.dynamic:
        text = "\n".join([command, *state.extra_texts])
        # コマンド名自体が変数のときは git/gh の語が現れなくても危険語で判定する
        label = coarse_danger(text, require_tool=not state.dynamic_head)
        if label:
            return f"{label}（変数展開・eval 等で静的に判定できないため安全側で判定）"
    return None


def _deny_message(reason: str) -> str:
    """拒否時に標準エラーへ出す文面を作る。"""
    return (
        f"危険操作ガード: {reason} を検出したため実行をブロックしました。\n"
        "この操作が必要な場合は、ユーザーに依頼して手動で実行してもらってください。\n"
    )


def main() -> int:
    """標準入力の hook 入力 JSON を検査し、終了コードを返す。"""
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
        tool_name = payload.get("tool_name", "")
        command = (payload.get("tool_input") or {}).get("command", "")
        if not isinstance(command, str):
            return EXIT_ALLOW
        reason = inspect_command(command, tool_name)
    except Exception:  # noqa: BLE001 - 判定の内部エラーは握りつぶし、危険語の有無で判定する
        label = coarse_danger(raw)
        reason = f"{label}（判定処理の内部エラーのため安全側で判定）" if label else None
    if reason:
        sys.stderr.buffer.write(_deny_message(reason).encode("utf-8"))
        sys.stderr.flush()
        return EXIT_DENY
    return EXIT_ALLOW


if __name__ == "__main__":
    sys.exit(main())
