import { describe, it, expect } from 'vitest'
import { splitSentences, SENTENCE_END_RE } from '../sentences'

describe('splitSentences（v6 逐句导演前端切句，与后端 synthesize.py 同规则）', () => {
  it('英文按 [.!?]+ 引号边界切分', () => {
    expect(splitSentences('Hello world. This is a test! Is it working?')).toEqual([
      'Hello world.',
      'This is a test!',
      'Is it working?',
    ])
  })

  it('中文按 [。！？；] 切分', () => {
    expect(splitSentences('你好世界。这是测试！')).toEqual(['你好世界。', '这是测试！'])
    expect(splitSentences('第一句；第二句？')).toEqual(['第一句；', '第二句？'])
  })

  it('收尾引号随它收的句子', () => {
    expect(splitSentences('He said "Go!" Then he left.')).toEqual([
      'He said "Go!"',
      'Then he left.',
    ])
    expect(splitSentences('“第一句。”第二句。')).toEqual(['“第一句。”', '第二句。'])
  })

  it('句尾无标点的余文作为末句', () => {
    expect(splitSentences('One. two three')).toEqual(['One.', 'two three'])
  })

  it('空文本返回空数组', () => {
    expect(splitSentences('')).toEqual([])
    expect(splitSentences('   ')).toEqual([])
  })

  it('已知可接受误差：缩写 "Mr." 被当句末切开（任务注明的既有边界）', () => {
    expect(splitSentences('Mr. Smith left.')).toEqual(['Mr.', 'Smith left.'])
  })

  it('SENTENCE_END_RE 为全局正则（matchAll 可用）', () => {
    expect(SENTENCE_END_RE.global).toBe(true)
  })
})
