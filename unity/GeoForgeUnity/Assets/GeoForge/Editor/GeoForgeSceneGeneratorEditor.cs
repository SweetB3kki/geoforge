using System;
using UnityEditor;
using UnityEngine;

namespace GeoForge.Editor
{
    [CustomEditor(typeof(GeoForgeSceneGenerator))]
    public sealed class GeoForgeSceneGeneratorEditor : UnityEditor.Editor
    {
        public override void OnInspectorGUI()
        {
            DrawDefaultInspector();
            var generator = (GeoForgeSceneGenerator)target;
            if (GUILayout.Button("Choose scene.json"))
            {
                string path = EditorUtility.OpenFilePanel("GeoForge scene", "", "json");
                if (!string.IsNullOrEmpty(path))
                { Undo.RecordObject(generator, "Select GeoForge scene"); generator.sceneJsonPath = path; EditorUtility.SetDirty(generator); }
            }
            if (GUILayout.Button("LoadScene")) generator.LoadScene();
            if (GUILayout.Button("GenerateScene"))
            {
                try { generator.GenerateScene(); SceneView.RepaintAll(); }
                catch (Exception ex) { Debug.LogError($"GeoForge: {ex.Message}", generator); }
            }
            if (GUILayout.Button("ClearGeneratedScene")) generator.ClearGeneratedScene();
            if (generator.LastStatistics != null) EditorGUILayout.HelpBox(generator.LastStatistics.ToString(), MessageType.Info);
            if(Application.isPlaying && generator.Player!=null)
            {EditorGUILayout.LabelField("Player FPS",generator.Player.SmoothedFps.ToString("F1"));Repaint();}
        }
    }
}
