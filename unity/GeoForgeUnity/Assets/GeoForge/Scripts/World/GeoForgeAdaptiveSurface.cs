using System;
using UnityEngine;

namespace GeoForge
{
    public sealed class GeoForgeTriangleBudgetException : InvalidOperationException
    { public GeoForgeTriangleBudgetException() : base("DEM tessellation triangle budget reached.") {} }
    [Serializable] public sealed class GeoForgeConformSettings
    {
        public bool adaptive=true;
        public bool exactFallback=true;
        public float terrainConformToleranceMeters=0.02f,minimumTriangleEdgeMeters=0.25f;
        public int maximumSubdivisionDepth=10,maximumGeneratedTrianglesPerObject=100000;
    }
    public static class GeoForgeAdaptiveSurface
    {
        // Offsets stay in the source vertices; only terrain height is sampled.
        public static GeoForgeMeshData Build(GeoForgeMeshData source,GeoForgeTerrainSampler sampler,GeoForgeConformSettings settings,out int limits)
        {
            int stopped=0;var result=new GeoForgeMeshData();
            if(!sampler.Available){limits=0;return source;}
            if(!settings.adaptive){limits=0;return sampler.Drape(source);}
            int initial=source.Triangles.Count/3,budget=Mathf.Max(1,settings.maximumGeneratedTrianglesPerObject),reserved=initial;
            if(initial>budget)throw new ArgumentException("Input mesh exceeds maximumGeneratedTrianglesPerObject; increase the explicit budget.");
            Func<Vector3,Vector3> lift=p=>p+Vector3.up*sampler.SampleHeight(p.x,p.z);
            Action<Vector3,Vector3,Vector3,int> emit=null;
            emit=(a,b,c,depth)=>
            {
                var pa=lift(a);var pb=lift(b);var pc=lift(c);
                float error=0;
                error=Mathf.Max(error,Mathf.Abs(lift((a+b)/2).y-(pa.y+pb.y)/2));
                error=Mathf.Max(error,Mathf.Abs(lift((b+c)/2).y-(pb.y+pc.y)/2));
                error=Mathf.Max(error,Mathf.Abs(lift((c+a)/2).y-(pc.y+pa.y)/2));
                error=Mathf.Max(error,Mathf.Abs(lift((a+b+c)/3).y-(pa.y+pb.y+pc.y)/3));
                float ab=(a-b).sqrMagnitude,bc=(b-c).sqrMagnitude,ca=(c-a).sqrMagnitude;
                bool split=error>Mathf.Max(0.0001f,settings.terrainConformToleranceMeters);
                if(split&&depth<Mathf.Clamp(settings.maximumSubdivisionDepth,0,16)&&Mathf.Sqrt(Mathf.Max(ab,Mathf.Max(bc,ca)))>settings.minimumTriangleEdgeMeters&&reserved<budget)
                {
                    reserved++;
                    if(ab>=bc&&ab>=ca){var m=(a+b)/2;emit(a,m,c,depth+1);emit(m,b,c,depth+1);}
                    else if(bc>=ca){var m=(b+c)/2;emit(a,b,m,depth+1);emit(a,m,c,depth+1);}
                    else {var m=(c+a)/2;emit(a,b,m,depth+1);emit(m,b,c,depth+1);}
                    return;
                }
                if(split)stopped++;
                if(Mathf.Abs(Vector3.Cross(pb-pa,pc-pa).y)<1e-8f)return;
                int k=result.Vertices.Count;result.Vertices.Add(pa);result.Vertices.Add(pb);result.Vertices.Add(pc);result.AddUpTriangle(k,k+1,k+2);
            };
            for(int i=0;i<source.Triangles.Count;i+=3)emit(source.Vertices[source.Triangles[i]],source.Vertices[source.Triangles[i+1]],source.Vertices[source.Triangles[i+2]],0);
            // Compare to the already proven DEM-aligned tessellation. A recursive grid is
            // not an improvement when it grows more or leaves unresolved deviations.
            if(settings.exactFallback)
            {
                try
                {
                    var exact=sampler.Drape(source,budget);
                    float offset=source.Vertices.Count>0?source.Vertices[0].y:0;
                    float clearance=Mathf.Min(settings.terrainConformToleranceMeters,Mathf.Max(0.0001f,Mathf.Abs(offset)*0.25f));
                    if(stopped>0||result.Triangles.Count>=exact.Triangles.Count||!sampler.ConformsEverywhere(result,offset,clearance,budget*12))
                    {limits=0;return exact;}
                }
                catch(GeoForgeTriangleBudgetException) { stopped++; /* Verification budget exhausted; keep bounded candidate and report. */ }
            }
            limits=stopped;return result;
        }
    }
}
