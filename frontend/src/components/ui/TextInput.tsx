import type { InputHTMLAttributes, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

type TextInputProps = InputHTMLAttributes<HTMLInputElement> & {
  label?: ReactNode
  hint?: ReactNode
  icon?: LucideIcon
}

export function TextInput({ label, hint, icon: Icon, className = '', type = 'text', ...props }: TextInputProps) {
  return <label className="text-input-field">
    {label && <span className="text-input-label">{label}</span>}
    {hint && <span className="text-input-hint">{hint}</span>}
    <span className={`text-input-shell${Icon ? ' has-icon' : ''}`}>
      {Icon && <Icon aria-hidden="true" />}
      <input className={className} type={type} {...props} />
    </span>
  </label>
}
