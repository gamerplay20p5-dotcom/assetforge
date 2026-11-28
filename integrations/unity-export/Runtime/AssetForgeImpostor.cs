using UnityEngine;
using UnityEngine.Rendering;

namespace AssetForge
{
    [RequireComponent(typeof(MeshRenderer))]
    public sealed class AssetForgeImpostor : MonoBehaviour
    {
        [System.Serializable]
        public sealed class Frame
        {
            public float azimuth_degrees;
            public int x;
            public int y;
        }

        public Frame[] frames;
        public int tileSize, columns, rows;
        private MeshRenderer target;
        private MaterialPropertyBlock properties;
        private static readonly int BaseMapST = Shader.PropertyToID("_BaseMap_ST");

        private void OnEnable()
        {
            target = GetComponent<MeshRenderer>();
            properties ??= new MaterialPropertyBlock();
            RenderPipelineManager.beginCameraRendering += FaceCamera;
        }

        private void OnDisable() => RenderPipelineManager.beginCameraRendering -= FaceCamera;

        private void FaceCamera(ScriptableRenderContext context, Camera camera)
        {
            if (frames == null || frames.Length == 0 || !transform.parent) return;
            Transform basis = transform.parent;
            Vector3 toward = camera.orthographic ? -camera.transform.forward : camera.transform.position - transform.position;
            Vector3 local = basis.InverseTransformDirection(toward);
            if (toward.sqrMagnitude < 0.000001f) return;
            float azimuth = Mathf.Atan2(-local.x, local.z) * Mathf.Rad2Deg;
            Frame nearest = frames[0];
            foreach (Frame frame in frames)
            {
                if (Mathf.Abs(Mathf.DeltaAngle(azimuth, frame.azimuth_degrees)) <
                    Mathf.Abs(Mathf.DeltaAngle(azimuth, nearest.azimuth_degrees))) nearest = frame;
            }
            transform.rotation = Quaternion.LookRotation(-toward, camera.transform.up);
            float width = columns * tileSize;
            float height = rows * tileSize;
            target.GetPropertyBlock(properties);
            properties.SetVector(BaseMapST, new Vector4((tileSize - 1f) / width, (tileSize - 1f) / height,
                (nearest.x + 0.5f) / width, (nearest.y + 0.5f) / height));
            target.SetPropertyBlock(properties);
        }
    }
}
