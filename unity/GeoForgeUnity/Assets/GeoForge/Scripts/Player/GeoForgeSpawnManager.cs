using System;
using System.Collections.Generic;
using UnityEngine;

namespace GeoForge
{
    public static class GeoForgeSpawnManager
    {
        public static bool Contains(GeoForgePolygon polygon, float x, float z)
        {
            if(polygon?.exterior==null || !InRing(polygon.exterior,x,z)) return false;
            foreach(var hole in polygon.holes ?? Array.Empty<double[][]>()) if(InRing(hole,x,z)) return false;
            return true;
        }
        private static bool InRing(double[][] ring,float x,float z)
        {
            bool inside=false;
            for(int i=0,j=ring.Length-1;i<ring.Length;j=i++)
            { var a=ring[i];var b=ring[j]; if((a[1]>z)!=(b[1]>z) && x<(b[0]-a[0])*(z-a[1])/(b[1]-a[1])+a[0]) inside=!inside; }
            return inside;
        }
        public static bool Near(GeoForgePolygon polygon,float x,float z,float clearance)
        {
            if(Contains(polygon,x,z))return true;
            var rings=new List<double[][]>{polygon.exterior};rings.AddRange(polygon.holes??Array.Empty<double[][]>());
            var p=new Vector2(x,z);
            foreach(var ring in rings)for(int i=1;i<ring.Length;i++)
            {
                var a=new Vector2((float)ring[i-1][0],(float)ring[i-1][1]);var b=new Vector2((float)ring[i][0],(float)ring[i][1]);
                var d=b-a;float t=d.sqrMagnitude>0?Mathf.Clamp01(Vector2.Dot(p-a,d)/d.sqrMagnitude):0;
                if(Vector2.Distance(p,a+d*t)<clearance)return true;
            }
            return false;
        }
        public static Vector3 Find(GeoForgeScene scene, Func<float,float,float> height)
        {
            Physics.SyncTransforms();
            var b=scene.bounds;
            float cx=(float)(b.min_x+b.max_x)/2,cz=(float)(b.min_y+b.max_y)/2;
            foreach(var offset in Candidates((float)Math.Max(b.max_x-b.min_x,b.max_y-b.min_y)))
            {
                float x=cx+offset.x,z=cz+offset.y;
                if(x<b.min_x+1 || x>b.max_x-1 || z<b.min_y+1 || z>b.max_y-1) continue;
                if(scene.metadata?.selection_boundary!=null && !Contains(scene.metadata.selection_boundary,x,z)) continue;
                bool blocked=false;
                foreach(var building in scene.buildings)
                    if(building?.footprint!=null && Near(building.footprint,x,z,0.7f)) { blocked=true; break; }
                foreach(var area in scene.water_areas)
                    if(area?.polygon!=null && Near(area.polygon,x,z,0.7f)) { blocked=true; break; }
                if(blocked) continue;
                float y=height(x,z);
                if(!Physics.Raycast(new Vector3(x,y+1,z),Vector3.down,out var hit,2,~0,QueryTriggerInteraction.Ignore) ||
                    Vector3.Angle(hit.normal,Vector3.up)>40) continue;
                var feet=new Vector3(x,hit.point.y+0.15f,z);
                // Wider than the controller: reserve clearance around nearby walls.
                if(Physics.CheckCapsule(feet+Vector3.up*0.6f,feet+Vector3.up*1.25f,0.55f,~0,QueryTriggerInteraction.Ignore)) continue;
                return feet;
            }
            throw new InvalidOperationException("No safe player spawn found after scanning scene. Player not created.");
        }
        private static IEnumerable<Vector2> Candidates(float extent)
        {
            yield return Vector2.zero;
            // Closest rings first, followed by a bounded coarse fallback over the full scene.
            for(int r=1;r<=60;r++)
                for(int i=0;i<Math.Max(8,r*8);i++)
                { float angle=i*Mathf.PI*2/Math.Max(8,r*8); yield return new Vector2(Mathf.Cos(angle),Mathf.Sin(angle))*r*2; }
            float step=Mathf.Max(4,extent/64);
            for(float z=-extent/2;z<extent/2;z+=step) for(float x=-extent/2;x<extent/2;x+=step) yield return new Vector2(x,z);
        }
        public static GameObject Create(Transform parent, GeoForgeScene scene, Func<float,float,float> height)
        {
            var spawn=Find(scene,height);
            var player=new GameObject("Player");player.transform.SetParent(parent,false);player.transform.position=spawn;
            var capsule=player.AddComponent<CharacterController>();capsule.height=1.8f;capsule.radius=0.35f;
            capsule.center=new Vector3(0,0.9f,0);capsule.stepOffset=0.3f;capsule.skinWidth=0.03f;capsule.slopeLimit=45;
            var camera=new GameObject("Player Camera").AddComponent<Camera>();camera.transform.SetParent(player.transform,false);
            camera.transform.localPosition=new Vector3(0,1.65f,0);camera.nearClipPlane=0.05f;camera.farClipPlane=10000;camera.enabled=false;
            float best=-1,bestAngle=0;
            for(int angle=0;angle<360;angle+=30)
            {
                var direction=Quaternion.Euler(0,angle,0)*Vector3.forward;
                float distance=Physics.Raycast(spawn+Vector3.up*1.65f,direction,out var hit,40,~0,QueryTriggerInteraction.Ignore)?hit.distance:40;
                if(distance>best){best=distance;bestAngle=angle;}
            }
            player.transform.rotation=Quaternion.Euler(0,bestAngle,0);
            var controller=player.AddComponent<GeoForgePlayerController>();controller.view=camera;controller.safeSpawn=spawn;
            return player;
        }
    }
}
