#pragma once
#include <winpr/wtypes.h>
#include <freerdp/freerdp.h>
#include <freerdp/input.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifdef _WIN32
// 在 Windows 平台上，使用 __declspec(dllexport) 匯出函數
#define EXPORT_FUNC __declspec(dllexport)
#else
// 在非 Windows 平台上，不需要特殊的匯出修飾符
#define EXPORT_FUNC
#endif

    // 連線與資源管理函數
    /**
     * @brief 建立 RDP 連線
     * @param ip RDP 伺服器 IP 位址
     * @param port RDP 連接埠 (通常為 3389)
     * @param username 使用者名稱
     * @param password 使用者密碼
     * @param width 桌面寬度
     * @param height 桌面高度
     * @param color_depth 色彩深度 (例如 16, 24, 32)
     * @return 成功時返回 freerdp 實例指標，失敗時返回 NULL
     * @details 此函數會先嘗試使用 NLA 自動登入，若失敗則回退到手動登入模式
     */
    EXPORT_FUNC freerdp* rdpb_connect(const char* ip, int port, const char* username, const char* password, int width, int height, int color_depth);
    
    /**
     * @brief 釋放 RDP 連線資源
     * @param instance freerdp 實例指標
     * @details 斷開連線並釋放所有相關資源，包括共享記憶體
     */
    EXPORT_FUNC void rdpb_free(freerdp* instance);

    // 連線維護與影像串流函數
    /**
     * @brief 處理 RDP 連線的心跳和影像更新
     * @param instance freerdp 實例指標
     * @return 連線正常時返回 1，連線中斷時返回 0
     * @details 此函數處理 RDP 事件並將最新影像更新到共享記憶體
     */
    EXPORT_FUNC int rdpb_step(freerdp* instance);

    // 輸入控制函數
    /**
     * @brief 發送鍵盤掃描碼到遠端桌面
     * @param instance freerdp 實例指標
     * @param scancode 鍵盤掃描碼
     * @param flags 按鍵狀態旗標 (1=按下, 0=釋放; 2=延伸鍵)
     */
    EXPORT_FUNC void rdpb_send_scancode(freerdp* instance, int scancode, int flags);
    
    /**
     * @brief 發送滑鼠事件到遠端桌面
     * @param instance freerdp 實例指標
     * @param flags 滑鼠事件旗標 (0=移動, 1=左鍵按下, 2=左鍵釋放, 3=右鍵按下, 4=右鍵釋放)
     * @param x X 座標
     * @param y Y 座標
     */
    EXPORT_FUNC void rdpb_send_mouse(freerdp* instance, int flags, int x, int y);

    // 狀態檢查函數
    /**
     * @brief 檢查 RDP 連線狀態
     * @param instance freerdp 實例指標
     * @return 連線正常時返回 TRUE，否則返回 FALSE
     */
    EXPORT_FUNC BOOL rdpb_check_connection(freerdp* instance);

    /**
     * @brief 同步鍵盤鎖定狀態 (NumLock, CapsLock, ScrollLock)
     * @param instance freerdp 實例指標
     * @param flags 鎖定旗標 (1=ScrollLock, 2=NumLock, 4=CapsLock)
     */
    EXPORT_FUNC void rdpb_sync_locks(freerdp* instance, int flags);

    // [新增] 匯出函數：讓 Python 取得正確的 SHM 名稱
    EXPORT_FUNC const char* rdpb_get_shm_name(freerdp* instance);

#ifdef __cplusplus
}
#endif