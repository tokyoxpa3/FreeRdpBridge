# RdpBridge

RdpBridge 是一個用於 RDP (Remote Desktop Protocol) 連線的 C 語言動態連結庫 (DLL)，主要作為 Python 應用程式與 FreeRDP 函式庫之間的橋接層。它提供了簡化的 API 來建立 RDP 連線、處理輸入事件、以及透過共享記憶體 (shared memory) 機制進行影像串流。

## 功能特色

- **簡化的 RDP 連線 API**：封裝複雜的 FreeRDP 初始化流程
- **雙模式認證**：支援自動登入 (NLA) 和手動登入 (GUI) 模式
- **共享記憶體影像傳輸**：使用高效能的共享記憶體機制傳輸桌面影像
- **輸入控制**：支援鍵盤掃描碼和滑鼠事件的發送
- **連線狀態管理**：提供連線檢查和資源清理功能

## 架構設計

### 共享記憶體 (Shared Memory) 機制

RdpBridge 使用 Windows 共享記憶體機制在不同進程間高效傳輸影像資料：

- **名稱**：`Local\RdpBridgeMem`
- **大小**：最大支援 1920x1080 解析度的 BGRA32 影像
- **結構**：
  - `ShmHeader`：包含影像的寬度、高度、步幅和框架 ID
  - `pPixelData`：指向實際影像像素資料的指標

### 同步機制

- 使用命名互斥鎖 (mutex) `Local\RdpBridgeMutex` 確保多執行緒存取共享記憶體的安全性

## API 函數說明

### 連線與資源管理

#### `rdpb_connect`
建立 RDP 連線的主函數

```c
freerdp* rdpb_connect(const char* ip, int port, const char* username, const char* password, int width, int height);
```

- **參數**：
  - `ip`：目標 RDP 伺服器 IP 位址
  - `port`：RDP 連接埠 (預設 3389)
  - `username`：使用者名稱
  - `password`：使用者密碼
  - `width`：桌面寬度
  - `height`：桌面高度
- **回傳值**：成功時回傳 freerdp 實例指標，失敗時回傳 NULL
- **功能**：
  - 嘗試使用 NLA (Network Level Authentication) 自動登入
  - 若自動登入失敗，則回退到手動登入模式

#### `rdpb_free`
釋放 RDP 連線資源

```c
void rdpb_free(freerdp* instance);
```

- **參數**：freerdp 實例指標
- **功能**：斷開連線、釋放資源、清理共享記憶體

### 連線維護與影像串流

#### `rdpb_step`
處理 RDP 連線的心跳和影像更新

```c
int rdpb_step(freerdp* instance);
```

- **參數**：freerdp 實例指標
- **回傳值**：連線正常時回傳 1，連線中斷時回傳 0
- **功能**：
  - 檢查並處理 RDP 事件
  - 將最新的桌面影像更新到共享記憶體

#### `rdpb_check_connection`
檢查 RDP 連線狀態

```c
BOOL rdpb_check_connection(freerdp* instance);
```

- **參數**：freerdp 實例指標
- **回傳值**：連線正常時回傳 TRUE，否則回傳 FALSE

### 輸入控制

#### `rdpb_send_scancode`
發送鍵盤掃描碼到遠端桌面

```c
void rdpb_send_scancode(freerdp* instance, int scancode, int flags);
```

- **參數**：
  - `instance`：freerdp 實例指標
  - `scancode`：鍵盤掃描碼
  - `flags`：按鍵狀態旗標 (1=按下, 0=釋放; 2=延伸鍵)

#### `rdpb_send_mouse`
發送滑鼠事件到遠端桌面

```c
void rdpb_send_mouse(freerdp* instance, int flags, int x, int y);
```

- **參數**：
  - `instance`：freerdp 實例指標
  - `flags`：滑鼠事件旗標 (0=移動, 1=左鍵按下, 2=左鍵釋放, 3=右鍵按下, 4=右鍵釋放)
  - `x`：X 座標
  - `y`：Y 座標

## 技術細節

### RDP 連線設定

RdpBridge 使用以下重要的 RDP 設定來優化連線品質：

- `SoftwareGdi = FALSE`：關閉軟體 GDI，啟用硬體加速
- `SupportGraphicsPipeline = TRUE`：啟用圖形管線
- `GfxH264 = TRUE`：使用 H.264 編碼
- `GfxAVC444 = TRUE`：使用高品質 AVC444 編碼

### 雙模式登入策略

RdpBridge 採用兩階段登入策略：

1. **自動登入模式 (NLA)**：嘗試使用提供的使用者名稱和密碼進行自動驗證
2. **手動登入模式 (GUI)**：若自動登入失敗，則顯示遠端桌面的登入畫面

這種設計確保了與不同安全設定的 RDP 伺服器的相容性。

## 編譯設定

此專案使用 Visual Studio 2022 (v143) 工具集編譯，生成 64 位元動態連結庫。編譯時需要指定 FreeRDP 和 WinPR 的標頭檔案路徑及函式庫路徑。

## 依賴關係

- FreeRDP 3.x
- WinPR (Windows Portable Runtime)
- Windows Sockets 2.0 (ws2_32.lib)

## 使用範例

在 Python 程式中可以透過 ctypes 載入並使用 RdpBridge：

```python
import ctypes

# 載入 DLL
bridge = ctypes.CDLL('./libs/RdpBridge.dll')

# 建立連線
rdp_instance = bridge.rdpb_connect(b"192.168.1.100", 3389, b"username", b"password", 1920, 1080)

# 定期處理連線
while bridge.rdpb_check_connection(rdp_instance):
    bridge.rdpb_step(rdp_instance)
    
# 釋放資源
bridge.rdpb_free(rdp_instance)