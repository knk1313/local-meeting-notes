export type MeetingPhase = 'recording' | 'transcribing' | 'summarizing' | 'completed' | 'failed'

export type TranscriptSegment = {
  speaker: string | null
  start: number | null
  end: number | null
  text: string
}

export type Meeting = {
  id: string
  title: string
  participants: string[]
  phase: MeetingPhase
  message: string
  transcript: TranscriptSegment[]
  note_path: string | null
  error: string | null
}
