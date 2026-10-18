// Writes lib/ontology-snapshot.json from ../ontology/*.json (the frozen ontology files): node types grouped by
// source and type-level relationships with node groups expanded. Real data, used by the landing page's graph
// model, the 3D hero fallback and the Connect canvas before any source is connected.
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const ontologyDir = join(root, '..', 'ontology')
const out = join(root, 'lib', 'ontology-snapshot.json')

if (!existsSync(ontologyDir)) {
  if (existsSync(out)) {
    console.log('ontology folder not found; keeping the existing snapshot')
    process.exit(0)
  }
  writeFileSync(out, JSON.stringify({ types: [], relationships: [], generatedFrom: null }, null, 2))
  process.exit(0)
}

const files = ['code', 'github', 'slack', 'linear', 'core']
const types = []
const rels = []
let groups = {}
for (const file of files) {
  const doc = JSON.parse(readFileSync(join(ontologyDir, `${file}.json`), 'utf8'))
  if (doc.node_groups) groups = { ...groups, ...doc.node_groups }
  for (const node of doc.nodes ?? []) {
    types.push({ type: node.name, group: file, description: String(node.description ?? '').split('. ')[0] })
  }
  for (const rel of doc.relationships ?? []) {
    rels.push({ name: rel.name, from: rel.from_node, to: rel.to_node, group: file })
  }
}

const known = new Set(types.map((t) => t.type))
const expand = (name) => (groups[name] ? groups[name] : [name])
const relationships = []
const seen = new Set()
for (const rel of rels) {
  for (const from of expand(rel.from)) {
    for (const to of expand(rel.to)) {
      if (!known.has(from) || !known.has(to)) continue
      const key = `${rel.name}|${from}|${to}`
      if (seen.has(key)) continue
      seen.add(key)
      relationships.push({ name: rel.name, from, to, group: rel.group })
    }
  }
}

writeFileSync(
  out,
  JSON.stringify(
    {
      generatedFrom: 'ontology/*.json',
      typeCount: types.length,
      relationshipCount: relationships.length,
      types,
      relationships,
    },
    null,
    1,
  ),
)
console.log(`ontology snapshot: ${types.length} node types, ${relationships.length} relationships`)
