using System;
using System.Collections.Generic;
using LibTessDotNet;
using UnityEngine;

namespace GeoForge
{
    /// <summary>Validated planar rings and even-odd tessellation; courtyards stay open.</summary>
    public static class GeoForgeTriangulator
    {
        public sealed class Polygon
        {
            public readonly List<List<Vector3>> Rings = new List<List<Vector3>>();
            public double Area;
        }

        public static Polygon Prepare(GeoForgePolygon source)
        {
            if (source == null) throw new ArgumentException("Missing polygon.");
            var polygon = new Polygon();
            polygon.Rings.Add(ReadRing(source.exterior, true));
            foreach (var hole in source.holes ?? Array.Empty<double[][]>())
                polygon.Rings.Add(ReadRing(hole, false));
            float altitude = polygon.Rings[0][0].y;
            for (int r = 0; r < polygon.Rings.Count; r++)
            {
                var ring = polygon.Rings[r];
                foreach (var point in ring)
                    if (Math.Abs(point.y - altitude) > 0.001) throw new ArgumentException("Polygon must be horizontal (no terrain support).");
                polygon.Area += SignedArea(ring);
                if (r > 0 && !Contains(polygon.Rings[0], ring[0]))
                    throw new ArgumentException("Hole lies outside exterior.");
                for (int s = 0; s < r; s++)
                {
                    if (RingsIntersect(ring, polygon.Rings[s])) throw new ArgumentException("Polygon rings intersect or touch.");
                    if (s > 0 && (Contains(ring, polygon.Rings[s][0]) || Contains(polygon.Rings[s], ring[0])))
                        throw new ArgumentException("Nested/overlapping holes are unsupported.");
                }
            }
            if (polygon.Area <= 1e-10) throw new ArgumentException("Polygon has no usable area.");
            return polygon;
        }

        private static List<Vector3> ReadRing(double[][] source, bool exterior)
        {
            if (source == null) throw new ArgumentException("Missing polygon ring.");
            var ring = new List<Vector3>();
            foreach (var point in source)
            {
                var mapped = GeoForgeCoordinateConverter.GeoForgeToUnity(point);
                if (ring.Count == 0 || (mapped - ring[ring.Count - 1]).sqrMagnitude > 1e-14f) ring.Add(mapped);
            }
            if (ring.Count > 1 && (ring[0] - ring[ring.Count - 1]).sqrMagnitude < 1e-14f) ring.RemoveAt(ring.Count - 1);
            if (ring.Count < 3 || Math.Abs(SignedArea(ring)) <= 1e-10) throw new ArgumentException("Degenerate polygon ring.");
            for (int i = 0; i < ring.Count; i++)
                for (int j = i + 1; j < ring.Count; j++)
                    if (j != i + 1 && !(i == 0 && j == ring.Count - 1) &&
                        Intersects(ring[i], ring[(i + 1) % ring.Count], ring[j], ring[(j + 1) % ring.Count]))
                        throw new ArgumentException("Self-intersecting ring.");
            if ((SignedArea(ring) > 0) != exterior) ring.Reverse();
            return ring;
        }

        public static double SignedArea(List<Vector3> ring)
        {
            double sum = 0;
            // Shift before products to retain precision for small polygons far from zero.
            var origin = ring[0];
            for (int i = 0; i < ring.Count; i++)
            {
                var a = ring[i] - origin; var b = ring[(i + 1) % ring.Count] - origin;
                sum += (double)a.x * b.z - (double)b.x * a.z;
            }
            return sum / 2;
        }
        private static double Cross(Vector3 a, Vector3 b, Vector3 c) =>
            ((double)b.x - a.x) * ((double)c.z - a.z) - ((double)b.z - a.z) * ((double)c.x - a.x);
        private static bool OnSegment(Vector3 a, Vector3 b, Vector3 p) =>
            Math.Abs(Cross(a, b, p)) < 1e-10 && p.x >= Math.Min(a.x,b.x) && p.x <= Math.Max(a.x,b.x) &&
            p.z >= Math.Min(a.z,b.z) && p.z <= Math.Max(a.z,b.z);
        private static bool Intersects(Vector3 a, Vector3 b, Vector3 c, Vector3 d) =>
            (Cross(a,b,c) * Cross(a,b,d) < 0 && Cross(c,d,a) * Cross(c,d,b) < 0) ||
            OnSegment(a,b,c) || OnSegment(a,b,d) || OnSegment(c,d,a) || OnSegment(c,d,b);
        private static bool RingsIntersect(List<Vector3> a, List<Vector3> b)
        {
            for (int i = 0; i < a.Count; i++) for (int j = 0; j < b.Count; j++)
                if (Intersects(a[i], a[(i+1)%a.Count], b[j], b[(j+1)%b.Count])) return true;
            return false;
        }
        private static bool Contains(List<Vector3> ring, Vector3 p)
        {
            bool inside = false;
            for (int i = 0, j = ring.Count - 1; i < ring.Count; j = i++)
            {
                var a = ring[i]; var b = ring[j];
                if ((a.z > p.z) != (b.z > p.z) && p.x < ((double)b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x) inside = !inside;
            }
            return inside;
        }

        public static GeoForgeMeshData Triangulate(Polygon polygon, float elevation = 0)
        {
            var tess = new Tess();
            foreach (var ring in polygon.Rings)
            {
                var contour = new ContourVertex[ring.Count];
                for (int i = 0; i < ring.Count; i++)
                    contour[i].Position = new Vec3(ring[i].x, ring[i].z, 0);
                tess.AddContour(contour);
            }
            tess.Tessellate(WindingRule.EvenOdd, ElementType.Polygons, 3, normal: new Vec3(0,0,1));
            var mesh = new GeoForgeMeshData();
            foreach (var vertex in tess.Vertices)
                mesh.Vertices.Add(new Vector3(vertex.Position.X, polygon.Rings[0][0].y + elevation, vertex.Position.Y));
            double area = 0;
            for (int i = 0; i < tess.ElementCount; i++)
            {
                int a = tess.Elements[3*i], b = tess.Elements[3*i+1], c = tess.Elements[3*i+2];
                if (a == Tess.Undef || b == Tess.Undef || c == Tess.Undef) continue;
                double triangleArea = Math.Abs(Cross(mesh.Vertices[a], mesh.Vertices[b], mesh.Vertices[c])) / 2;
                if (triangleArea <= 1e-12) continue;
                area += triangleArea;
                mesh.AddUpTriangle(a,b,c);
            }
            if (mesh.Triangles.Count == 0 || Math.Abs(area-polygon.Area) > Math.Max(1e-7, polygon.Area * 1e-4))
                throw new ArgumentException("Tessellation area check failed; polygon skipped.");
            return mesh;
        }
    }
}
