import { useEffect, useState } from 'react'
import { CircleAlert, FileText, LoaderCircle } from 'lucide-react'
import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import { AiPanels } from './components/AiPanels'
import { HomeView } from './components/HomeView'
import { MeetingHeader } from './components/MeetingHeader'
import { NewMeetingDrawer } from './components/NewMeetingDrawer'
import { PageHeader } from './components/PageHeader'
import { Sidebar, type AppPage } from './components/Sidebar'
import { TranscriptCard } from './components/TranscriptCard'
import { Card } from './components/ui/Card'
import { request } from './lib/api'
import type { Meeting } from './types/meeting'
import './App.css'

function AppLayout() {
  const [compactSidebar, setCompactSidebar] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const isHome = location.pathname === '/' || location.pathname === '/meetings/new'
  const page: AppPage = isHome ? 'home' : 'meeting'
  return <div className={`shell${compactSidebar ? ' compact' : ''}`}><Sidebar page={page} compact={compactSidebar} onToggle={() => setCompactSidebar((compact) => !compact)} onPageChange={(nextPage) => navigate(nextPage === 'home' ? '/' : '/meetings/new')} /><main className={isHome ? 'is-scrollable' : ''}><PageHeader title={isHome ? 'ホーム' : 'ミーティング'} /><div className="layout"><Outlet /></div></main></div>
}

function HomeRoute() {
  const navigate = useNavigate()
  const isNewMeeting = useLocation().pathname === '/meetings/new'
  return <><HomeView onStartMeeting={() => navigate('/meetings/new')} />{isNewMeeting && <NewMeetingDrawer onClose={() => navigate('/')} onCreated={(meeting) => navigate(`/meetings/${meeting.id}/live`)} />}</>
}

function LiveMeetingRoute() {
  const { meetingId = '' } = useParams()
  const [meeting, setMeeting] = useState<Meeting | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [stopping, setStopping] = useState(false)
  const isActive = meeting?.phase === 'recording' || meeting?.phase === 'transcribing' || meeting?.phase === 'summarizing'
  const canStop = meeting?.phase === 'recording' || meeting?.phase === 'transcribing'

  useEffect(() => { void request<Meeting>(`/meetings/${meetingId}`).then(setMeeting).catch((loadError: Error) => setError(loadError.message)) }, [meetingId])
  useEffect(() => {
    if (!isActive) return undefined
    const timer = window.setInterval(() => { void request<Meeting>(`/meetings/${meetingId}`).then(setMeeting).catch((pollError: Error) => setError(pollError.message)) }, 1000)
    return () => window.clearInterval(timer)
  }, [isActive, meetingId])

  async function stopMeeting() {
    setStopping(true); setError(null)
    try { setMeeting(await request<Meeting>('/meetings/current/stop', { method: 'POST' })) } catch (stopError) { setError(stopError instanceof Error ? stopError.message : '録音を停止できませんでした。') } finally { setStopping(false) }
  }

  if (!meeting && !error) return <div className="route-loading"><LoaderCircle className="spin" />会議を読み込んでいます…</div>
  if (!meeting) return <div className="route-error"><CircleAlert />{error}</div>
  return <><MeetingHeader meeting={meeting} canStop={Boolean(canStop)} isStopping={stopping} onStop={() => void stopMeeting()} />{error && <p className="form-error page-error"><CircleAlert />{error}</p>}<div className="meeting-grid"><TranscriptCard message={meeting.message} transcript={meeting.transcript} isMeetingActive={Boolean(isActive)} /><AiPanels meeting={meeting} /></div></>
}

function MeetingDetailRoute() {
  const { meetingId = '' } = useParams()
  return <Card className="meeting-detail-card"><FileText /><h2>会議詳細</h2><p>要約・タスク・Markdown本文を表示する会議詳細のルートです。</p><Link to={`/meetings/${meetingId}/live`}>リアルタイム表示を開く</Link></Card>
}

function App() {
  return <Routes><Route element={<AppLayout />}><Route path="/" element={<HomeRoute />} /><Route path="/meetings/new" element={<HomeRoute />} /><Route path="/meetings/:meetingId/live" element={<LiveMeetingRoute />} /><Route path="/meetings/:meetingId" element={<MeetingDetailRoute />} /><Route path="*" element={<Navigate to="/" replace />} /></Route></Routes>
}

export default App
