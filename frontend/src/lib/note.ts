export function formatNoteDate(date: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date.replaceAll('-', '/') : date
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const minutes = Math.max(1, Math.round(seconds / 60))
  if (minutes < 60) return `約${minutes}分`
  return `約${Math.floor(minutes / 60)}時間${String(minutes % 60).padStart(2, '0')}分`
}
