import { enUS, Locale } from 'date-fns/locale'

const LOCALE_MAP: Record<string, Locale> = {
  'en-US': enUS,
}

/**
 * Get the date-fns locale for a given language code.
 * Falls back to English (en-US).
 */
export function getDateLocale(language?: string): Locale {
  if (!language) return enUS
  return LOCALE_MAP[language] || enUS
}
