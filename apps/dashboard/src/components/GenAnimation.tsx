import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * Decorative "model is being built" animation: a point cloud condenses into a wireframe and then a solid.
 * It is driven by the REAL job progress (0..1), but the shape itself is illustrative — it is not the model being generated.
 */
export function GenAnimation({ progress }: { progress: number }) {
  const host = useRef<HTMLDivElement>(null);
  const target = useRef(progress);
  target.current = progress;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      return; // no WebGL: the overlay text still shows the real progress
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);
    const accent = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#ffd028");
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 0.6, 7.2);
    camera.lookAt(0, 0, 0);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x222233, 1.2));
    const key = new THREE.DirectionalLight(0xffffff, 2);
    key.position.set(3, 4, 5);
    scene.add(key);

    const group = new THREE.Group();
    scene.add(group);

    // illustrative target shape: a faceted gem (icosahedron, slightly stretched)
    const shape = new THREE.IcosahedronGeometry(1.5, 2);
    shape.scale(1, 1.18, 1);
    const surface = shape.attributes.position;
    const N = 3200;
    const start = new Float32Array(N * 3);
    const end = new Float32Array(N * 3);
    const delay = new Float32Array(N);
    const cur = new Float32Array(N * 3);
    const tmp = new THREE.Vector3();
    for (let i = 0; i < N; i++) {
      const v = (Math.random() * surface.count) | 0;
      tmp.fromBufferAttribute(surface, v);
      end.set([tmp.x, tmp.y, tmp.z], i * 3);
      const r = 2.4 + Math.random() * 2.6;
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(2 * Math.random() - 1);
      start.set([r * Math.sin(ph) * Math.cos(th), r * Math.cos(ph) * 0.8, r * Math.sin(ph) * Math.sin(th)], i * 3);
      delay[i] = Math.random() * 0.45;
    }
    const pg = new THREE.BufferGeometry();
    pg.setAttribute("position", new THREE.BufferAttribute(cur, 3));
    const pm = new THREE.PointsMaterial({ color: accent, size: 0.035, transparent: true, opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending });
    const points = new THREE.Points(pg, pm);
    group.add(points);

    const wire = new THREE.LineSegments(new THREE.WireframeGeometry(shape), new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: 0, blending: THREE.AdditiveBlending }));
    group.add(wire);
    const solid = new THREE.Mesh(shape, new THREE.MeshStandardMaterial({ color: accent.clone().lerp(new THREE.Color(0x777777), 0.55), flatShading: true, roughness: 0.45, metalness: 0.1, transparent: true, opacity: 0 }));
    group.add(solid);

    // scanner ring and ground glow
    const ring = new THREE.Mesh(new THREE.TorusGeometry(1.95, 0.012, 8, 128), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.85 }));
    ring.rotation.x = Math.PI / 2;
    scene.add(ring);
    const floor = new THREE.Mesh(new THREE.RingGeometry(2.1, 2.14, 96), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.25, side: THREE.DoubleSide }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -1.9;
    scene.add(floor);
    const floor2 = floor.clone();
    floor2.scale.setScalar(1.35);
    (floor2.material as THREE.MeshBasicMaterial) = (floor.material as THREE.MeshBasicMaterial).clone();
    (floor2.material as THREE.MeshBasicMaterial).opacity = 0.1;
    scene.add(floor2);

    const resize = () => {
      const w = el.clientWidth || 300;
      const h = el.clientHeight || 300;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    const smooth = (a: number, b: number, x: number) => {
      const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
      return t * t * (3 - 2 * t);
    };
    let p = 0;
    let raf = 0;
    const t0 = performance.now();
    const tick = () => {
      const t = (performance.now() - t0) / 1000;
      p += (Math.max(0.04, target.current) - p) * 0.025; // ease towards the real progress
      for (let i = 0; i < N; i++) {
        const k = smooth(0, 1, (p - delay[i] * 0.6) / 0.6);
        const sw = (1 - k) * 0.35;
        for (let a = 0; a < 3; a++) {
          const s = start[i * 3 + a];
          const e = end[i * 3 + a];
          cur[i * 3 + a] = s + (e - s) * k + (a === 1 ? 0 : Math.sin(t * 1.3 + i) * 0.04 * (1 - k)) + (a === 0 ? Math.sin(t * 0.8 + i * 0.1) * sw * 0.2 : 0);
        }
      }
      pg.attributes.position.needsUpdate = true;
      (wire.material as THREE.LineBasicMaterial).opacity = smooth(0.3, 0.8, p) * 0.55;
      (solid.material as THREE.MeshStandardMaterial).opacity = smooth(0.78, 1, p) * 0.85;
      pm.opacity = 0.9 - smooth(0.8, 1, p) * 0.5;
      ring.position.y = Math.sin(t * 1.1) * 1.75;
      (ring.material as THREE.MeshBasicMaterial).opacity = 0.35 + 0.5 * (1 - Math.abs(Math.sin(t * 1.1)));
      group.rotation.y = t * 0.45;
      floor.rotation.z = t * 0.2;
      floor2.rotation.z = -t * 0.12;
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      [pg, shape, wire.geometry, ring.geometry, floor.geometry, floor2.geometry].forEach((g) => g.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div className="gen-anim" ref={host} aria-hidden="true" />;
}
