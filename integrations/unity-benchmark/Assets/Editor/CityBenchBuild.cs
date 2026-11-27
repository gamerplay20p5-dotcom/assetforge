using System;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public static class CityBenchBuild
{
    [Serializable] private sealed class Level
    {
        public int index;
        public float relativeHeight;
    }
    [Serializable] private sealed class Collision
    {
        public string kind;
        public float[] center, size;
        public float radius, height;
    }
    [Serializable] private sealed class Surface
    {
        public string name, albedo, normal, metallicSmoothness;
        public float[] baseColor;
        public float metallic, smoothness;
    }
    [Serializable] private sealed class Package
    {
        public int schema;
        public string units;
        public Collision collider;
        public Level[] lods;
        public Surface[] materials;
    }

    [MenuItem("AssetForge/Build isolated benchmark")]
    public static void Build()
    {
        var input = Required("ASSETFORGE_PACKAGES");
        var output = Required("ASSETFORGE_PLAYER");
        const string root = "Assets/BenchmarkGenerated";
        Directory.CreateDirectory(root);
        var raster = LoadOrCreate<UniversalRendererData>($"{root}/Renderer.asset");
        const string pipelinePath = root + "/URP.asset";
        var pipeline = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(pipelinePath);
        if (pipeline == null)
        {
            pipeline = UniversalRenderPipelineAsset.Create(raster);
            AssetDatabase.CreateAsset(pipeline, pipelinePath);
        }
        GraphicsSettings.defaultRenderPipeline = pipeline;
        QualitySettings.renderPipeline = pipeline;
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var controller = new GameObject("AssetForge Benchmark").AddComponent<CityBench>();
        controller.building = Import(input, root, "building");
        controller.npc = Import(input, root, "npc");
        controller.vehicle = Import(input, root, "vehicle");
        controller.view = new GameObject("Benchmark Camera").AddComponent<Camera>();
        controller.view.farClipPlane = 1300;
        var light = new GameObject("Sun").AddComponent<Light>();
        light.type = LightType.Directional;
        light.transform.rotation = Quaternion.Euler(50, -30, 0);
        const string target = root + "/Benchmark.unity";
        EditorSceneManager.SaveScene(scene, target);
        AssetDatabase.SaveAssets();
        var report = BuildPipeline.BuildPlayer(new[] {target}, output, BuildTarget.StandaloneLinux64, BuildOptions.Development);
        if (report.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException($"Unity build failed: {report.summary.result}");
    }

    private static GameObject Import(string input, string root, string category)
    {
        var src = Path.Combine(input, category);
        var dst = $"{root}/{category}";
        var meta = JsonUtility.FromJson<Package>(File.ReadAllText(Path.Combine(src, "assetforge-import.json")));
        if (meta.schema != 1 || meta.units != "meters" || meta.lods.Length == 0)
            throw new InvalidOperationException($"Invalid package: {category}");
        Directory.CreateDirectory(dst);
        File.Copy(Path.Combine(src, "model.fbx"), $"{dst}/model.fbx", true);
        foreach (var surface in meta.materials)
        {
            CopyMap(surface.albedo, src, dst);
            CopyMap(surface.normal, src, dst);
            CopyMap(surface.metallicSmoothness, src, dst);
        }
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        var model = AssetDatabase.LoadAssetAtPath<GameObject>($"{dst}/model.fbx");
        if (model == null) throw new InvalidOperationException($"FBX import failed: {category}");
        var holder = new GameObject(category);
        var meshes = (GameObject)PrefabUtility.InstantiatePrefab(model, holder.transform);
        PrefabUtility.UnpackPrefabInstance(meshes, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
        foreach (var lod in meshes.GetComponentsInChildren<LODGroup>()) UnityEngine.Object.DestroyImmediate(lod);
        var renderers = meshes.GetComponentsInChildren<Renderer>();
        var shader = Shader.Find("Universal Render Pipeline/Lit");
        if (shader == null) throw new InvalidOperationException("URP Lit was not loaded.");
        var materials = meta.materials.Select((surface, index) => Material(surface, shader, dst, index)).ToArray();
        foreach (var renderer in renderers)
            renderer.sharedMaterials = renderer.sharedMaterials.Select(old =>
            {
                var index = Array.FindIndex(meta.materials, surface => old != null && old.name == surface.name);
                if (index >= 0) return materials[index];
                if (materials.Length == 1) return materials[0];
                throw new InvalidOperationException($"Unmapped FBX material: {old?.name}");
            }).ToArray();
        var levels = meta.lods.Select(level =>
        {
            var parts = renderers.Where(renderer =>
                Regex.IsMatch(renderer.name, $"_LOD{level.index}(?![0-9])", RegexOptions.IgnoreCase)).ToArray();
            if (parts.Length == 0) throw new InvalidOperationException($"Missing LOD {level.index}: {category}");
            return new LOD(level.relativeHeight, parts);
        }).ToArray();
        var group = holder.AddComponent<LODGroup>();
        group.fadeMode = LODFadeMode.None;
        group.SetLODs(levels);
        group.RecalculateBounds();
        if (meta.collider.kind == "capsule")
        {
            var capsule = holder.AddComponent<CapsuleCollider>();
            capsule.center = Vector(meta.collider.center);
            capsule.radius = meta.collider.radius;
            capsule.height = meta.collider.height;
        }
        else
        {
            var box = holder.AddComponent<BoxCollider>();
            box.center = Vector(meta.collider.center);
            box.size = Vector(meta.collider.size);
        }
        var prefab = PrefabUtility.SaveAsPrefabAsset(holder, $"{dst}/{category}.prefab");
        UnityEngine.Object.DestroyImmediate(holder);
        return prefab;
    }

    private static Material Material(Surface source, Shader shader, string folder, int index)
    {
        var path = $"{folder}/Surface{index}.mat";
        var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (mat == null)
        {
            mat = new Material(shader);
            AssetDatabase.CreateAsset(mat, path);
        }
        mat.SetColor("_BaseColor", new Color(source.baseColor[0], source.baseColor[1], source.baseColor[2], source.baseColor[3]));
        mat.SetFloat("_Metallic", source.metallic);
        mat.SetFloat("_Smoothness", string.IsNullOrEmpty(source.metallicSmoothness) ? source.smoothness : 1);
        Map(mat, folder, source.albedo, "_BaseMap", null, false);
        Map(mat, folder, source.normal, "_BumpMap", "_NORMALMAP", true);
        Map(mat, folder, source.metallicSmoothness, "_MetallicGlossMap", "_METALLICSPECGLOSSMAP", false);
        EditorUtility.SetDirty(mat);
        return mat;
    }

    private static void Map(Material mat, string folder, string file, string property, string keyword, bool normal)
    {
        if (string.IsNullOrEmpty(file)) return;
        var path = $"{folder}/{file}";
        if (AssetImporter.GetAtPath(path) is TextureImporter importer && (normal || keyword != null))
        {
            importer.textureType = normal ? TextureImporterType.NormalMap : TextureImporterType.Default;
            importer.sRGBTexture = false;
            importer.SaveAndReimport();
        }
        mat.SetTexture(property, AssetDatabase.LoadAssetAtPath<Texture2D>(path));
        if (keyword != null) mat.EnableKeyword(keyword);
    }

    private static void CopyMap(string relative, string src, string dst)
    {
        if (string.IsNullOrEmpty(relative)) return;
        if (!Regex.IsMatch(relative, @"^textures/[0-9]+-[a-z-]+\.png$"))
            throw new InvalidOperationException($"Invalid texture path: {relative}");
        var target = Path.Combine(dst, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(target));
        File.Copy(Path.Combine(src, relative), target, true);
    }

    private static T LoadOrCreate<T>(string path) where T : ScriptableObject
    {
        var asset = AssetDatabase.LoadAssetAtPath<T>(path);
        if (asset != null) return asset;
        asset = ScriptableObject.CreateInstance<T>();
        AssetDatabase.CreateAsset(asset, path);
        return asset;
    }

    private static Vector3 Vector(float[] values) => new(values[0], values[1], values[2]);
    private static string Required(string key) => Environment.GetEnvironmentVariable(key)
        ?? throw new InvalidOperationException($"Set {key}.");
}
