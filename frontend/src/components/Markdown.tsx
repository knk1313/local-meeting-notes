import { Fragment, type ReactNode } from 'react'

const INLINE_PATTERN = /(\*\*[^*]+\*\*|`[^`]+`)/
const HEADING_PATTERN = /^(#{1,6})\s+(.*)$/
const TASK_PATTERN = /^[-*]\s+\[([ xX])\]\s*(.*)$/
const BULLET_PATTERN = /^[-*]\s+(.*)$/
const HEADING_TAGS = ['h2', 'h3', 'h4', 'h5', 'h6', 'h6'] as const

type ListItem = { text: string; checked: boolean | null }

/** Markdown会議ノートの本文を、そのままの構造でHTMLへ変換して表示する。 */
export function Markdown({ source }: { source: string }) {
  const lines = source.split('\n')
  const blocks: ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index].trim()
    if (!line) { index += 1; continue }

    const heading = HEADING_PATTERN.exec(line)
    if (heading) {
      const Tag = HEADING_TAGS[heading[1].length - 1]
      blocks.push(<Tag key={index}>{renderInline(heading[2], index)}</Tag>)
      index += 1
      continue
    }

    const start = index
    if (toListItem(line)) {
      const items: ListItem[] = []
      for (let item = toListItem(lines[index]?.trim() ?? ''); item; item = toListItem(lines[index]?.trim() ?? '')) { items.push(item); index += 1 }
      const isTaskList = items.some((item) => item.checked !== null)
      blocks.push(<ul className={isTaskList ? 'task-list' : undefined} key={start}>{items.map((item, itemIndex) => <li key={itemIndex}>{item.checked !== null && <input type="checkbox" checked={item.checked} disabled readOnly />}{renderInline(item.text, itemIndex)}</li>)}</ul>)
      continue
    }

    const paragraph: string[] = []
    for (let text = lines[index]?.trim() ?? ''; text && !HEADING_PATTERN.test(text) && !toListItem(text); text = lines[index]?.trim() ?? '') { paragraph.push(text); index += 1 }
    blocks.push(<p key={start}>{paragraph.map((text, textIndex) => <Fragment key={textIndex}>{textIndex > 0 && <br />}{renderInline(text, textIndex)}</Fragment>)}</p>)
  }

  return <>{blocks}</>
}

function toListItem(line: string): ListItem | null {
  const task = TASK_PATTERN.exec(line)
  if (task) return { text: task[2], checked: task[1].toLowerCase() === 'x' }
  const bullet = BULLET_PATTERN.exec(line)
  return bullet ? { text: bullet[1], checked: null } : null
}

function renderInline(text: string, key: number): ReactNode {
  return <Fragment key={key}>{text.split(INLINE_PATTERN).filter(Boolean).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
    return <Fragment key={index}>{part}</Fragment>
  })}</Fragment>
}
