'use client'
import { useId, useState } from 'react'
import type { Evidence, Question } from '@/lib/api/types'
import { surfaceName } from '@/lib/events'
import { Glyph } from '../glyphs/Glyph'
import { Button } from '../ui/Button'
import { RelativeTime } from '../core/Formatting'
import { cx } from '../ui/cx'

export interface QuestionCardProps {
  question: Question
  onAnswer?: (questionId: string, value: string) => void
  evidence?: Evidence[]
  disabled?: boolean
  pending?: boolean
  index?: number
}

/** A question tied to its evidence; buttons for choices, a short field for text; answered shows who and where. */
export function QuestionCard({ question, onAnswer, evidence = [], disabled = false, pending = false, index }: QuestionCardProps) {
  const id = useId()
  const preselected = question.options.find((o) => o.preselected)?.value ?? ''
  const [choice, setChoice] = useState(preselected)
  const [text, setText] = useState('')
  const related = evidence.filter((e) => question.evidenceIds.includes(e.evidenceId))
  const answered = question.answer
  const textError = text.trim().length > 0 && text.trim().length < 2 ? 'Write at least two characters.' : null

  return (
    <section
      data-testid="question-card"
      data-answered={answered ? 'true' : 'false'}
      aria-labelledby={`${id}-q`}
      className={cx('flex flex-col gap-3 rounded-md border p-4', answered ? 'border-line-1' : 'border-accent/50')}
    >
      <header className="flex items-center gap-2">
        <span className={answered ? 'text-fg-3' : 'text-accent'}>
          <Glyph name="Question" size={16} />
        </span>
        <span className="eyebrow">
          Question{typeof index === 'number' ? ` ${index + 1}` : ''}
          {question.required ? '' : ' · optional'}
        </span>
      </header>
      <h3 id={`${id}-q`} className="display text-title-sm text-fg-1">
        {question.text}
      </h3>
      {related.length ? (
        <p className="text-caption text-fg-3">
          Asked because of: {related.map((e) => e.title.replace(/[.\s]+$/, '')).join('; ')}.
        </p>
      ) : null}

      {answered ? (
        <div className="flex flex-col gap-1 rounded-sm bg-ink-2 px-3 py-2" data-testid="answer">
          <p className="text-small text-fg-1">
            {question.options.find((o) => o.value === answered.value)?.label ?? answered.value}
          </p>
          <p className="text-caption text-fg-3">
            {answered.by.name} · {surfaceName(answered.surface)} · <RelativeTime value={answered.at} />
          </p>
        </div>
      ) : disabled && !onAnswer ? (
        <p className="text-small text-fg-3" data-testid="question-unanswered">
          Not answered yet.
        </p>
      ) : question.kind === 'choice' ? (
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (choice) onAnswer?.(question.questionId, choice)
          }}
        >
          <fieldset className="flex flex-col gap-1.5" aria-describedby={`${id}-q`}>
            <legend className="sr-only">{question.text}</legend>
            {question.options.map((option) => (
              <label
                key={option.value}
                className={cx(
                  'flex cursor-pointer items-start gap-3 rounded-sm border px-3 py-2 transition-colors duration-1',
                  choice === option.value ? 'border-accent/60 bg-accent-wash' : 'border-line-1 hover:bg-ink-2',
                )}
              >
                <input
                  type="radio"
                  name={`${id}-choice`}
                  value={option.value}
                  checked={choice === option.value}
                  onChange={() => setChoice(option.value)}
                  disabled={disabled}
                  className="mt-1 accent-[var(--accent)]"
                />
                <span className="flex flex-col">
                  <span className="text-small text-fg-1">{option.label}</span>
                  {option.note ? <span className="text-caption text-fg-3">{option.note}</span> : null}
                </span>
              </label>
            ))}
          </fieldset>
          <div>
            <Button type="submit" variant="primary" size="sm" disabled={!choice || disabled} loading={pending} loadingText="Sending">
              Send answer
            </Button>
          </div>
        </form>
      ) : (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (text.trim().length >= 2) onAnswer?.(question.questionId, text.trim())
          }}
        >
          <label htmlFor={`${id}-text`} className="sr-only">
            Your answer
          </label>
          <textarea
            id={`${id}-text`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            disabled={disabled}
            aria-invalid={textError ? true : undefined}
            aria-describedby={textError ? `${id}-err` : undefined}
            className="w-full resize-y rounded-sm border border-line-2 bg-ink-1 px-3 py-2 text-small text-fg-1 focus-visible:border-accent"
            placeholder="A short answer"
          />
          {textError ? (
            <p id={`${id}-err`} className="text-caption text-state-conflict">
              {textError}
            </p>
          ) : null}
          <div>
            <Button type="submit" variant="primary" size="sm" disabled={text.trim().length < 2 || disabled} loading={pending} loadingText="Sending">
              Send answer
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}
