import { House, Menu, PanelLeftClose, PanelLeftOpen } from 'lucide-react'

export type AppPage = 'home' | 'meeting'

type SidebarProps = { page: AppPage; compact: boolean; onPageChange: (page: AppPage) => void; onToggle: () => void }

const items = [
  { page: 'home' as const, label: 'ホーム', icon: House },
]

export function Sidebar({ page, compact, onPageChange, onToggle }: SidebarProps) {
  return <aside className="sidebar">
    <button className="sidebar-toggle" type="button" aria-label="サイドバーを折りたたむ" onClick={onToggle}>{compact ? <PanelLeftOpen /> : <PanelLeftClose />}</button>
    <nav className="nav expanded-nav" aria-label="メインメニュー">{items.map(({ page: itemPage, label, icon: Icon }) => <button className={page === itemPage ? 'active' : ''} type="button" key={itemPage} onClick={() => onPageChange(itemPage)}><Icon className="icon" /><span>{label}</span></button>)}</nav>
    <nav className="rail-nav" aria-label="コンパクトメニュー"><button className="rail-button" type="button" title="サイドバーを開く" onClick={onToggle}><Menu className="rail-icon" /><span>サイドバー</span></button>{items.map(({ page: itemPage, label, icon: Icon }) => <button className={`rail-button${page === itemPage ? ' active' : ''}`} type="button" title={label} key={itemPage} onClick={() => onPageChange(itemPage)}><Icon className="rail-icon" /><span>{label}</span></button>)}</nav>
  </aside>
}
