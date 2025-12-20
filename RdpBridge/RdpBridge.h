#pragma once
#include <winpr/wtypes.h>
#include <freerdp/freerdp.h>
#include <freerdp/input.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifdef _WIN32
// On Windows platform, use __declspec(dllexport) to export functions
#define EXPORT_FUNC __declspec(dllexport)
#else
// On non-Windows platforms, no special export modifier is needed
#define EXPORT_FUNC
#endif

    // Connection and resource management functions
    /**
     * @brief Establish RDP connection
     * @param ip RDP server IP address
     * @param port RDP port (usually 3389)
     * @param username Username
     * @param password User password
     * @param width Desktop width
     * @param height Desktop height
     * @param color_depth Color depth (e.g., 16, 24, 32)
     * @return Returns pointer to freerdp instance on success, NULL on failure
     * @details This function first tries automatic login using NLA, and falls back to manual login mode if it fails
     */
    EXPORT_FUNC freerdp* rdpb_connect(const char* ip, int port, const char* username, const char* password, int width, int height, int color_depth);
    
    /**
     * @brief Release RDP connection resources
     * @param instance Pointer to freerdp instance
     * @details Disconnect and release all associated resources, including shared memory
     */
    EXPORT_FUNC void rdpb_free(freerdp* instance);

    // Connection maintenance and image streaming functions
    /**
     * @brief Handle RDP connection heartbeat and image updates
     * @param instance Pointer to freerdp instance
     * @return Returns 1 when connection is normal, 0 when connection is interrupted
     * @details This function handles RDP events and updates the latest image to shared memory
     */
    EXPORT_FUNC int rdpb_step(freerdp* instance);

    // Input control functions
    /**
     * @brief Send keyboard scan code to remote desktop
     * @param instance Pointer to freerdp instance
     * @param scancode Keyboard scan code
     * @param flags Key state flags (1=pressed, 0=released; 2=extended key)
     */
    EXPORT_FUNC void rdpb_send_scancode(freerdp* instance, int scancode, int flags);
    
    /**
     * @brief Send mouse event to remote desktop
     * @param instance Pointer to freerdp instance
     * @param flags Mouse event flags (0=move, 1=left button down, 2=left button up, 3=right button down, 4=right button up)
     * @param x X coordinate
     * @param y Y coordinate
     */
    EXPORT_FUNC void rdpb_send_mouse(freerdp* instance, int flags, int x, int y);

    // Status check functions
    /**
     * @brief Check RDP connection status
     * @param instance Pointer to freerdp instance
     * @return Returns TRUE when connection is normal, otherwise returns FALSE
     */
    EXPORT_FUNC BOOL rdpb_check_connection(freerdp* instance);

    /**
     * @brief Synchronize keyboard lock states (NumLock, CapsLock, ScrollLock)
     * @param instance Pointer to freerdp instance
     * @param flags Lock flags (1=ScrollLock, 2=NumLock, 4=CapsLock)
     */
    EXPORT_FUNC void rdpb_sync_locks(freerdp* instance, int flags);

    // [Added] Export function: Allow Python to get the correct SHM name
    EXPORT_FUNC const char* rdpb_get_shm_name(freerdp* instance);

    // [Added] Export function: Allow Python to get the event name
    EXPORT_FUNC const char* rdpb_get_event_name(freerdp* instance);

#ifdef __cplusplus
}
#endif