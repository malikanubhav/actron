/** When the hero runs in 3D and when it shows the static image instead (spec C, C6; C-AC-28, C-AC-29). */

export interface HeroEnvironment {
  reducedMotion: boolean
  hardwareConcurrency: number | undefined
  saveData: boolean
  webgl: boolean
  /** Phones and small tablets get the static image: the scene costs seconds of main-thread time there. */
  smallScreen?: boolean
  /** WebGL drawn on the CPU (SwiftShader, llvmpipe): the orbit would block the main thread for seconds. */
  softwareGL?: boolean
}

export type HeroMode = '3d' | 'fallback'

export function heroMode(env: HeroEnvironment): HeroMode {
  if (env.reducedMotion) return 'fallback'
  if (env.saveData) return 'fallback'
  if (env.smallScreen) return 'fallback'
  if (env.softwareGL) return 'fallback'
  if (!env.webgl) return 'fallback'
  if (typeof env.hardwareConcurrency === 'number' && env.hardwareConcurrency <= 4) return 'fallback'
  return '3d'
}

/** True when the browser renders WebGL in software, judged from the unmasked renderer string. */
export function isSoftwareRenderer(renderer: string | null | undefined): boolean {
  if (!renderer) return false
  return /swiftshader|llvmpipe|software|softpipe|basic render/i.test(renderer)
}

export function webglRenderer(doc: Document = document): string | null {
  try {
    const gl = (doc.createElement('canvas').getContext('webgl2') ?? doc.createElement('canvas').getContext('webgl')) as WebGLRenderingContext | null
    if (!gl) return null
    const info = gl.getExtension('WEBGL_debug_renderer_info')
    return info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : String(gl.getParameter(gl.RENDERER))
  } catch {
    return null
  }
}

export function hasWebGL(doc: Document = document): boolean {
  try {
    const canvas = doc.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}

export function readEnvironment(): HeroEnvironment {
  const nav = navigator as Navigator & { connection?: { saveData?: boolean } }
  return {
    reducedMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
    hardwareConcurrency: nav.hardwareConcurrency,
    saveData: nav.connection?.saveData === true,
    webgl: hasWebGL(),
    smallScreen: window.matchMedia?.('(max-width: 767px)').matches === true,
    // Tests that exercise the 3D scene in headless browsers (software WebGL) opt in explicitly.
    softwareGL: (window as Window & { __actronHeroForce3d?: boolean }).__actronHeroForce3d ? false : isSoftwareRenderer(webglRenderer()),
  }
}

/**
 * Rendering runs only while the hero is on screen and the tab is visible. The controller holds both signals and
 * reports changes of the combined state.
 */
export function createVisibilityController(onChange: (active: boolean) => void, initiallyVisible = true) {
  let intersecting = initiallyVisible
  let documentHidden = false
  let active = intersecting && !documentHidden
  const update = () => {
    const next = intersecting && !documentHidden
    if (next !== active) {
      active = next
      onChange(active)
    }
  }
  return {
    setIntersecting(value: boolean) {
      intersecting = value
      update()
    },
    setDocumentHidden(value: boolean) {
      documentHidden = value
      update()
    },
    get active() {
      return active
    },
  }
}
