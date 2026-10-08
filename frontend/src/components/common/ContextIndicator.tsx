'use client'

import { FileText, Lightbulb, StickyNote } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface ContextIndicatorProps {
  sourcesInsights: number
  sourcesFull: number
  notesCount: number
  tokenCount?: number
  charCount?: number
  className?: string
}

// Helper function to format large numbers with K/M suffixes
function formatNumber(num: number): string {
  if (num >= 1000000) {
    return `${(num / 1000000).toFixed(1)}M`
  }
  if (num >= 1000) {
    return `${(num / 1000).toFixed(1)}K`
  }
  return num.toString()
}

export function ContextIndicator({
  sourcesInsights,
  sourcesFull,
  notesCount,
  tokenCount,
  charCount,
  className
}: ContextIndicatorProps) {
  const hasContext = (sourcesInsights + sourcesFull) > 0 || notesCount > 0

  if (!hasContext) {
    return null
  }

  return (
    <div className={cn('flex items-center gap-1.5 text-xs text-muted-foreground shrink-0', className)}>
      <span className="text-muted-foreground/30 font-light select-none">|</span>

      <div className="flex items-center gap-1">
        {sourcesInsights > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" className="text-[11px] h-5 flex items-center gap-1 px-1.5 py-0 text-ctx-insights border-ctx-insights/50 cursor-default">
                <Lightbulb className="h-3 w-3" />
                <span>{sourcesInsights}</span>
              </Badge>
            </TooltipTrigger>
            <TooltipContent>
              <p>Insights for {sourcesInsights} source{sourcesInsights !== 1 ? 's' : ''}</p>
            </TooltipContent>
          </Tooltip>
        )}

        {sourcesFull > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" className="text-[11px] h-5 flex items-center gap-1 px-1.5 py-0 text-ctx-full border-ctx-full/50 cursor-default">
                <FileText className="h-3 w-3" />
                <span>{sourcesFull}</span>
              </Badge>
            </TooltipTrigger>
            <TooltipContent>
              <p>{sourcesFull} full source{sourcesFull !== 1 ? 's' : ''}</p>
            </TooltipContent>
          </Tooltip>
        )}

        {notesCount > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" className="text-[11px] h-5 flex items-center gap-1 px-1.5 py-0 text-ctx-full border-ctx-full/50 cursor-default">
                <StickyNote className="h-3 w-3" />
                <span>{notesCount}</span>
              </Badge>
            </TooltipTrigger>
            <TooltipContent>
              <p>{notesCount} full note{notesCount !== 1 ? 's' : ''}</p>
            </TooltipContent>
          </Tooltip>
        )}
      </div>

      {(tokenCount !== undefined || charCount !== undefined) && (
        <span className="text-[11px] text-muted-foreground/70 hidden sm:inline-flex items-center gap-0.5 whitespace-nowrap">
          {tokenCount !== undefined && tokenCount > 0 && (
            <span>{formatNumber(tokenCount)} tok</span>
          )}
          {tokenCount !== undefined && charCount !== undefined && tokenCount > 0 && charCount > 0 && (
            <span>/</span>
          )}
          {charCount !== undefined && charCount > 0 && (
            <span>{formatNumber(charCount)} ch</span>
          )}
        </span>
      )}
    </div>
  )
}
