using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace GeoForge
{
    public static class GeoForgeRoofGenerator
    {
        public static GeoForgeMeshData Build(GeoForgeBuilding building,out string actualShape)
        {
            actualShape="flat";string requested=GeoForgeBuildingStyleResolver.Tag(building,"roof:shape")??"flat";
            if(requested=="flat")return GeoForgeBuildingGenerator.Build(building);
            var polygon=GeoForgeTriangulator.Prepare(building.footprint);var ring=polygon.Rings[0];
            bool rectangle=polygon.Rings.Count==1&&ring.Count==4;
            if(rectangle)for(int i=0;i<4;i++)
                rectangle&=Mathf.Abs(Vector3.Dot((ring[(i+1)%4]-ring[i]).normalized,(ring[(i+2)%4]-ring[(i+1)%4]).normalized))<0.03f;
            if(!rectangle||(requested!="gabled"&&requested!="hipped"))
            {Debug.Log($"GeoForge roof fallback {building.id}: {requested}, unsupported footprint/shape; using flat.");return GeoForgeBuildingGenerator.Build(building);}
            if((ring[1]-ring[0]).sqrMagnitude<(ring[2]-ring[1]).sqrMagnitude)ring=new List<Vector3>{ring[1],ring[2],ring[3],ring[0]};
            float width=(ring[3]-ring[0]).magnitude,length=(ring[1]-ring[0]).magnitude;
            float rise=Mathf.Min((float)building.height*0.25f,width*0.3f,4f);
            if(double.TryParse(GeoForgeBuildingStyleResolver.Tag(building,"roof:height"),System.Globalization.NumberStyles.Float,System.Globalization.CultureInfo.InvariantCulture,out var specified)&&specified>=0&&specified<building.height)
                rise=(float)specified;
            if(rise<0.1f)return GeoForgeBuildingGenerator.Build(building);
            float eave=(float)building.height-rise;
            var walls=new GeoForgeBuilding{id=building.id,footprint=building.footprint,height=eave};
            var mesh=GeoForgeBuildingGenerator.Build(walls);
            mesh.Triangles.RemoveRange(0,mesh.RoofTriangleIndexCount);mesh.RoofTriangleIndexCount=0;
            var p=ring.Select(v=>new Vector3(v.x,eave,v.z)).ToArray();
            var r0=(p[0]+p[3])/2+Vector3.up*rise;var r1=(p[1]+p[2])/2+Vector3.up*rise;
            if(requested=="hipped")
            {var along=(p[1]-p[0]).normalized*Mathf.Min(width/2,length/2);r0+=along;r1-=along;}
            var roof=new GeoForgeMeshData();
            Face(roof,p[0],p[1],r1,r0);Face(roof,p[3],r0,r1,p[2]);
            if(requested=="hipped"){Face(roof,p[0],r0,p[3]);Face(roof,p[1],p[2],r1);}
            else
            {
                int k=mesh.Vertices.Count;mesh.Vertices.AddRange(new[]{p[0],p[3],r0,p[1],r1,p[2]});
                mesh.Triangles.AddRange(new[]{k,k+1,k+2,k+3,k+4,k+5});
            }
            int offset=mesh.Vertices.Count;mesh.Vertices.AddRange(roof.Vertices);
            mesh.Triangles.InsertRange(0,roof.Triangles.Select(i=>i+offset));mesh.RoofTriangleIndexCount=roof.Triangles.Count;
            actualShape=requested;return mesh;
        }
        private static void Face(GeoForgeMeshData mesh,params Vector3[] points)
        {
            int k=mesh.Vertices.Count;mesh.Vertices.AddRange(points);
            for(int i=1;i<points.Length-1;i++)if(Vector3.Cross(points[i]-points[0],points[i+1]-points[0]).sqrMagnitude>1e-10f)
                mesh.AddUpTriangle(k,k+i,k+i+1);
        }
    }
}
