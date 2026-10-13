'use client'

import { useState, useMemo } from 'react'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  Command,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandSeparator,
} from '@/components/ui/command'
import { Button } from '@/components/ui/button'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Check, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Model } from '@/lib/types/models'

export interface ModelComboboxOption {
  value: string
  label: string
  provider?: string
}

export interface ModelComboboxProps {
  id?: string
  name?: string
  value?: string
  onChange: (value: string) => void
  models?: Model[]
  options?: ModelComboboxOption[]
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  disabled?: boolean
  isLoading?: boolean
  size?: 'sm' | 'default'
  className?: string
  triggerClassName?: string
  contentClassName?: string
  noneOption?: {
    value: string
    label: string
  }
  defaultOption?: {
    value: string
    label: string
    provider?: string
  }
}

/**
 * Fuzzy search filter for cmdk:
 * Supports substring, multi-token, prefix, and character-subsequence fuzzy matching.
 */
export function fuzzyModelFilter(value: string, search: string, keywords?: string[]): number {
  if (!search) return 1
  const searchLower = search.toLowerCase().trim()
  if (!searchLower) return 1

  const valueLower = value.toLowerCase()
  const kw = keywords ? keywords.join(' ').toLowerCase() : ''
  const combined = `${valueLower} ${kw}`

  // 1. Exact match
  if (valueLower === searchLower || kw === searchLower) return 1
  if (valueLower.startsWith(searchLower)) return 0.95

  // 2. Substring match
  if (combined.includes(searchLower)) return 0.9

  // 3. Multi-token match: all tokens present anywhere in combined text
  const tokens = searchLower.split(/\s+/).filter(Boolean)
  if (tokens.length > 1 && tokens.every((t) => combined.includes(t))) {
    return 0.8
  }

  // 4. Character subsequence fuzzy match (e.g. "qwen7b" matches "qwen2.5-7b")
  let sIdx = 0
  for (let i = 0; i < combined.length && sIdx < searchLower.length; i++) {
    if (combined[i] === searchLower[sIdx]) {
      sIdx++
    }
  }
  if (sIdx === searchLower.length) {
    return 0.5
  }

  return 0
}

export function ModelCombobox({
  id,
  value,
  onChange,
  models: providedModels,
  options: customOptions,
  placeholder,
  searchPlaceholder,
  emptyText,
  disabled = false,
  isLoading: externalLoading = false,
  size = 'default',
  className,
  triggerClassName,
  contentClassName,
  noneOption,
  defaultOption,
}: ModelComboboxProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const isLoading = externalLoading

  // Resolve list of selectable models
  const resolvedModels = useMemo<Model[]>(() => {
    if (customOptions) return []
    return providedModels || []
  }, [providedModels, customOptions])

  // Sort models alphabetically by name
  const sortedModels = useMemo(() => {
    return [...resolvedModels].sort((a, b) => a.name.localeCompare(b.name))
  }, [resolvedModels])

  // Determine current display label on trigger button
  const currentDisplay = useMemo(() => {
    if (!value) {
      return {
        label: placeholder || t('models.selectModelPlaceholder'),
        provider: undefined,
        isPlaceholder: true,
      }
    }

    if (defaultOption && value === defaultOption.value) {
      return {
        label: defaultOption.label,
        provider: defaultOption.provider,
        isPlaceholder: false,
      }
    }

    if (noneOption && value === noneOption.value) {
      return {
        label: noneOption.label,
        provider: undefined,
        isPlaceholder: false,
      }
    }

    if (customOptions) {
      const match = customOptions.find((o) => o.value === value)
      if (match) {
        return {
          label: match.label,
          provider: match.provider,
          isPlaceholder: false,
        }
      }
    }

    const matchedModel = resolvedModels.find((m) => m.id === value)
    if (matchedModel) {
      return {
        label: matchedModel.name,
        provider: matchedModel.provider,
        isPlaceholder: false,
      }
    }

    // Fallback: value string itself
    return {
      label: value,
      provider: undefined,
      isPlaceholder: false,
    }
  }, [value, defaultOption, noneOption, customOptions, resolvedModels, placeholder, t])

  const hasSpecialOptions = !!defaultOption || !!noneOption
  const hasItems = customOptions ? customOptions.length > 0 : sortedModels.length > 0

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled || isLoading}
          className={cn(
            'w-full justify-between font-normal text-left gap-2',
            size === 'sm' ? 'h-8 text-xs px-2.5' : 'h-9 text-sm px-3',
            currentDisplay.isPlaceholder && 'text-muted-foreground',
            triggerClassName,
            className
          )}
        >
          <span className="truncate flex-1">{currentDisplay.label}</span>
          {currentDisplay.provider && !currentDisplay.isPlaceholder && (
            <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded shrink-0">
              {currentDisplay.provider}
            </span>
          )}
          {isLoading ? (
            <LoadingSpinner size="sm" className="ml-1 shrink-0" />
          ) : (
            <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className={cn(
          'w-[--radix-popover-trigger-width] min-w-[280px] max-w-[480px] p-0 z-50 shadow-md',
          contentClassName
        )}
      >
        <Command filter={fuzzyModelFilter}>
          <CommandInput
            placeholder={
              searchPlaceholder ||
              t('models.searchPlaceholder', { defaultValue: 'Search models (fuzzy)...' })
            }
          />
          <CommandList className="max-h-[280px] overflow-y-auto">
            <CommandEmpty className="py-4 text-center text-xs text-muted-foreground">
              {emptyText || t('common.noResults', { defaultValue: 'No models found' })}
            </CommandEmpty>

            {/* Special Top-Level Options: System Default / None */}
            {hasSpecialOptions && (
              <CommandGroup>
                {defaultOption && (
                  <CommandItem
                    key={defaultOption.value}
                    value={`${defaultOption.label} default system ${defaultOption.provider || ''}`}
                    keywords={[defaultOption.label, 'default', 'system', defaultOption.provider || '']}
                    onSelect={() => {
                      onChange(defaultOption.value)
                      setOpen(false)
                    }}
                    className="flex items-center justify-between cursor-pointer py-1.5 px-2"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
                      <Check
                        className={cn(
                          'size-3.5 shrink-0',
                          value === defaultOption.value ? 'opacity-100 text-primary' : 'opacity-0'
                        )}
                      />
                      <span className="truncate text-xs font-medium">{defaultOption.label}</span>
                    </div>
                    {defaultOption.provider && (
                      <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded shrink-0">
                        {defaultOption.provider}
                      </span>
                    )}
                  </CommandItem>
                )}

                {noneOption && (
                  <CommandItem
                    key={noneOption.value}
                    value={`${noneOption.label} none unset fallback`}
                    keywords={[noneOption.label, 'none', 'unset', 'fallback']}
                    onSelect={() => {
                      onChange(noneOption.value)
                      setOpen(false)
                    }}
                    className="flex items-center justify-between cursor-pointer py-1.5 px-2"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
                      <Check
                        className={cn(
                          'size-3.5 shrink-0',
                          value === noneOption.value ? 'opacity-100 text-primary' : 'opacity-0'
                        )}
                      />
                      <span className="truncate text-xs text-muted-foreground">
                        {noneOption.label}
                      </span>
                    </div>
                  </CommandItem>
                )}
              </CommandGroup>
            )}

            {hasSpecialOptions && hasItems && <CommandSeparator />}

            {/* Custom Options */}
            {customOptions && customOptions.length > 0 && (
              <CommandGroup>
                {customOptions.map((opt) => (
                  <CommandItem
                    key={opt.value}
                    value={`${opt.label} ${opt.provider || ''} ${opt.value}`}
                    keywords={[opt.label, opt.provider || '', opt.value]}
                    onSelect={() => {
                      onChange(opt.value)
                      setOpen(false)
                    }}
                    className="flex items-center justify-between cursor-pointer py-1.5 px-2"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
                      <Check
                        className={cn(
                          'size-3.5 shrink-0',
                          value === opt.value ? 'opacity-100 text-primary' : 'opacity-0'
                        )}
                      />
                      <span className="truncate text-xs">{opt.label}</span>
                    </div>
                    {opt.provider && (
                      <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded shrink-0">
                        {opt.provider}
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {/* Standard Model List */}
            {!customOptions && sortedModels.length > 0 && (
              <CommandGroup>
                {sortedModels.map((model) => (
                  <CommandItem
                    key={model.id}
                    value={`${model.name} ${model.provider} ${model.id}`}
                    keywords={[model.provider, model.name, model.id]}
                    onSelect={() => {
                      onChange(model.id)
                      setOpen(false)
                    }}
                    className="flex items-center justify-between cursor-pointer py-1.5 px-2"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
                      <Check
                        className={cn(
                          'size-3.5 shrink-0',
                          value === model.id ? 'opacity-100 text-primary' : 'opacity-0'
                        )}
                      />
                      <span className="truncate text-xs font-medium">{model.name}</span>
                    </div>
                    <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded shrink-0">
                      {model.provider}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
