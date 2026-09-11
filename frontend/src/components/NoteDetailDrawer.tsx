import { X } from 'lucide-react'
import { Markdown } from './Markdown'
import { formatDuration, formatNoteDate } from '../lib/note'
import type { NoteDetail } from '../types/note'

type NoteDetailDrawerProps = { note: NoteDetail | null; onClose: () => void }

export function NoteDetailDrawer({ note, onClose }: NoteDetailDrawerProps) {
  const meta = note && [formatNoteDate(note.date), formatDuration(note.duration_seconds), note.participants.join('、'), note.tags.map((tag) => `#${tag}`).join(' ')].filter(Boolean).join(' ・ ')
  return <><aside className={`note-detail${note ? ' is-open' : ''}`} aria-hidden={note === null} aria-label="会議ノート詳細"><header className="note-detail-head"><h2>{note?.title}</h2><button className="note-detail-close" type="button" aria-label="詳細を閉じる" onClick={onClose}><X /></button></header><div className="note-detail-body"><p className="note-detail-meta">{meta}</p><article className="note-markdown">{note && <Markdown source={note.markdown} />}</article></div></aside><button className={`note-detail-backdrop${note ? ' is-open' : ''}`} type="button" aria-label="詳細を閉じる" onClick={onClose} /></>
}
