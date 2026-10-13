import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ModelCombobox, fuzzyModelFilter } from './ModelCombobox'
import { Model } from '@/lib/types/models'

const mockModels: Model[] = [
  {
    id: 'Qwen/Qwen2.5-7B-Instruct',
    name: 'Qwen/Qwen2.5-7B-Instruct',
    provider: 'kaggle',
    type: 'language',
    created: '2026-01-01',
    updated: '2026-01-01',
  },
  {
    id: 'gpt-4o',
    name: 'GPT-4o',
    provider: 'openai',
    type: 'language',
    created: '2026-01-01',
    updated: '2026-01-01',
  },
  {
    id: 'claude-3-5-sonnet',
    name: 'Claude 3.5 Sonnet',
    provider: 'anthropic',
    type: 'language',
    created: '2026-01-01',
    updated: '2026-01-01',
  },
]

describe('fuzzyModelFilter', () => {
  it('returns 1 when search is empty', () => {
    expect(fuzzyModelFilter('Qwen/Qwen2.5-7B-Instruct kaggle', '')).toBe(1)
  })

  it('matches exact and substring queries', () => {
    expect(fuzzyModelFilter('Qwen/Qwen2.5-7B-Instruct kaggle', 'qwen')).toBeGreaterThan(0)
    expect(fuzzyModelFilter('Qwen/Qwen2.5-7B-Instruct kaggle', 'kaggle')).toBeGreaterThan(0)
    expect(fuzzyModelFilter('Qwen/Qwen2.5-7B-Instruct kaggle', '7b')).toBeGreaterThan(0)
  })

  it('supports fuzzy character subsequence matching', () => {
    // 'qw7b' fuzzily matches 'Qwen/Qwen2.5-7B-Instruct kaggle'
    expect(fuzzyModelFilter('Qwen/Qwen2.5-7B-Instruct kaggle', 'qw7b')).toBeGreaterThan(0)
  })

  it('filters out non-matching queries', () => {
    expect(fuzzyModelFilter('Qwen/Qwen2.5-7B-Instruct kaggle', 'llama')).toBe(0)
  })
})

describe('ModelCombobox', () => {
  it('renders trigger button displaying selected model', () => {
    render(
      <ModelCombobox
        models={mockModels}
        value="Qwen/Qwen2.5-7B-Instruct"
        onChange={vi.fn()}
      />
    )

    expect(screen.getByRole('combobox')).toBeInTheDocument()
    expect(screen.getByText('Qwen/Qwen2.5-7B-Instruct')).toBeInTheDocument()
    expect(screen.getByText('kaggle')).toBeInTheDocument()
  })

  it('displays placeholder when no value is selected', () => {
    render(
      <ModelCombobox
        models={mockModels}
        value=""
        onChange={vi.fn()}
        placeholder="Pick an AI model"
      />
    )

    expect(screen.getByText('Pick an AI model')).toBeInTheDocument()
  })

  it('supports special defaultOption', () => {
    render(
      <ModelCombobox
        models={mockModels}
        value="default"
        onChange={vi.fn()}
        defaultOption={{
          value: 'default',
          label: 'System Default (Qwen 7B)',
          provider: 'kaggle',
        }}
      />
    )

    expect(screen.getByText('System Default (Qwen 7B)')).toBeInTheDocument()
  })
})
