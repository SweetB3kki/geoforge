using System;
using System.Collections.Generic;
using LibTessDotNet;
using UnityEngine;

namespace GeoForge
{
    /// <summary>
    /// Derived planar land surface minus replacement surfaces. Raw DEM and input
    /// meshes stay immutable. Drape the result with the original terrain sampler;
    /// replacement road meshes must supply their own collision surface.
    /// </summary>
    public static class GeoForgeGroundCutout
    {
        /// <summary>Cut an already draped mesh per source triangle. This preserves
        /// each source plane exactly and avoids tessellating long land triangles
        /// against thousands of DEM cells after a global road subtraction.</summary>
        public static GeoForgeMeshData SubtractPreservingPlanes(GeoForgeMeshData ground,
            IEnumerable<GeoForgeMeshData> replacements,int maximumTriangles=1000000)
        {
            const float cell=32;
            if(ground==null)throw new ArgumentNullException(nameof(ground));
            if(ground.Triangles.Count==0)return new GeoForgeMeshData();
            var groundBounds=BoundsOf(ground);int indexEntries=0;
            var masks=new List<GeoForgeMeshData>();
            var index=new Dictionary<(int,int),List<int>>();
            foreach(var replacement in replacements)for(int i=0;i<replacement.Triangles.Count;i+=3)
            {
                var mask=new GeoForgeMeshData();
                for(int j=0;j<3;j++)mask.Vertices.Add(replacement.Vertices[replacement.Triangles[i+j]]);
                mask.AddUpTriangle(0,1,2);
                var bounds=BoundsOf(mask);int id=masks.Count;masks.Add(mask);
                if(masks.Count>200000)throw new ArgumentException("Ground replacement input budget exceeded.");
                for(int z=Mathf.FloorToInt(Mathf.Max(bounds.min.z,groundBounds.min.z)/cell);z<=Mathf.FloorToInt(Mathf.Min(bounds.max.z,groundBounds.max.z)/cell);z++)
                for(int x=Mathf.FloorToInt(Mathf.Max(bounds.min.x,groundBounds.min.x)/cell);x<=Mathf.FloorToInt(Mathf.Min(bounds.max.x,groundBounds.max.x)/cell);x++)
                {
                    if(++indexEntries>2000000)throw new ArgumentException("Ground replacement spatial index budget exceeded.");
                    var key=(x,z);if(!index.TryGetValue(key,out var entries)){entries=new List<int>();index.Add(key,entries);}
                    entries.Add(id);
                }
            }
            var result=new GeoForgeMeshData();
            for(int i=0;i<ground.Triangles.Count;i+=3)
            {
                var triangle=new GeoForgeMeshData();
                for(int j=0;j<3;j++)triangle.Vertices.Add(ground.Vertices[ground.Triangles[i+j]]);
                triangle.AddUpTriangle(0,1,2);var bounds=BoundsOf(triangle);
                var ids=new HashSet<int>();
                for(int z=Mathf.FloorToInt(bounds.min.z/cell);z<=Mathf.FloorToInt(bounds.max.z/cell);z++)
                for(int x=Mathf.FloorToInt(bounds.min.x/cell);x<=Mathf.FloorToInt(bounds.max.x/cell);x++)
                    if(index.TryGetValue((x,z),out var entries))foreach(int id in entries)ids.Add(id);
                var candidates=new List<GeoForgeMeshData>();
                foreach(int id in ids)
                {
                    var other=BoundsOf(masks[id]);
                    if(other.max.x>=bounds.min.x&&other.min.x<=bounds.max.x&&other.max.z>=bounds.min.z&&other.min.z<=bounds.max.z)candidates.Add(masks[id]);
                }
                var clipped=candidates.Count==0?triangle:Subtract(triangle,candidates);
                var a=triangle.Vertices[0];var b=triangle.Vertices[1];var c=triangle.Vertices[2];
                double determinant=(b.z-c.z)*(double)(a.x-c.x)+(c.x-b.x)*(double)(a.z-c.z);
                if(Math.Abs(determinant)<1e-12)continue;
                int first=result.Vertices.Count;
                foreach(var point in clipped.Vertices)
                {
                    double u=((b.z-c.z)*(double)(point.x-c.x)+(c.x-b.x)*(double)(point.z-c.z))/determinant;
                    double v=((c.z-a.z)*(double)(point.x-c.x)+(a.x-c.x)*(double)(point.z-c.z))/determinant;
                    result.Vertices.Add(new Vector3(point.x,(float)(u*a.y+v*b.y+(1-u-v)*c.y),point.z));
                }
                foreach(int vertex in clipped.Triangles)result.Triangles.Add(first+vertex);
                if(result.Triangles.Count/3>maximumTriangles)throw new ArgumentException("Derived ground triangle budget exceeded.");
            }
            return result;
        }
        private static Bounds BoundsOf(GeoForgeMeshData mesh)
        {
            var bounds=new Bounds(mesh.Vertices[0],Vector3.zero);
            foreach(var p in mesh.Vertices)bounds.Encapsulate(p);
            return bounds;
        }
        public static GeoForgeMeshData Subtract(GeoForgeMeshData ground,
            IEnumerable<GeoForgeMeshData> replacements, int maximumInputTriangles = 200000)
        {
            if (ground == null) throw new ArgumentNullException(nameof(ground));
            var tess = new Tess();
            int count = 0;
            Add(tess, ground, false, ref count, maximumInputTriangles);
            if(ground.Vertices.Count==0)return new GeoForgeMeshData();
            var bounds=new Bounds(ground.Vertices[0],Vector3.zero);
            foreach(var p in ground.Vertices)bounds.Encapsulate(p);
            foreach (var replacement in replacements)
            {
                if(replacement==null)throw new ArgumentNullException(nameof(replacements));
                if(replacement.Vertices.Count==0)continue;
                var other=new Bounds(replacement.Vertices[0],Vector3.zero);
                foreach(var p in replacement.Vertices)other.Encapsulate(p);
                if(other.max.x<bounds.min.x||other.min.x>bounds.max.x||other.max.z<bounds.min.z||other.min.z>bounds.max.z)continue;
                Add(tess, replacement, true, ref count, maximumInputTriangles);
            }
            // Ground is triangulated without overlapping interiors. Its winding is
            // one, so one or more overlapping negative masks remove the same region.
            tess.Tessellate(WindingRule.Positive, ElementType.Polygons, 3,
                normal: new Vec3(0, 0, 1));
            var result = new GeoForgeMeshData();
            float offset = ground.Vertices.Count == 0 ? 0 : ground.Vertices[0].y;
            foreach (var vertex in tess.Vertices ?? new ContourVertex[0])
                result.Vertices.Add(new Vector3(vertex.Position.X, offset, vertex.Position.Y));
            for (int i = 0; i < tess.ElementCount; i++)
            {
                int a = tess.Elements[i * 3], b = tess.Elements[i * 3 + 1], c = tess.Elements[i * 3 + 2];
                if (a != Tess.Undef && b != Tess.Undef && c != Tess.Undef &&
                    !IsClippingSliver(result.Vertices[a],result.Vertices[b],result.Vertices[c]))
                    result.AddUpTriangle(a, b, c);
            }
            return result;
        }

        // Float tessellation can leave micrometre-wide fragments along internal
        // mask edges. PhysX can still hit their tips above the replacement road.
        // Discard derived triangles with minimum planar altitude <= 0.1 mm.
        // This tolerance affects only the clipped surface, never source DEM data.
        private static bool IsClippingSliver(Vector3 a,Vector3 b,Vector3 c)
        {
            double abx=(double)b.x-a.x,abz=(double)b.z-a.z;
            double acx=(double)c.x-a.x,acz=(double)c.z-a.z;
            double bcx=(double)c.x-b.x,bcz=(double)c.z-b.z;
            double longest=Math.Sqrt(Math.Max(abx*abx+abz*abz,Math.Max(acx*acx+acz*acz,bcx*bcx+bcz*bcz)));
            return Math.Abs(abx*acz-abz*acx)<=0.0001*longest;
        }

        private static void Add(Tess tess, GeoForgeMeshData mesh, bool subtract,
            ref int count, int maximum)
        {
            if (mesh == null) throw new ArgumentNullException(nameof(mesh));
            if (mesh.Triangles.Count % 3 != 0) throw new ArgumentException("Invalid triangle index count.");
            for (int i = 0; i < mesh.Triangles.Count; i += 3)
            {
                if (++count > maximum) throw new ArgumentException("Ground cutout triangle budget exceeded.");
                var a = mesh.Vertices[mesh.Triangles[i]];
                var b = mesh.Vertices[mesh.Triangles[i + 1]];
                var c = mesh.Vertices[mesh.Triangles[i + 2]];
                foreach (var point in new[] { a, b, c })
                    if (!GeoForgeCoordinateConverter.IsFinite(point.x) || !GeoForgeCoordinateConverter.IsFinite(point.z))
                        throw new ArgumentException("Nonfinite cutout coordinate.");
                float signed = (b.x - a.x) * (c.z - a.z) - (b.z - a.z) * (c.x - a.x);
                if (Mathf.Abs(signed) < 1e-8f) continue;
                if ((signed > 0) == subtract) { var swap = b; b = c; c = swap; }
                tess.AddContour(new[] { Vertex(a), Vertex(b), Vertex(c) });
            }
        }

        private static ContourVertex Vertex(Vector3 p)
            => new ContourVertex { Position = new Vec3(p.x, p.z, 0) };
    }
}
