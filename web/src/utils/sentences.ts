/**
 * 句切分（v6 逐句导演前端预览）。
 *
 * 与后端 `pipeline/synthesize.py` 的 `_SENT_END_RE` / `_split_sentences`
 * 保持同一套规则（前端预览编号 = 后端逐句合成的句序号 idx）：
 * - 英文：句末标点 `[.!?]+` + 可选收尾引号/括号，其后须为空白或文本末；
 *   句后空白随本句吞掉（v6 同款）。
 * - 中文：`[。！？；]` + 可选收尾引号/括号后即切（中文句间通常无空格，不吞空白）。
 * - 收尾引号随它收的句子：'He said "Go!" Then.' → ['He said "Go!"', 'Then.']。
 *
 * 已知可接受误差（任务注明）：缩写（如 "Mr."）会被当作句末切开。
 */

/** 句末边界正则 — 源码与后端 _SENT_END_RE 逐字符一致（含弯引号 ” ’） */
export const SENTENCE_END_RE = /[.!?]+["')\]”’]*(?=\s|$)|[。！？；]["')\]”’]*/g

/** 将段落文本切为句列表；空文本返回空数组，各句已 trim、空段丢弃，句尾余文作为末句。 */
export function splitSentences(text: string): string[] {
  if (!text || !text.trim()) return []
  const sentences: string[] = []
  let start = 0
  for (const m of text.matchAll(SENTENCE_END_RE)) {
    const matched = m[0]
    if (!matched || m.index === undefined) continue
    let end = m.index + matched.length
    // 英文边界：吞掉句后空白（空格/制表符，与后端一致）；中文边界不吞
    if (matched[0] === '.' || matched[0] === '!' || matched[0] === '?') {
      while (end < text.length && (text[end] === ' ' || text[end] === '\t')) end++
    }
    const seg = text.slice(start, end).trim()
    if (seg) sentences.push(seg)
    start = end
  }
  const tail = text.slice(start).trim()
  if (tail) sentences.push(tail)
  return sentences
}
