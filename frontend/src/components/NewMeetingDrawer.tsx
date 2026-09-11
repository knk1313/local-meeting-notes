import { CircleAlert, LoaderCircle, Mic, X } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { request } from '../lib/api'
import type { Meeting } from '../types/meeting'
import { Button } from './ui/Button'
import { TextInput } from './ui/TextInput'

type NewMeetingDrawerProps = { onClose: () => void; onCreated: (meeting: Meeting) => void }

export function NewMeetingDrawer({ onClose, onCreated }: NewMeetingDrawerProps) {
  const [title, setTitle] = useState('')
  const [participants, setParticipants] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isStarting, setIsStarting] = useState(false)
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setIsOpen(true))
    return () => window.cancelAnimationFrame(frame)
  }, [])

  function closeDrawer() {
    setIsOpen(false)
    window.setTimeout(onClose, 420)
  }

  async function startMeeting(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!title.trim()) { setError('会議名を入力してください。'); return }
    setIsStarting(true); setError(null)
    try {
      const meeting = await request<Meeting>('/meetings', { method: 'POST', body: JSON.stringify({ title: title.trim(), participants: participants.split(/[、,]/).map((name) => name.trim()).filter(Boolean) }) })
      onCreated(meeting)
    } catch (startError) { setError(startError instanceof Error ? startError.message : '会議を開始できませんでした。') } finally { setIsStarting(false) }
  }

  return <><aside className={`note-detail new-meeting-drawer${isOpen ? ' is-open' : ''}`} aria-label="新しいミーティング"><header className="note-detail-head"><h2>新しいミーティング</h2><button className="note-detail-close" type="button" aria-label="閉じる" onClick={closeDrawer}><X /></button></header><form className="note-detail-body new-meeting-form" onSubmit={startMeeting}><TextInput label="会議名" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例：プロジェクト定例" autoFocus /><TextInput label="参加者" hint="任意・カンマ区切り" value={participants} onChange={(event) => setParticipants(event.target.value)} placeholder="例：田中, 鈴木" />{error && <p className="form-error"><CircleAlert />{error}</p>}<Button className="drawer-start-button" type="submit" disabled={isStarting}>{isStarting ? <LoaderCircle className="spin" /> : <Mic />}録音を開始</Button></form></aside><button className={`note-detail-backdrop${isOpen ? ' is-open' : ''}`} type="button" aria-label="新しいミーティングを閉じる" onClick={closeDrawer} /></>
}
