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

// 定義共享記憶體名稱，用於在不同進程間傳輸影像資料
#define SHM_NAME "Local\\RdpBridgeMem"
// 定義互斥鎖名稱，確保多執行緒存取共享記憶體的安全性
#define MUTEX_NAME "Local\\RdpBridgeMutex"
// 最大支援的桌面解析度
#define MAX_WIDTH 1920
#define MAX_HEIGHT 1080
// 計算共享記憶體總大小 (標頭 + 影像資料)
#define SHM_SIZE (sizeof(ShmHeader) + (MAX_WIDTH * MAX_HEIGHT * 4))

// 共享記憶體標頭結構，存放影像的基本資訊
typedef struct {
    uint32_t width;      // 影像寬度
    uint32_t height;     // 影像高度
    uint32_t stride;     // 每行像素的位元組數
    uint32_t frameId;    // 幀識別碼，用於追蹤影像更新
} ShmHeader;

// 共享記憶體相關的全域變數
static HANDLE hMapFile = NULL;    // 檔案映射物件句柄
static void* pSharedMem = NULL;   // 映射到程序地址空間的共享記憶體指標
static HANDLE hMutex = NULL;      // 用於同步存取共享記憶體的互斥鎖
static ShmHeader* pHeader = NULL; // 指向共享記憶體標頭的指標
static uint8_t* pPixelData = NULL; // 指向影像像素資料的指標

static BOOL Shm_Init() {
    // 如果共享記憶體已初始化，直接返回成功
    if (hMapFile) return TRUE;
    
    // 建立命名的檔案映射物件，作為跨進程共享記憶體
    hMapFile = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, SHM_SIZE, SHM_NAME);
    if (!hMapFile) return FALSE;
    
    // 將檔案映射物件映射到當前進程的地址空間
    pSharedMem = MapViewOfFile(hMapFile, FILE_MAP_ALL_ACCESS, 0, 0, SHM_SIZE);
    if (!pSharedMem) { CloseHandle(hMapFile); return FALSE; }
    
    // 設定共享記憶體各部分的指標
    pHeader = (ShmHeader*)pSharedMem;
    pPixelData = (uint8_t*)pSharedMem + sizeof(ShmHeader);
    // 初始化標頭資訊
    pHeader->width = 0; pHeader->height = 0; pHeader->frameId = 0;
    
    // 建立互斥鎖，確保多執行緒安全存取共享記憶體
    hMutex = CreateMutexA(NULL, FALSE, MUTEX_NAME);
    return TRUE;
}

static void Shm_Update(freerdp* instance) {
    // 檢查輸入參數的有效性
    if (!instance || !instance->context || !instance->context->gdi) return;
    if (!pSharedMem || !hMutex) return;
    rdpGdi* gdi = instance->context->gdi;
    if (!gdi->primary || !gdi->primary->bitmap) return;

    // 取得目前桌面影像的像素資料
    uint8_t* srcData = gdi->primary->bitmap->data;
    int width = gdi->width;
    int height = gdi->height;
    int stride = width * 4; // 假設 BGRA32 格式，每像素 4 bytes

    // 檢查影像大小是否超出最大支援範圍
    if (width > MAX_WIDTH || height > MAX_HEIGHT) return;

    // 獲取互斥鎖以確保安全存取共享記憶體
    WaitForSingleObject(hMutex, INFINITE);
    // 更新共享記憶體中的影像資訊
    pHeader->width = width;
    pHeader->height = height;
    pHeader->stride = stride;
    // 複製影像像素資料到共享記憶體
    memcpy(pPixelData, srcData, stride * height);
    // 增加幀識別碼，表示有新的影像更新
    pHeader->frameId++;
    // 釋放互斥鎖
    ReleaseMutex(hMutex);
}

static void Shm_Free() {
    // 解除映射並清理共享記憶體資源
    if (pSharedMem) { UnmapViewOfFile(pSharedMem); pSharedMem = NULL; }
    if (hMapFile) { CloseHandle(hMapFile); hMapFile = NULL; }
    if (hMutex) { CloseHandle(hMutex); hMutex = NULL; }
}

static BOOL Bridge_PreConnect(freerdp* instance)
{
    // 驗證輸入參數的有效性
    if (!instance || !instance->context || !instance->context->settings) return FALSE;
    rdpSettings* settings = instance->context->settings;
    
    // 1. 關閉軟體 GDI (關鍵)
    // 軟體 GDI 會影響效能，關閉後可啟用硬體加速
    settings->SoftwareGdi = FALSE;

    // 2. 啟用圖形管線 (Graphics Pipeline)
    // 使用更高效的圖形處理方式
    settings->SupportGraphicsPipeline = TRUE;
    settings->GfxThinClient = TRUE;  // 使用精簡客戶端模式
    settings->GfxSmallCache = TRUE;  // 使用小快取模式

    // 3. 強制要求 H.264 (AVC444 = 高畫質, AVC420 = 高壓縮)
    // 使用現代化的視訊編碼技術提升畫質和效能
    settings->GfxH264 = TRUE;
    settings->GfxAVC444 = TRUE;      // 選擇高畫質的 AVC444 編碼

    // 4. 重要：告訴伺服器我們支援的寬高與色彩
    // 這些設定已在 _connect_attempt 中設定，此處註解掉避免重複設定
    //settings->DesktopWidth = 1920;
    //settings->DesktopHeight = 1080;
    //settings->ColorDepth = 32;

    // 優化效能設定
    settings->BitmapCacheEnabled = FALSE;       // 關閉位圖快取
    settings->OffscreenSupportLevel = FALSE;    // 關閉離屏表面支援
    settings->GlyphSupportLevel = GLYPH_SUPPORT_NONE;  // 關閉字形快取
    return TRUE;
}

static BOOL Bridge_PostConnect(freerdp* instance)
{
    // 初始化 GDI 子系統，使用 BGRA32 像素格式
    if (!gdi_init(instance, PIXEL_FORMAT_BGRA32)) {
        printf("[Bridge Warning] GDI init failed\n");
    }
    return TRUE;
}

// 輔助函式：建立並嘗試連線
// try_nla: TRUE (嘗試自動登入), FALSE (回退到手動登入畫面)
static freerdp* _connect_attempt(const char* ip, int port, const char* username, const char* password, int width, int height, int color_depth, BOOL try_nla) {
    // 建立新的 freerdp 實例
    freerdp* instance = freerdp_new();
    if (!instance) return NULL;

    // 設定上下文大小和回調函數
    instance->ContextSize = sizeof(rdpContext);
    instance->PreConnect = Bridge_PreConnect;      // 連線前的設定回調
    instance->PostConnect = Bridge_PostConnect;    // 連線後的初始化回調

    // 初始化 freerdp 上下文
    if (!freerdp_context_new(instance)) {
        freerdp_free(instance);
        return NULL;
    }

    rdpSettings* settings = instance->context->settings;
    // 設定伺服器資訊
    settings->ServerHostname = _strdup("localhost");   // 主機名稱
    settings->TargetNetAddress = _strdup(ip);          // 目標網路位址
    settings->ServerPort = (port > 0) ? port : 3389;   // 連接埠
    settings->Username = _strdup(username);            // 使用者名稱

    settings->ServerMode = FALSE;                      // 不是伺服器模式
    
    // 4. 重要：告訴伺服器我們支援的桌面解析度與色彩深度
    settings->DesktopWidth = width;                    // 桌面寬度
    settings->DesktopHeight = height;                  // 桌面高度
    settings->ColorDepth = color_depth;                // 色彩深度 (16, 24, 32)
    
    // 1. 關閉軟體 GDI (關鍵)
    settings->SoftwareGdi = FALSE;                     // 使用硬體加速而非軟體 GDI

    // 2. 啟用圖形管線 (Graphics Pipeline)
    settings->SupportGraphicsPipeline = TRUE;          // 啟用圖形管線
    settings->GfxThinClient = TRUE;                    // 使用精簡客戶端模式
    settings->GfxSmallCache = TRUE;                    // 使用小快取模式

    // 3. 強制要求 H.264 (AVC444 = 高畫質, AVC420 = 高壓縮)
    settings->GfxH264 = TRUE;                          // 啟用 H.264 編碼
    settings->GfxAVC444 = TRUE;                        // 使用高畫質 AVC444 編碼

    // 證書設定 (開發環境中忽略證書驗證)
    settings->IgnoreCertificate = TRUE;                // 忽略證書驗證
    settings->AutoAcceptCertificate = TRUE;            // 自動接受證書

    if (try_nla) {
        // --- 模式 A: 自動登入 (Network Level Authentication) ---
        printf("[Bridge] Trying Auto-Login (NLA) for user: %s\n", username);
        if (password) settings->Password = _strdup(password);  // 設定密碼
        settings->NlaSecurity = TRUE;                   // 啟用 NLA 安全層
        settings->TlsSecurity = TRUE;                  // 啟用 TLS 安全層
        settings->RdpSecurity = TRUE;                  // 啟用 RDP 安全層
        settings->AutoLogonEnabled = TRUE;             // 啟用自動登入
    }
    else {
        // --- 模式 B: 回退模式 (顯示 GUI 登入畫面) ---
        printf("[Bridge] Auto-Login failed or skipped. Falling back to Manual Login GUI...\n");

        // 1. 清空密碼，確保不會再次嘗試自動驗證
        settings->Password = NULL;

        // 2. 關閉 NLA (重要)
        // 現代 Windows 若開啟 NLA，會拒絕沒有憑證的連線。
        // 若要看到 GUI，必須將 NLA 設為 FALSE (且伺服器端需允許非 NLA 連線)。
        settings->NlaSecurity = FALSE;                 // 關閉 NLA 安全層

        // 3. 保持 TLS/RDP 安全層，確保能連上現代伺服器
        settings->TlsSecurity = TRUE;                  // 保持 TLS 安全層
        settings->RdpSecurity = TRUE;                  // 保持 RDP 安全層
        settings->NegotiateSecurityLayer = TRUE;       // 啟用安全層協商

        // 4. 關鍵：關閉 AutoLogon，這會告訴伺服器我們想要 Logon Screen
        settings->AutoLogonEnabled = FALSE;            // 關閉自動登入

        // 5. 嘗試連線到 Console Session (有助於顯示登入畫面)
        settings->ConsoleSession = TRUE;               // 啟用主控台工作階段
    }

    // 嘗試建立 RDP 連線
    if (!freerdp_connect(instance)) {
        // 連線失敗，取得錯誤碼並清理資源
        UINT32 error = freerdp_get_last_error(instance->context);
        printf("[Bridge] Connect Failed. Error: 0x%08X\n", error);
        freerdp_context_free(instance);
        freerdp_free(instance);
        return NULL;
    }

    return instance;  // 返回成功的連線實例
}

EXPORT_FUNC freerdp* rdpb_connect(const char* ip, int port, const char* username, const char* password, int width, int height, int color_depth) {
    // 初始化共享記憶體系統
    Shm_Init();
    // 初始化 Windows Socket API
    WSADATA wsaData;
    WSAStartup(0x0202, &wsaData);

    // 1. 先嘗試 NLA (Network Level Authentication) 自動登入
    freerdp* instance = _connect_attempt(ip, port, username, password, width, height, color_depth, TRUE);

    if (instance) {
        // 自動登入成功
        printf("[Bridge] Connected successfully using NLA.\n");
        return instance;
    }

    // 2. 失敗則回退到 GUI 手動登入
    // 注意：如果伺服器群組原則強制要求 "Require NLA"，這步也會失敗，因為 NLA 強制要求先驗證後連線。
    printf("[Bridge] NLA Connection failed. Retrying with Manual Login Mode...\n");
    // 在回退模式中不使用密碼，讓使用者在 GUI 中手動輸入
    instance = _connect_attempt(ip, port, username, NULL, width, height, color_depth, FALSE);

    if (instance) {
        // 手動登入模式成功，使用者應該能看到遠端桌面的登入畫面
        printf("[Bridge] Fallback successful! You should see the Windows Login Screen.\n");
        return instance;
    }

    // 所有連線嘗試都失敗
    printf("[Bridge] All connection attempts failed.\n");
    return NULL;
}

EXPORT_FUNC int rdpb_step(freerdp* instance) {
    // 檢查連線實例是否有效
    if (!instance || !instance->context) return 0;
    // 檢查是否應該斷開連線
    if (freerdp_shall_disconnect_context(instance->context)) return 0;

    // 取得 RDP 事件的控制代碼
    HANDLE handles[64];
    DWORD count = freerdp_get_event_handles(instance->context, handles, 64);
    if (count == 0) return 0;

    // 等待事件發生或逾時 (5ms)
    WaitForMultipleObjects(count, handles, FALSE, 5);
    // 檢查並處理事件
    if (!freerdp_check_event_handles(instance->context)) return 0;

    // 更新共享記憶體中的影像資料
    Shm_Update(instance);
    return 1;  // 表示連線仍然活躍
}

EXPORT_FUNC void rdpb_send_scancode(freerdp* instance, int scancode, int flags) {
    // 檢查參數有效性
    if (!instance || !instance->context || !instance->context->input) return;
    // 構建鍵盤事件旗標
    UINT16 kbdFlags = 0;
    if (flags & 1) kbdFlags |= KBD_FLAGS_DOWN; else kbdFlags |= KBD_FLAGS_RELEASE;  // 按下或釋放
    if (flags & 2) kbdFlags |= KBD_FLAGS_EXTENDED;                                  // 延伸鍵
    // 發送鍵盤掃描碼事件到遠端桌面
    instance->context->input->KeyboardEvent(instance->context->input, kbdFlags, scancode);
}

EXPORT_FUNC void rdpb_send_mouse(freerdp* instance, int flags, int x, int y) {
    // 檢查參數有效性
    if (!instance || !instance->context || !instance->context->input) return;
    // 根據旗標構建滑鼠事件
    UINT16 ptrFlags = 0;
    switch (flags) {
    case 1: ptrFlags = PTR_FLAGS_BUTTON1 | PTR_FLAGS_DOWN; break; // 左鍵按下
    case 2: ptrFlags = PTR_FLAGS_BUTTON1; break;                   // 左鍵釋放
    case 3: ptrFlags = PTR_FLAGS_BUTTON2 | PTR_FLAGS_DOWN; break;  // 右鍵按下
    case 4: ptrFlags = PTR_FLAGS_BUTTON2; break;                   // 右鍵釋放
    case 0: ptrFlags = PTR_FLAGS_MOVE; break;                      // 滑鼠移動
    default: return;                                               // 無效旗標
    }
    // 發送滑鼠事件到遠端桌面
    instance->context->input->MouseEvent(instance->context->input, ptrFlags, x, y);
}

EXPORT_FUNC BOOL rdpb_check_connection(freerdp* instance) {
    // 檢查參數有效性
    if (!instance || !instance->context) return FALSE;
    // 檢查是否應該斷開連線，返回相反值 (TRUE 表示連線正常)
    return !freerdp_shall_disconnect_context(instance->context);
}

EXPORT_FUNC void rdpb_free(freerdp* instance) {
    if (instance) {
        // 釋放共享記憶體資源
        Shm_Free();
        // 釋放 GDI 資源
        gdi_free(instance);
        // 斷開 RDP 連線
        freerdp_disconnect(instance);
        // 釋放 RDP 上下文
        freerdp_context_free(instance);
        // 釋放 RDP 實例
        freerdp_free(instance);
        // 清理 Windows Socket API
        WSACleanup();
    }
}