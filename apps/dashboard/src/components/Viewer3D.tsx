import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export interface ViewerStats {
  triangles: number;
  size: [number, number, number];
  meshes: number;
}

interface Props {
  url: string | null;
  wireframe: boolean;
  showBounds: boolean;
  autoRotate: boolean;
  /** transparent background + shadow-catcher floor, for the studio stage (CSS paints the backdrop) */
  studio?: boolean;
  onStats?: (s: ViewerStats) => void;
  onCapture?: (image: string) => void;
}

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Interactive glTF viewer (orbit/zoom/pan). Everything shown is loaded from the real exported GLB. */
export function Viewer3D({ url, wireframe, showBounds, autoRotate, studio, onStats, onCapture }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    controls: OrbitControls;
    model: THREE.Object3D | null;
    box: THREE.Box3Helper | null;
    raf: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const flags = useRef({ wireframe, showBounds, autoRotate });
  flags.current = { wireframe, showBounds, autoRotate };

  // scene lifecycle
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: false, alpha: !!studio });
    } catch {
      setError("WebGL indisponível neste navegador.");
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const bg = cssVar("--viewer-bg", "#1b1e24");
    if (!studio) {
      scene.background = new THREE.Color(bg);
      scene.fog = new THREE.Fog(bg, 120, 420);
    }
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 2000);
    camera.position.set(25, 18, 30);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI * 0.495;
    scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x556048, 1.1));
    const sun = new THREE.DirectionalLight(0xfff1dd, 2.4);
    const ext = studio ? 12 : 60;
    sun.position.set(ext * 0.66, ext * 1.16, ext * 0.5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -ext, right: ext, top: ext, bottom: -ext, near: 1, far: ext * 4 });
    sun.shadow.bias = -0.0004;
    scene.add(sun);
    const ground = new THREE.Mesh(new THREE.CircleGeometry(400, 64), studio ? new THREE.ShadowMaterial({ opacity: 0.35 }) : new THREE.MeshStandardMaterial({ color: cssVar("--viewer-ground", "#46543f"), roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.02;
    ground.receiveShadow = true;
    scene.add(ground);
    const grid = new THREE.GridHelper(studio ? 30 : 200, studio ? 30 : 100, studio ? 0x666b75 : 0x888888, studio ? 0x3a3e46 : 0x666666);
    (grid.material as THREE.Material).opacity = 0.25;
    (grid.material as THREE.Material).transparent = true;
    scene.add(grid);

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

    const st = { renderer, scene, camera, controls, model: null as THREE.Object3D | null, box: null as THREE.Box3Helper | null, raf: 0 };
    state.current = st;
    const tick = () => {
      controls.autoRotate = flags.current.autoRotate;
      controls.autoRotateSpeed = 1.2;
      controls.update();
      renderer.render(scene, camera);
      st.raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(st.raf);
      ro.disconnect();
      controls.dispose();
      if (st.model) disposeModel(st.model);
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.geometry) m.geometry.dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
      state.current = null;
    };
  }, []);

  // model loading
  useEffect(() => {
    const st = state.current;
    if (!st || !url) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    new GLTFLoader().load(
      url,
      (gltf) => {
        if (cancelled || !state.current) {
          disposeModel(gltf.scene);
          return;
        }
        const s = state.current;
        if (s.model) {
          s.scene.remove(s.model);
          disposeModel(s.model);
        }
        if (s.box) s.scene.remove(s.box);
        const model = gltf.scene;
        let tris = 0;
        let meshes = 0;
        model.traverse((o) => {
          const m = o as THREE.Mesh;
          if (m.isMesh) {
            meshes++;
            m.castShadow = m.receiveShadow = true;
            const idx = m.geometry.index;
            tris += idx ? idx.count / 3 : m.geometry.attributes.position.count / 3;
            const mats = Array.isArray(m.material) ? m.material : [m.material];
            mats.forEach((mm) => {
              const t = (mm as THREE.MeshStandardMaterial).map;
              if (t) t.anisotropy = 8;
            });
          }
        });
        s.scene.add(model);
        s.model = model;
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const centre = box.getCenter(new THREE.Vector3());
        const helper = new THREE.Box3Helper(box, new THREE.Color(0xf59e42));
        helper.visible = flags.current.showBounds;
        s.scene.add(helper);
        s.box = helper;
        const radius = size.length() / 2;
        s.camera.position.copy(centre).add(new THREE.Vector3(0.9, 0.55, 1.1).normalize().multiplyScalar(radius * (studio ? 3.2 : 2.6)));
        s.controls.target.copy(centre);
        s.camera.near = Math.max(radius / 200, 0.05);
        s.camera.far = radius * 40;
        s.camera.updateProjectionMatrix();
        applyWire(model, flags.current.wireframe);
        onStats?.({ triangles: Math.round(tris), size: [size.x, size.y, size.z], meshes });
        setLoading(false);
      },
      undefined,
      (e) => {
        if (cancelled) return;
        setError(`Falha ao carregar o modelo: ${(e as Error)?.message ?? "erro desconhecido"}`);
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  useEffect(() => {
    if (state.current?.model) applyWire(state.current.model, wireframe);
  }, [wireframe]);
  useEffect(() => {
    if (state.current?.box) state.current.box.visible = showBounds;
  }, [showBounds]);

  return (
    <div className="viewer" ref={host}>
      {onCapture && !loading && !error && url && state.current?.model &&
        <button type="button" className="viewer-capture" onClick={() => {
          const rendered = state.current;
          if (!rendered?.model) return;
          rendered.renderer.render(rendered.scene, rendered.camera);
          onCapture(rendered.renderer.domElement.toDataURL("image/jpeg", 0.85).split(",")[1]);
        }}>Capturar vista</button>}
      {loading && <div className="viewer-overlay">Carregando modelo…</div>}
      {error && <div className="viewer-overlay err">{error}</div>}
    </div>
  );
}

function disposeModel(root: THREE.Object3D) {
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry.dispose();
    for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) materials.add(material);
  });
  for (const material of materials) {
    for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value);
    material.dispose();
  }
  for (const texture of textures) texture.dispose();
}

function applyWire(root: THREE.Object3D, on: boolean) {
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    (Array.isArray(m.material) ? m.material : [m.material]).forEach((mm) => ((mm as THREE.MeshStandardMaterial).wireframe = on));
  });
}
