#include "RdpBridge.h"
#include <freerdp/settings.h>
#include <freerdp/gdi/gdi.h>
#include <winpr/crt.h>
#include <winpr/library.h>
#include <winpr/synch.h>
#include <stdio.h>
#include <string.h>
#include <windows.h>

#pragma comment(lib, "ws2_32.lib")

#define MAX_WIDTH 1920
#define MAX_HEIGHT 1080
// Basic header + pixel data
#define CALC_SHM_SIZE(w, h) (sizeof(ShmHeader) + ((w) * (h) * 4))

// Shared memory header
typedef struct {
    uint32_t width;
    uint32_t height;
    uint32_t stride;
    uint32_t frameId;
} ShmHeader;

// [Key modification] Custom Context structure, containing resources unique to each connection
typedef struct {
    rdpContext _p; // Must be the first member, inheriting FreeRDP context

    // Resources handles unique to each instance
    HANDLE hMapFile;
    void* pSharedMem;
    HANDLE hMutex;
    HANDLE hEvent;         // [Added] Event handle
    ShmHeader* pHeader;
    uint8_t* pPixelData;

    // Names unique to each instance
    char shmName[128];
    char mutexName[128];
    char eventName[128];   // [Added] Event name

    // Record current shared memory size to avoid repeated overhead
    size_t currentShmSize;
} BridgeContext;

// Initialize shared memory for this Context
static BOOL Shm_Init(BridgeContext* ctx, int width, int height) {
    if (!ctx) return FALSE;
    if (ctx->hMapFile) return TRUE; // Already initialized

    // Use unique name within the Context
    size_t size = CALC_SHM_SIZE(MAX_WIDTH, MAX_HEIGHT); // Allocate maximum space to prevent resolution changes

    ctx->hMapFile = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, (DWORD)size, ctx->shmName);
    if (!ctx->hMapFile) {
        printf("[Bridge Error] Failed to create FileMapping: %s\n", ctx->shmName);
        return FALSE;
    }

    ctx->pSharedMem = MapViewOfFile(ctx->hMapFile, FILE_MAP_ALL_ACCESS, 0, 0, size);
    if (!ctx->pSharedMem) {
        CloseHandle(ctx->hMapFile);
        ctx->hMapFile = NULL;
        return FALSE;
    }

    ctx->pHeader = (ShmHeader*)ctx->pSharedMem;
    ctx->pPixelData = (uint8_t*)ctx->pSharedMem + sizeof(ShmHeader);

    // Initialize header
    ctx->pHeader->width = 0;
    ctx->pHeader->height = 0;
    ctx->pHeader->frameId = 0;
    ctx->currentShmSize = size;

    // Create mutex
    ctx->hMutex = CreateMutexA(NULL, FALSE, ctx->mutexName);
    
    // [Added] Create event
	sprintf_s(ctx->eventName, 128, "Local\\RdpBridgeEvent_%p", ctx);
    ctx->hEvent = CreateEventA(NULL, FALSE, FALSE, ctx->eventName); // Auto-reset event
    return TRUE;
}

// Release resources
static void Shm_Free(BridgeContext* ctx) {
    if (!ctx) return;
    if (ctx->pSharedMem) { UnmapViewOfFile(ctx->pSharedMem); ctx->pSharedMem = NULL; }
    if (ctx->hMapFile) { CloseHandle(ctx->hMapFile); ctx->hMapFile = NULL; }
    if (ctx->hMutex) { CloseHandle(ctx->hMutex); ctx->hMutex = NULL; }
    if (ctx->hEvent) { CloseHandle(ctx->hEvent); ctx->hEvent = NULL; }
}

// Update image
static void Shm_Update(freerdp* instance) {
    if (!instance || !instance->context) return;
    BridgeContext* ctx = (BridgeContext*)instance->context;

    if (!ctx->pSharedMem || !ctx->hMutex || !ctx->hEvent) return;

    // 鎖定標頭資訊
    WaitForSingleObject(ctx->hMutex, INFINITE);

    rdpGdi* gdi = instance->context->gdi;
    ctx->pHeader->width = gdi->width;
    ctx->pHeader->height = gdi->height;
    ctx->pHeader->stride = gdi->width * 4;
    
    // [重要] 這裡不需要 memcpy 了！影像已經由 FreeRDP 自動填入 pPixelData
    
    ctx->pHeader->frameId++;

    ReleaseMutex(ctx->hMutex);
    
    // 敲門通知 Python
    SetEvent(ctx->hEvent);
}

static BOOL Bridge_PreConnect(freerdp* instance) {
    if (!instance || !instance->context || !instance->context->settings) return FALSE;
    rdpSettings* settings = instance->context->settings;

    // Generate unique SHM name (based on instance pointer address)
        // So different instances will have different memory blocks
        BridgeContext* ctx = (BridgeContext*)instance->context;
        sprintf_s(ctx->shmName, 128, "Local\\RdpBridgeMem_%p", instance);
        sprintf_s(ctx->mutexName, 128, "Local\\RdpBridgeMutex_%p", instance);
    
        printf("[Bridge] Initializing SHM: %s\n", ctx->shmName);
    
        // Initialize SHM
        if (!Shm_Init(ctx, settings->DesktopWidth, settings->DesktopHeight)) {
            return FALSE;
        }

    settings->SoftwareGdi = FALSE;
    settings->SupportGraphicsPipeline = TRUE;
    settings->GfxThinClient = TRUE;
    settings->GfxSmallCache = TRUE;
    settings->GfxH264 = TRUE;
    settings->GfxAVC444 = TRUE;

    settings->BitmapCacheEnabled = FALSE;
    settings->OffscreenSupportLevel = FALSE;
    settings->GlyphSupportLevel = GLYPH_SUPPORT_NONE;

    return TRUE;
}

static BOOL Bridge_PostConnect(freerdp* instance) {
    if (!instance || !instance->context || !instance->context->settings) return FALSE;

    BridgeContext* ctx = (BridgeContext*)instance->context;
    rdpSettings* settings = instance->context->settings; // [修正點]

    // 定義格式：BGRA32 匹配 Python 端
    UINT32 pixel_format = PIXEL_FORMAT_BGRA32;
    
    // [修正點] 從 settings 獲取寬度
    int stride = settings->DesktopWidth * 4;

    // [核心優化] 使用 gdi_init_ex 直接綁定 SHM 指標
    if (!gdi_init_ex(instance, pixel_format, stride, ctx->pPixelData, NULL)) {
        printf("[Bridge Error] GDI Zero-copy init failed\n");
        return FALSE;
    }

    printf("[Bridge] Zero-copy GDI initialized (%dx%d). Buffer: %p\n",
           settings->DesktopWidth, settings->DesktopHeight, ctx->pPixelData);
    
    return TRUE;
}

static freerdp* _connect_attempt(const char* ip, int port, const char* username, const char* password, int width, int height, int color_depth, BOOL try_nla) {
    freerdp* instance = freerdp_new();
    if (!instance) return NULL;

    // [Key] Set Context size to our custom structure size
        instance->ContextSize = sizeof(BridgeContext);
    
        instance->PreConnect = Bridge_PreConnect;
        instance->PostConnect = Bridge_PostConnect;

    if (!freerdp_context_new(instance)) {
        freerdp_free(instance);
        return NULL;
    }

    rdpSettings* settings = instance->context->settings;
    settings->ServerHostname = _strdup(ip);
    settings->TargetNetAddress = _strdup(ip);
    settings->ServerPort = (port > 0) ? port : 3389;
    settings->Username = _strdup(username);
    settings->ServerMode = FALSE;

    settings->DesktopWidth = width;
    settings->DesktopHeight = height;
    settings->ColorDepth = color_depth;

    settings->IgnoreCertificate = TRUE;
    settings->AutoAcceptCertificate = TRUE;

    if (try_nla) {
        if (password) settings->Password = _strdup(password);
        settings->NlaSecurity = TRUE;
        settings->TlsSecurity = TRUE;
        settings->RdpSecurity = TRUE;
        settings->AutoLogonEnabled = TRUE;
    }
    else {
        settings->Password = NULL;
        settings->NlaSecurity = FALSE;
        settings->TlsSecurity = TRUE;
        settings->RdpSecurity = TRUE;
        settings->NegotiateSecurityLayer = TRUE;
        settings->AutoLogonEnabled = FALSE;
        settings->ConsoleSession = TRUE;
    }

    if (!freerdp_connect(instance)) {
        // When connection fails, the SHM created in PreConnect needs to be released during context_free
                // But since we put the release in rdpb_free, it's safer to manually clean up here
                BridgeContext* ctx = (BridgeContext*)instance->context;
                Shm_Free(ctx);
        
        freerdp_context_free(instance);
        freerdp_free(instance);
        return NULL;
    }

    return instance;
}

EXPORT_FUNC freerdp* rdpb_connect(const char* ip, int port, const char* username, const char* password, int width, int height, int color_depth) {
    // Shm_Init has been moved to PreConnect, here we only need to initialize the network library
        WSADATA wsaData;
        WSAStartup(0x0202, &wsaData);
    
    freerdp* instance = _connect_attempt(ip, port, username, password, width, height, color_depth, TRUE);
    if (instance) return instance;

    printf("[Bridge] NLA failed, retrying manual login...\n");
    instance = _connect_attempt(ip, port, username, NULL, width, height, color_depth, FALSE);

    return instance;
}

EXPORT_FUNC int rdpb_step(freerdp* instance) {
    if (!instance || !instance->context) return 0;
    if (freerdp_shall_disconnect_context(instance->context)) return 0;

    HANDLE handles[64];
    DWORD count = freerdp_get_event_handles(instance->context, handles, 64);
    if (count == 0) return 0;

    WaitForMultipleObjects(count, handles, FALSE, 5);
    if (!freerdp_check_event_handles(instance->context)) return 0;

    Shm_Update(instance);
    return 1;
}

EXPORT_FUNC void rdpb_send_scancode(freerdp* instance, int scancode, int flags) {
    if (!instance || !instance->context || !instance->context->input) return;
    UINT16 kbdFlags = 0;
    if (flags & 1) kbdFlags |= KBD_FLAGS_DOWN; else kbdFlags |= KBD_FLAGS_RELEASE;
    if (flags & 2) kbdFlags |= KBD_FLAGS_EXTENDED;
    instance->context->input->KeyboardEvent(instance->context->input, kbdFlags, scancode);
}

EXPORT_FUNC void rdpb_send_mouse(freerdp* instance, int flags, int x, int y) {
    if (!instance || !instance->context || !instance->context->input) return;
    UINT16 ptrFlags = 0;
    switch (flags) {
    case 1: ptrFlags = PTR_FLAGS_BUTTON1 | PTR_FLAGS_DOWN; break;
    case 2: ptrFlags = PTR_FLAGS_BUTTON1; break;
    case 3: ptrFlags = PTR_FLAGS_BUTTON2 | PTR_FLAGS_DOWN; break;
    case 4: ptrFlags = PTR_FLAGS_BUTTON2; break;
    case 0: ptrFlags = PTR_FLAGS_MOVE; break;
    
    // --- 新增滾輪支援 ---
    case 5: // 滾輪向上 (Wheel Up)
        // 0x0200 = PTR_FLAGS_WHEEL
        // 0x0078 = 120 (標準滾動步長)
        ptrFlags = PTR_FLAGS_WHEEL | 0x0078;
        break;
    case 6: // 滾輪向下 (Wheel Down)
        // 0x0100 = PTR_FLAGS_WHEEL_NEGATIVE
        ptrFlags = PTR_FLAGS_WHEEL | PTR_FLAGS_WHEEL_NEGATIVE | 0x0078;
        break;
    case 7: ptrFlags = PTR_FLAGS_BUTTON3 | PTR_FLAGS_DOWN; break; // Middle Down
    case 8: ptrFlags = PTR_FLAGS_BUTTON3; break; // Middle Up
        
    default: return;
    }
    instance->context->input->MouseEvent(instance->context->input, ptrFlags, x, y);
}

EXPORT_FUNC BOOL rdpb_check_connection(freerdp* instance) {
    if (!instance || !instance->context) return FALSE;
    return !freerdp_shall_disconnect_context(instance->context);
}

// [Added] Export function: Let Python get the correct SHM name
EXPORT_FUNC const char* rdpb_get_shm_name(freerdp* instance) {
    if (!instance || !instance->context) return "";
    BridgeContext* ctx = (BridgeContext*)instance->context;
    return ctx->shmName;
}

EXPORT_FUNC void rdpb_free(freerdp* instance) {
    if (instance) {
        if (instance->context) {
            BridgeContext* ctx = (BridgeContext*)instance->context;
            Shm_Free(ctx);
        }
        gdi_free(instance);
        freerdp_disconnect(instance);
        freerdp_context_free(instance);
        freerdp_free(instance);
        WSACleanup();
    }
}

// ... (add implementation at the end of the file)

EXPORT_FUNC void rdpb_sync_locks(freerdp* instance, int flags) {
    if (!instance || !instance->context || !instance->context->input) return;
    if (instance->context->input->SynchronizeEvent) {
        instance->context->input->SynchronizeEvent(instance->context->input, flags);
    }
}

EXPORT_FUNC const char* rdpb_get_event_name(freerdp* instance) {
    if (!instance || !instance->context) return "";
    BridgeContext* ctx = (BridgeContext*)instance->context;
    return ctx->eventName;
}