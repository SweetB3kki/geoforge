using UnityEngine;

namespace GeoForge
{
    public static class GeoForgeWorldBoundary
    {
        public static void Create(Transform parent, GeoForgeScene scene, float minHeight=-1000, float maxHeight=1000)
        {
            var boundary=new GameObject("Boundary");boundary.transform.SetParent(parent,false);
            var b=scene.bounds;
            var points=scene.metadata?.selection_boundary?.exterior;
            if(points==null) points=new[]{new[]{b.min_x,b.min_y,0},new[]{b.max_x,b.min_y,0},new[]{b.max_x,b.max_y,0},new[]{b.min_x,b.max_y,0},new[]{b.min_x,b.min_y,0}};
            for(int i=0;i<points.Length-1;i++)
            {
                var a=GeoForgeCoordinateConverter.GeoForgeToUnity(points[i]);var c=GeoForgeCoordinateConverter.GeoForgeToUnity(points[i+1]);
                var wall=new GameObject("Boundary collider");wall.transform.SetParent(boundary.transform,false);
                wall.transform.position=(a+c)/2+Vector3.up*(minHeight+maxHeight)/2;
                wall.transform.rotation=Quaternion.LookRotation((c-a).normalized,Vector3.up);
                wall.AddComponent<BoxCollider>().size=new Vector3(1,maxHeight-minHeight,(c-a).magnitude+0.1f);
            }
        }
    }
}
