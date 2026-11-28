using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace AssetForge
{
    public static class AssetForgeImporter
    {
        [Serializable] private sealed class Manifest
        {
            public int schema;
            public MaterialInfo[] materials;
            public Level[] lods;
            public ColliderInfo collider;
            public Atlas impostor;
        }

        [Serializable] private sealed class Level
        {
            public int index;
            public float relativeHeight;
            public string[] materialSlots;
        }

        [Serializable] private sealed class MaterialInfo
        {
            public string name, albedo, normal, metallicSmoothness;
            public float[] baseColor;
            public float metallic, smoothness, normalScale;
        }

        [Serializable] private sealed class ColliderInfo
        {
            public string kind;
            public float[] center, size;
            public float height, radius;
        }

        [Serializable] private sealed class Atlas
        {
            public string atlas;
            public int rows, columns, tile_size;
            public float world_extent, relativeHeight;
            public float[] center_gltf;
            public AssetForgeImpostor.Frame[] frames;
        }

        [MenuItem("Assets/AssetForge/Build URP prefab", true)]
        private static bool CanBuild() => Path.GetFileName(AssetDatabase.GetAssetPath(Selection.activeObject)) == "assetforge-import.json";

        [MenuItem("Assets/AssetForge/Build URP prefab")]
        private static void Build()
        {
            string metadata = AssetDatabase.GetAssetPath(Selection.activeObject);
            string root = Path.GetDirectoryName(metadata).Replace('\\', '/');
            Manifest info = JsonUtility.FromJson<Manifest>(File.ReadAllText(metadata));
            if (info.schema != 2 || info.lods == null || info.lods.Length == 0)
                throw new InvalidDataException("Expected an AssetForge schema 2 export.");
            Shader lit = Shader.Find("Universal Render Pipeline/Lit");
            Shader unlit = Shader.Find("Universal Render Pipeline/Unlit");
            if (!lit || !unlit) throw new InvalidOperationException("Install and enable URP in this project.");
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(root + "/model.fbx");
            if (!model) throw new FileNotFoundException("Extract model.fbx alongside assetforge-import.json.");
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(model);
            try
            {
                PrefabUtility.UnpackPrefabInstance(instance, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
                var renderers = instance.GetComponentsInChildren<MeshRenderer>(true);
                List<LOD> lods = new List<LOD>();
                foreach (Level level in info.lods)
                {
                    string suffix = "_LOD" + level.index;
                    Renderer[] parts = Array.FindAll(renderers, item => item.name.EndsWith(suffix, StringComparison.Ordinal));
                    if (parts.Length == 0) throw new InvalidDataException("Missing mesh renderer for " + suffix);
                    lods.Add(new LOD(level.relativeHeight, parts));
                }
                ApplyMaterials(root, lit, info.materials, renderers, info.lods);
                var group = instance.GetComponent<LODGroup>() ?? instance.AddComponent<LODGroup>();
                group.SetLODs(lods.ToArray());
                group.RecalculateBounds();
                if (info.impostor != null && !string.IsNullOrEmpty(info.impostor.atlas))
                {
                    lods.Add(new LOD(info.impostor.relativeHeight, new[] { AddImpostor(instance.transform, root, unlit, info.impostor) }));
                    group.SetLODs(lods.ToArray());
                }
                AddCollider(instance, info.collider);
                PrefabUtility.SaveAsPrefabAsset(instance, root + "/AssetForge.prefab");
                AssetDatabase.SaveAssets();
            }
            finally { UnityEngine.Object.DestroyImmediate(instance); }
        }

        private static void ApplyMaterials(string root, Shader shader, MaterialInfo[] entries, MeshRenderer[] renderers, Level[] levels)
        {
            var materials = new Dictionary<string, Material>(StringComparer.Ordinal);
            for (int i = 0; i < entries.Length; i++)
            {
                MaterialInfo entry = entries[i];
                Material mat = GetMaterial(root + $"/AssetForge-PBR-{i:00}.mat", shader);
                mat.SetColor("_BaseColor", entry.baseColor == null ? Color.white :
                    new Color(entry.baseColor[0], entry.baseColor[1], entry.baseColor[2], entry.baseColor[3]));
                mat.SetTexture("_BaseMap", Texture(root, entry.albedo, TextureImporterType.Default, true));
                mat.SetTexture("_BumpMap", Texture(root, entry.normal, TextureImporterType.NormalMap, false));
                mat.SetFloat("_BumpScale", entry.normalScale);
                SetKeyword(mat, "_NORMALMAP", mat.GetTexture("_BumpMap"));
                var metallicMap = Texture(root, entry.metallicSmoothness, TextureImporterType.Default, false);
                mat.SetTexture("_MetallicGlossMap", metallicMap);
                mat.SetFloat("_Metallic", entry.metallic);
                mat.SetFloat("_Smoothness", metallicMap ? 1f : entry.smoothness);
                SetKeyword(mat, "_METALLICSPECGLOSSMAP", metallicMap);
                EditorUtility.SetDirty(mat);
                materials.Add(entry.name, mat);
            }
            foreach (MeshRenderer renderer in renderers)
            {
                Level level = Array.Find(levels, item => renderer.name.EndsWith("_LOD" + item.index, StringComparison.Ordinal));
                if (level == null) continue;
                renderer.sharedMaterials = renderer.sharedMaterials.Select((original, index) =>
                {
                    if (original && materials.TryGetValue(original.name, out Material replacement)) return replacement;
                    string[] slots = level.materialSlots;
                    return slots != null && index < slots.Length && materials.TryGetValue(slots[index], out replacement)
                        ? replacement : original;
                }).ToArray();
            }
        }

        private static Material GetMaterial(string path, Shader shader)
        {
            var existing = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (existing) { existing.shader = shader; return existing; }
            var created = new Material(shader);
            AssetDatabase.CreateAsset(created, path);
            return created;
        }

        private static Texture2D Texture(string root, string relativePath, TextureImporterType type, bool srgb, bool atlas = false)
        {
            if (string.IsNullOrEmpty(relativePath)) return null;
            string path = root + "/" + relativePath;
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) throw new FileNotFoundException(path);
            importer.textureType = type;
            importer.sRGBTexture = srgb;
            importer.alphaIsTransparency = atlas;
            if (atlas)
            {
                importer.npotScale = TextureImporterNPOTScale.None;
                importer.mipmapEnabled = false;
                importer.wrapMode = TextureWrapMode.Clamp;
            }
            importer.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        private static void SetKeyword(Material mat, string keyword, bool enabled)
        {
            if (enabled) mat.EnableKeyword(keyword);
            else mat.DisableKeyword(keyword);
        }

        private static MeshRenderer AddImpostor(Transform parent, string root, Shader shader, Atlas info)
        {
            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = "Impostor";
            quad.transform.SetParent(parent, false);
            quad.transform.localPosition = new Vector3(-info.center_gltf[0], info.center_gltf[1], info.center_gltf[2]);
            quad.transform.localScale = Vector3.one * info.world_extent;
            UnityEngine.Object.DestroyImmediate(quad.GetComponent<Collider>());
            var mat = GetMaterial(root + "/AssetForge-Impostor.mat", shader);
            mat.SetTexture("_BaseMap", Texture(root, info.atlas, TextureImporterType.Default, true, true));
            float width = info.columns * info.tile_size;
            float height = info.rows * info.tile_size;
            var frame = info.frames[0];
            mat.SetTextureScale("_BaseMap", new Vector2((info.tile_size - 1f) / width, (info.tile_size - 1f) / height));
            mat.SetTextureOffset("_BaseMap", new Vector2((frame.x + 0.5f) / width, (frame.y + 0.5f) / height));
            mat.SetFloat("_AlphaClip", 1);
            mat.SetFloat("_Cutoff", 0.45f);
            mat.SetFloat("_Cull", 0);
            mat.EnableKeyword("_ALPHATEST_ON");
            mat.SetOverrideTag("RenderType", "TransparentCutout");
            mat.renderQueue = (int)RenderQueue.AlphaTest;
            EditorUtility.SetDirty(mat);
            var renderer = quad.GetComponent<MeshRenderer>();
            renderer.sharedMaterial = mat;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            var view = quad.AddComponent<AssetForgeImpostor>();
            view.frames = info.frames;
            view.columns = info.columns;
            view.rows = info.rows;
            view.tileSize = info.tile_size;
            return renderer;
        }

        private static void AddCollider(GameObject root, ColliderInfo info)
        {
            if (info == null) return;
            var center = new Vector3(info.center[0], info.center[1], info.center[2]);
            if (info.kind == "capsule")
            {
                var shape = root.AddComponent<CapsuleCollider>();
                shape.center = center;
                shape.height = info.height;
                shape.radius = info.radius;
            }
            else if (info.kind == "box")
            {
                var shape = root.AddComponent<BoxCollider>();
                shape.center = center;
                shape.size = new Vector3(info.size[0], info.size[1], info.size[2]);
            }
        }
    }
}
