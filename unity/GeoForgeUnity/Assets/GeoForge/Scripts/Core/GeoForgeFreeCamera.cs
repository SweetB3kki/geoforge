using UnityEngine;

namespace GeoForge
{
    public sealed class GeoForgeFreeCamera : MonoBehaviour
    {
        public float speed = 30, boost = 4, sensitivity = 2;
        private float yaw, pitch;
        private void OnEnable() { yaw = transform.eulerAngles.y; pitch = transform.eulerAngles.x; }
        private void Update()
        {
            if (!GetComponent<Camera>().enabled) return;
            // RMB look leaves the cursor available for the Editor and Inspector.
            bool look = Input.GetMouseButton(1);
            Cursor.lockState = look ? CursorLockMode.Locked : CursorLockMode.None;
            Cursor.visible = !look;
            if (look)
            {
                yaw += Input.GetAxisRaw("Mouse X") * sensitivity;
                pitch = Mathf.Clamp(pitch - Input.GetAxisRaw("Mouse Y") * sensitivity, -89, 89);
                transform.rotation = Quaternion.Euler(pitch, yaw, 0);
            }
            var movement = new Vector3((Input.GetKey(KeyCode.D)?1:0)-(Input.GetKey(KeyCode.A)?1:0),
                (Input.GetKey(KeyCode.E)?1:0)-(Input.GetKey(KeyCode.Q)?1:0),
                (Input.GetKey(KeyCode.W)?1:0)-(Input.GetKey(KeyCode.S)?1:0));
            transform.position += transform.TransformDirection(movement.normalized) * speed *
                (Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift) ? boost : 1) * Time.unscaledDeltaTime;
            if (Input.GetKeyDown(KeyCode.Escape)) { Cursor.lockState = CursorLockMode.None; Cursor.visible = true; }
        }
        private void OnDisable() { Cursor.lockState = CursorLockMode.None; Cursor.visible = true; }
    }
}
