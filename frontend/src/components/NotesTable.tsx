import { ChevronsUpDown, Maximize2, Search } from 'lucide-react'
import type { ReactNode } from 'react'
import type { NoteRow } from '../data/sampleNotes'
import { TextInput } from './ui/TextInput'

type NotesTableProps = { notes: NoteRow[]; onOpen: (note: NoteRow) => void; action?: ReactNode }

export function NotesTable({ notes, onOpen, action }: NotesTableProps) {
  return <>
    <div className="notes-toolbar"><TextInput icon={Search} type="search" placeholder="会議名・参加者・タグで検索" aria-label="会議ノートを検索" />{action}</div>
    <div className="notes-list" role="table"><div className="note-table-head" role="row"><span>日付<ChevronsUpDown /></span><span>会議名<ChevronsUpDown /></span><span>要約</span><span>時間<ChevronsUpDown /></span><span /></div>{notes.map((note) => <div className="note-row" role="row" key={`${note.date}-${note.title}`}><span className="note-date">{note.date}</span><span className="note-title">{note.title}</span><span className="note-excerpt">{note.excerpt}</span><span className="note-duration">{note.duration}</span><span className="note-open"><button type="button" aria-label={`${note.title}を開く`} onClick={() => onOpen(note)}><Maximize2 />開く</button></span></div>)}</div>
  </>
}
