using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeRoadProfileSurfaceTests
    {
        private static GeoForgeRoadVerticalProfile Profile()=>new GeoForgeRoadVerticalProfile{
            points=new[]{new[]{0d,0d,10d},new[]{50d,0d,12d},new[]{100d,0d,11d}}};
        private static GeoForgeMeshData Strip()
        {
            var road=new GeoForgeRoad{id="r",width=6,path=new[]{new[]{0d,0d,0d},new[]{100d,0d,0d}}};
            return GeoForgeRoadGenerator.Build(road);
        }
        [Test]
        public void MeshFollowsProfileAcrossWidthAndKeepsPlanarArea()
        {
            var source=Strip();var profile=Profile();var mesh=GeoForgeRoadProfileSurface.Build(source,profile);
            double area=0;
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var a=mesh.Vertices[mesh.Triangles[i]];var b=mesh.Vertices[mesh.Triangles[i+1]];var c=mesh.Vertices[mesh.Triangles[i+2]];
                area+=Math.Abs(Vector3.Cross(b-a,c-a).y)/2;
            }
            Assert.That(area,Is.EqualTo(600).Within(0.001));
            Assert.That(mesh.Triangles.Count,Is.GreaterThan(source.Triangles.Count));
            foreach(var p in mesh.Vertices)
                Assert.That(p.y,Is.EqualTo(GeoForgeRoadProfileSurface.Height(profile,p.x,p.z)+0.03f).Within(0.0001));
            foreach(var p in source.Vertices)Assert.That(p.y,Is.EqualTo(0.03f));
            Assert.That(GeoForgeRoadProfileSurface.Height(profile,50,3),Is.EqualTo(12));
        }
        [Test]
        public void ShortTrianglesRefineAtProfileCrestWithoutChangingTheirFootprint()
        {
            var source=new GeoForgeMeshData();
            source.Vertices.AddRange(new[]{new Vector3(0,0,0),new Vector3(4,0,0),new Vector3(0,0,2)});
            source.AddUpTriangle(0,1,2);
            var profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{0d,0d,0d},new[]{2d,0d,0.2d},new[]{4d,0d,0d}}};
            var mesh=GeoForgeRoadProfileSurface.Build(source,profile);
            Assert.That(mesh.Triangles.Count,Is.GreaterThan(3));
            double area=0;
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var a=mesh.Vertices[mesh.Triangles[i]];var b=mesh.Vertices[mesh.Triangles[i+1]];var c=mesh.Vertices[mesh.Triangles[i+2]];
                area+=Math.Abs(Vector3.Cross(b-a,c-a).y)/2;
                var midpoint=(a+b+c)/3;
                Assert.That(midpoint.y,Is.EqualTo(GeoForgeRoadProfileSurface.Height(profile,midpoint.x,midpoint.z)).Within(0.011));
            }
            Assert.That(area,Is.EqualTo(4).Within(0.0001));
            Assert.That(source.Vertices.TrueForAll(p=>p.y==0),Is.True);
            Assert.Throws<ArgumentException>(()=>GeoForgeRoadProfileSurface.Build(source,profile,maximumHeightErrorMeters:float.NaN));
        }
        [Test]
        public void OffGridConditionedStationsAreVerticesOfTheRenderedSurface()
        {
            var source=Strip();
            var profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{0d,0d,0d},new[]{1.37d,0d,0.009d},new[]{100d,0d,0d}}};
            var mesh=GeoForgeRoadProfileSurface.Build(source,profile);
            foreach(var station in profile.points)
            {
                var vertices=mesh.Vertices.Where(v=>Math.Abs(v.x-station[0])<0.00001&&Math.Abs(v.z-station[1])<0.00001).ToArray();
                Assert.That(vertices,Is.Not.Empty);
                foreach(var vertex in vertices)Assert.That(vertex.y,Is.EqualTo(station[2]+0.03).Within(0.00001));
            }
            double area=0;
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var a=mesh.Vertices[mesh.Triangles[i]];var b=mesh.Vertices[mesh.Triangles[i+1]];var c=mesh.Vertices[mesh.Triangles[i+2]];
                area+=Math.Abs(Vector3.Cross(b-a,c-a).y)/2;
            }
            Assert.That(area,Is.EqualTo(600).Within(0.001));
        }
        [Test]
        public void StationWithinFloatEdgeToleranceIsInsertedInTheAdjacentFace()
        {
            var source=new GeoForgeMeshData();
            source.Vertices.AddRange(new[]{new Vector3(0,0,0),new Vector3(4,0,0),new Vector3(0,0,4)});
            source.AddUpTriangle(0,1,2);
            var profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{0d,0d,0d},new[]{2d,2.00002d,0.009d},new[]{4d,4d,0d}}};
            var mesh=GeoForgeRoadProfileSurface.Build(source,profile);
            Assert.That(mesh.Vertices.Any(p=>Math.Abs(p.x-2)<0.000001&&Math.Abs(p.z-2.00002)<0.000001&&Math.Abs(p.y-0.009)<0.000001),Is.True);
            double area=0;
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var a=mesh.Vertices[mesh.Triangles[i]];var b=mesh.Vertices[mesh.Triangles[i+1]];var c=mesh.Vertices[mesh.Triangles[i+2]];
                area+=Math.Abs(Vector3.Cross(b-a,c-a).y)/2;
            }
            Assert.That(area,Is.EqualTo(8).Within(0.0001));
        }
        [Test]
        public void AcuteFaceToleranceDoesNotCaptureDistantProfileStations()
        {
            var source=new GeoForgeMeshData();
            source.Vertices.AddRange(new[]{new Vector3(0,0,0),new Vector3(5,0,0),new Vector3(2,0,0.0002f)});
            source.AddUpTriangle(0,1,2);
            var profile=new GeoForgeRoadVerticalProfile{points=Enumerable.Range(0,200).Select(i=>new[]{(double)i,0d,i*0.01d}).ToArray()};
            var mesh=GeoForgeRoadProfileSurface.Build(source,profile,maximumTriangles:100);
            foreach(var p in mesh.Vertices)
            {
                Assert.That(p.x,Is.InRange(-0.0001f,5.0001f));
                Assert.That(p.z,Is.InRange(-0.0001f,0.0003f));
            }
        }
        [Test]
        public void HiddenTunnelProducesNoSurfaceAndInvalidProfilesFail()
        {
            var profile=Profile();profile.surface_visible=false;
            Assert.That(GeoForgeRoadProfileSurface.Build(Strip(),profile).Triangles,Is.Empty);
            profile.surface_visible=true;
            Assert.Throws<ArgumentException>(()=>GeoForgeRoadProfileSurface.Build(Strip(),profile,5,2));
            profile.points[1][2]=double.NaN;
            Assert.Throws<ArgumentException>(()=>GeoForgeRoadProfileSurface.Build(Strip(),profile));
        }
        [Test]
        public void SharedSeamIsStitchedWithoutMovingPlanarGeometryOrJoiningLayers()
        {
            var a=new GeoForgeRoad{id="a",width=2,path=new[]{new[]{0d,0d,0d},new[]{10d,0d,0d}},node_ids=new List<string>{"a","j"}};
            var b=new GeoForgeRoad{id="b",width=2,path=new[]{new[]{10d,0d,0d},new[]{20d,0d,0d}},node_ids=new List<string>{"j","b"}};
            var ma=GeoForgeRoadGenerator.Build(a);var mb=GeoForgeRoadGenerator.Build(b);
            for(int i=0;i<mb.Vertices.Count;i++)mb.Vertices[i]+=Vector3.up;
            var before=ma.Vertices.Concat(mb.Vertices).Select(p=>new Vector2(p.x,p.z)).ToArray();
            var meshes=new Dictionary<GeoForgeRoad,GeoForgeMeshData>{{a,ma},{b,mb}};
            b.layer=1;Assert.That(GeoForgeRoadProfileSurface.StitchSharedVertices(meshes),Is.Zero);
            b.layer=0;Assert.That(GeoForgeRoadProfileSurface.StitchSharedVertices(meshes),Is.EqualTo(2));
            foreach(var p in ma.Vertices.Concat(mb.Vertices).Where(p=>Math.Abs(p.x-10)<0.001))Assert.That(p.y,Is.EqualTo(0.53f).Within(0.0001));
            CollectionAssert.AreEqual(before,ma.Vertices.Concat(mb.Vertices).Select(p=>new Vector2(p.x,p.z)).ToArray());
        }
        [Test]
        public void SharedPatchCannotAverageAwayAConditionedStation()
        {
            var a=new GeoForgeRoad{id="a",width=2,path=new[]{new[]{0d,0d,0d},new[]{10d,0d,0d}},node_ids=new List<string>{"a","j"},
                vertical_profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{0d,0d,1d},new[]{10d,0d,1d}}}};
            var b=new GeoForgeRoad{id="b",width=2,path=new[]{new[]{10d,0d,0d},new[]{20d,0d,0d}},node_ids=new List<string>{"j","b"}};
            var ma=new GeoForgeMeshData();ma.Vertices.Add(new Vector3(10.0001f,2.03f,0));ma.Vertices.Add(new Vector3(10,1.03f,0));
            var mb=new GeoForgeMeshData();mb.Vertices.Add(new Vector3(10,2.03f,0));
            GeoForgeRoadProfileSurface.StitchSharedVertices(new Dictionary<GeoForgeRoad,GeoForgeMeshData>{{a,ma},{b,mb}});
            Assert.That(ma.Vertices[0].y,Is.EqualTo(1.03f));
            Assert.That(mb.Vertices[0].y,Is.EqualTo(1.03f));
            var built=GeoForgeRoadProfileSurface.Build(Strip(),a.vertical_profile,heightSampler:(x,z)=>9);
            Assert.That(built.Vertices.Any(p=>p.x==10&&p.z==0&&Math.Abs(p.y-1.03f)<0.00001),Is.True);
        }
        [Test]
        public void TransitionMeshBeyondSourceEndpointUsesConnectedProfileInsteadOfClamping()
        {
            var a=new GeoForgeRoad{id="a",width=6,path=new[]{new[]{0d,0d,0d},new[]{10d,0d,0d}},node_ids=new List<string>{"a","j"},
                vertical_profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{0d,0d,0d},new[]{10d,0d,1d}}}};
            var b=new GeoForgeRoad{id="b",width=6,path=new[]{new[]{10d,0d,0d},new[]{20d,0d,0d}},node_ids=new List<string>{"j","b"},
                vertical_profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{10d,0d,1d},new[]{20d,0d,2d}}}};
            var roads=new[]{a,b};var settings=new GeoForgeRoadGeometrySettings();
            Assert.That(GeoForgeRoadProfileSurface.ConnectedHeight(a,roads,settings)(15,2),Is.EqualTo(1.5f).Within(0.001));
            b.layer=1;
            Assert.That(GeoForgeRoadProfileSurface.ConnectedHeight(a,roads,settings)(15,2),Is.EqualTo(1f).Within(0.001));
        }
        [Test]
        public void JunctionHeightIsContinuousAcrossNearestRoadBisectorAndPreservesAxes()
        {
            var a=new GeoForgeRoad{id="a",width=6,path=new[]{new[]{0d,0d,0d},new[]{30d,0d,0d}},node_ids=new List<string>{"j","a"}};
            var b=new GeoForgeRoad{id="b",width=6,path=new[]{new[]{0d,0d,0d},new[]{0d,30d,0d}},node_ids=new List<string>{"j","b"}};
            a.vertical_profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{0d,0d,0d},new[]{30d,0d,6d}}};
            b.vertical_profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{0d,0d,0d},new[]{0d,30d,-6d}}};
            var roads=new[]{a,b};var settings=new GeoForgeRoadGeometrySettings();
            var fa=GeoForgeRoadProfileSurface.ConnectedHeight(a,roads,settings);
            var fb=GeoForgeRoadProfileSurface.ConnectedHeight(b,roads,settings);
            Assert.That(Math.Abs(fa(2,1.999f)-fa(2,2.001f)),Is.LessThan(0.01f),"Nearest-road switch must not create a height step");
            Assert.That(fa(2,2),Is.EqualTo(fb(2,2)).Within(0.00001));
            Assert.That(fa(2,0),Is.EqualTo(0.4f).Within(0.00001));
            Assert.That(fb(0,2),Is.EqualTo(-0.4f).Within(0.00001));
            b.layer=1;
            Assert.That(GeoForgeRoadProfileSurface.ConnectedHeight(a,roads,settings)(2,2),Is.EqualTo(0.4f).Within(0.00001));
        }
        [Test]
        public void BendWithinOneProfileHasNoNearestSegmentStep()
        {
            var profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{30d,0d,6d},new[]{0d,0d,0d},new[]{0d,30d,-6d}}};
            Assert.That(Math.Abs(GeoForgeRoadProfileSurface.Height(profile,2,1.999f)-GeoForgeRoadProfileSurface.Height(profile,2,2.001f)),Is.LessThan(0.01));
            Assert.That(GeoForgeRoadProfileSurface.Height(profile,2,0),Is.EqualTo(0.4).Within(0.00001));
            Assert.That(GeoForgeRoadProfileSurface.Height(profile,0,2),Is.EqualTo(-0.4).Within(0.00001));
            var source=new GeoForgeMeshData();
            source.Vertices.AddRange(new[]{new Vector3(0,0,0),new Vector3(4,0,0),new Vector3(4,0,4),new Vector3(0,0,4)});
            source.AddUpTriangle(0,1,2);source.AddUpTriangle(0,2,3);
            var mesh=GeoForgeRoadProfileSurface.Build(source,profile).ToMesh("bend regression");
            var go=new GameObject("bend collider");
            try
            {
                var collider=go.AddComponent<MeshCollider>();collider.sharedMesh=mesh;Physics.SyncTransforms();
                Assert.That(collider.Raycast(new Ray(new Vector3(2,10,1.999f),Vector3.down),out var first,20),Is.True);
                Assert.That(collider.Raycast(new Ray(new Vector3(2,10,2.001f),Vector3.down),out var second,20),Is.True);
                Assert.That(Math.Abs(first.point.y-second.point.y),Is.LessThan(0.01));
                Assert.That(first.point.y,Is.EqualTo(0).Within(0.011));
            }
            finally{UnityEngine.Object.DestroyImmediate(go);UnityEngine.Object.DestroyImmediate(mesh);}
        }
        [Test]
        public void CollinearStationsDoNotDistortHeightAcrossRoadWidth()
        {
            var profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{0d,0d,0d},new[]{2d,0d,1d},new[]{5d,0d,0d},new[]{10d,0d,2d}}};
            foreach(float x in new[]{0f,1f,2f,3f,5f,7f,10f})
            foreach(float z in new[]{-10f,-3f,0f,3f,10f})
                Assert.That(GeoForgeRoadProfileSurface.Height(profile,x,z),Is.EqualTo(GeoForgeRoadProfileSurface.Height(profile,x,0)).Within(0.00001));
        }
    }
}
