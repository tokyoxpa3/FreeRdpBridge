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
// 基本標頭 + 像素資料
#define CALC_SHM_SIZE(w, h) (sizeof(ShmHeader) + ((w) * (h) * 4))

// 共享記憶體標頭
typedef struct {
    uint32_t width;
    uint32_t height;
    uint32_t stride;
    uint32_t frameId;
} ShmHeader;

// [關鍵修改] 自定義 Context 結構，包含每個連線獨有的資源
typedef struct {
    rdpContext _p; // 必須是第一個成員，繼承 FreeRDP context

    // 每個實例獨有的資源句柄
    HANDLE hMapFile;
    void* pSharedMem;
    HANDLE hMutex;
    ShmHeader* pHeader;
    uint8_t* pPixelData;

    // 每個實例獨有的名稱
    char shmName[128];
    char mutexName[128];

    // 紀錄當前共享記憶體大小，避免重複開銷
    size_t currentShmSize;
} BridgeContext;

// 初始化該 Context 的共享記憶體
static BOOL Shm_Init(BridgeContext* ctx, int width, int height) {
    if (!ctx) return FALSE;
    if (ctx->hMapFile) return TRUE; // 已經初始化過

    // 使用 Context 內部的唯一名稱
    size_t size = CALC_SHM_SIZE(MAX_WIDTH, MAX_HEIGHT); // 分配最大空間以防解析度變更

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

    // 初始化標頭
    ctx->pHeader->width = 0;
    ctx->pHeader->height = 0;
    ctx->pHeader->frameId = 0;
    ctx->currentShmSize = size;

    // 建立互斥鎖
    ctx->hMutex = CreateMutexA(NULL, FALSE, ctx->mutexName);
    return TRUE;
}

// 釋放資源
static void Shm_Free(BridgeContext* ctx) {
    if (!ctx) return;
    if (ctx->pSharedMem) { UnmapViewOfFile(ctx->pSharedMem); ctx->pSharedMem = NULL; }
    if (ctx->hMapFile) { CloseHandle(ctx->hMapFile); ctx->hMapFile = NULL; }
    if (ctx->hMutex) { CloseHandle(ctx->hMutex); ctx->hMutex = NULL; }
}

// 更新影像
static void Shm_Update(freerdp* instance) {
    if (!instance || !instance->context) return;

    // 轉型為我們自定義的 Context
    BridgeContext* ctx = (BridgeContext*)instance->context;

    if (!ctx->pSharedMem || !ctx->hMutex) return;

    // 檢查 GDI 是否就緒
    if (!instance->context->gdi || !instance->context->gdi->primary || !instance->context->gdi->primary->bitmap) return;

    rdpGdi* gdi = instance->context->gdi;
    int width = gdi->width;
    int height = gdi->height;
    int stride = width * 4;

    if (width > MAX_WIDTH || height > MAX_HEIGHT) return;

    // 鎖定並寫入
    WaitForSingleObject(ctx->hMutex, INFINITE);

    ctx->pHeader->width = width;
    ctx->pHeader->height = height;
    ctx->pHeader->stride = stride;

    memcpy(ctx->pPixelData, gdi->primary->bitmap->data, stride * height);

    ctx->pHeader->frameId++; // 更新計數器

    ReleaseMutex(ctx->hMutex);
}

static BOOL Bridge_PreConnect(freerdp* instance) {
    if (!instance || !instance->context || !instance->context->settings) return FALSE;
    rdpSettings* settings = instance->context->settings;

    // 產生唯一的 SHM 名稱 (基於 instance 指標位址)
    // 這樣不同的 instance 就會有不同的記憶體區塊
    BridgeContext* ctx = (BridgeContext*)instance->context;
    sprintf_s(ctx->shmName, 128, "Local\\RdpBridgeMem_%p", instance);
    sprintf_s(ctx->mutexName, 128, "Local\\RdpBridgeMutex_%p", instance);

    printf("[Bridge] Initializing SHM: %s\n", ctx->shmName);

    // 初始化 SHM
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
    if (!gdi_init(instance, PIXEL_FORMAT_BGRA32)) {
        printf("[Bridge Warning] GDI init failed\n");
    }

    // 建議：這裡可以註解掉，改由 Python 端在連線成功後動態發送正確的狀態
    // 或者將 1 (ScrollLock) 改為 2 (NumLock) 以預設開啟
    /*
    if (instance->context->input && instance->context->input->SynchronizeEvent) {
        // KBD_SYNC_NUM_LOCK = 2
        instance->context->input->SynchronizeEvent(instance->context->input, 2);
    }
    */

    return TRUE;
}

static freerdp* _connect_attempt(const char* ip, int port, const char* username, const char* password, int width, int height, int color_depth, BOOL try_nla) {
    freerdp* instance = freerdp_new();
    if (!instance) return NULL;

    // [關鍵] 設定 Context 大小為我們自定義結構的大小
    instance->ContextSize = sizeof(BridgeContext);

    instance->PreConnect = Bridge_PreConnect;
    instance->PostConnect = Bridge_PostConnect;

    if (!freerdp_context_new(instance)) {
        freerdp_free(instance);
        return NULL;
    }

    rdpSettings* settings = instance->context->settings;
    settings->ServerHostname = _strdup("localhost");
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
        // 連線失敗時，PreConnect 裡建立的 SHM 會在 context_free 時需要釋放
        // 但由於我們把釋放寫在 rdpb_free，這裡手動清理一下比較保險
        BridgeContext* ctx = (BridgeContext*)instance->context;
        Shm_Free(ctx);

        freerdp_context_free(instance);
        freerdp_free(instance);
        return NULL;
    }

    return instance;
}

EXPORT_FUNC freerdp* rdpb_connect(const char* ip, int port, const char* username, const char* password, int width, int height, int color_depth) {
    // Shm_Init 已移至 PreConnect，這裡只需初始化網路庫
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

// [新增] 匯出函數：讓 Python 取得正確的 SHM 名稱
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

// ... (在檔案末端加入實作)

EXPORT_FUNC void rdpb_sync_locks(freerdp* instance, int flags) {
    if (!instance || !instance->context || !instance->context->input) return;
    if (instance->context->input->SynchronizeEvent) {
        instance->context->input->SynchronizeEvent(instance->context->input, flags);
    }
}