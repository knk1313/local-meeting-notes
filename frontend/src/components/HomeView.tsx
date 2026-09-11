import { useState } from 'react'
import { Plus } from 'lucide-react'
import { NoteDetailDrawer } from './NoteDetailDrawer'
import { NotesTable } from './NotesTable'
import { sampleNotes, type NoteRow } from '../data/sampleNotes'

type HomeViewProps = { onStartMeeting: () => void }

export function HomeView({ onStartMeeting }: HomeViewProps) {
  const [selectedNote, setSelectedNote] = useState<NoteRow | null>(null)
  const startAction = <button type="button" className="new-meeting-button" onClick={onStartMeeting}><Plus />新しいミーティングを開始</button>
  return <section className="notes-view"><NotesTable notes={sampleNotes} onOpen={setSelectedNote} action={startAction} /><NoteDetailDrawer note={selectedNote} onClose={() => setSelectedNote(null)} /></section>
}
