export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options?.headers },
    })
  } catch {
    throw new Error('APIへ接続できませんでした。バックエンドが起動しているか確認してください。')
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null
    throw new Error(typeof body?.detail === 'string' ? body.detail : `通信に失敗しました。（HTTP ${response.status}）`)
  }

  try {
    return (await response.json()) as T
  } catch {
    throw new Error('APIの応答を読み取れませんでした。')
  }
}
