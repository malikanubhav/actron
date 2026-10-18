/**
 * Plain names for ontology node types, for people rather than the graph: "GithubPullRequest" → "Pull requests",
 * "CodeFunction" → "Functions", "SlackMessage" → "Messages".
 */
const PREFIXES = ['Github', 'Git', 'Code', 'Slack', 'Linear']

const SPECIAL: Record<string, string> = {
  GithubPullRequest: 'Pull requests',
  GithubPullRequestFile: 'PR files',
  GithubReviewComment: 'Review comments',
  GithubIssueComment: 'Issue comments',
  GitFileChange: 'File changes',
  CodeChunk: 'Code chunks',
  CodeFile: 'Files',
  CodeRepository: 'Repositories',
  GithubRepository: 'Repositories',
}

function singular(text: string): string {
  if (text.endsWith('ies')) return `${text.slice(0, -3)}y`
  if (/(ches|shes|xes|sses)$/.test(text)) return text.slice(0, -2)
  return text.replace(/s$/, '')
}

function plural(word: string): string {
  if (/(s|x|ch|sh)$/.test(word)) return `${word}es`
  if (/[^aeiou]y$/.test(word)) return `${word.slice(0, -1)}ies`
  return `${word}s`
}

export function typeName(type: string, count = 2): string {
  if (SPECIAL[type]) return count === 1 ? singular(SPECIAL[type]) : SPECIAL[type]
  let core = type
  for (const p of PREFIXES) {
    if (core.startsWith(p) && core.length > p.length && /[A-Z]/.test(core[p.length] ?? '')) {
      core = core.slice(p.length)
      break
    }
  }
  const words = core.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase().split(' ')
  const last = words.length - 1
  if (count !== 1) words[last] = plural(words[last] as string)
  const text = words.join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}
