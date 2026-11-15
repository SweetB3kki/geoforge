using UnityEngine;

namespace GeoForge
{
    [RequireComponent(typeof(CharacterController))]
    public sealed class GeoForgePlayerController : MonoBehaviour
    {
        public float walkSpeed = 4.5f, sprintSpeed = 8, jumpHeight = 1.1f, gravity = -20, mouseSensitivity = 2, maxSlopeAngle = 45;
        public float headHeight = 1.65f, fieldOfView = 70;
        public Camera view;
        public float SmoothedFps { get; private set; }
        public Vector3 safeSpawn;
        private CharacterController controller;
        private Camera overview;
        private bool previousOverviewEnabled, flying;
        private float verticalSpeed, pitch;

        private void Start()
        {
            controller = GetComponent<CharacterController>(); controller.slopeLimit = maxSlopeAngle;
            foreach (var candidate in FindObjectsByType<Camera>(FindObjectsSortMode.None))
                if (candidate != view && candidate.CompareTag("MainCamera")) { overview = candidate; break; }
            if (overview != null) { previousOverviewEnabled = overview.enabled; overview.enabled = false; }
            view.transform.localPosition = Vector3.up * headHeight; view.fieldOfView = fieldOfView;
            view.enabled = true;
            Cursor.lockState = CursorLockMode.Locked; Cursor.visible = false;
        }
        private void Update()
        {
            SmoothedFps = Mathf.Lerp(SmoothedFps, 1f / Mathf.Max(Time.unscaledDeltaTime, 0.0001f), 0.05f);
            if (Input.GetKeyDown(KeyCode.F) && overview != null)
            { flying = !flying; overview.enabled = flying; view.enabled = !flying; }
            if (Input.GetKeyDown(KeyCode.Escape)) { Cursor.lockState = CursorLockMode.None; Cursor.visible = true; }
            if (!flying && Input.GetMouseButtonDown(0)) { Cursor.lockState = CursorLockMode.Locked; Cursor.visible = false; }
            if (flying) return;
            if (Cursor.lockState == CursorLockMode.Locked)
            {
                transform.Rotate(0,Input.GetAxisRaw("Mouse X") * mouseSensitivity,0);
                pitch = Mathf.Clamp(pitch-Input.GetAxisRaw("Mouse Y") * mouseSensitivity,-85,85);
                view.transform.localRotation = Quaternion.Euler(pitch,0,0);
            }
            Tick(new Vector2((Input.GetKey(KeyCode.D)?1:0)-(Input.GetKey(KeyCode.A)?1:0),
                (Input.GetKey(KeyCode.W)?1:0)-(Input.GetKey(KeyCode.S)?1:0)),
                Input.GetKeyDown(KeyCode.Space),Input.GetKey(KeyCode.LeftShift),Time.deltaTime);
        }
        /// <summary>Same movement path for input and deterministic physics tests.</summary>
        public void Tick(Vector2 input, bool jump, bool sprint, float deltaTime)
        {
            if (controller == null) controller = GetComponent<CharacterController>();
            deltaTime = Mathf.Min(deltaTime,0.05f);
            if (controller.isGrounded && verticalSpeed < 0) verticalSpeed = -2;
            if (jump && controller.isGrounded) verticalSpeed = Mathf.Sqrt(jumpHeight * -2 * gravity);
            verticalSpeed += gravity * deltaTime;
            var horizontal = transform.TransformDirection(new Vector3(input.x,0,input.y).normalized) * (sprint?sprintSpeed:walkSpeed);
            var flags = controller.Move((horizontal + Vector3.up * verticalSpeed) * deltaTime);
            if ((flags & CollisionFlags.Above) != 0) verticalSpeed = Mathf.Min(verticalSpeed,0);
            if (transform.position.y < safeSpawn.y-300)
            { controller.enabled=false; transform.position=safeSpawn; controller.enabled=true; verticalSpeed=0; }
        }
        private void OnDisable()
        {
            if (overview != null) overview.enabled = previousOverviewEnabled;
            Cursor.lockState = CursorLockMode.None; Cursor.visible = true;
        }
    }
}
