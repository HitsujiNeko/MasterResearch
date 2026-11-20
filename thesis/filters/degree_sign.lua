--[[
修士論文の docx で「°」（U+00B0）を文字スタイル付きの Span に分ける pandoc の Lua フィルタ。

ＭＳ 明朝・ＭＳ ゴシック・游ゴシックの「°」は全角幅の字形のため、docx で「°C」が
「° C」のように空いて見える。本文は pandoc が日本語を含むランに w:hint="eastAsia" を
付けると「°」が和文フォントで描かれ、表は欧文フォントにも游ゴシックを指定しているため
hint の有無によらず全角になる。そこで「°」だけを、和文・欧文の全スロットに欧文フォントを
指定した文字スタイル（reference.docx に定義。scripts/make_thesis_reference_docx.py）で描く。

- 明朝の文脈（本文・脚注・参考文献・表紙など）: 文字スタイル「Degree Sign」
- ゴシックの文脈（表・見出し・図。表題・図題を含む）: 文字スタイル「Degree Sign Sans」。
  ただし、その中の脚注の本文は明朝の文脈として扱う

コード（Code・CodeBlock）・数式・生の XML は Str でないため変えない。
scripts/build_thesis.py が pandoc-crossref と citeproc の後に適用する（crossref が付ける
図表番号・表題と、citeproc が作る参考文献リストも対象にするため）。
]]

-- 分ける文字（U+00B0 DEGREE SIGN）
local DEGREE_SIGN = "\u{B0}"
-- 文字スタイルの名前（reference.docx のスタイル名と一致させる）
local SERIF_STYLE = "Degree Sign"
local SANS_STYLE = "Degree Sign Sans"

--- 文字列の「°」を、指定した文字スタイルの Span に分けた Inline の列を返す。
--- 「°」を含まない場合は nil を返す（要素を変えない）。
local function split_degree_sign(text, style)
  if not text:find(DEGREE_SIGN, 1, true) then
    return nil
  end
  local inlines = pandoc.Inlines({})
  local position = 1
  while true do
    local first, last = text:find(DEGREE_SIGN, position, true)
    if not first then
      break
    end
    if first > position then
      inlines:insert(pandoc.Str(text:sub(position, first - 1)))
    end
    inlines:insert(pandoc.Span(pandoc.Str(DEGREE_SIGN), { ["custom-style"] = style }))
    position = last + 1
  end
  if position <= #text then
    inlines:insert(pandoc.Str(text:sub(position)))
  end
  return inlines
end

--- Str の「°」を指定した文字スタイルに分ける関数を返す。
local function split_str_with(style)
  return function(str)
    -- 分けた後の Span の中の「°」を再び分けないよう、子は走査しない
    return split_degree_sign(str.text, style), false
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
