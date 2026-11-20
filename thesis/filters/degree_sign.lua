--[[
修士論文の docx で「°」（U+00B0）を文字スタイル付きの Span に分ける pandoc の Lua フィルタ。

ＭＳ 明朝・ＭＳ ゴシック・游ゴシックの「°」は全角幅の字形のため、docx で「°C」が
「° C」のように空いて見える。本文は pandoc が日本語を含むランに w:hint="eastAsia" を
付けると「°」が和文フォントで描かれ、表は欧文フォントにも游ゴシックを指定しているため
hint の有無によらず全角になる。そこで「°」だけを、和文・欧文の全スロットに欧文フォントを
指定した文字スタイル（reference.docx に定義。scripts/make_thesis_reference_docx.py）で描く。

- 明朝の文脈（本文・脚注・参考文献など）: 文字スタイル「Degree Sign」
- ゴシックの文脈（表・見出し・図。表題・図題を含む）: 文字スタイル「Degree Sign Sans」

コード（Code・CodeBlock）・数式・生の XML は Str でないため変えない。
scripts/build_thesis.py が pandoc-crossref の後・citeproc の前に適用する。
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

--- Str の「°」を指定した文字スタイルに分けるフィルタを返す。
local function degree_sign_filter(style)
  return {
    Str = function(str)
      -- 分けた後の Span の中の「°」を再び分けないよう、子は走査しない
      return split_degree_sign(str.text, style), false
    end,
  }
end

local sans_filter = degree_sign_filter(SANS_STYLE)

--- ゴシックの文脈の要素（表・見出し・図）は配下をすべて Sans にし、外側の走査を止める。
local function apply_sans(element)
  return element:walk(sans_filter), false
end

local serif_filter = degree_sign_filter(SERIF_STYLE)

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
