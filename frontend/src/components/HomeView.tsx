import { useEffect, useState } from 'react'
import { CircleAlert, Plus } from 'lucide-react'
import { NoteDetailDrawer } from './NoteDetailDrawer'
import { NotesTable } from './NotesTable'
import { request } from '../lib/api'
import type { NoteDetail, NoteSummary } from '../types/note'

type HomeViewProps = { onStartMeeting: () => void }

export function HomeView({ onStartMeeting }: HomeViewProps) {
  const [notes, setNotes] = useState<NoteSummary[] | null>(null)
  const [selectedNote, setSelectedNote] = useState<NoteDetail | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { void request<NoteSummary[]>('/notes').then(setNotes).catch((loadError: Error) => { setNotes([]); setError(loadError.message) }) }, [])

  async function openNote(note: NoteSummary) {
    setError(null)
    try { setSelectedNote(await request<NoteDetail>(`/notes/${encodeURIComponent(note.id)}`)) } catch (openError) { setError(openError instanceof Error ? openError.message : '会議ノートを読み込めませんでした。') }
  }

  const keyword = query.trim().toLowerCase()
  const visibleNotes = (notes ?? []).filter((note) => !keyword || [note.title, note.excerpt, note.date, ...note.participants, ...note.tags].some((value) => value.toLowerCase().includes(keyword)))
  const startAction = <button type="button" className="new-meeting-button" onClick={onStartMeeting}><Plus />新しいミーティングを開始</button>
  return <section className="notes-view">{error && <p className="form-error page-error"><CircleAlert />{error}</p>}<NotesTable notes={visibleNotes} query={query} isLoading={notes === null} onQueryChange={setQuery} onOpen={(note) => void openNote(note)} action={startAction} /><NoteDetailDrawer note={selectedNote} onClose={() => setSelectedNote(null)} /></section>
}
