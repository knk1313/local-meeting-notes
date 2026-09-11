import { CheckCircle2, FileText, Sparkles } from 'lucide-react'
import { Card } from './ui/Card'
import type { Meeting } from '../types/meeting'

type AiPanelsProps = { meeting: Meeting }

export function AiPanels({ meeting }: AiPanelsProps) {
  const isComplete = meeting.phase === 'completed'
  return <aside className="side-column">
    <Card className="summary-card"><header className="card-heading"><span className="card-icon"><Sparkles /></span><div><h2>AI要約</h2><p>{isComplete ? '会議ノートを生成しました' : '録音停止後に要約を生成します'}</p></div></header><div className="summary-content">{isComplete ? <><CheckCircle2 /><p>会議ノートを保存しました。</p>{meeting.note_path && <code>{meeting.note_path}</code>}</> : <><Sparkles /><p>録音を停止すると、文字起こし全文から要約とタスクを抽出します。</p></>}</div></Card>
    <Card className="assistant-card"><header className="card-heading"><span className="card-icon"><Sparkles /></span><div><h2>AIアシスタント</h2><p>会議の完了後に利用できます</p></div></header><div className="assistant-empty"><FileText /><p>会議中の文字起こしと、生成されたノートをもとに質問できるようになります。</p></div></Card>
  </aside>
}
