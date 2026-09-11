import { CircleAlert, LoaderCircle, Mic } from 'lucide-react'
import type { FormEvent } from 'react'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { TextInput } from './ui/TextInput'

type MeetingStartFormProps = {
  title: string
  participants: string
  error: string | null
  isStarting: boolean
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onTitleChange: (value: string) => void
  onParticipantsChange: (value: string) => void
}

export function MeetingStartForm({ title, participants, error, isStarting, onSubmit, onTitleChange, onParticipantsChange }: MeetingStartFormProps) {
  return <section className="start-view"><Card className="start-card">
    <span className="hero-icon"><Mic /></span><p className="eyebrow">準リアルタイム文字起こし</p><h1>会議をはじめましょう</h1><p className="intro">会議名と参加者を入力して録音を開始すると、文字起こしがここに順次表示されます。</p>
    <form className="meeting-form" onSubmit={onSubmit}>
      <TextInput label="会議名" value={title} onChange={(event) => onTitleChange(event.target.value)} placeholder="例：プロジェクト定例" autoFocus />
      <TextInput label="参加者" hint="任意・カンマ区切り" value={participants} onChange={(event) => onParticipantsChange(event.target.value)} placeholder="例：田中, 鈴木" />
      {error && <p className="form-error"><CircleAlert />{error}</p>}
      <Button className="primary-button" disabled={isStarting} type="submit">{isStarting ? <LoaderCircle className="spin" /> : <Mic />}録音を開始</Button>
    </form>
  </Card></section>
}
