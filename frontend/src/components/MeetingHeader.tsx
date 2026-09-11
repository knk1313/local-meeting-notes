import { LoaderCircle, MicOff, Users } from 'lucide-react'
import { Button } from './ui/Button'
import type { Meeting, MeetingPhase } from '../types/meeting'

const phaseLabel: Record<MeetingPhase, string> = {
  recording: '録音中', transcribing: '文字起こし中', summarizing: '要約を生成中', completed: '完了', failed: 'エラー',
}

type MeetingHeaderProps = { meeting: Meeting; canStop: boolean; isStopping: boolean; onStop: () => void }

export function MeetingHeader({ meeting, canStop, isStopping, onStop }: MeetingHeaderProps) {
  return <header className="meeting-header">
    <div><p className="eyebrow">会議</p><h1>{meeting.title}</h1>{meeting.participants.length > 0 && <p className="participants"><Users />{meeting.participants.join('、')}</p>}</div>
    <div className="meeting-actions"><span className={`status ${meeting.phase}`}><i />{phaseLabel[meeting.phase]}</span>{canStop && <Button className="stop-button" variant="secondary" type="button" onClick={onStop} disabled={isStopping}>{isStopping ? <LoaderCircle className="spin" /> : <MicOff />}録音を停止</Button>}</div>
  </header>
}
