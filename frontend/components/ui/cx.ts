import { clsx, type ClassValue } from 'clsx'

export function cx(...values: ClassValue[]): string {
  return clsx(values)
}
