import { notFound } from 'next/navigation'

export const metadata = { title: 'Not found', description: 'This page isn’t in Actron’s memory.' }

/** Unknown /app/* paths render the 404 inside the shell. */
export default function Missing() {
  notFound()
}
