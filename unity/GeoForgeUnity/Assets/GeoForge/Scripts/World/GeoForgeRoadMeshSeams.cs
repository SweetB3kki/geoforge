using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace GeoForge
{
    /// <summary>Insert existing edge vertices into neighbouring coarse faces.
    /// Adaptive faces otherwise form T-junctions with different interpolated heights.</summary>
    public static class GeoForgeRoadMeshSeams
    {
        public static GeoForgeMeshData Conform(GeoForgeMeshData source,int maximumTriangles=100000)
        {
            const double tolerance=0.0001;
            const float cell=5;
            var unique=new List<Vector3>();var ids=new Dictionary<(float,float),int>();
            var index=new Dictionary<(int,int),List<int>>();
            var mapped=new int[source.Vertices.Count];
            for(int i=0;i<source.Vertices.Count;i++)
            {
                var p=source.Vertices[i];var key=(p.x,p.z);
                if(!ids.TryGetValue(key,out int id))
                {
                    id=unique.Count;ids.Add(key,id);unique.Add(p);
                    var bucket=(Mathf.FloorToInt(p.x/cell),Mathf.FloorToInt(p.z/cell));
                    if(!index.TryGetValue(bucket,out var list)){list=new List<int>();index.Add(bucket,list);}list.Add(id);
                }
                mapped[i]=id;
            }
            var cache=new Dictionary<(int,int),int[]>();
            int[] Edge(int first,int last)
            {
                var key=(Math.Min(first,last),Math.Max(first,last));
                if(cache.TryGetValue(key,out var found))return found;
                var a=unique[key.Item1];var b=unique[key.Item2];
                double dx=(double)b.x-a.x,dz=(double)b.z-a.z,length2=dx*dx+dz*dz;
                var points=new List<(double t,int id)>();
                if(length2>tolerance*tolerance)
                {
                    double length=Math.Sqrt(length2);
                    for(int ix=Mathf.FloorToInt((Math.Min(a.x,b.x)-(float)tolerance)/cell);ix<=Mathf.FloorToInt((Math.Max(a.x,b.x)+(float)tolerance)/cell);ix++)
                    for(int iz=Mathf.FloorToInt((Math.Min(a.z,b.z)-(float)tolerance)/cell);iz<=Mathf.FloorToInt((Math.Max(a.z,b.z)+(float)tolerance)/cell);iz++)
                    {
                        if(!index.TryGetValue((ix,iz),out var candidates))continue;
                        foreach(int id in candidates)
                        {
                            if(id==first||id==last)continue;
                            var p=unique[id];double px=(double)p.x-a.x,pz=(double)p.z-a.z;
                            double t=(px*dx+pz*dz)/length2;
                            if(t*length<=tolerance||(1-t)*length<=tolerance)continue;
                            if(Math.Abs(px*dz-pz*dx)>tolerance*length)continue;
                            points.Add((t,id));
                        }
                    }
                }
                found=points.OrderBy(p=>p.t).ThenBy(p=>p.id).Select(p=>p.id).ToArray();cache.Add(key,found);return found;
            }
            var result=new GeoForgeMeshData();
            void Emit(Vector3 a,Vector3 b,Vector3 c)
            {
                double area=Math.Abs(((double)b.x-a.x)*((double)c.z-a.z)-((double)b.z-a.z)*((double)c.x-a.x));
                if(area<1e-12)return;
                if(result.Triangles.Count/3>=maximumTriangles)throw new ArgumentException("Conforming road mesh exceeds triangle budget.");
                int k=result.Vertices.Count;result.Vertices.Add(a);result.Vertices.Add(b);result.Vertices.Add(c);result.AddUpTriangle(k,k+1,k+2);
            }
            for(int i=0;i<source.Triangles.Count;i+=3)
            {
                var triangle=new[]{mapped[source.Triangles[i]],mapped[source.Triangles[i+1]],mapped[source.Triangles[i+2]]};
                var boundary=new List<int>();bool changed=false;
                for(int j=0;j<3;j++)
                {
                    int a=triangle[j],b=triangle[(j+1)%3];boundary.Add(a);var edge=Edge(a,b);
                    changed|=edge.Length>0;
                    if(a<b)boundary.AddRange(edge);else for(int k=edge.Length-1;k>=0;k--)boundary.Add(edge[k]);
                }
                if(!changed){Emit(unique[triangle[0]],unique[triangle[1]],unique[triangle[2]]);continue;}
                var center=(unique[triangle[0]]+unique[triangle[1]]+unique[triangle[2]])/3;
                for(int j=0;j<boundary.Count;j++)Emit(center,unique[boundary[j]],unique[boundary[(j+1)%boundary.Count]]);
            }
            return result;
        }
    }
}
