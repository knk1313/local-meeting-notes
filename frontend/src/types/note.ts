export type NoteSummary = {
  id: string
  title: string
  date: string
  participants: string[]
  tags: string[]
  excerpt: string
  duration_seconds: number | null
}

export type NoteDetail = NoteSummary & { markdown: string }
