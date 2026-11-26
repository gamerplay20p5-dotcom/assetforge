import { useEffect, useRef } from "react";
import * as THREE from "three";

interface Cloud {
  /** target positions (x, y, z) and colours (r, g, b) of every point */
  pos: Float32Array;
  col: Float32Array;
  n: number;
}

const GRID = 120; // the reference is sampled on a GRID x GRID raster

/** Turn an image into a coloured, slightly volumetric point cloud of the object it shows (background removed by corner colour). */
export function cloudFromImage(img: HTMLImageElement, count: number): Cloud | null {
  const scale = GRID / Math.max(img.naturalWidth, img.naturalHeight);
  const w = Math.max(8, Math.round(img.naturalWidth * scale));
  const h = Math.max(8, Math.round(img.naturalHeight * scale));
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const g = c.getContext("2d", { willReadFrequently: true });
  if (!g) return null;
  g.drawImage(img, 0, 0, w, h);
  const data = g.getImageData(0, 0, w, h).data;
  // background = average colour of the four corners
  const corner = [0, 0, 0];
  let nc = 0;
  for (const [x0, y0] of [[0, 0], [w - 6, 0], [0, h - 6], [w - 6, h - 6]]) {
    for (let y = y0; y < y0 + 6; y++) {
      for (let x = x0; x < x0 + 6; x++) {
        const i = (y * w + x) * 4;
        corner[0] += data[i];
        corner[1] += data[i + 1];
        corner[2] += data[i + 2];
        nc++;
      }
    }
  }
  const bg = corner.map((v) => v / nc);
  const mask = new Uint8Array(w * h);
  let on = 0;
  for (let i = 0; i < w * h; i++) {
    const a = data[i * 4 + 3];
    const d = Math.hypot(data[i * 4] - bg[0], data[i * 4 + 1] - bg[1], data[i * 4 + 2] - bg[2]);
    if (a > 100 && d > 34) {
      mask[i] = 1;
      on++;
    }
  }
  if (on < 60) return null;
  // chamfer distance to the nearest background pixel -> thickness (thicker in the middle of the shape)
  const dist = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) dist[i] = mask[i] ? 1e6 : 0;
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (!mask[i]) continue;
      let d = dist[i];
      if (x > 0) d = Math.min(d, dist[i - 1] + 1);
      if (y > 0) d = Math.min(d, dist[i - w] + 1);
      dist[i] = d;
    }
  let maxd = 1;
  for (let y = h - 1; y >= 0; y--)
    for (let x = w - 1; x >= 0; x--) {
      const i = y * w + x;
      if (!mask[i]) continue;
      let d = dist[i];
      if (x < w - 1) d = Math.min(d, dist[i + 1] + 1);
      if (y < h - 1) d = Math.min(d, dist[i + w] + 1);
      dist[i] = d;
      maxd = Math.max(maxd, d);
    }
  const idx: number[] = [];
  for (let i = 0; i < w * h; i++) if (mask[i]) idx.push(i);
  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const S = 5.0 / Math.max(w, h); // world units per raster cell: the object is ~5 tall/wide
  for (let k = 0; k < count; k++) {
    const i = idx[(Math.random() * idx.length) | 0];
    const x = (i % w) + Math.random() - 0.5;
    const y = Math.floor(i / w) + Math.random() - 0.5;
    const depth = Math.sqrt(dist[i] / maxd) * 0.9 + 0.08;
    const side = k % 3 === 0 ? -1 : 1; // front surface carries the picture, the back gets fewer points
    pos[k * 3] = (x - w / 2) * S;
    pos[k * 3 + 1] = -(y - h / 2) * S;
    pos[k * 3 + 2] = side * depth * (0.85 + Math.random() * 0.3);
    col[k * 3] = data[i * 4] / 255;
    col[k * 3 + 1] = data[i * 4 + 1] / 255;
    col[k * 3 + 2] = data[i * 4 + 2] / 255;
  }
  return { pos, col, n: count };
}

/** Fallback when there is no picture: a faceted gem, so the animation never shows an empty stage. */
function cloudFromGem(count: number, accent: THREE.Color): Cloud {
  const shape = new THREE.IcosahedronGeometry(1.5, 2);
  shape.scale(1, 1.18, 1);
  const s = shape.attributes.position;
  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const tmp = new THREE.Vector3();
  for (let i = 0; i < count; i++) {
    tmp.fromBufferAttribute(s, (Math.random() * s.count) | 0);
    pos.set([tmp.x, tmp.y, tmp.z], i * 3);
    col.set([accent.r, accent.g, accent.b], i * 3);
  }
  shape.dispose();
  return { pos, col, n: count };
}

/**
 * "The model is being built" animation. Dots start scattered and condense into the shape of the object (its silhouette and colours, read from
 * the reference image or the kit preview), driven by the REAL job progress (0..1). The shape is the picture's outline given some depth; it is
 * not the 3D model itself, which appears in the viewer when the job finishes.
 */
export function GenAnimation({ progress, source }: { progress: number; source?: string | null }) {
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
    let disposed = false;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);
    const accent = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#ffd028");
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
    camera.position.set(0, 0.3, 8.8);
    camera.lookAt(0, 0, 0);
    const group = new THREE.Group();
    scene.add(group);

    const N = 6500;
    const start = new Float32Array(N * 3);
    const delay = new Float32Array(N);
    const cur = new Float32Array(N * 3);
    const colors = new Float32Array(N * 3);
    let end = new Float32Array(N * 3);
    let tint = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      const r = 2.6 + Math.random() * 3.4;
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(2 * Math.random() - 1);
      start.set([r * Math.sin(ph) * Math.cos(th), r * Math.cos(ph) * 0.8, r * Math.sin(ph) * Math.sin(th)], i * 3);
      delay[i] = Math.random() * 0.5;
    }
    const setCloud = (c: Cloud) => {
      end = c.pos;
      tint = c.col;
    };
    setCloud(cloudFromGem(N, accent));
    if (source) {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        if (disposed) return;
        const c = cloudFromImage(img, N);
        if (c) setCloud(c);
      };
      img.src = source;
    }

    const pg = new THREE.BufferGeometry();
    pg.setAttribute("position", new THREE.BufferAttribute(cur, 3));
    pg.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const pm = new THREE.PointsMaterial({ size: 0.055, vertexColors: true, transparent: true, opacity: 0.95, depthWrite: false, sizeAttenuation: true });
    group.add(new THREE.Points(pg, pm));

    // scanner ring + ground glow
    const ring = new THREE.Mesh(new THREE.TorusGeometry(2.3, 0.012, 8, 128), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.8 }));
    ring.rotation.x = Math.PI / 2;
    scene.add(ring);
    const floor = new THREE.Mesh(new THREE.RingGeometry(2.5, 2.54, 96), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.25, side: THREE.DoubleSide }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -2.0;
    scene.add(floor);

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

    const smooth = (x: number) => {
      const t = Math.min(1, Math.max(0, x));
      return t * t * (3 - 2 * t);
    };
    let p = 0;
    let raf = 0;
    const t0 = performance.now();
    const tick = () => {
      const t = (performance.now() - t0) / 1000;
      p += (Math.max(0.05, target.current) - p) * 0.02; // ease towards the real progress
      for (let i = 0; i < N; i++) {
        const k = smooth((p * 1.25 - delay[i] * 0.55) / 0.55);
        for (let a = 0; a < 3; a++) {
          const s = start[i * 3 + a];
          const e = end[i * 3 + a];
          cur[i * 3 + a] = s + (e - s) * k + (a === 1 ? 0 : Math.sin(t * 1.4 + i * 0.37) * 0.05 * (1 - k));
        }
        // dots glow in the accent colour while travelling and take the picture's colour as they settle
        const m = smooth((k - 0.5) / 0.5);
        colors[i * 3] = accent.r * (1 - m) + tint[i * 3] * m;
        colors[i * 3 + 1] = accent.g * (1 - m) + tint[i * 3 + 1] * m;
        colors[i * 3 + 2] = accent.b * (1 - m) + tint[i * 3 + 2] * m;
      }
      pg.attributes.position.needsUpdate = true;
      pg.attributes.color.needsUpdate = true;
      ring.position.y = Math.sin(t * 1.1) * 1.9;
      (ring.material as THREE.MeshBasicMaterial).opacity = 0.3 + 0.5 * (1 - Math.abs(Math.sin(t * 1.1))) - 0.25 * smooth((p - 0.85) / 0.15);
      group.rotation.y = Math.sin(t * 0.55) * 0.55; // sways instead of spinning so the front of the object stays readable
      floor.rotation.z = t * 0.2;
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      [pg, ring.geometry, floor.geometry].forEach((g) => g.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [source]);

  return <div className="gen-anim" ref={host} aria-hidden="true" />;
}
