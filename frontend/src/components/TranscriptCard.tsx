import { LoaderCircle, NotebookPen } from 'lucide-react'
import { Card } from './ui/Card'
import type { TranscriptSegment } from '../types/meeting'

type TranscriptCardProps = { message: string; transcript: TranscriptSegment[]; isMeetingActive: boolean }

function formatTime(seconds: number | null): string {
  if (seconds === null) return '--:--'
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
}

export function TranscriptCard({ message, transcript, isMeetingActive }: TranscriptCardProps) {
  return <Card className="transcript-card"><header className="card-heading"><span className="card-icon"><NotebookPen /></span><div><h2>リアルタイム文字起こし</h2><p>{message}</p></div></header><div className="transcript-list" aria-live="polite">
    {transcript.length === 0 ? <div className="empty-transcript"><LoaderCircle className="spin" /><p>音声を待っています…</p><span>最初のチャンクが処理されると、ここへ文字起こしが表示されます。</span></div> : transcript.map((segment, index) => {
      const isLatest = index === transcript.length - 1 && isMeetingActive
      return <article className={`transcript-row${isLatest ? ' live' : ''}`} key={`${index}-${segment.start ?? ''}-${segment.text}`}><time>{formatTime(segment.start)}</time><span className="speaker-badge">{segment.speaker ?? '?'}</span><div><strong>{segment.speaker === null ? '話者' : `話者${segment.speaker}`}</strong><p>{segment.text}{isLatest && <span className="cursor" />}</p></div></article>
    })}
  </div></Card>
}
