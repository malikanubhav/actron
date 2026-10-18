'use client'
import { Canvas, useFrame } from '@react-three/fiber'
import { Billboard } from '@react-three/drei'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { createVisibilityController } from './mode'
import { layoutHeroGraph, loadHeroGraph } from './data'
import type { HeroGraph, HeroGroup } from './layout3d'
import { heroFrame, type HeroStage } from './timeline'

/** Orbit speed in radians per second (a full turn in about two minutes; it was five). */
const ORBIT_SPEED = 0.055
/** One breath: the whole graph swells and settles by 2% over this long. */
const BREATH_MS = 4_500
/** How far the query rings travel from the request, in scene units. */
const RING_REACH = 7.5

declare global {
  interface Window {
    __actronHeroFrames?: number
  }
}

function readColour(token: string, fallback: string): THREE.Color {
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim()
  try {
    return new THREE.Color(value || fallback)
  } catch {
    return new THREE.Color(fallback)
  }
}

const GROUP_TOKENS: Record<HeroGroup, string> = {
  code: '--node-code',
  github: '--node-github',
  slack: '--node-slack',
  linear: '--node-linear',
  core: '--node-core',
}

/** A text label as a camera-facing sprite: a dark plate with the text on it, drawn once into a texture. */
function makeLabel(text: string): { texture: THREE.CanvasTexture; width: number; height: number } {
  const scale = 2
  const family = getComputedStyle(document.body).fontFamily
  const font = `500 ${13 * scale}px ${family}`
  const probe = document.createElement('canvas').getContext('2d') as CanvasRenderingContext2D
  probe.font = font
  const w = Math.ceil(probe.measureText(text).width) + 14 * scale
  const h = 24 * scale
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d') as CanvasRenderingContext2D
  const css = getComputedStyle(document.documentElement)
  ctx.fillStyle = css.getPropertyValue('--ink-0').trim() || '#0a0a0a'
  ctx.globalAlpha = 0.85
  ctx.beginPath()
  ctx.roundRect(0, 0, w, h, 4 * scale)
  ctx.fill()
  ctx.globalAlpha = 1
  ctx.font = font
  ctx.fillStyle = css.getPropertyValue('--text-2').trim() || '#b4b4b4'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, w / 2, h / 2 + scale)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  // Scene units: the label is 0.62 high, so it reads at about the size of the page's 12–13 px text.
  const height = 0.62
  return { texture, width: (w / h) * height, height }
}

function LabelSprite({ text, position, spriteRef, opacity = 1 }: { text: string; position: [number, number, number]; spriteRef?: React.Ref<THREE.Sprite>; opacity?: number }) {
  const label = useMemo(() => makeLabel(text), [text])
  useEffect(() => () => label.texture.dispose(), [label])
  return (
    <sprite ref={spriteRef} position={position} scale={[label.width, label.height, 1]} renderOrder={10}>
      <spriteMaterial map={label.texture} transparent opacity={opacity} depthTest={false} toneMapped={false} />
    </sprite>
  )
}

function Scene({ graph, positions, onStage }: { graph: HeroGraph; positions: Float32Array; onStage?: (stage: HeroStage) => void }) {
  const group = useRef<THREE.Group>(null)
  const nodesRef = useRef<THREE.InstancedMesh>(null)
  const linkMaterial = useRef<THREE.LineBasicMaterial>(null)
  const tubeRef = useRef<THREE.Mesh>(null)
  const ringRefs = useRef<(THREE.Mesh | null)[]>([])
  const endMark = useRef<THREE.Mesh>(null)
  const endPulse = useRef<THREE.Mesh>(null)
  const functionLabel = useRef<THREE.Sprite>(null)
  const lastStage = useRef<HeroStage | null>(null)
  const colours = useMemo(() => {
    const out = {} as Record<HeroGroup, THREE.Color>
    // Colours come from tokens.css at runtime (the same --node-* tokens as the 2D canvas); the fallbacks only apply
    // when a token is missing.
    for (const g of Object.keys(GROUP_TOKENS) as HeroGroup[]) out[g] = readColour(GROUP_TOKENS[g], 'grey')
    return { ...out, accent: readColour('--accent', 'yellow'), line: readColour('--graph-link', 'grey') }
  }, [])
  const index = useMemo(() => new Map(graph.nodes.map((n, i) => [n.id, i])), [graph])
  const onPath = useMemo(() => new Set(graph.path), [graph])

  const linkGeometry = useMemo(() => {
    const arr = new Float32Array(graph.links.length * 6)
    let k = 0
    for (const l of graph.links) {
      const a = index.get(l.from)
      const b = index.get(l.to)
      if (a === undefined || b === undefined) continue
      for (const i of [a, b]) {
        arr[k++] = positions[i * 3] ?? 0
        arr[k++] = positions[i * 3 + 1] ?? 0
        arr[k++] = positions[i * 3 + 2] ?? 0
      }
    }
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(arr.subarray(0, k), 3))
    return geo
  }, [graph, index, positions])

  const tubeGeometry = useMemo(() => {
    const pts = graph.path
      .map((id) => index.get(id))
      .filter((i): i is number => i !== undefined)
      .map((i) => new THREE.Vector3(positions[i * 3] ?? 0, positions[i * 3 + 1] ?? 0, positions[i * 3 + 2] ?? 0))
    if (pts.length < 2) return null
    // Straight hops (a polyline as a thin tube): a plain accent line, no glow.
    const curve = new THREE.CurvePath<THREE.Vector3>()
    for (let i = 0; i < pts.length - 1; i++) curve.add(new THREE.LineCurve3(pts[i] as THREE.Vector3, pts[i + 1] as THREE.Vector3))
    return new THREE.TubeGeometry(curve, pts.length * 8, 0.035, 6, false)
  }, [graph, index, positions])

  // The path's two ends: the request it starts from and the function it reaches.
  const ends = useMemo(() => {
    const at = (id: string | undefined) => {
      const i = id === undefined ? undefined : index.get(id)
      return i === undefined ? null : new THREE.Vector3(positions[i * 3] ?? 0, positions[i * 3 + 1] ?? 0, positions[i * 3 + 2] ?? 0)
    }
    return graph.path.length > 1 ? { start: at(graph.path[0]), end: at(graph.path[graph.path.length - 1]) } : null
  }, [graph, index, positions])

  useLayoutEffect(() => {
    const mesh = nodesRef.current
    if (!mesh) return
    const m = new THREE.Matrix4()
    const q = new THREE.Quaternion()
    const first = graph.path[0]
    const last = graph.path[graph.path.length - 1]
    graph.nodes.forEach((node, i) => {
      // The two ends are drawn as their own marks (square and ring); hops between keep their source colour, larger.
      const end = graph.path.length > 1 && (node.id === first || node.id === last)
      const s = end ? 0 : onPath.has(node.id) ? 1.8 : 1
      m.compose(
        new THREE.Vector3(positions[i * 3] ?? 0, positions[i * 3 + 1] ?? 0, positions[i * 3 + 2] ?? 0),
        q,
        new THREE.Vector3(s, s, s),
      )
      mesh.setMatrixAt(i, m)
      mesh.setColorAt(i, colours[node.group])
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }, [graph, positions, colours, onPath])

  const nodeSize = graph.nodes.length > 600 ? 0.07 : 0.16
  const baseLinkOpacity = graph.nodes.length > 600 ? 0.08 : 0.22

  useFrame((state, delta) => {
    window.__actronHeroFrames = (window.__actronHeroFrames ?? 0) + 1
    // The scene clock stops while the hero is off-screen, so the story pauses with the rendering.
    const ms = state.clock.elapsedTime * 1000
    const frame = heroFrame(ms)
    const breath = Math.sin((ms / BREATH_MS) * Math.PI * 2)
    if (group.current) {
      group.current.rotation.y += ORBIT_SPEED * delta
      group.current.scale.setScalar(1 + 0.02 * breath)
    }
    if (linkMaterial.current) linkMaterial.current.opacity = baseLinkOpacity * (1 + 0.25 * breath)

    // The evidence path draws itself hop by hop, holds, then fades before the loop starts again.
    const tube = tubeRef.current
    if (tube && tubeGeometry?.index) {
      const drawn = Math.floor((tubeGeometry.index.count * frame.pathProgress) / 3) * 3
      tubeGeometry.setDrawRange(0, drawn)
      ;(tube.material as THREE.MeshBasicMaterial).opacity = frame.pathOpacity
    }
    const reached = frame.pathProgress >= 0.99
    if (endMark.current) {
      endMark.current.visible = reached
      ;(endMark.current.material as THREE.MeshBasicMaterial).opacity = frame.pathOpacity
    }
    if (functionLabel.current) (functionLabel.current.material as THREE.SpriteMaterial).opacity = reached ? frame.pathOpacity : 0
    if (endPulse.current) {
      endPulse.current.visible = frame.endPulse !== null
      if (frame.endPulse !== null) {
        endPulse.current.scale.setScalar(nodeSize * 2.4 * (1 + frame.endPulse * 2.5))
        ;(endPulse.current.material as THREE.MeshBasicMaterial).opacity = 1 - frame.endPulse
      }
    }

    // Query rings leave the request while Actron searches: the search spreading through the graph.
    for (let i = 0; i < ringRefs.current.length; i++) {
      const ring = ringRefs.current[i]
      if (!ring) continue
      const phase = frame.rings[i]
      ring.visible = phase !== undefined
      if (phase !== undefined) {
        ring.scale.setScalar(nodeSize * 3 + phase * RING_REACH)
        ;(ring.material as THREE.MeshBasicMaterial).opacity = 0.55 * (1 - phase) ** 1.5
      }
    }

    if (lastStage.current !== frame.stage) {
      lastStage.current = frame.stage
      onStage?.(frame.stage)
    }
  })

  return (
    <group ref={group} rotation={[0.3, 0, 0]}>
      <lineSegments geometry={linkGeometry}>
        <lineBasicMaterial ref={linkMaterial} color={colours.line} transparent opacity={baseLinkOpacity} depthWrite={false} />
      </lineSegments>
      <instancedMesh ref={nodesRef} args={[undefined, undefined, graph.nodes.length]}>
        <icosahedronGeometry args={[nodeSize, 1]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
      {tubeGeometry ? (
        <mesh ref={tubeRef} geometry={tubeGeometry}>
          <meshBasicMaterial color={colours.accent} transparent toneMapped={false} />
        </mesh>
      ) : null}
      {ends?.start ? (
        <>
          {/* Query rings: the search spreading out of the request through the graph. */}
          {[0, 1, 2].map((i) => (
            <Billboard key={i} position={ends.start as THREE.Vector3}>
              <mesh
                ref={(m) => {
                  ringRefs.current[i] = m
                }}
                visible={false}
              >
                <ringGeometry args={[0.97, 1, 64]} />
                <meshBasicMaterial color={colours.core} transparent opacity={0} toneMapped={false} depthWrite={false} side={THREE.DoubleSide} />
              </mesh>
            </Billboard>
          ))}
          <Billboard position={ends.start}>
            <mesh>
              <planeGeometry args={[nodeSize * 4.2, nodeSize * 4.2]} />
              <meshBasicMaterial color={colours.core} toneMapped={false} />
            </mesh>
          </Billboard>
          <LabelSprite text="Request" position={[ends.start.x, ends.start.y - nodeSize * 4.6, ends.start.z]} />
        </>
      ) : null}
      {ends?.end ? (
        <Billboard position={ends.end}>
          <mesh ref={endMark} visible={false}>
            <ringGeometry args={[nodeSize * 1.6, nodeSize * 2.4, 32]} />
            <meshBasicMaterial color={colours.accent} transparent toneMapped={false} side={THREE.DoubleSide} />
          </mesh>
          <mesh ref={endPulse} visible={false}>
            <ringGeometry args={[0.9, 1, 48]} />
            <meshBasicMaterial color={colours.accent} transparent toneMapped={false} depthWrite={false} side={THREE.DoubleSide} />
          </mesh>
        </Billboard>
      ) : null}
      {ends?.end ? (
        <LabelSprite text="Function" position={[ends.end.x, ends.end.y - nodeSize * 4.6, ends.end.z]} spriteRef={functionLabel} opacity={0} />
      ) : null}
    </group>
  )
}

/** The hero's 3D memory graph: real sample (or the ontology), slow orbit, paused off-screen or in hidden tabs. */
export default function HeroScene({ onUnavailable, onStage }: { onUnavailable?: () => void; onStage?: (stage: HeroStage) => void }) {
  const wrap = useRef<HTMLDivElement>(null)
  const [data, setData] = useState<{ graph: HeroGraph; positions: Float32Array } | null>(null)
  const [active, setActive] = useState(true)

  useEffect(() => {
    let cancelled = false
    loadHeroGraph()
      .then(async (graph) => ({ graph, positions: await layoutHeroGraph(graph) }))
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch(() => onUnavailable?.())
    return () => {
      cancelled = true
    }
  }, [onUnavailable])

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const controller = createVisibilityController(setActive)
    const io = new IntersectionObserver(([entry]) => controller.setIntersecting(Boolean(entry?.isIntersecting)))
    io.observe(el)
    const onVisibility = () => controller.setDocumentHidden(document.visibilityState === 'hidden')
    document.addEventListener('visibilitychange', onVisibility)
    onVisibility()
    return () => {
      io.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  return (
    <div ref={wrap} className="fade-in absolute inset-0" data-testid="hero-scene" data-active={active ? 'true' : 'false'}>
      {data ? (
        <Canvas
          frameloop={active ? 'always' : 'never'}
          dpr={[1, 1.75]}
          camera={{ position: [0, 0, 20], fov: 45 }}
          gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
          aria-label={`Graph of ${data.graph.nodes.length} ontology node types coloured by source, with one evidence path highlighted`}
          onCreated={({ gl }) => {
            gl.domElement.addEventListener('webglcontextlost', () => onUnavailable?.())
          }}
        >
          <Scene graph={data.graph} positions={data.positions} onStage={onStage} />
        </Canvas>
      ) : null}
    </div>
  )
}
