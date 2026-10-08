'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Sparkles,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  Check,
  X,
  Layers,
  Award,
  Loader2,
  BookOpen,
  HelpCircle,
  Lightbulb,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { chatApi } from '@/lib/api/chat'
import { notebooksApi } from '@/lib/api/notebooks'
import { SourceListResponse, NoteResponse, FlashcardDeckPayload } from '@/lib/types/api'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

export interface Flashcard {
  id: number
  question: string
  answer: string
  category?: string
}

interface FlashcardsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  notebookId: string
  notebookName: string
  sources?: SourceListResponse[]
  notes?: NoteResponse[]
}

const MIN_CARDS_REQUIRED = 25

export function FlashcardsModal({
  open,
  onOpenChange,
  notebookId,
  notebookName,
  sources = [],
  notes = [],
}: FlashcardsModalProps) {
  const [cards, setCards] = useState<Flashcard[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isFlipped, setIsFlipped] = useState(false)
  const [correctCount, setCorrectCount] = useState(0)
  const [wrongCount, setWrongCount] = useState(0)
  const [isGenerating, setIsGenerating] = useState(false)
  const [isCompleted, setIsCompleted] = useState(false)

  const storageKey = `notebook-flashcards-${notebookId}`

  // Persist state to SurrealDB (and localStorage fallback)
  const persistDeckState = useCallback(
    async (
      deckCards: Flashcard[],
      correct: number,
      wrong: number,
      lastIndex: number
    ) => {
      // 1. Cache locally
      try {
        localStorage.setItem(storageKey, JSON.stringify(deckCards))
        localStorage.setItem(
          `${storageKey}-progress`,
          JSON.stringify({ correct, wrong, lastIndex })
        )
      } catch {
        // ignore local storage errors
      }

      // 2. Persist to SurrealDB
      try {
        const payload: FlashcardDeckPayload = {
          cards: deckCards,
          correct_count: correct,
          wrong_count: wrong,
          last_card_index: lastIndex,
        }
        await notebooksApi.saveFlashcards(notebookId, payload)
      } catch (err) {
        console.error('Failed to save flashcards to SurrealDB:', err)
      }
    },
    [notebookId, storageKey]
  )

  // Load existing cards and scores from SurrealDB (or localStorage fallback) when opened
  useEffect(() => {
    if (!open) return

    let cancelled = false

    const loadDeck = async () => {
      try {
        // Check SurrealDB first
        const remote = await notebooksApi.getFlashcards(notebookId)
        if (cancelled) return

        if (remote && Array.isArray(remote.cards) && remote.cards.length > 0) {
          setCards(remote.cards)
          setCorrectCount(remote.correct_count ?? 0)
          setWrongCount(remote.wrong_count ?? 0)
          const idx = Math.min(remote.last_card_index ?? 0, remote.cards.length - 1)
          setCurrentIndex(Math.max(0, idx))
          setIsCompleted(
            remote.cards.length > 0 &&
              remote.correct_count + remote.wrong_count >= remote.cards.length
          )
          return
        }
      } catch (e) {
        console.warn('Could not load flashcards from SurrealDB, checking localStorage', e)
      }

      // Fallback: check localStorage
      try {
        const cached = localStorage.getItem(storageKey)
        if (cached) {
          const parsed = JSON.parse(cached)
          if (Array.isArray(parsed) && parsed.length > 0) {
            setCards(parsed)
            const progress = localStorage.getItem(`${storageKey}-progress`)
            if (progress) {
              const { correct, wrong, lastIndex } = JSON.parse(progress)
              setCorrectCount(correct ?? 0)
              setWrongCount(wrong ?? 0)
              setCurrentIndex(lastIndex ?? 0)
            }
            return
          }
        }
      } catch {
        // ignore
      }

      // If no cards exist anywhere, trigger generation
      generateFlashcards()
    }

    loadDeck()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, notebookId])

  const generateFlashcards = async () => {
    setIsGenerating(true)
    setIsFlipped(false)
    setCurrentIndex(0)
    setCorrectCount(0)
    setWrongCount(0)
    setIsCompleted(false)

    try {
      // 1. Build context configuration
      const sourceConfig: Record<string, 'full' | 'insights'> = {}
      sources.forEach((s) => {
        sourceConfig[s.id] = 'full'
      })

      const noteConfig: Record<string, 'full'> = {}
      notes.forEach((n) => {
        noteConfig[n.id] = 'full'
      })

      const contextData = await chatApi.buildContext({
        notebook_id: notebookId,
        context_config: {
          sources: sourceConfig,
          notes: noteConfig,
        },
      })

      // 2. Create a generation session
      const session = await chatApi.createSession({
        notebook_id: notebookId,
        title: `Flashcards: ${notebookName}`,
      })

      // 3. Prompt for at least 25 flashcards like NotebookLM
      const flashcardPrompt = `You are an expert tutor creating study flashcards like NotebookLM.
Analyze all provided sources and notes thoroughly.
Generate a comprehensive, rigorous study deck of at least 25 high-quality flashcards covering core concepts, key mechanisms, definitions, critical facts, and application scenarios.

STRICT INSTRUCTIONS:
1. Generate AT LEAST 25 flashcards (minimum 25 cards, numbered 1 to 25+).
2. Questions must be crisp, insightful, and test genuine understanding.
3. Answers must be direct, clear, and comprehensive.
4. Output ONLY valid JSON in this exact structure without conversational markdown:
[
  {
    "id": 1,
    "question": "Question text here?",
    "answer": "Answer explanation here.",
    "category": "Topic Name"
  }
]
`

      const result = await chatApi.sendMessage({
        session_id: session.id,
        message: flashcardPrompt,
        context: contextData.context,
      })

      const aiMessage = result.messages.find((m) => m.type === 'ai')?.content || ''

      // 4. Parse JSON from output
      let parsedCards: Flashcard[] = []
      const jsonMatch = aiMessage.match(/\[[\s\S]*\]/)
      if (jsonMatch) {
        try {
          parsedCards = JSON.parse(jsonMatch[0])
        } catch {
          // Fallback parsing cleanup
          const cleaned = jsonMatch[0]
            .replace(/,\s*([}\]])/g, '$1')
            .replace(/[\u0000-\u001F]+/g, ' ')
          parsedCards = JSON.parse(cleaned)
        }
      }

      if (!Array.isArray(parsedCards) || parsedCards.length === 0) {
        throw new Error('Could not parse flashcards from model response.')
      }

      // Ensure valid structure
      const validCards = parsedCards
        .filter((c) => c && typeof c.question === 'string' && typeof c.answer === 'string')
        .map((c, idx) => ({
          id: c.id || idx + 1,
          question: c.question.trim(),
          answer: c.answer.trim(),
          category: c.category || 'General',
        }))

      if (validCards.length === 0) {
        throw new Error('No valid flashcards found.')
      }

      setCards(validCards)
      persistDeckState(validCards, 0, 0, 0)
      toast.success(`Generated ${validCards.length} flashcards!`)
    } catch (err) {
      console.error('Failed to generate flashcards:', err)
      toast.error('Failed to generate flashcards. Please try again.')
    } finally {
      setIsGenerating(false)
    }
  }

  // Answer Handlers
  const handleCorrect = useCallback(() => {
    if (cards.length === 0 || isCompleted) return

    const nextCorrect = correctCount + 1
    const nextIndex = Math.min(currentIndex + 1, cards.length - 1)
    const completed = currentIndex + 1 >= cards.length

    setCorrectCount(nextCorrect)
    setIsFlipped(false)

    if (completed) {
      setIsCompleted(true)
    } else {
      setCurrentIndex(nextIndex)
    }

    persistDeckState(cards, nextCorrect, wrongCount, completed ? 0 : nextIndex)
  }, [cards, correctCount, currentIndex, isCompleted, persistDeckState, wrongCount])

  const handleWrong = useCallback(() => {
    if (cards.length === 0 || isCompleted) return

    const nextWrong = wrongCount + 1
    const nextIndex = Math.min(currentIndex + 1, cards.length - 1)
    const completed = currentIndex + 1 >= cards.length

    setWrongCount(nextWrong)
    setIsFlipped(false)

    if (completed) {
      setIsCompleted(true)
    } else {
      setCurrentIndex(nextIndex)
    }

    persistDeckState(cards, correctCount, nextWrong, completed ? 0 : nextIndex)
  }, [cards, correctCount, currentIndex, isCompleted, persistDeckState, wrongCount])

  const handleFlip = useCallback(() => {
    setIsFlipped((prev) => !prev)
  }, [])

  const restartDeck = () => {
    setCurrentIndex(0)
    setIsFlipped(false)
    setCorrectCount(0)
    setWrongCount(0)
    setIsCompleted(false)
    persistDeckState(cards, 0, 0, 0)
  }

  // Keyboard navigation
  useEffect(() => {
    if (!open || isGenerating) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onOpenChange(false)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        handleCorrect()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        handleWrong()
      } else if (e.key === ' ' || e.key === 'Enter' || e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault()
        handleFlip()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, isGenerating, handleCorrect, handleWrong, handleFlip, onOpenChange])

  const currentCard = cards[currentIndex]
  const nextCard1 = cards[currentIndex + 1]
  const nextCard2 = cards[currentIndex + 2]

  const progressPercent = cards.length > 0 ? Math.round(((currentIndex) / cards.length) * 100) : 0
  const totalAnswered = correctCount + wrongCount
  const accuracyPercent = totalAnswered > 0 ? Math.round((correctCount / totalAnswered) * 100) : 0

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 bg-background/85 backdrop-blur-md flex flex-col justify-between p-4 sm:p-6 overflow-hidden animate-in fade-in duration-200">
      {/* Top Header Bar */}
      <div className="w-full max-w-4xl mx-auto flex items-center justify-between gap-4 py-2 border-b border-border/60">
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded-md bg-fern-tint/40 text-fern">
            <Sparkles className="size-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold tracking-tight text-foreground font-display">
                Flashcards
              </h2>
              <Badge variant="outline" className="text-[10px] font-mono py-0 h-4 px-1.5">
                {cards.length > 0 ? `${currentIndex + 1} / ${cards.length}` : '0 / 0'}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground truncate max-w-xs sm:max-w-md">
              {notebookName}
            </p>
          </div>
        </div>

        {/* Real-time score badges */}
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="gap-1 border-destructive/40 text-destructive bg-destructive-tint/20 text-xs px-2 py-0.5"
          >
            <X className="size-3" />
            <span>{wrongCount} Wrong</span>
          </Badge>

          <Badge
            variant="outline"
            className="gap-1 border-fern/40 text-fern bg-fern-tint/20 text-xs px-2 py-0.5"
          >
            <Check className="size-3" />
            <span>{correctCount} Correct</span>
          </Badge>

          <Button
            variant="ghost"
            size="icon"
            onClick={() => onOpenChange(false)}
            className="size-8 text-muted-foreground hover:text-foreground ml-2"
            aria-label="Close"
          >
            <X className="size-4" />
          </Button>
        </div>
      </div>

      {/* Main Flashcard Deck Stage */}
      <div className="flex-1 flex flex-col items-center justify-center p-2 sm:p-4 w-full max-w-4xl mx-auto min-h-0">
        {isGenerating ? (
          <div className="flex flex-col items-center justify-center gap-4 text-center max-w-md p-8 rounded-2xl border border-border/80 bg-card/60 shadow-lg">
            <Loader2 className="size-10 text-fern animate-spin" />
            <div className="space-y-1">
              <h3 className="font-display font-semibold text-base text-foreground">
                Synthesizing Flashcards
              </h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Analyzing all sources and notes in <span className="font-medium text-foreground">{notebookName}</span> to generate at least {MIN_CARDS_REQUIRED} intelligent study cards...
              </p>
            </div>
          </div>
        ) : isCompleted ? (
          /* Completion Screen */
          <div className="flex flex-col items-center justify-center text-center max-w-md w-full p-8 rounded-2xl border border-border/80 bg-card shadow-xl space-y-6 animate-in zoom-in-95 duration-200">
            <div className="size-16 rounded-full bg-fern-tint/50 text-fern flex items-center justify-center shadow-inner">
              <Award className="size-8" />
            </div>

            <div className="space-y-1">
              <h3 className="font-display font-bold text-xl text-foreground">
                Deck Completed!
              </h3>
              <p className="text-xs text-muted-foreground">
                You reviewed all {cards.length} flashcards for this notebook.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3 w-full">
              <div className="p-3 rounded-lg border border-border/60 bg-muted/30">
                <p className="text-xs text-muted-foreground">Accuracy</p>
                <p className="text-2xl font-bold font-display text-foreground mt-0.5">
                  {accuracyPercent}%
                </p>
              </div>
              <div className="p-3 rounded-lg border border-border/60 bg-muted/30">
                <p className="text-xs text-muted-foreground">Mastered</p>
                <p className="text-2xl font-bold font-display text-fern mt-0.5">
                  {correctCount} / {cards.length}
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-2 w-full pt-2">
              <Button onClick={restartDeck} className="w-full gap-2 bg-fern text-on-primary hover:bg-fern-deep">
                <RotateCcw className="size-4" />
                <span>Review Deck Again</span>
              </Button>
              <Button variant="outline" onClick={generateFlashcards} className="w-full gap-2">
                <Sparkles className="size-4" />
                <span>Regenerate Fresh Cards</span>
              </Button>
            </div>
          </div>
        ) : cards.length === 0 ? (
          <div className="text-center p-8 border border-border/80 rounded-2xl bg-card space-y-4 max-w-md">
            <HelpCircle className="size-10 text-muted-foreground mx-auto" />
            <div>
              <h3 className="font-semibold text-foreground">No Flashcards Available</h3>
              <p className="text-xs text-muted-foreground mt-1">
                Add sources or notes to this notebook and click below to generate a study deck.
              </p>
            </div>
            <Button onClick={generateFlashcards} className="gap-2 bg-fern text-on-primary hover:bg-fern-deep">
              <Sparkles className="size-4" />
              <span>Generate 25+ Flashcards</span>
            </Button>
          </div>
        ) : (
          /* 3D Stacked Flashcards Deck */
          <div className="relative w-full max-w-xl h-[360px] sm:h-[420px] flex items-center justify-center">
            {/* Third Stacked Card (bottom) */}
            {nextCard2 && (
              <div
                aria-hidden="true"
                className="absolute inset-0 translate-y-6 scale-[0.90] opacity-35 bg-card rounded-2xl border border-border shadow-sm pointer-events-none transition-all duration-300"
              />
            )}

            {/* Second Stacked Card (middle) */}
            {nextCard1 && (
              <div
                aria-hidden="true"
                className="absolute inset-0 translate-y-3 scale-[0.95] opacity-70 bg-card rounded-2xl border border-border/80 shadow-md pointer-events-none transition-all duration-300"
              />
            )}

            {/* Top Interactive Card */}
            {currentCard && (
              <div
                onClick={handleFlip}
                className={cn(
                  'relative w-full h-full bg-card rounded-2xl border border-border shadow-xl p-6 sm:p-8 flex flex-col justify-between cursor-pointer select-none transition-all duration-300 transform hover:scale-[1.01] hover:border-fern/60 group',
                  isFlipped ? 'bg-card/95 border-teal/40' : 'bg-card'
                )}
              >
                {/* Card Header Info */}
                <div className="flex items-center justify-between gap-2 border-b border-border/40 pb-3">
                  <Badge variant="secondary" className="text-[11px] font-medium tracking-wide">
                    {currentCard.category || 'Concept'}
                  </Badge>
                  <span className="text-[11px] font-mono text-muted-foreground">
                    {isFlipped ? 'Answer' : 'Question'}
                  </span>
                </div>

                {/* Card Main Body */}
                <div className="flex-1 flex flex-col items-center justify-center text-center p-2 sm:p-4 overflow-y-auto max-h-[220px] no-scrollbar">
                  {!isFlipped ? (
                    <div className="space-y-2">
                      <p className="text-base sm:text-lg font-semibold text-foreground leading-relaxed font-display">
                        {currentCard.question}
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-3 animate-in fade-in duration-150">
                      <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-teal-tint/30 text-teal text-xs font-medium">
                        <Lightbulb className="size-3.5" />
                        <span>Explanation</span>
                      </div>
                      <p className="text-sm sm:text-base font-normal text-foreground/90 leading-relaxed">
                        {currentCard.answer}
                      </p>
                    </div>
                  )}
                </div>

                {/* Card Footer Hint */}
                <div className="border-t border-border/40 pt-3 flex items-center justify-between text-xs text-muted-foreground/70">
                  <span className="text-[11px] flex items-center gap-1 group-hover:text-foreground transition-colors">
                    <RotateCcw className="size-3" />
                    <span>{isFlipped ? 'Click card to view question' : 'Click card to reveal answer'}</span>
                  </span>
                  <span className="text-[10px] font-mono">
                    {currentIndex + 1} of {cards.length}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Bottom Action Controls Dock */}
      {cards.length > 0 && !isCompleted && !isGenerating && (
        <div className="w-full max-w-xl mx-auto flex flex-col items-center gap-3 pt-2">
          {/* Progress bar */}
          <div className="w-full space-y-1">
            <div className="flex justify-between text-[11px] text-muted-foreground font-mono">
              <span>Progress</span>
              <span>{progressPercent}%</span>
            </div>
            <Progress value={progressPercent} className="h-1.5" />
          </div>

          {/* Left (Wrong) - Flip - Right (Correct) Interactive Dock */}
          <div className="w-full flex items-center justify-between gap-3 pt-1">
            {/* Click Left: Wrong / Increments Wrong count by 1 */}
            <Button
              variant="outline"
              size="lg"
              onClick={handleWrong}
              className="flex-1 border-destructive/40 text-destructive hover:bg-destructive-tint/30 hover:border-destructive gap-2 h-12 text-sm font-semibold shadow-xs"
              title="Mark as Wrong / Needs Review (Left Arrow)"
            >
              <ChevronLeft className="size-4" />
              <span>Wrong (←)</span>
            </Button>

            {/* Center: Flip */}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleFlip}
              className="px-3 h-12 text-xs text-muted-foreground hover:text-foreground flex flex-col gap-0.5"
            >
              <RotateCcw className="size-4" />
              <span className="text-[10px]">Flip (Space)</span>
            </Button>

            {/* Click Right: Correct / Increments Correct count by 1 */}
            <Button
              variant="outline"
              size="lg"
              onClick={handleCorrect}
              className="flex-1 border-fern/40 text-fern hover:bg-fern-tint/40 hover:border-fern gap-2 h-12 text-sm font-semibold shadow-xs"
              title="Mark as Correct / Mastered (Right Arrow)"
            >
              <span>Correct (→)</span>
              <ChevronRight className="size-4" />
            </Button>
          </div>

          <div className="flex items-center gap-4 text-[11px] text-muted-foreground/60 pt-1">
            <button
              onClick={restartDeck}
              className="hover:text-foreground transition-colors flex items-center gap-1 cursor-pointer"
            >
              <RotateCcw className="size-3" />
              <span>Restart deck</span>
            </button>
            <span>•</span>
            <button
              onClick={generateFlashcards}
              className="hover:text-foreground transition-colors flex items-center gap-1 cursor-pointer"
            >
              <Sparkles className="size-3" />
              <span>Regenerate cards</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
