using System.IO;
using System.Text;
using System.Linq;

namespace GeoForge.Editor
{
    public static class GeoForgeTerrainReferenceAudit
    {
        public static void Export()
        {
            foreach (string city in new[] { "moscow", "sevastopol" })
            {
                string folder = GeoForgeJsonLoader.ResolvePath("../../output/v05-g5/" + city);
                string input = Path.Combine(folder, "scene.json");
                var scene = GeoForgeJsonLoader.Load(input);
                var sampler = new GeoForgeTerrainSampler(scene);
                var dry = GeoForgeTerrainGenerator.Build(scene, sampler);
                using (var writer = new BinaryWriter(File.Create(Path.Combine(folder, "terrain-reference.bin"))))
                using (var sha = System.Security.Cryptography.SHA256.Create())
                {
                    writer.Write(Encoding.ASCII.GetBytes("GFM1"));
                    writer.Write(sha.ComputeHash(File.ReadAllBytes(input)));
                    writer.Write(1);
                    var key = Encoding.UTF8.GetBytes("Terrain/dry");
                    writer.Write(key.Length); writer.Write(key);
                    writer.Write(dry.Triangles.Count / 3);
                    foreach (int i in dry.Triangles)
                    {
                        var p = dry.Vertices[i];
                        writer.Write(p.x); writer.Write(p.z); writer.Write(p.y);
                    }
                }
            }
        }
    }
}
