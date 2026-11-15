using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace GeoForge
{
    public static class GeoForgeJsonLoader
    {
        public static string ResolvePath(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException("Set sceneJsonPath first.");
            return Path.GetFullPath(Path.IsPathRooted(path) ? path :
                Path.Combine(Application.dataPath, "..", path));
        }

        public static GeoForgeScene Load(string path)
        {
            string resolved = ResolvePath(path);
            try
            {
                var scene = Parse(File.ReadAllText(resolved, new UTF8Encoding(false, true)));
                Debug.Log($"GeoForge scene loaded: {resolved}\nSchema: {scene.metadata.schema_version}\n" +
                    $"Buildings: {scene.buildings.Count}\nRoads: {scene.roads.Count}\n" +
                    $"Water areas: {scene.water_areas.Count}\nGreen areas: {scene.green_areas.Count}");
                return scene;
            }
            catch (Exception ex) { throw new InvalidDataException($"Cannot load GeoForge JSON '{resolved}': {ex.Message}", ex); }
        }

        public static GeoForgeScene Parse(string json)
        {
            var root = JObject.Parse(json, new JsonLoadSettings { DuplicatePropertyNameHandling = DuplicatePropertyNameHandling.Error });
            var serializer = JsonSerializer.Create(new JsonSerializerSettings { TypeNameHandling = TypeNameHandling.None, MaxDepth = 128 });
            var metadata = root["metadata"]?.ToObject<GeoForgeMetadata>(serializer);
            if (metadata == null || (metadata.schema_version != "1.0" && metadata.schema_version != "1.1"))
                throw new InvalidDataException("Expected metadata.schema_version = '1.0' or '1.1'.");
            if (metadata.units != "meters" || metadata.axes != "X=east,Y=north,Z=up")
                throw new InvalidDataException("Expected meters and axes X=east,Y=north,Z=up.");
            // Deserialize each feature independently: a malformed feature cannot abort the file.
            return new GeoForgeScene {
                metadata = metadata,
                processing_audit = root["processing_audit"] as JObject,
                terrain = root["terrain"]?.ToObject<GeoForgeTerrainData>(serializer),
                origin = root["origin"]?.ToObject<GeoForgeOrigin>(serializer),
                bounds = root["bounds"]?.ToObject<GeoForgeBounds>(serializer),
                buildings = ReadFeatures<GeoForgeBuilding>(root, "buildings", serializer),
                roads = ReadFeatures<GeoForgeRoad>(root, "roads", serializer),
                water_areas = ReadFeatures<GeoForgeArea>(root, "water_areas", serializer),
                green_areas = ReadFeatures<GeoForgeArea>(root, "green_areas", serializer)
            };
        }

        private static List<T> ReadFeatures<T>(JObject root, string key, JsonSerializer serializer) where T : class
        {
            if (!(root[key] is JArray array)) throw new InvalidDataException($"'{key}' must be an array.");
            var result = new List<T>();
            foreach (var token in array)
            {
                try { result.Add(token.ToObject<T>(serializer)); }
                catch (Exception ex)
                {
                    string id = (token as JObject)?["id"]?.ToString() ?? "<unknown>";
                    Debug.LogWarning($"GeoForge: invalid {key} object {id}: {ex.Message}");
                    result.Add(null); // Retain input counts; generator records the failure.
                }
            }
            return result;
        }
    }
}
