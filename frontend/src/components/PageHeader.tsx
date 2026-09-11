type PageHeaderProps = { title: string }

export function PageHeader({ title }: PageHeaderProps) {
  return <header className="topbar"><h1>{title}</h1></header>
}
