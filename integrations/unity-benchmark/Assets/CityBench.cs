using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Unity.Profiling;
using UnityEngine;
using UnityEngine.Rendering;

public sealed class CityBench : MonoBehaviour
{
    [Serializable]
    private sealed class Scenario
    {
        public string name;
        public int buildings;
        public int npcs;
        public int vehicles;
    }

    [Serializable] private sealed class ScenarioFile { public Scenario[] cases; }

    public GameObject building, npc, vehicle;
    public Camera view;
    private readonly List<LODGroup> groups = new();
    private readonly List<int> current = new();
    private readonly List<Renderer[][]> levels = new();

    private IEnumerator Start()
    {
        if (SystemInfo.graphicsDeviceType == GraphicsDeviceType.Null)
            throw new InvalidOperationException("A graphics device is required for a rendering benchmark.");
        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = -1;
        var path = Environment.GetEnvironmentVariable("ASSETFORGE_BENCH_OUTPUT") ?? Application.persistentDataPath;
        Directory.CreateDirectory(path);
        File.WriteAllText(Path.Combine(path, "environment.txt"),
            $"{Application.unityVersion}\n{SystemInfo.graphicsDeviceName}\n{SystemInfo.graphicsDeviceType}\n" +
            $"{SystemInfo.processorType}\n{Screen.width}x{Screen.height}\n");
        var scenarioPath = Environment.GetEnvironmentVariable("ASSETFORGE_BENCH_CASES");
        var cases = string.IsNullOrEmpty(scenarioPath) ? DefaultCases()
            : JsonUtility.FromJson<ScenarioFile>(File.ReadAllText(scenarioPath)).cases;
        if (cases == null || cases.Length == 0)
            throw new InvalidOperationException("Configure at least one benchmark scenario.");

        using var draws = ProfilerRecorder.StartNew(ProfilerCategory.Render, "Draw Calls Count");
        using var triangles = ProfilerRecorder.StartNew(ProfilerCategory.Render, "Triangles Count");
        using var memory = ProfilerRecorder.StartNew(ProfilerCategory.Memory, "Total Used Memory");
        using var csv = new StreamWriter(Path.Combine(path, "frames.csv"));
        csv.WriteLine("scenario,frame,frame_ms,draw_calls,rendered_triangles,used_bytes,visible_lod_switches");
        foreach (var scenario in cases)
        {
            if (string.IsNullOrWhiteSpace(scenario.name) || scenario.name.Contains(',') ||
                scenario.buildings < 0 || scenario.npcs < 0 || scenario.vehicles < 0)
                throw new InvalidOperationException("Invalid benchmark scenario.");
            var world = new GameObject("Scenario");
            Place(building, scenario.buildings, world.transform, 48, 1.5f);
            Place(npc, scenario.npcs, world.transform, 3, 0.2f);
            Place(vehicle, scenario.vehicles, world.transform, 9, 1.1f);
            groups.AddRange(world.GetComponentsInChildren<LODGroup>());
            foreach (var group in groups)
            {
                current.Add(-1);
                levels.Add(Array.ConvertAll(group.GetLODs(), level => level.renderers));
            }
            var endOfFrame = new WaitForEndOfFrame();
            const int warmUp = 120, frames = 600;
            for (var frame = -warmUp; frame < frames; frame++)
            {
                var phase = Mathf.Clamp01((float)frame / (frames - 1));
                var distance = Mathf.Lerp(250, 15, Mathf.PingPong(phase * 2, 1));
                view.transform.position = new Vector3(distance * 0.6f, distance * 0.45f + 2, -distance);
                view.transform.LookAt(new Vector3(0, Mathf.Lerp(10, 1.6f, phase), 0));
                yield return endOfFrame;
                var switches = CountVisibleLodSwitches();
                if (frame >= 0)
                    csv.WriteLine(FormattableString.Invariant(
                        $"{scenario.name},{frame},{Time.unscaledDeltaTime * 1000:F4},{Metric(draws)},{Metric(triangles)},{Metric(memory)},{switches}"));
            }
            csv.Flush();
            Destroy(world);
            groups.Clear();
            current.Clear();
            levels.Clear();
            yield return null;
        }
        Application.Quit(0);
    }

    private static Scenario[] DefaultCases() => new[] {
        new Scenario {name = "empty"},
        new Scenario {name = "buildings-small", buildings = 12},
        new Scenario {name = "buildings-large", buildings = 60},
        new Scenario {name = "npcs-small", npcs = 24},
        new Scenario {name = "npcs-large", npcs = 160},
        new Scenario {name = "vehicles-small", vehicles = 12},
        new Scenario {name = "vehicles-large", vehicles = 80},
        new Scenario {name = "mixed", buildings = 30, npcs = 100, vehicles = 40},
    };

    private static string Metric(ProfilerRecorder recorder) => recorder.Valid && recorder.Count > 0
        ? recorder.LastValue.ToString(CultureInfo.InvariantCulture) : "";

    private static void Place(GameObject prefab, int count, Transform parent, float spacing, float shift)
    {
        if (count == 0) return;
        var side = Mathf.CeilToInt(Mathf.Sqrt(count));
        for (var i = 0; i < count; i++)
        {
            var x = (i % side - (side - 1) * 0.5f + shift) * spacing;
            var z = (i / side - (side - 1) * 0.5f) * spacing;
            Instantiate(prefab, new Vector3(x, 0, z), Quaternion.Euler(0, i * 57, 0), parent);
        }
    }

    private int CountVisibleLodSwitches()
    {
        var switches = 0;
        for (var i = 0; i < groups.Count; i++)
        {
            var previous = current[i];
            var visible = Array.FindIndex(levels[i], level => Array.Exists(level, renderer => renderer.isVisible));
            if (visible >= 0 && previous >= 0 && previous != visible) switches++;
            current[i] = visible;
        }
        return switches;
    }
}
