## v1 (2026-10-12)
- 初版音频导演模板: 克制优先原则 (无演绎价值的句子不给建议)、情感手法速查表
  (speed/pitch_st/gain_db/pause_category 四轴)、对白换声规则、严格 JSON Schema 输出、
  few-shot 自检清单。输出 SentenceOverrideSuggestion 列表, 落库走人工优先
  (Paragraph.sentence_overrides 非空即人工领地, 导演不覆盖)。
