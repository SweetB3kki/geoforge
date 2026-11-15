using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace GeoForge
{
    [Serializable] public sealed class GeoForgeBuildingFit
    {
        public string id;
        public float baseElevation,minimumTerrainUnderFootprint,maximumTerrainUnderFootprint,medianTerrainHeight;
        public float terrainHeightRange,maximumGap,maximumPenetration,foundationDepth,remainingGap;
        public Vector3 center;
    }
    [Serializable] public sealed class GeoForgeSurfaceQuality
    {
        public string id,category;
        public int verticesChecked,trianglesChecked,samples,floatingSamples,terrainPenetrations,degenerateTriangles,limitReached;
        public float maxTerrainErrorMeters,averageTerrainErrorMeters;
    }
    public static class GeoForgeGeometryQuality
    {
        public static GeoForgeBuildingFit Building(GeoForgeBuilding b,GeoForgeTerrainSampler sampler,bool enabled,float threshold,float maxDepth)
        {
            var polygon=GeoForgeTriangulator.Prepare(b.footprint);
            var heights=new List<float>();var center=Vector3.zero;int count=0;
            foreach(var ring in polygon.Rings)for(int i=0;i<ring.Count;i++)
            {
                var a=ring[i];var end=ring[(i+1)%ring.Count];center+=a;count++;
                int steps=Mathf.Clamp(Mathf.CeilToInt(Vector3.Distance(a,end)/Mathf.Max(1,sampler.CellSize/2)),1,256);
                for(int k=0;k<steps;k++){var p=Vector3.Lerp(a,end,(float)k/steps);heights.Add(sampler.SampleHeight(p.x,p.z));}
            }
            center/=count;
            if(GeoForgeSpawnManager.Contains(b.footprint,center.x,center.z))heights.Add(sampler.SampleHeight(center.x,center.z));
            float minX=(float)b.footprint.exterior.Min(p=>p[0]),maxX=(float)b.footprint.exterior.Max(p=>p[0]);
            float minZ=(float)b.footprint.exterior.Min(p=>p[1]),maxZ=(float)b.footprint.exterior.Max(p=>p[1]);
            float step=Mathf.Max(sampler.CellSize/2,Mathf.Max(maxX-minX,maxZ-minZ)/32);
            for(float z=minZ;z<=maxZ;z+=step)for(float x=minX;x<=maxX;x+=step)
                if(GeoForgeSpawnManager.Contains(b.footprint,x,z))heights.Add(sampler.SampleHeight(x,z));
            heights.Sort();float basis=GeoForgeBuildingVolumes.Ground(b,sampler)+(float)b.min_height;
            var q=new GeoForgeBuildingFit {id=b.id,baseElevation=basis,minimumTerrainUnderFootprint=heights[0],maximumTerrainUnderFootprint=heights[heights.Count-1],medianTerrainHeight=heights[heights.Count/2],center=center};
            q.center.y=basis;q.terrainHeightRange=q.maximumTerrainUnderFootprint-q.minimumTerrainUnderFootprint;
            q.maximumGap=Mathf.Max(0,basis-q.minimumTerrainUnderFootprint);q.maximumPenetration=Mathf.Max(0,q.maximumTerrainUnderFootprint-basis);
            q.foundationDepth=enabled&&q.terrainHeightRange>threshold?Mathf.Min(Mathf.Max(0,maxDepth),q.maximumGap):0;
            q.remainingGap=Mathf.Max(0,q.maximumGap-q.foundationDepth);return q;
        }
        public static GeoForgeMeshData Foundation(GeoForgeBuilding b,GeoForgeBuildingFit fit)
        {
            var mesh=GeoForgeBuildingGenerator.Build(new GeoForgeBuilding {id=b.id+"/foundation",footprint=b.footprint,height=fit.foundationDepth});
            mesh.RoofTriangleIndexCount=0;
            for(int i=0;i<mesh.Vertices.Count;i++)mesh.Vertices[i]+=Vector3.up*(fit.baseElevation-fit.foundationDepth);
            return mesh;
        }
        public static GeoForgeSurfaceQuality Surface(string id,string category,GeoForgeMeshData mesh,GeoForgeTerrainSampler sampler,float offset,float tolerance)
        {
            var q=new GeoForgeSurfaceQuality{id=id,category=category,verticesChecked=mesh.Vertices.Count,trianglesChecked=mesh.Triangles.Count/3};
            double total=0;
            Action<Vector3> sample=p=>{float e=p.y-sampler.SampleHeight(p.x,p.z)-offset;float a=Mathf.Abs(e);total+=a;q.samples++;q.maxTerrainErrorMeters=Mathf.Max(q.maxTerrainErrorMeters,a);if(e>tolerance)q.floatingSamples++;if(e< -tolerance)q.terrainPenetrations++;};
            foreach(var v in mesh.Vertices)sample(v);
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var a=mesh.Vertices[mesh.Triangles[i]];var b=mesh.Vertices[mesh.Triangles[i+1]];var c=mesh.Vertices[mesh.Triangles[i+2]];
                if(Vector3.Cross(b-a,c-a).sqrMagnitude<1e-14f)q.degenerateTriangles++;
                sample((a+b+c)/3);sample((a+b)/2);sample((b+c)/2);sample((c+a)/2);
            }
            q.averageTerrainErrorMeters=q.samples>0?(float)(total/q.samples):0;return q;
        }
    }
}
