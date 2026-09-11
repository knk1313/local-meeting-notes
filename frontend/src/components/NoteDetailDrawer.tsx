import { X } from 'lucide-react'
import type { NoteRow } from '../data/sampleNotes'

type NoteDetailDrawerProps = { note: NoteRow | null; onClose: () => void }

export function NoteDetailDrawer({ note, onClose }: NoteDetailDrawerProps) {
  return <><aside className={`note-detail${note ? ' is-open' : ''}`} aria-hidden={note === null} aria-label="会議ノート詳細"><header className="note-detail-head"><h2>{note?.title}</h2><button className="note-detail-close" type="button" aria-label="詳細を閉じる" onClick={onClose}><X /></button></header><div className="note-detail-body"><p className="note-detail-meta">{note && `${note.date} ・ ${note.duration}`}</p><article className="note-markdown"><h3>要約</h3><ul><li>{note?.excerpt}</li><li>会議の論点と次の進め方を整理した。</li></ul><h3>決定事項</h3><ul><li>会議で確認した内容をノートへ残す。</li><li>次回までの担当タスクを明確にする。</li></ul><h3>タスク</h3><ul><li>関連資料と処理フローを整理する。</li><li>次回の会議までに進捗を共有する。</li></ul></article></div></aside><button className={`note-detail-backdrop${note ? ' is-open' : ''}`} type="button" aria-label="詳細を閉じる" onClick={onClose} /></>
}
