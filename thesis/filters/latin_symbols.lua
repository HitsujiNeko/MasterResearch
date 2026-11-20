--[[
修士論文の docx で、欧文の記号（「°」「−」「±」「×」）を文字スタイル付きの Span に分ける
pandoc の Lua フィルタ。

これらの記号は和文フォントでは全角幅の字形になる（「°」「±」「×」はＭＳ 明朝・
ＭＳ ゴシック・游ゴシック、「−」は游ゴシック）。本文は pandoc が日本語を含むランに
w:hint="eastAsia" を付けると記号が和文フォントで描かれ、「°C」が「° C」のように空いたり、
同じ段落の中で記号の幅が揃わなかったりする。表は欧文フォントにも游ゴシックを指定している
ため、hint の有無によらず全角になる。そこで記号だけを、和文・欧文の全スロットに欧文フォントを
指定した文字スタイル（reference.docx に定義。scripts/make_thesis_reference_docx.py）で描く。

- 明朝の文脈（本文・脚注・参考文献・表紙など）: 文字スタイル「Latin Symbol」
- ゴシックの文脈（表・見出し・図。表題・図題を含む）: 文字スタイル「Latin Symbol Sans」。
  ただし、その中の脚注の本文は明朝の文脈として扱う

コード（Code・CodeBlock）・数式・生の XML は Str でないため変えない。
scripts/build_thesis.py が pandoc-crossref と citeproc の後に適用する（crossref が付ける
図表番号・表題と、citeproc が作る参考文献リストも対象にするため）。
]]

-- 分ける文字（Unicode のコードポイント）
local LATIN_SYMBOLS = {
  [0x00B0] = true, -- ° DEGREE SIGN
  [0x2212] = true, -- − MINUS SIGN
  [0x00B1] = true, -- ± PLUS-MINUS SIGN
  [0x00D7] = true, -- × MULTIPLICATION SIGN
}
-- 文字スタイルの名前（reference.docx のスタイル名と一致させる）
local SERIF_STYLE = "Latin Symbol"
local SANS_STYLE = "Latin Symbol Sans"

--- 文字列の対象の記号を 1 文字ずつ、指定した文字スタイルの Span に分けた Inline の列を返す。
--- 対象の記号を含まない場合は nil を返す（要素を変えない）。
local function split_latin_symbols(text, style)
  local inlines = pandoc.Inlines({})
  -- 記号以外の文字をためておき、記号の前でまとめて Str にする
  local pending = {}
  local found = false
  for _, code in utf8.codes(text) do
    if LATIN_SYMBOLS[code] then
      found = true
      if #pending > 0 then
        inlines:insert(pandoc.Str(table.concat(pending)))
        pending = {}
      end
      inlines:insert(pandoc.Span(pandoc.Str(utf8.char(code)), { ["custom-style"] = style }))
    else
      pending[#pending + 1] = utf8.char(code)
    end
  end
  if not found then
    return nil
  end
  if #pending > 0 then
    inlines:insert(pandoc.Str(table.concat(pending)))
  end
  return inlines
end

--- Str の対象の記号を指定した文字スタイルに分ける関数を返す。
local function split_str_with(style)
  return function(str)
    -- 分けた後の Span の中の記号を再び分けないよう、子は走査しない
    return split_latin_symbols(str.text, style), false
  end
end

-- 明朝の文脈のフィルタ（脚注の本文にも使う）
local serif_filter = {
  traverse = "topdown",
  Str = split_str_with(SERIF_STYLE),
}

-- ゴシックの文脈のフィルタ。脚注は本文が明朝の脚注スタイルで描かれるため、明朝の文脈に戻す。
-- 親（脚注）を先に処理するため、上から下へ走査する
local sans_filter = {
  traverse = "topdown",
  Note = function(note)
    return note:walk(serif_filter), false
  end,
  Str = split_str_with(SANS_STYLE),
}

--- ゴシックの文脈の要素（表・見出し・図）は配下を Sans にし、外側の走査を止める。
local function apply_sans(element)
  return element:walk(sans_filter), false
end

return {
  {
    -- 親（表・見出し・図）を先に処理するため、上から下へ走査する
    traverse = "topdown",
    Table = apply_sans,
    Header = apply_sans,
    Figure = apply_sans,
    Str = serif_filter.Str,
  },
}
