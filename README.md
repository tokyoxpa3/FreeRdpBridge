# RDP Client

一個基於 Python 和 FreeRDP 的遠端桌面協定 (RDP) 客戶端應用程式，提供完整的遠端桌面控制功能，使用 PySide6 和 OpenGL GPU 加速進行影像渲染。

## 功能特性

- **即時桌面串流**：透過 RDP 協定接收遠端桌面畫面
- **滑鼠控制**：支援完整的滑鼠操作（點擊、移動、滾輪、中鍵）
- **鍵盤控制**：支援完整的鍵盤輸入（包括修飾鍵和功能鍵）
- **GPU 加速渲染**：使用 PySide6 QOpenGLWidget 進行硬體加速顯示
- **三級效能優化**：實現 Level 1-3 的逐層效能優化架構
- **零複製記憶體管理**：使用 memoryview 和 gdi_init_ex 實現零複製影像傳輸
- **多執行緒架構**：確保 UI 流暢性
- **鍵盤鎖定狀態同步**：自動同步本機與遠端的 NumLock/CapsLock/ScrollLock 狀態
- **防手震機制**：避免滑鼠快速點擊時的誤觸問題

## RdpBridge 模組

本專案使用自訂的 RdpBridge 模組作為 Python 應用程式與 FreeRDP 函式庫之間的橋接層。RdpBridge 是一個 C 語言編寫的動態連結庫 (DLL)，提供以下核心功能：

### 功能特色
- **簡化的 RDP 連線 API**：封裝複雜的 FreeRDP 初始化流程
- **雙模式認證**：支援自動登入 (NLA) 和手動登入 (GUI) 模式
- **動態共享記憶體影像傳輸**：使用高效能的共享記憶體機制傳輸桌面影像，每個連線實例有獨立的共享記憶體名稱
- **輸入控制**：支援鍵盤掃描碼和滑鼠事件的發送
- **連線狀態管理**：提供連線檢查和資源清理功能
- **鍵盤鎖定狀態同步**：支援同步 NumLock/CapsLock/ScrollLock 狀態

### 架構設計
RdpBridge 使用 Windows 共享記憶體機制在不同進程間高效傳輸影像資料：
- **名稱**：動態生成，格式為 `Local\RdpBridgeMem_<instance_address>`
- **大小**：根據解析度動態調整
- **同步**：使用命名互斥鎖 `Local\RdpBridgeMutex_<instance_address>` 確保多執行緒存取安全

### API 函數介面
- `rdpb_connect`：建立 RDP 連線 (支援自動和手動登入模式)
- `rdpb_free`：釋放 RDP 連線資源
- `rdpb_step`：處理連線心跳和影像更新
- `rdpb_send_scancode`：發送鍵盤掃描碼
- `rdpb_send_mouse`：發送滑鼠事件（支援左鍵、右鍵、中鍵、滾輪）
- `rdpb_check_connection`：檢查連線狀態
- `rdpb_get_shm_name`：取得該實例專屬的共享記憶體名稱
- `rdpb_sync_locks`：同步鍵盤鎖定狀態 (NumLock, CapsLock, ScrollLock)

## 系統需求

- Windows 作業系統
- Python 3.7 或更高版本
- FreeRDP 3.x (包含 RdpBridge.dll)
- Microsoft Visual C++ Redistributable (VC++ Runtime)

## 依賴套件

- numpy
- opencv-python
- pynput
- pywin32
- PySide6
- PyOpenGL
- PyOpenGL_accelerate

## 安裝方式

1. 安裝 Python 3.7+
2. 安裝 Microsoft Visual C++ Redistributable (VC++ Runtime)
   - 下載並安裝適用於 Visual Studio 2015-2022 的 Visual C++ Redistributable
   - 下載連結：https://aka.ms/vc14/vc_redist.x64.exe
   - 資訊來源：https://learn.microsoft.com/zh-tw/cpp/windows/latest-supported-vc-redist?view=msvc-170
3. 安裝所需的 Python 套件：
```bash
pip install -r requirements.txt
```

4. 確保 FreeRDP 相關 DLL 檔案存在於專案目錄下的 libs 資料夾中：
- libs/rdp/RdpBridge.dll
- libs/rdp/freerdp3.dll
- libs/rdp/avcodec-61.dll
- libs/rdp/avutil-59.dll
- libs/rdp/libcrypto-3-x64.dll
- libs/rdp/libssl-3-x64.dll
- libs/rdp/swresample-5.dll
- libs/rdp/swscale-8.dll
- libs/rdp/winpr3.dll
- libs/rdp/zlib1.dll

## 使用方式

編輯 `rdp_client_gpu.py` 中的連線參數：

```python
RDP_IP = "127.0.0.2"
RDP_PORT = 3389
RDP_USER = "Admin1"
RDP_PASS = ""
```

然後執行：

```bash
python rdp_client_gpu.py
```

## 技術架構

### 核心組件

- **RdpBackend 類別**：負責 RDP 連線管理和影像串流，支援動態共享記憶體名稱
- **HeartbeatThread 類別**：處理 RDP 連線心跳和斷線檢測
- **RdpGLWidget 類別**：使用 OpenGL GPU 加速的影像顯示組件，支援鍵盤鎖定狀態同步
- **FrameWatcherThread 類別**：使用 Windows 事件機制監控幀更新，實現高效的事件驅動更新
- **GlobalKeyboardHook 類別**：實現全局鍵盤鉤子，特別處理 Windows 鍵等特殊按鍵，確保在遠端桌面環境中的正常使用
- **MainWindow 類別**：主視窗管理，包含系統托盤功能和視窗顯示/隱藏切換
- **三級效能優化架構**：
  - Level 1：使用 glTexSubImage2D 替代傳統繪圖方法，直接更新 VRAM 紋理
  - Level 2：事件驅動架構取代輪詢，降低 CPU 使用率
  - Level 3：使用 gdi_init_ex 實現 C 端零拷貝，直接綁定共享記憶體指標
- **共享記憶體 (SHM)**：用於高效能影像資料傳輸，每個連線實例有獨立的共享記憶體
- **memoryview 零複製技術**：避免不必要的記憶體複製
- **系統托盤功能**：支援視窗最小化至系統托盤，並可在背景持續接收 RDP 影像串流
- **視窗可見性控制**：當視窗隱藏時自動停止 GPU 渲染，降低資源消耗，但仍維持 RDP 連線和影像串流接收

### 鍵盤掃描碼對應

應用程式支援完整的鍵盤掃描碼對應，包括：

- 修飾鍵（Shift、Ctrl、Alt、Win）
- 功能鍵（F1-F12）
- 導航鍵（方向鍵、Home、End、Page Up/Down）
- 特殊鍵（Enter、Tab、Esc、Backspace）
- 鎖定鍵（NumLock、CapsLock、ScrollLock）

### 滑鼠支援

應用程式支援完整的滑鼠操作：

- 左鍵點擊/釋放
- 右鍵點擊/釋放
- 中鍵點擊/釋放
- 滑鼠移動
- 滾輪上下滾動
- 雙擊事件
- 防手震機制

## 輸入處理機制

### 滑鼠處理

滑鼠事件透過 PySide6 的回調函數處理，支援：

- 左鍵點擊/釋放
- 右鍵點擊/釋放
- 中鍵點擊/釋放
- 滑鼠移動
- 滾輪事件（向上/向下）
- 雙擊事件
- 防手震機制避免快速點擊時的誤觸

### 鍵盤處理

鍵盤事件透過 PySide6 監聽，並根據按鍵事件進行處理。
支援延伸鍵碼處理，確保特殊按鍵正確傳遞至遠端主機。
支援鍵盤鎖定狀態同步（NumLock、CapsLock、ScrollLock），確保本機與遠端狀態一致。

## 視窗管理

應用程式使用 PySide6 的 QOpenGLWidget 進行 GPU 加速渲染，提供流暢的影像顯示體驗。

## 記憶體管理

使用動態共享記憶體機制和 memoryview 零複製技術進行影像資料傳輸，確保高效能串流。每個 RDP 連線實例都有其專屬的共享記憶體空間。
## 三級效能優化架構

本專案實現了三級效能優化架構，逐層提升效能表現：

### Level 1 (簡單且有效)：OpenGL 渲染優化
- 修改 Python 的渲染邏輯，改用 `glTexSubImage2D` 替代傳統繪圖方法
- 直接更新 VRAM 中的紋理數據，避免重新分配紋理記憶體
- 使用純 OpenGL 渲染管道，避免 QPainter 與 OpenGL 的衝突

### Level 2 (減少 CPU)：事件驅動架構
- 在 C 與 Python 之間建立 Event Object 通知機制，取代 QTimer 輪詢
- 採用 Windows 事件機制實現高效的幀更新通知，取代傳統的輪詢方式
- 透過 `FrameWatcherThread` 監聽由 RdpBridge 發出的命名事件，當有新幀可用時才觸發更新
- 使用 `WaitForSingleObject` 實現低功耗睡眠模式，大幅降低 CPU 使用率

### Level 3 (進階)：C 端零拷貝技術
- 實作 `gdi_init_ex` 達成真正意義上的 C 端零拷貝
- 在 C 端直接將像素數據寫入共享記憶體，消除記憶體複製開銷
- 使用 `gdi_init_ex` 直接綁定共享記憶體指標，實現真正的零拷貝傳輸

## 事件驅動架構

### FrameWatcherThread
- 使用 Windows 命名事件機制監控 RDP 影像更新
- 透過 `WaitForSingleObject` 實現低功耗等待，僅在有新幀時才觸發 UI 更新
- 避免傳統輪詢方式造成的 CPU 資源浪費

### Windows API 集成
- 使用底層 Windows API (`SetWindowsHookExW`, `GetMessage`, `TranslateMessage`, `DispatchMessage`) 實現全局鍵盤事件捕獲
- 正確處理擴展鍵碼和特殊按鍵（如 Windows 鍵）

## 系統托盤功能

### 視窗管理
- 支援將 RDP 視窗最小化至系統托盤
- 提供「顯示 RDP 視窗」和「隱藏 RDP 視窗」選項
- 點擊系統托盤圖示可快速切換視窗顯示狀態
- 使用 `Ctrl+H` 快捷鍵可快速隱藏視窗

### 背景模式
- 視窗隱藏時維持 RDP 連線和影像串流接收
- 自動停止 GPU 渲染以降低資源消耗
- 透過 `is_ui_visible` 標誌控制 OpenGL 渲染邏輯

## 全局鍵盤鉤子

### 特殊按鍵處理
- 捕獲全局 Windows 鍵事件（VK_LWIN, VK_RWIN）
- 當 RDP 視窗為前景視窗時，將 Windows 鍵事件轉發至遠端桌面
- 防止 Windows 鍵在遠端桌面環境中失效

### 鍵盤鎖定狀態同步
- 自動同步本機與遠端的 NumLock、CapsLock、ScrollLock 狀態
- 在視窗獲得焦點時自動更新鎖定狀態
- 支援手動觸發狀態同步（如按下 NumLock 鍵時）

## 設計考量

- **效能優化**：GPU 加速渲染和零複製記憶體管理
- **穩定性**：妥善處理連線異常和視窗關閉事件
- **相容性**：支援常見的鍵盤掃描碼對應
- **即時性**：移除不必要的延遲，確保即時響應
- **多連線支援**：每個連線實例有獨立的共享記憶體空間
- **狀態同步**：自動同步鍵盤鎖定狀態
- **三級效能優化**：實現 Level 1-3 的逐層效能提升架構，包含 OpenGL 渲染優化、事件驅動機制和 C 端零拷貝技術
- **純 GPU 渲染管道**：完全使用 OpenGL 渲染，避免與 QPainter 的衝突
- **高效事件通知**：使用 Windows 事件機制實現低功耗的幀更新通知
## API 函數介面

### RdpBridge.dll 函數介面
- `rdpb_connect(ip, port, username, password, width, height, color_depth)`：建立 RDP 連線
- `rdpb_step(instance)`：處理連線心跳和影像更新
- `rdpb_send_scancode(instance, scancode, flags)`：發送鍵盤掃描碼
- `rdpb_send_mouse(instance, flags, x, y)`：發送滑鼠事件
- `rdpb_free(instance)`：釋放連線資源
- `rdpb_get_shm_name(instance)`：取得該實例專屬的共享記憶體名稱
- `rdpb_get_event_name(instance)`：取得該實例專屬的事件名稱
- `rdpb_sync_locks(instance, flags)`：同步鍵盤鎖定狀態
- `rdpb_set_visibility(instance, is_visible)`：設定連線可見性

### 滑鼠事件旗標
- 0: 滑鼠移動
- 1: 左鍵按下
- 2: 左鍵釋放
- 3: 右鍵按下
- 4: 右鍵釋放
- 5: 滾輪向上
- 6: 滾輪向下
- 7: 中鍵按下
- 8: 中鍵釋放

### 鍵盤鎖定狀態旗標
- 1: ScrollLock
- 2: NumLock
- 4: CapsLock

## 已知問題

- 在某些系統配置下可能存在游標顯示問題
- 特定鍵盤佈局可能需要調整掃描碼對應

## 故障排除

### 常見問題與解決方案

#### 1. 連線失敗
- 確認目標主機的 RDP 服務是否已啟用
- 檢查防火牆設定，確保連接埠 3389 未被封鎖
- 驗證使用者名稱和密碼是否正確
- 確認網路連線是否穩定

#### 2. 影像顯示異常
- 確認 GPU 驅動程式已更新至最新版本
- 檢查是否正確安裝了 Visual C++ Redistributable
- 嘗試調整 RDP_COLOR 設定（16, 24, 32 位元）

#### 3. 輸入反應遲緩
- 檢查網路連線品質
- 確認共享記憶體設定是否正確
- 驗證 OpenGL 硬體加速是否正常工作

#### 4. Windows 鍵無法使用
- 確認全局鍵盤鉤子已正確安裝
- 檢查是否有其他應用程式佔用了相同的鍵盤事件
- 驗證 RDP 視窗是否為前景視窗

#### 5. 系統托盤功能異常
- 確認 Qt 的系統托盤功能是否支援
- 檢查 `setQuitOnLastWindowClosed(False)` 是否正確設定
- 驗證 Windows API 訪問權限


## 授權

本專案採用 MIT 授權條款，詳見 LICENSE 檔案。

## 貢獻

歡迎提交 Issue 和 Pull Request。請參考 CONTRIBUTING.md 瞭解詳細貢獻指南。

## 更新日誌

請參考 CHANGELOG.md 瞭解版本更新資訊。