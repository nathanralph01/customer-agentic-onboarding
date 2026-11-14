import { useEffect, useRef } from 'react'
import createGlobe from 'cobe'

export function RotatingGlobe({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)')
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    let phi = 4.4
    let frame = 0
    let last = 0
    let visible = false
    const globe = createGlobe(canvas, {
      width: canvas.offsetWidth * dpr, height: canvas.offsetWidth * dpr,
      devicePixelRatio: dpr, phi, theta: 0.25, dark: 0, diffuse: 1.4,
      mapSamples: 16000, mapBrightness: 7, baseColor: [0.22, 0.45, 0.95],
      markerColor: [1, 1, 1], glowColor: [0.75, 0.85, 1], markers: [],
    })
    function tick(now: number) {
      frame = requestAnimationFrame(tick)
      const dt = now - last
      if (dt < 1000 / 30) return
      // Scale by elapsed time so rotation speed stays constant at 30fps.
      phi += 0.003 * (dt / (1000 / 60))
      last = now
      globe.update({ phi })
    }
    function stop() { cancelAnimationFrame(frame); frame = 0 }
    function start() {
      if (motion.matches || frame || !visible || document.hidden) return
      last = performance.now()
      frame = requestAnimationFrame(tick)
    }
    function sync() { stop(); start() }
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; sync() })
    const resize = new ResizeObserver(() => globe.update({ width: canvas.offsetWidth * dpr, height: canvas.offsetWidth * dpr }))
    observer.observe(canvas)
    resize.observe(canvas)
    document.addEventListener('visibilitychange', sync)
    motion.addEventListener('change', sync)
    return () => {
      stop()
      observer.disconnect()
      resize.disconnect()
      document.removeEventListener('visibilitychange', sync)
      motion.removeEventListener('change', sync)
      globe.destroy()
    }
  }, [])
  return <canvas ref={canvasRef} role="img" aria-label="A rotating blue globe connecting customers around the world" className={className} style={{ width: '100%', aspectRatio: '1 / 1' }} />
}
