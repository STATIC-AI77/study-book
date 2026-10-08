import { describe, expect, it } from 'vitest'
import { enUS } from 'date-fns/locale'

import { getDateLocale } from './date-locale'

describe('getDateLocale', () => {
  it('returns English date locale', () => {
    expect(getDateLocale('en-US')).toBe(enUS)
  })

  it('falls back to English for unknown codes or undefined', () => {
    expect(getDateLocale('xx-XX')).toBe(enUS)
    expect(getDateLocale()).toBe(enUS)
  })
})
