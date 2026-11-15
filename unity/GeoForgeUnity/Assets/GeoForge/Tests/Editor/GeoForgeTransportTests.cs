using System.Linq;
using NUnit.Framework;

namespace GeoForge.Tests
{
    public sealed class GeoForgeTransportTests
    {
        [Test]
        public void EnrichedWidthFlowsFromJsonIntoRoadMesh()
        {
            string json="{\"metadata\":{\"schema_version\":\"1.1\",\"units\":\"meters\",\"axes\":\"X=east,Y=north,Z=up\"},\"buildings\":[],\"water_areas\":[],\"green_areas\":[],\"roads\":[{\"id\":\"r\",\"road_type\":\"residential\",\"road_category\":\"automotive\",\"width\":8.5,\"width_source\":\"overture_width_rule\",\"path\":[[0,0,0],[30,0,0]],\"width_rules\":[{\"value\":8.5,\"between\":null}],\"transportation_matches\":[{\"confidence\":1}]}]}";
            var scene=GeoForgeJsonLoader.Parse(json);var road=scene.roads[0];
            Assert.That(road.width_source,Is.EqualTo("overture_width_rule"));
            var mesh=GeoForgeRoadGenerator.BuildNetwork(scene.roads,new GeoForgeRoadGeometrySettings()).Mesh(road);
            Assert.That(mesh.Vertices.Max(v=>v.z)-mesh.Vertices.Min(v=>v.z),Is.EqualTo(8.5f).Within(0.001));
        }
    }
}
