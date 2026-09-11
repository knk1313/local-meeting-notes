import { ChevronsUpDown, LoaderCircle, Maximize2, Search } from 'lucide-react'
import type { ReactNode } from 'react'
import { formatDuration, formatNoteDate } from '../lib/note'
import type { NoteSummary } from '../types/note'
import { TextInput } from './ui/TextInput'

type NotesTableProps = {
  notes: NoteSummary[]
  query: string
  isLoading: boolean
  onQueryChange: (query: string) => void
  onOpen: (note: NoteSummary) => void
  action?: ReactNode
}

export function NotesTable({ notes, query, isLoading, onQueryChange, onOpen, action }: NotesTableProps) {
  return <>
    <div className="notes-toolbar"><TextInput icon={Search} type="search" placeholder="会議名・参加者・タグで検索" aria-label="会議ノートを検索" value={query} onChange={(event) => onQueryChange(event.target.value)} />{action}</div>
    <div className="notes-list" role="table"><div className="note-table-head" role="row"><span>日付<ChevronsUpDown /></span><span>会議名<ChevronsUpDown /></span><span>要約</span><span>時間<ChevronsUpDown /></span><span /></div>
      {isLoading && <p className="notes-placeholder"><LoaderCircle className="spin" />会議ノートを読み込んでいます…</p>}
      {!isLoading && notes.length === 0 && <p className="notes-placeholder">{query ? '検索条件に一致する会議ノートはありません。' : '会議ノートはまだありません。録音を開始すると、ここに保存されます。'}</p>}
      {notes.map((note) => <div className="note-row" role="row" key={note.id}><span className="note-date">{formatNoteDate(note.date)}</span><span className="note-title">{note.title}</span><span className="note-excerpt">{note.excerpt}</span><span className="note-duration">{formatDuration(note.duration_seconds)}</span><span className="note-open"><button type="button" aria-label={`${note.title}を開く`} onClick={() => onOpen(note)}><Maximize2 />開く</button></span></div>)}
    </div>
  </>
}
