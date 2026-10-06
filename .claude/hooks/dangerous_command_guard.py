"""危険な git/gh 操作を実行前に検査する PreToolUse hook の判定ロジック。

Claude Code の Bash / PowerShell ツールが実行しようとするコマンド文字列を字句解析し、
force push・リモートブランチ削除・``git reset --hard``・``git clean``・``gh pr merge``・
``gh repo delete`` を検出したら拒否する。``permissions.deny`` の前方一致では防げない
サブシェル・``git -C``・変数展開などの形も対象とする。

入出力は Claude Code の hook 仕様に従う。

- 入力: 標準入力の JSON（``tool_name`` と ``tool_input.command``）
- 出力: 許可は終了コード 0、拒否は終了コード 2 と標準エラーへの理由

静的に判定できない形（変数展開・``eval``・インタプリタのコード文字列など）は、
判定できなかった単純コマンド自身と、同じコマンド内の代入・パイプの接続元に危険語の組が
含まれる場合に限り安全側（拒否）に倒す。
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
    comments: bool


BASH = Dialect("bash", "\\", True, True, True, False, True)
POWERSHELL = Dialect("powershell", "`", True, False, True, False, True)
CMD = Dialect("cmd", "^", False, False, False, True, False)

# ツール名 → 字句規則
TOOL_DIALECTS = {"Bash": BASH, "PowerShell": POWERSHELL}


@dataclass
class Word:
    """1 語。

    ``text`` はクォート・エスケープを解いた値で、変数展開・コマンド置換の部分は
    元の表記（``$VAR`` 等）のまま残す。
    """

    text: str
    quoted: bool = False
    has_expansion: bool = False


@dataclass
class SimpleCommand:
    """区切り（``;`` ``&&`` ``|`` 改行など）で分けた 1 つの単純コマンド。"""

    words: list[Word] = field(default_factory=list)
    # 元のコマンド文字列のうち、このコマンドに当たる部分（安全側の判定に使う）
    raw: str = ""
    # 標準入力に渡すヒアドキュメント・ヒア文字列の本文
    stdin_texts: list[str] = field(default_factory=list)
    # パイプ（|）で標準出力をこのコマンドに渡している直前のコマンド
    piped_from: SimpleCommand | None = None


@dataclass
class ScanState:
    """1 回の検査全体で共有する状態。"""

    # 検査対象のコマンド文字列全体
    top_text: str = ""
    # 変数展開・eval 等により静的に判定できない箇所があったか
    dynamic: bool = False
    # 実行するコマンド名そのものが変数で決まる箇所があったか
    dynamic_head: bool = False
    # 安全側の判定で危険語を探す文字列（判定できなかったコマンド・代入・復号した文字列等）
    coarse_texts: list[str] = field(default_factory=list)


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
_HEREDOC_START = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|(\\?)([^\s;&|()<>]+))")
_WHITESPACE = " \t\r"


def _match_heredoc(s: str, i: int) -> re.Match[str] | None:
    """位置 ``i`` が bash のヒアドキュメント開始（``<<EOF`` 等）ならその一致を返す。

    Args:
        s: コマンド文字列。
        i: 調べる位置。

    Returns:
        ヒアドキュメント開始の一致。該当しない（``<<<`` を含む）場合は None。
    """
    if s.startswith("<<<", i):
        return None
    return _HEREDOC_START.match(s, i)


def _heredoc_spec(m: re.Match[str]) -> tuple[str, bool, bool]:
    """ヒアドキュメント開始の一致から終端語と読み方を取り出す。

    Args:
        m: ``_match_heredoc`` の一致。

    Returns:
        (終端語, 本文を展開しないか, 各行の先頭タブを除くか)。
    """
    for quoted in (m.group(2), m.group(3)):
        if quoted is not None:
            return quoted, True, m.group(1) == "-"
    return m.group(5), m.group(4) == "\\", m.group(1) == "-"


def _read_heredoc_body(s: str, newline: int, delim: str, strip_tabs: bool) -> tuple[str, int]:
    """改行の次の行から終端語の行までを本文として読む。

    終端語が見つからない場合は末尾までを本文とする（bash も同様に扱う）。

    Args:
        s: コマンド文字列。
        newline: ヒアドキュメント開始行の末尾の改行位置。
        delim: 終端語。
        strip_tabs: ``<<-`` のとき True（終端語の行の先頭タブを無視する）。

    Returns:
        (本文, 終端語の行の末尾の改行位置)。
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

    Args:
        s: コマンド文字列。
        start: 開き括弧の次の位置。
        dialect: 字句規則。

    Returns:
        対応する閉じ括弧の位置。

    Raises:
        ParseError: 括弧・引用符が閉じていない場合。
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
    """``start`` の直後から対応する ``}`` の位置を返す（入れ子のみ考慮）。

    Args:
        s: コマンド文字列。
        start: 開き波括弧の次の位置。

    Returns:
        対応する閉じ波括弧の位置。

    Raises:
        ParseError: 波括弧が閉じていない場合。
    """
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
    """bash の ``$'…'`` の中身を復号する。

    Args:
        s: コマンド文字列。
        start: ``$'`` の直後の位置。

    Returns:
        (復号した値, 閉じ引用符の次の位置)。

    Raises:
        ParseError: 引用符が閉じていない場合。
    """
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
            hex_digits = {"x": 2, "u": 4, "U": 8}.get(nxt)
            m = re.match(rf"[0-9A-Fa-f]{{1,{hex_digits}}}", s[i + 2 :]) if hex_digits else None
            if m:
                out.append(chr(int(m.group(0), 16)))
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
    """コマンド文字列を単純コマンドの列に分割する。

    ``$(…)``・バッククォート・``${…}``・プロセス置換・PowerShell の引数中の ``(…)`` の
    内側は、独立したコマンド文字列として ``nested`` に集める（呼び出し側が再帰的に検査する）。
    リダイレクト（``>file``・``2>&1`` 等）の対象はコマンドの引数から除く。
    """

    def __init__(self, s: str, dialect: Dialect) -> None:
        """字句解析の状態を初期化する。

        Args:
            s: コマンド文字列。
            dialect: 字句規則。
        """
        self.s = s
        self.d = dialect
        self.commands: list[SimpleCommand] = []
        self.nested: list[tuple[str, Dialect]] = []
        self._cur = SimpleCommand()
        self._cur_start = 0
        self._chars: list[str] = []
        self._in_word = False
        self._quoted = False
        self._expansion = False
        # 次に確定する語の扱い（"redirect": 捨てる、"herestring": 標準入力に回す）
        self._next_word_role = ""
        self._pending_heredocs: list[tuple[str, bool, bool, SimpleCommand]] = []
        # PowerShell の呼び出し演算子（&）の直後か
        self._after_call_operator = False

    # --- 語・コマンドの組み立て ---
    def _add(self, text: str, quoted: bool = False) -> None:
        """組み立て中の語に文字列を加える。

        Args:
            text: 加える文字列。
            quoted: 引用符・エスケープで囲まれた部分か。
        """
        self._chars.append(text)
        self._in_word = True
        self._quoted = self._quoted or quoted

    def _add_expansion(self, raw: str) -> None:
        """展開部分を元の表記のまま語に加え、展開ありと記録する。

        Args:
            raw: 展開部分の元の表記。
        """
        self._add(raw)
        self._expansion = True

    def _flush(self) -> None:
        """組み立て中の語を確定し、役割に応じてコマンドへ加える。"""
        if not self._in_word:
            return
        word = Word("".join(self._chars), self._quoted, self._expansion)
        if self._next_word_role == "herestring":
            self._cur.stdin_texts.append(word.text)
        elif self._next_word_role != "redirect":
            self._cur.words.append(word)
        self._next_word_role = ""
        self._chars = []
        self._in_word = False
        self._quoted = False
        self._expansion = False

    def _end_command(self, end: int, piped: bool = False) -> None:
        """組み立て中の単純コマンドを確定し、次のコマンドを始める。

        Args:
            end: このコマンドの終わり（区切りの位置）。
            piped: 区切りがパイプ（|）か。
        """
        self._flush()
        self._next_word_role = ""
        cur = self._cur
        # 2 文字の区切り（&& || |&）の 2 文字目が先頭に残るため除く
        cur.raw = self.s[self._cur_start : end].strip().lstrip("&|").strip()
        if cur.words or cur.stdin_texts:
            self.commands.append(cur)
        self._cur = SimpleCommand(piped_from=cur if piped else None)
        self._after_call_operator = False
        self._cur_start = end + 1

    def _at_command_start(self) -> bool:
        """まだ語が 1 つもない（コマンドの先頭にいる）か。"""
        return not self._cur.words and not self._in_word

    # --- 展開 ---
    def _dollar(self, i: int) -> int:
        """``$`` で始まる展開を処理する。

        Args:
            i: ``$`` の位置。

        Returns:
            次に読む位置。
        """
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

    def _paren_expansion(self, start: int, open_at: int) -> int:
        """``(`` で始まる部分式を入れ子として集め、展開として語に加える。

        Args:
            start: 部分式の表記の先頭（``@(`` や ``<(`` の 1 文字目）。
            open_at: ``(`` の位置。

        Returns:
            次に読む位置。
        """
        end = _find_closing_paren(self.s, open_at + 1, self.d)
        self.nested.append((self.s[open_at + 1 : end], self.d))
        self._add_expansion(self.s[start : end + 1])
        return end + 1

    def _backtick(self, i: int) -> int:
        """bash のバッククォートによるコマンド置換を処理する。

        Args:
            i: 開きバッククォートの位置。

        Returns:
            次に読む位置。

        Raises:
            ParseError: バッククォートが閉じていない場合。
        """
        j = i + 1
        while j < len(self.s) and self.s[j] != "`":
            j += 2 if self.s[j] == "\\" else 1
        if j >= len(self.s):
            raise ParseError("バッククォートが閉じていない")
        self.nested.append((self.s[i + 1 : j], self.d))
        self._add_expansion(self.s[i : j + 1])
        return j + 1

    def _percent(self, i: int) -> int:
        """cmd の ``%VAR%`` を展開として扱う。

        Args:
            i: ``%`` の位置。

        Returns:
            次に読む位置。
        """
        m = re.match(r"%[^%\s]+%", self.s[i:])
        if m:
            self._add_expansion(m.group(0))
            return i + len(m.group(0))
        self._add("%")
        return i + 1

    # --- 引用符 ---
    def _single_quote(self, i: int) -> int:
        """単一引用符の文字列を処理する（PowerShell の ``''`` は 1 文字の ``'``）。

        Args:
            i: 開き引用符の位置。

        Returns:
            次に読む位置。

        Raises:
            ParseError: 引用符が閉じていない場合。
        """
        s = self.s
        out = []
        j = i + 1
        while True:
            k = s.find("'", j)
            if k == -1:
                raise ParseError("引用符が閉じていない")
            out.append(s[j:k])
            if self.d is POWERSHELL and s[k + 1 : k + 2] == "'":
                out.append("'")
                j = k + 2
                continue
            self._add("".join(out), quoted=True)
            return k + 1

    def _double_quote(self, i: int) -> int:
        """二重引用符の文字列を処理する（中の変数展開・コマンド置換も扱う）。

        Args:
            i: 開き引用符の位置。

        Returns:
            次に読む位置。

        Raises:
            ParseError: 引用符が閉じていない場合。
        """
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
            elif c == "`" and d.backtick_subst:
                j = self._backtick(j)
            elif c == "%" and d.percent_vars:
                j = self._percent(j)
            else:
                self._add(c)
                j += 1
        raise ParseError("引用符が閉じていない")

    def _expandable_body(self, body: str) -> None:
        """展開される本文（ヒアドキュメント等）からコマンド置換を集める。

        Args:
            body: 本文。
        """
        escaped = body.replace(self.d.escape, self.d.escape * 2).replace('"', self.d.escape + '"')
        inner = _Tokenizer('"' + escaped + '"', self.d)
        inner.run()
        self.nested.extend(inner.nested)

    def _here_string(self, i: int) -> int:
        """PowerShell のヒア文字列 ``@'…'@`` / ``@"…"@`` を処理する。

        Args:
            i: ``@`` の位置。

        Returns:
            次に読む位置。

        Raises:
            ParseError: ヒア文字列が閉じていない場合。
        """
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
        """改行位置で、保留中のヒアドキュメント本文を読み、書いたコマンドへ渡す。

        Args:
            newline: ヒアドキュメント開始行の末尾の改行位置。

        Returns:
            最後の終端語の行の末尾の位置。
        """
        pos = newline
        for delim, literal, strip_tabs, command in self._pending_heredocs:
            body, pos = _read_heredoc_body(self.s, pos, delim, strip_tabs)
            if not literal:
                self._expandable_body(body)
            command.stdin_texts.append(body)
        self._pending_heredocs = []
        return pos

    # --- リダイレクト・コメント ---
    def _redirect(self, i: int) -> int:
        """``<`` ``>`` で始まるリダイレクト・ヒアドキュメント・プロセス置換を処理する。

        Args:
            i: ``<`` または ``>`` の位置。

        Returns:
            次に読む位置。
        """
        s = self.s
        if self.d is BASH and s[i + 1 : i + 2] == "(":
            return self._paren_expansion(i, i + 1)
        # 直前の数字（2>&1 の 2）・PowerShell の * はファイル記述子の指定
        if self._in_word and not self._quoted and re.fullmatch(r"\d+|\*", "".join(self._chars)):
            self._chars, self._in_word, self._expansion = [], False, False
        self._flush()
        if self.d is BASH:
            m = _match_heredoc(s, i)
            if m:
                delim, literal, strip_tabs = _heredoc_spec(m)
                self._pending_heredocs.append((delim, literal, strip_tabs, self._cur))
                return m.end()
            if s.startswith("<<<", i):
                self._next_word_role = "herestring"
                return i + 3
        m = re.match(r"[<>]+&?\|?-?", s[i:])
        self._next_word_role = "redirect"
        return i + len(m.group(0))

    def _skip_comment(self, i: int) -> int:
        """コメントを読み飛ばす（改行は残す）。

        Args:
            i: ``#`` または PowerShell の ``<#`` の位置。

        Returns:
            次に読む位置。
        """
        if self.s.startswith("<#", i):
            end = self.s.find("#>", i + 2)
            return len(self.s) if end == -1 else end + 2
        end = self.s.find("\n", i)
        return len(self.s) if end == -1 else end

    # --- 本体 ---
    def _ampersand(self, i: int) -> int:
        """``&`` を処理する（``&&``・バックグラウンド・``&>``・PowerShell の呼び出し演算子）。

        Args:
            i: ``&`` の位置。

        Returns:
            次に読む位置。
        """
        s = self.s
        if s[i + 1 : i + 2] == "&":
            self._end_command(i)
            return i + 2
        if self.d is BASH and s[i + 1 : i + 2] == ">":
            self._flush()
            m = re.match(r"&>>?", s[i:])
            self._next_word_role = "redirect"
            return i + len(m.group(0))
        if self.d is POWERSHELL and self._at_command_start():
            # 呼び出し演算子（& git …）は実行するコマンドを変えない
            self._cur_start = i + 1
            self._after_call_operator = True
            return i + 1
        self._end_command(i)
        return i + 1

    def _pipe(self, i: int) -> int:
        """``|`` を処理する（``||`` はパイプではない区切り）。

        Args:
            i: ``|`` の位置。

        Returns:
            次に読む位置。
        """
        nxt = self.s[i + 1 : i + 2]
        if nxt == "|":
            self._end_command(i)
            return i + 2
        self._end_command(i, piped=True)
        return i + (2 if nxt == "&" and self.d is BASH else 1)

    def _open_paren(self, i: int) -> int:
        """``(`` を処理する。

        PowerShell の引数位置の ``(…)`` は部分式（入れ子）として扱い、それ以外は区切りとする。

        Args:
            i: ``(`` の位置。

        Returns:
            次に読む位置。
        """
        if self.d is POWERSHELL and (self._after_call_operator or not self._at_command_start()):
            # & (Get-Command git) … の ( ) は実行するコマンドを決める式
            return self._paren_expansion(i, i)
        self._end_command(i)
        return i + 1

    def _brace(self, i: int) -> int:
        """``{`` ``}`` を処理する。

        PowerShell のスクリプトブロックは常に、bash の ``{ …; }`` は単独の語のときだけ区切りとする。

        Args:
            i: 波括弧の位置。

        Returns:
            次に読む位置。
        """
        c = self.s[i]
        boundary = i + 1 >= len(self.s) or self.s[i + 1] in _WHITESPACE + "\n;&|()"
        if self.d is POWERSHELL or (self.d is BASH and not self._in_word and boundary):
            self._end_command(i)
        else:
            # 語中の { はブレース展開になりうる
            self._add(c)
            self._expansion = self._expansion or (c == "{" and self.d is BASH)
        return i + 1

    def _special(self, i: int) -> int | None:
        """引用符・展開・区切りなど、特別な意味を持つ文字を処理する。

        Args:
            i: 文字の位置。

        Returns:
            次に読む位置。通常の文字の場合は None。
        """
        s = self.s
        d = self.d
        c = s[i]
        nxt = s[i + 1 : i + 2]
        if c == "'" and d.single_quote:
            return self._single_quote(i)
        if c == '"':
            return self._double_quote(i)
        if c == "$" and d.dollar:
            return self._dollar(i)
        if c == "`" and d.backtick_subst:
            return self._backtick(i)
        if c == "%" and d.percent_vars:
            return self._percent(i)
        if (
            d.comments
            and not self._in_word
            and (c == "#" or (d is POWERSHELL and s.startswith("<#", i)))
        ):
            return self._skip_comment(i)
        if d is POWERSHELL and c == "@":
            if re.match(r"@['\"][ \t]*\r?\n", s[i:]):
                return self._here_string(i)
            if nxt == "(":
                return self._paren_expansion(i, i + 1)
            if _NAME_CHARS.match(nxt or " "):
                # スプラッティング（@args）
                j = i + 1
                while j < len(s) and _NAME_CHARS.match(s[j]):
                    j += 1
                self._add_expansion(s[i:j])
                return j
        if c in "<>":
            return self._redirect(i)
        if c == "&":
            return self._ampersand(i)
        if c == "|":
            return self._pipe(i)
        if c == ";":
            self._end_command(i)
            return i + 1
        if c == "(":
            return self._open_paren(i)
        if c == ")":
            self._end_command(i)
            return i + 1
        if c in "{}" and d is not CMD:
            return self._brace(i)
        return None

    def run(self) -> None:
        """コマンド文字列全体を字句解析する。"""
        s = self.s
        d = self.d
        i = 0
        n = len(s)
        while i < n:
            c = s[i]
            if c in _WHITESPACE:
                self._flush()
                i += 1
            elif c == "\n":
                self._end_command(i)
                if self._pending_heredocs:
                    i = self._heredoc_bodies(i)
                    self._cur_start = i + 1
                i += 1
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
            else:
                nxt = self._special(i)
                if nxt is None:
                    self._add(c)
                    if d is BASH and c in "*?":
                        # グロブは実行時のファイル名に依存する
                        self._expansion = True
                    i += 1
                else:
                    i = nxt
        self._end_command(n)
        if self._pending_heredocs:
            self._heredoc_bodies(n)


def tokenize(
    command: str, dialect: Dialect
) -> tuple[list[SimpleCommand], list[tuple[str, Dialect]]]:
    """コマンド文字列を単純コマンドの列と、入れ子のコマンド文字列に分ける。

    Args:
        command: コマンド文字列。
        dialect: 字句規則。

    Returns:
        (単純コマンドの列, 入れ子のコマンド文字列と字句規則の組の列)。
    """
    tok = _Tokenizer(command, dialect)
    tok.run()
    return tok.commands, tok.nested


# --- コマンド名の正規化と分類 ------------------------------------------------

_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".com")
_SCRIPT_SUFFIXES = (".sh", ".bash", ".ps1", ".py", ".bat", ".cmd")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
_PS_ASSIGNMENT_OPERATOR = re.compile(r"^(?:[-+*/%]|\?\?)?=$")

# 先頭にあっても実行対象を変えない語（シェルの予約語）
_BASH_KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}"}
# 後続の引数のどこかで別のコマンドを実行しうる語（後続の各位置を検査する）
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
    "parallel",
    "timeout",
    "nice",
    "ionice",
    "setsid",
    "stdbuf",
    "watch",
    "find",
    "wsl",
    "start",
    "call",
    "coproc",
    "conda",
    "mamba",
    "micromamba",
    "uv",
    "uvx",
    "npx",
    "pnpm",
    "yarn",
    "bunx",
    "poetry",
    "pipx",
    "pdm",
    "hatch",
}
# 標準入力から引数を受け取るラッパー
_STDIN_ARG_WRAPPERS = {"xargs", "parallel"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ash", "busybox"}
_POWERSHELLS = {"powershell", "pwsh", "powershell_ise"}
_INTERPRETERS = re.compile(
    r"^(python[0-9.]*|pythonw|py|node|nodejs|perl|ruby|php|deno|bun|rscript|lua|osascript)$"
)
# 変数に値を設定するコマンド（値に危険語を仕込める）
_ASSIGNING_COMMANDS = {
    "export",
    "declare",
    "typeset",
    "local",
    "readonly",
    "set",
    "for",
    "foreach",
    "read",
    "mapfile",
    "readarray",
    "set-variable",
    "sv",
    "new-variable",
    "nv",
}
# 標準入力から値を読む代入コマンド
_STDIN_ASSIGNING_COMMANDS = {"read", "mapfile", "readarray"}
# PowerShell でパイプラインの値を受け取る自動変数
_PS_PIPELINE_VARS = re.compile(r"\$(?:_|PSItem|input)\b", re.IGNORECASE)


def normalize_name(text: str) -> str:
    """実行ファイル名を、パス・拡張子を除いた小文字の名前にする。

    Args:
        text: コマンド名の語（例: ``C:\\Program Files\\Git\\cmd\\git.exe``）。

    Returns:
        正規化した名前（例: ``git``）。
    """
    name = text.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in _EXECUTABLE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _short_letters(arg: str, value_letters: str) -> tuple[str, bool]:
    """結合された短縮オプション（``-fdx``）を文字に分ける。

    Args:
        arg: ``-`` で始まる 1 語。
        value_letters: 値を取るオプション文字（それ以降は値として扱う）。

    Returns:
        (値を取る文字より前のオプション文字, 値を次の語で受け取るか)。
    """
    letters = []
    for k, ch in enumerate(arg[1:], start=1):
        if ch in value_letters:
            return "".join(letters), k == len(arg) - 1
        letters.append(ch)
    return "".join(letters), False


def _long_name(arg: str) -> str:
    """``--name=value`` から ``name`` を取り出す。

    Args:
        arg: ``--`` で始まる 1 語。

    Returns:
        オプション名。
    """
    return arg[2:].split("=", 1)[0]


def _abbrev_of(name: str, *targets: str) -> bool:
    """長いオプションの省略形（前方一致）として ``targets`` のいずれかに当たるか。

    Args:
        name: 先頭の ``-`` を除いたオプション名。
        *targets: 正式なオプション名。

    Returns:
        いずれかの省略形であれば True。
    """
    return bool(name) and any(t.startswith(name) for t in targets)


def _command_start(words: list[Word], dialect: Dialect) -> int:
    """代入・予約語などの前置きを除いた、実行するコマンド名の位置を返す。

    Args:
        words: 単純コマンドの語。
        dialect: 字句規則。

    Returns:
        コマンド名の語の位置（前置きだけの場合は ``len(words)``）。
    """
    i = 0
    while i < len(words):
        w = words[i]
        if dialect is not POWERSHELL and _ASSIGNMENT.match(w.text):
            i += 1
        elif dialect is BASH and not w.quoted and w.text in _BASH_KEYWORDS:
            i += 1
        elif dialect is POWERSHELL and w.text == "." and not w.quoted:
            i += 1
        elif (
            dialect is POWERSHELL
            and w.has_expansion
            and i + 1 < len(words)
            and _PS_ASSIGNMENT_OPERATOR.match(words[i + 1].text)
        ):
            # 代入文（$x = …）は右辺をコマンドとして検査する
            i += 2
        else:
            break
    return i


# --- 静的に判定できない形の記録 ----------------------------------------------


def _mark_dynamic(
    state: ScanState,
    command: SimpleCommand,
    dialect: Dialect,
    *,
    head: bool = False,
    stdin: bool = False,
) -> None:
    """静的に判定できない単純コマンドを、安全側の判定対象として記録する。

    Args:
        state: 検査全体の状態。
        command: 判定できなかった単純コマンド。
        dialect: 字句規則。
        head: 実行するコマンド名そのものが変数で決まる場合は True。
        stdin: 標準入力の内容がコマンドの動作を決める場合は True（パイプの接続元も対象にする）。
    """
    state.dynamic = True
    state.dynamic_head = state.dynamic_head or head
    state.coarse_texts.append(command.raw)
    state.coarse_texts.extend(command.stdin_texts)
    if dialect is POWERSHELL and _PS_PIPELINE_VARS.search(command.raw):
        # パイプラインの値（$_ 等）はどこから来るか追えないため全体を対象にする
        state.coarse_texts.append(state.top_text)
    source = command.piped_from if stdin else None
    while source is not None:
        state.coarse_texts.append(source.raw)
        state.coarse_texts.extend(source.stdin_texts)
        source = source.piped_from


def _record_assignment(command: SimpleCommand, dialect: Dialect, state: ScanState) -> None:
    """代入を含む単純コマンドを、安全側の判定対象として記録する。

    ``FLAG=--force; git push $FLAG`` のように、判定できないコマンドの値の出どころになるため。

    Args:
        command: 単純コマンド。
        dialect: 字句規則。
        state: 検査全体の状態。
    """
    words = command.words
    start = _command_start(words, dialect)
    name = normalize_name(words[start].text) if start < len(words) else ""
    has_assignment = start > 0 and any(
        _ASSIGNMENT.match(w.text) or _PS_ASSIGNMENT_OPERATOR.match(w.text) for w in words[:start]
    )
    if dialect is POWERSHELL and words and re.match(r"^\$[\w:]+\s*[-+*/]?=", command.raw):
        has_assignment = True
    if has_assignment or name in _ASSIGNING_COMMANDS:
        state.coarse_texts.append(command.raw)
        state.coarse_texts.extend(command.stdin_texts)
    if name in _STDIN_ASSIGNING_COMMANDS:
        _mark_dynamic(state, command, dialect, stdin=True)


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
# 値を別の語で受け取る git push のオプション
_PUSH_VALUE_OPTIONS = {"--repo", "--receive-pack", "--exec", "--push-option"}


def _check_push(args: list[Word]) -> str | None:
    """git push の引数から force・リモート削除を検出する。

    Args:
        args: ``push`` より後ろの語。

    Returns:
        拒否理由。該当しなければ None。
    """
    options_ended = False
    skip_next = False
    for w in args:
        t = w.text
        if skip_next:
            skip_next = False
            continue
        if not options_ended and t == "--":
            options_ended = True
            continue
        if not options_ended and t.startswith("--"):
            name = _long_name(t)
            if _abbrev_of(name, "force", "force-with-lease"):
                return f"git push の強制 push（{t}）"
            if _abbrev_of(name, "delete", "mirror", "prune"):
                return f"git push によるリモート ref の削除（{t}）"
            skip_next = t in _PUSH_VALUE_OPTIONS
            continue
        if not options_ended and t.startswith("-") and len(t) > 1:
            letters, skip_next = _short_letters(t, value_letters="o")
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
    """git reset --hard を検出する。

    Args:
        args: ``reset`` より後ろの語。

    Returns:
        拒否理由。該当しなければ None。
    """
    for w in args:
        t = w.text
        if t == "--":
            break
        if t.startswith("--") and _abbrev_of(_long_name(t), "hard"):
            return f"git reset --hard（{t}）"
    return None


def _check_clean(args: list[Word]) -> str | None:
    """git clean の実削除を検出する（-n / --dry-run を含む場合は許可）。

    Args:
        args: ``clean`` より後ろの語。

    Returns:
        拒否理由。該当しなければ None。
    """
    dangerous = None
    skip_next = False
    for w in args:
        t = w.text
        if skip_next:
            skip_next = False
            continue
        if t == "--":
            break
        if t.startswith("--"):
            name = _long_name(t)
            if _abbrev_of(name, "dry-run"):
                return None
            if _abbrev_of(name, "force"):
                dangerous = dangerous or t
            # --exclude <pattern> の値は次の語
            skip_next = "=" not in t and _abbrev_of(name, "exclude")
        elif t.startswith("-") and len(t) > 1:
            letters, skip_next = _short_letters(t, value_letters="e")
            if "n" in letters:
                return None
            if set(letters) & set("fxXd"):
                dangerous = dangerous or t
    return f"git clean によるファイル削除（{dangerous}）" if dangerous else None


_GIT_SUBCOMMAND_CHECKS = {"push": _check_push, "reset": _check_reset, "clean": _check_clean}


def _check_git(
    command: SimpleCommand, args: list[Word], dialect: Dialect, state: ScanState
) -> str | None:
    """git の呼び出しを検査する。

    Args:
        command: 単純コマンド。
        args: ``git`` より後ろの語。
        dialect: 字句規則。
        state: 検査全体の状態。

    Returns:
        拒否理由。該当しなければ None。
    """
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
        _mark_dynamic(state, command, dialect)
    return check(args[i + 1 :]) if check else None


def _check_gh(
    command: SimpleCommand, args: list[Word], dialect: Dialect, state: ScanState
) -> str | None:
    """gh の呼び出しを検査する（-R/--repo の位置を問わない）。

    Args:
        command: 単純コマンド。
        args: ``gh`` より後ろの語。
        dialect: 字句規則。
        state: 検査全体の状態。

    Returns:
        拒否理由。該当しなければ None。
    """
    positional: list[Word] = []
    skip_next = False
    for w in args:
        t = w.text
        if skip_next:
            skip_next = False
        elif t in ("-R", "--repo"):
            skip_next = True
        elif not t.startswith("-"):
            positional.append(w)
    # サブコマンドが変数で決まる場合は静的に判定できない（--body "$(…)" 等の値は対象外）
    if any(w.has_expansion for w in positional[:2]):
        _mark_dynamic(state, command, dialect)
    subcommand = [w.text for w in positional[:2]]
    if subcommand == ["pr", "merge"]:
        return "gh pr merge（マージはユーザーの専権）"
    if subcommand == ["repo", "delete"]:
        return "gh repo delete"
    return None


# --- 入れ子のコマンド文字列 --------------------------------------------------


def _join(words: list[Word]) -> str:
    """語を空白で連結してコマンド文字列に戻す。

    Args:
        words: 語の列。

    Returns:
        連結した文字列。
    """
    return " ".join(w.text for w in words)


def _ps_param(text: str) -> tuple[str, str | None]:
    """PowerShell のパラメータ語を名前と値に分ける（``-Name:value`` 形式に対応）。

    Args:
        text: ``-`` または ``/`` で始まる 1 語。

    Returns:
        (小文字のパラメータ名, ``:`` の後ろの値。なければ None)。
    """
    body = text.lstrip("-/")
    if ":" in body:
        name, value = body.split(":", 1)
        return name.lower(), value
    return body.lower(), None


def _check_shell(
    command: SimpleCommand, args: list[Word], dialect: Dialect, state: ScanState, depth: int
) -> str | None:
    """``bash -c "…"`` の文字列、または標準入力で渡したスクリプトを検査する。

    Args:
        command: 単純コマンド。
        args: シェル名より後ろの語。
        dialect: 呼び出し元の字句規則。
        state: 検査全体の状態。
        depth: 入れ子の深さ。

    Returns:
        拒否理由。該当しなければ None。
    """
    for k, w in enumerate(args):
        t = w.text
        if t.startswith("-") and not t.startswith("--") and "c" in t[1:]:
            rest = [a for a in args[k + 1 :] if not a.text.startswith("-")]
            if not rest:
                return None
            if rest[0].has_expansion:
                _mark_dynamic(state, command, dialect)
            return _scan(rest[0].text, BASH, state, depth + 1)
    if command.stdin_texts:
        return _scan("\n".join(command.stdin_texts), BASH, state, depth + 1)
    # スクリプトファイル・パイプから読む場合は内容を静的に判定できない
    reads_stdin = not any(not a.text.startswith("-") for a in args)
    _mark_dynamic(state, command, dialect, stdin=reads_stdin)
    return None


# 値を別の語で受け取る powershell.exe / pwsh のパラメータ（正式名。省略形は前方一致で判定）
_POWERSHELL_VALUE_PARAMS = (
    "executionpolicy",
    "windowstyle",
    "configurationname",
    "configurationfile",
    "workingdirectory",
    "settingsfile",
    "outputformat",
    "inputformat",
    "version",
    "psconsolefile",
    "custompipename",
)
_POWERSHELL_VALUE_ALIASES = {"ep", "ex", "wd", "of", "if", "w", "v"}


def _check_powershell(
    command: SimpleCommand, args: list[Word], dialect: Dialect, state: ScanState, depth: int
) -> str | None:
    """``powershell -Command "…"`` / ``-EncodedCommand`` の文字列を検査する。

    Args:
        command: 単純コマンド。
        args: ``powershell`` より後ろの語。
        dialect: 呼び出し元の字句規則。
        state: 検査全体の状態。
        depth: 入れ子の深さ。

    Returns:
        拒否理由。該当しなければ None。
    """
    if command.stdin_texts:
        reason = _scan("\n".join(command.stdin_texts), POWERSHELL, state, depth + 1)
        if reason:
            return reason
    k = 0
    while k < len(args):
        t = args[k].text
        if not (t.startswith(("-", "/")) and len(t) > 1):
            # 位置引数以降はコマンドとして解釈される（powershell.exe の既定）。
            # パラメータの読み違いに備えて安全側の判定対象にもする
            _mark_dynamic(state, command, dialect)
            return _scan(_join(args[k:]), POWERSHELL, state, depth + 1)
        name, inline = _ps_param(t)
        if name in ("e", "ec") or (len(name) >= 3 and "encodedcommand".startswith(name)):
            encoded = (
                inline if inline is not None else (args[k + 1].text if k + 1 < len(args) else "")
            )
            try:
                decoded = base64.b64decode(encoded, validate=True).decode("utf-16-le")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                _mark_dynamic(state, command, dialect)
                return None
            state.coarse_texts.append(decoded)
            return _scan(decoded, POWERSHELL, state, depth + 1)
        if "command".startswith(name):
            rest = ([inline] if inline is not None else []) + [a.text for a in args[k + 1 :]]
            body = " ".join(rest)
            if body.strip() in ("", "-") or any(a.has_expansion for a in args[k + 1 :]):
                _mark_dynamic(state, command, dialect, stdin=body.strip() in ("", "-"))
            return _scan(body, POWERSHELL, state, depth + 1)
        if _abbrev_of(name, "file"):
            _mark_dynamic(state, command, dialect)
            return None
        takes_value = name in _POWERSHELL_VALUE_ALIASES or _abbrev_of(
            name, *_POWERSHELL_VALUE_PARAMS
        )
        k += 2 if takes_value and inline is None else 1
    # 引数なしは標準入力から読む
    _mark_dynamic(state, command, dialect, stdin=True)
    return None


def _check_cmd(
    command: SimpleCommand, args: list[Word], dialect: Dialect, state: ScanState, depth: int
) -> str | None:
    """``cmd /c "…"`` の文字列を検査する。

    Args:
        command: 単純コマンド。
        args: ``cmd`` より後ろの語。
        dialect: 呼び出し元の字句規則。
        state: 検査全体の状態。
        depth: 入れ子の深さ。

    Returns:
        拒否理由。該当しなければ None。
    """
    for k, w in enumerate(args):
        if w.text.lower().startswith(("/c", "/k")):
            head = w.text[2:]
            body = " ".join(([head] if head else []) + [a.text for a in args[k + 1 :]])
            return _scan(body, CMD, state, depth + 1)
    _mark_dynamic(state, command, dialect, stdin=True)
    return None


def _check_invoke_expression(
    command: SimpleCommand, args: list[Word], dialect: Dialect, state: ScanState, depth: int
) -> str | None:
    """``Invoke-Expression "…"`` の文字列を検査する。

    Args:
        command: 単純コマンド。
        args: ``Invoke-Expression`` より後ろの語。
        dialect: 呼び出し元の字句規則。
        state: 検査全体の状態。
        depth: 入れ子の深さ。

    Returns:
        拒否理由。該当しなければ None。
    """
    parts = []
    for w in args:
        if w.text.startswith("-"):
            name, inline = _ps_param(w.text)
            if "command".startswith(name):
                # -Command パラメータ名そのものは除く（-Command:'…' は値を残す）
                if inline:
                    parts.append(inline)
                continue
        parts.append(w.text)
    if any(w.has_expansion for w in args):
        _mark_dynamic(state, command, dialect)
    return _scan(" ".join(parts), POWERSHELL, state, depth + 1)


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


def _take_ps_array(args: list[Word], k: int) -> tuple[list[str], int]:
    """PowerShell のカンマ区切りの配列（``'push', '--force'``）を 1 つの値として読む。

    Args:
        args: 語の列。
        k: 配列の先頭の語の位置。

    Returns:
        (配列の要素, 次に読む位置)。
    """
    items: list[str] = []
    while k < len(args):
        text = args[k].text
        items.extend(p for p in text.split(",") if p)
        k += 1
        continues = text.endswith(",") or (k < len(args) and args[k].text.startswith(","))
        if not continues:
            break
    return items, k


def _check_start_process(
    command: SimpleCommand, args: list[Word], dialect: Dialect, state: ScanState, depth: int
) -> str | None:
    """``Start-Process git -ArgumentList …`` を実行ファイル＋引数として検査する。

    Args:
        command: 単純コマンド。
        args: ``Start-Process`` より後ろの語。
        dialect: 呼び出し元の字句規則。
        state: 検査全体の状態。
        depth: 入れ子の深さ。

    Returns:
        拒否理由。該当しなければ None。
    """
    if any(w.has_expansion for w in args):
        _mark_dynamic(state, command, dialect)
    file_path = None
    arg_list: list[str] = []
    positional: list[list[str]] = []
    k = 0
    while k < len(args):
        t = args[k].text
        if not t.startswith("-"):
            items, k = _take_ps_array(args, k)
            positional.append(items)
            continue
        name, inline = _ps_param(t)
        if _abbrev_of(name, "filepath"):
            file_path = (
                inline if inline is not None else (args[k + 1].text if k + 1 < len(args) else None)
            )
            k += 1 if inline is not None else 2
        elif _abbrev_of(name, "argumentlist") or name == "args":
            items, k = _take_ps_array(args, k + 1)
            arg_list.extend(([inline] if inline else []) + items)
        else:
            k += 2 if _abbrev_of(name, *_START_PROCESS_VALUE_OPTIONS) and inline is None else 1
    if file_path is None and positional:
        file_path = positional.pop(0)[0]
    if not arg_list and positional:
        arg_list = positional[0]
    if file_path is None:
        return None
    quoted_path = f'"{file_path}"' if re.search(r"\s", file_path) else file_path
    return _scan(quoted_path + " " + " ".join(arg_list), POWERSHELL, state, depth + 1)


# --- 単純コマンドの検査 ------------------------------------------------------


def _reads_code_from_stdin(args: list[Word]) -> bool:
    """インタプリタがコードを標準入力から読む呼び出しか（引数なし、または ``-``）。

    Args:
        args: インタプリタ名より後ろの語。

    Returns:
        標準入力からコードを読む場合は True。
    """
    positional = [a.text for a in args if a.text == "-" or not a.text.startswith("-")]
    return not positional or positional[0] == "-"


def _check_words(
    command: SimpleCommand, words: list[Word], dialect: Dialect, state: ScanState, depth: int
) -> str | None:
    """単純コマンド（またはラッパーの後ろの部分）を検査する。

    Args:
        command: 単純コマンド（安全側の判定に使う元の文字列などを持つ）。
        words: 検査する語の列。
        dialect: 字句規則。
        state: 検査全体の状態。
        depth: 入れ子の深さ。

    Returns:
        拒否理由。該当しなければ None。
    """
    start = _command_start(words, dialect)
    if start >= len(words):
        return None
    head = words[start]
    args = words[start + 1 :]
    if head.has_expansion:
        # 実行するコマンド自体が変数で決まる
        _mark_dynamic(state, command, dialect, head=True)
        return None
    name = normalize_name(head.text)

    if name == "git":
        return _check_git(command, args, dialect, state)
    if name == "gh":
        return _check_gh(command, args, dialect, state)
    nested_checks = {
        **dict.fromkeys(_SHELLS, _check_shell),
        **dict.fromkeys(_POWERSHELLS, _check_powershell),
        "cmd": _check_cmd,
        "invoke-expression": _check_invoke_expression,
        "iex": _check_invoke_expression,
        "start-process": _check_start_process,
        "saps": _check_start_process,
    }
    if name == "start" and dialect is POWERSHELL:
        name = "start-process"
    if name in nested_checks:
        return nested_checks[name](command, args, dialect, state, depth)
    if name == "eval":
        if any(w.has_expansion for w in args):
            _mark_dynamic(state, command, dialect)
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
    if _INTERPRETERS.match(name):
        # インタプリタのコードは静的に判定できない
        _mark_dynamic(state, command, dialect, stdin=_reads_code_from_stdin(args))
        return None
    if name in ("source", ".") or head.text.lower().endswith(_SCRIPT_SUFFIXES):
        # スクリプトファイルの内容は静的に判定できない
        _mark_dynamic(state, command, dialect)
        return None
    if name in _WRAPPERS:
        if name in _STDIN_ARG_WRAPPERS:
            _mark_dynamic(state, command, dialect, stdin=True)
        # 後ろの各位置をコマンド名として検査する。ラッパー名の位置は、そのラッパー自身が
        # 後ろを検査する代わりに外側で扱い、入れ子のラッパーで計算量が増えないようにする
        for k in range(len(args)):
            if normalize_name(args[k].text) in _WRAPPERS and not args[k].has_expansion:
                if normalize_name(args[k].text) in _STDIN_ARG_WRAPPERS:
                    _mark_dynamic(state, command, dialect, stdin=True)
                continue
            reason = _check_words(command, args[k:], dialect, state, depth + 1)
            if reason:
                return reason
    return None


def _scan(command: str, dialect: Dialect, state: ScanState, depth: int) -> str | None:
    """コマンド文字列を（入れ子も含めて）検査する。

    Args:
        command: コマンド文字列。
        dialect: 字句規則。
        state: 検査全体の状態。
        depth: 入れ子の深さ。

    Returns:
        拒否理由。該当しなければ None。
    """
    if depth > MAX_DEPTH:
        state.dynamic = True
        state.coarse_texts.append(command)
        return None
    commands, nested = tokenize(command, dialect)
    for inner, inner_dialect in nested:
        reason = _scan(inner, inner_dialect, state, depth + 1)
        if reason:
            return reason
    for simple in commands:
        _record_assignment(simple, dialect, state)
        reason = _check_words(simple, simple.words, dialect, state, depth)
        if reason:
            return reason
    return None


# --- 静的に判定できない形の安全側判定 ----------------------------------------

_TOOL_WORD = re.compile(r"\b(git|gh)\b", re.IGNORECASE)
_WORD_START = r"(?:^|(?<=[\s'\"=]))"
_WORD_END = r"(?=$|[\s'\";&|)])"
# オプションの位置に変数を置く形（-$F・--$MODE 等）
_OPTION_VARIABLE = rf"{_WORD_START}-+['\"]?\$"
_COARSE_RULES = (
    (
        re.compile(r"\bpush\b"),
        re.compile(
            r"force(?!-if-includes)|delete|mirror|prune"
            + rf"|{_WORD_START}-[uvqn46]*[fd][uvqnfd46]*{_WORD_END}"
            + rf"|{_WORD_START}[+:][^\s:]"
            + rf"|{_OPTION_VARIABLE}"
        ),
        "git push の強制 push またはリモート削除",
    ),
    (re.compile(r"\breset\b"), re.compile(rf"hard|{_OPTION_VARIABLE}"), "git reset --hard"),
    (
        re.compile(r"\bclean\b"),
        re.compile(
            rf"force|{_WORD_START}-[dfxXinqe]*[dfxX][dfxXinqe]*{_WORD_END}|{_OPTION_VARIABLE}"
        ),
        "git clean によるファイル削除",
    ),
    (re.compile(r"\bpr\b"), re.compile(r"\bmerge\b"), "gh pr merge"),
    (re.compile(r"\brepo\b"), re.compile(r"\bdelete\b"), "gh repo delete"),
)


def coarse_danger(text: str, require_tool: bool = True) -> str | None:
    """文字列に危険語の組が含まれるかを粗く判定する。

    Args:
        text: 判定する文字列。
        require_tool: True のとき、``git`` / ``gh`` の語を含む場合に限り判定する。

    Returns:
        該当した操作名。該当しなければ None。
    """
    if require_tool and not _TOOL_WORD.search(text):
        return None
    for trigger, danger, label in _COARSE_RULES:
        if trigger.search(text) and danger.search(text):
            return label
    return None


# --- 公開関数と CLI ----------------------------------------------------------


def inspect_command(command: str, tool_name: str = "Bash") -> str | None:
    """コマンド文字列を検査する。

    Args:
        command: ツールが実行しようとするコマンド文字列。
        tool_name: Claude Code のツール名（``Bash`` / ``PowerShell``）。

    Returns:
        拒否する場合はその理由。許可する場合は None。
    """
    dialect = TOOL_DIALECTS.get(tool_name)
    if dialect is None or not command.strip():
        return None
    state = ScanState(top_text=command)
    try:
        reason = _scan(command, dialect, state, depth=0)
    except Exception:  # noqa: BLE001 - 解析できない入力・内部エラーは危険語の有無で判定する
        label = coarse_danger(command)
        return f"{label}（構文を解析できないため安全側で判定）" if label else None
    if reason:
        return reason
    if state.dynamic:
        # コマンド名自体が変数のときは git/gh の語が現れなくても危険語で判定する
        label = coarse_danger("\n".join(state.coarse_texts), require_tool=not state.dynamic_head)
        if label:
            return f"{label}（変数展開・eval 等で静的に判定できないため安全側で判定）"
    return None


def _deny_message(reason: str) -> str:
    """拒否時に標準エラーへ出す文面を作る。

    Args:
        reason: 拒否理由。

    Returns:
        標準エラーへ出す文面。
    """
    return (
        f"危険操作ガード: {reason} を検出したため実行をブロックしました。\n"
        "この操作が必要な場合は、ユーザーに依頼して手動で実行してもらってください。\n"
    )


def main() -> int:
    """標準入力の hook 入力 JSON を検査する。

    Returns:
        終了コード（許可は 0、拒否は 2）。
    """
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
