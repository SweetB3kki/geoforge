using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

namespace GeoForge.Editor
{
    public static class GeoForgeProjectSetup
    {
        [MenuItem("GeoForge/Create Test Scene")]
        public static void CreateTestScene()
        {
            if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var root = new GameObject("GeoForge");
            var generator = root.AddComponent<GeoForgeSceneGenerator>();
            generator.buildingMaterial = MakeMaterial("Buildings", new Color(0.67f,0.59f,0.47f));
            generator.roadMaterial = MakeMaterial("RoadLocal", new Color(0.43f,0.47f,0.51f));
            generator.pedestrianMaterial = MakeMaterial("Pedestrian",new Color(0.58f,0.51f,0.40f));
            generator.cycleMaterial = MakeMaterial("Cycle",new Color(0.28f,0.43f,0.46f));
            generator.trackMaterial = MakeMaterial("Track",new Color(0.40f,0.32f,0.22f));
            generator.otherRoadMaterial = MakeMaterial("OtherRoads",new Color(0.55f,0.55f,0.55f));
            generator.motorwayMaterial = MakeMaterial("RoadMotorway",new Color(0.18f,0.22f,0.28f));
            generator.primaryMaterial = MakeMaterial("RoadPrimary",new Color(0.24f,0.29f,0.36f));
            generator.secondaryMaterial = MakeMaterial("RoadSecondary",new Color(0.32f,0.38f,0.45f));
            generator.tertiaryMaterial = MakeMaterial("RoadTertiary",new Color(0.38f,0.43f,0.48f));
            generator.serviceMaterial = MakeMaterial("RoadService",new Color(0.58f,0.61f,0.57f));
            generator.linkMaterial = MakeMaterial("RoadLink",new Color(0.49f,0.54f,0.59f));
            generator.stepsMaterial = MakeMaterial("PathSteps",new Color(0.55f,0.39f,0.51f));
            generator.crossingMaterial = MakeMaterial("PathCrossing",new Color(0.78f,0.64f,0.35f));
            generator.waterMaterial = MakeMaterial("Water", new Color(0.22f,0.55f,0.77f));
            generator.greenMaterial = MakeMaterial("Green", new Color(0.35f,0.61f,0.31f));
            var light = new GameObject("Directional Light").AddComponent<Light>();
            light.type = LightType.Directional; light.intensity = 1.1f; light.shadows = LightShadows.Soft;
            QualitySettings.shadowDistance=150;
            var sky=AssetDatabase.LoadAssetAtPath<Material>("Assets/GeoForge/Materials/GeoForgeSky.mat");
            if(sky==null){sky=new Material(Shader.Find("Skybox/Procedural"));AssetDatabase.CreateAsset(sky,"Assets/GeoForge/Materials/GeoForgeSky.mat");}
            RenderSettings.skybox=sky;
            light.transform.rotation = Quaternion.Euler(50,-30,0);
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.55f,0.55f,0.55f);
            var camera = new GameObject("Main Camera").AddComponent<Camera>();
            camera.tag = "MainCamera"; camera.farClipPlane = 10000; camera.nearClipPlane = 0.1f;
            camera.clearFlags = CameraClearFlags.Skybox; camera.backgroundColor = new Color(0.88f,0.90f,0.92f);
            camera.transform.position = new Vector3(0,650,-750);
            camera.transform.LookAt(Vector3.zero);
            camera.gameObject.AddComponent<GeoForgeFreeCamera>();
            EditorSceneManager.SaveScene(root.scene, "Assets/GeoForge/Scenes/GeoForgeTest.unity");
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene("Assets/GeoForge/Scenes/GeoForgeTest.unity", true) };
            Selection.activeGameObject = root;
            AssetDatabase.SaveAssets();
            Debug.Log("GeoForge test scene ready. Select GeoForge and click GenerateScene.");
        }
        private static Material MakeMaterial(string name, Color color)
        {
            string path = $"Assets/GeoForge/Materials/{name}.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material != null) return material;
            Directory.CreateDirectory("Assets/GeoForge/Materials");
            material = new Material(Shader.Find("Legacy Shaders/Diffuse")) { name = name, color = color };
            AssetDatabase.CreateAsset(material,path); return material;
        }
    }
}
