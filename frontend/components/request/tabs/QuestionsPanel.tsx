'use client'
import type { PersonRef, RequestDetail } from '@/lib/api/types'
import { useAnswer } from '@/lib/hooks/mutations'
import { QuestionCard } from '../QuestionCard'
import { EmptyState } from '../../states/States'

export function QuestionsPanel({ detail, me, readOnly = false }: { detail: RequestDetail; me: PersonRef; readOnly?: boolean }) {
  const answer = useAnswer(detail.id, me)
  if (detail.questions.length === 0) return <EmptyState glyph="Question" title="No questions." body="Actron asks only when the evidence leaves a real choice." />
  const open = detail.questions.filter((q) => !q.answer).length
  return (
    <div className="flex flex-col gap-3" data-testid="questions-panel">
      <p className="text-small text-fg-2">
        {readOnly
          ? open === 0
            ? 'Answered as shown. This is a recording.'
            : `${open} of ${detail.questions.length} not answered yet at this point in the recording.`
          : open === 0
            ? 'All questions are answered.'
            : `${open} of ${detail.questions.length} still open. Answers here also update the Slack thread.`}
      </p>
      {detail.questions.map((q, i) => (
        <QuestionCard
          key={q.questionId}
          index={i}
          question={q}
          evidence={detail.evidence}
          disabled={readOnly || !detail.allowedActions.includes('answer')}
          pending={answer.isPending && answer.variables?.questionId === q.questionId}
          onAnswer={readOnly ? undefined : (questionId, value) => void answer.run({ questionId, value }).catch(() => undefined)}
        />
      ))}
    </div>
  )
}
