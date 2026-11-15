using UnityEngine;

namespace GeoForge
{
    public static class GeoForgeCollisionSetup
    {
        public static void Building(GameObject target, Mesh mesh)
        { target.AddComponent<MeshCollider>().sharedMesh=mesh; }
        public static void FlatGround(Transform parent, GeoForgeBounds bounds)
        {
            var ground=new GameObject("Ground");ground.transform.SetParent(parent,false);
            var collider=ground.AddComponent<BoxCollider>();
            collider.center=new Vector3((float)(bounds.min_x+bounds.max_x)/2,-0.5f,(float)(bounds.min_y+bounds.max_y)/2);
            collider.size=new Vector3((float)(bounds.max_x-bounds.min_x),1,(float)(bounds.max_y-bounds.min_y));
        }
    }
}
