import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import LocaleSwitcher from '../LocaleSwitcher.vue'
import { setLocale, getLocale, initLocale, SUPPORTED_LOCALES } from '../../i18n'

const LS_KEY = 'app-locale'

describe('LocaleSwitcher (M-03)', () => {
  beforeEach(() => {
    localStorage.removeItem(LS_KEY)
    initLocale()
  })

  it('renders one option per supported locale', () => {
    const wrapper = mount(LocaleSwitcher)
    const options = wrapper.findAll('option')
    expect(options.length).toBe(Object.keys(SUPPORTED_LOCALES).length)
    const values = options.map((o) => o.attributes('value'))
    expect(values).toContain('zh-CN')
    expect(values).toContain('en-US')
  })

  it('reflects the current locale as the selected value', () => {
    setLocale('en-US')
    const wrapper = mount(LocaleSwitcher)
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('en-US')
  })

  it('switches the active locale when the user selects an option', async () => {
    setLocale('zh-CN')
    const wrapper = mount(LocaleSwitcher)
    const select = wrapper.find('select')
    await select.setValue('en-US')
    expect(getLocale()).toBe('en-US')
  })
})
