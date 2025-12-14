# RDP Client

一個基於 Python 和 FreeRDP 的遠端桌面協定 (RDP) 客戶端應用程式，提供完整的遠端桌面控制功能，使用 PySide6 和 OpenGL GPU 加速進行影像渲染。

## 功能特性

- **即時桌面串流**：透過 RDP 協定接收遠端桌面畫面
- **滑鼠控制**：支援完整的滑鼠操作（點擊、移動、滾輪）
- **鍵盤控制**：支援完整的鍵盤輸入（包括修飾鍵和功能鍵）
- **GPU 加速渲染**：使用 PySide6 QOpenGLWidget 進行硬體加速顯示
- **零複製記憶體管理**：使用 memoryview 實現零複製影像傳輸
- **多執行緒架構**：確保 UI 流暢性

## RdpBridge 模組

本專案使用自訂的 RdpBridge 模組作為 Python 應用程式與 FreeRDP 函式庫之間的橋接層。RdpBridge 是一個 C 語言編寫的動態連結庫 (DLL)，提供以下核心功能：

### 功能特色
- **簡化的 RDP 連線 API**：封裝複雜的 FreeRDP 初始化流程
- **雙模式認證**：支援自動登入 (NLA) 和手動登入 (GUI) 模式
- **共享記憶體影像傳輸**：使用高效能的共享記憶體機制傳輸桌面影像
- **輸入控制**：支援鍵盤掃描碼和滑鼠事件的發送
- **連線狀態管理**：提供連線檢查和資源清理功能

### 架構設計
RdpBridge 使用 Windows 共享記憶體機制在不同進程間高效傳輸影像資料：
- **名稱**：`Local\RdpBridgeMem`
- **大小**：最大支援 1920x1080 解析度的 BGRA32 影像
- **同步**：使用命名互斥鎖 `Local\RdpBridgeMutex` 確保多執行緒存取安全

### API 函數介面
- `rdpb_connect`：建立 RDP 連線 (支援自動和手動登入模式)
- `rdpb_free`：釋放 RDP 連線資源
- `rdpb_step`：處理連線心跳和影像更新
- `rdpb_send_scancode`：發送鍵盤掃描碼
- `rdpb_send_mouse`：發送滑鼠事件
- `rdpb_check_connection`：檢查連線狀態

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
- libs/RdpBridge.dll
- libs/freerdp3.dll
- libs/avcodec-61.dll
- libs/avutil-59.dll
- libs/libcrypto-3-x64.dll
- libs/libssl-3-x64.dll
- libs/swresample-5.dll
- libs/swscale-8.dll
- libs/winpr3.dll
- libs/zlib1.dll

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

- **RdpBackend 類別**：負責 RDP 連線管理和影像串流
- **HeartbeatThread 類別**：處理 RDP 連線心跳和斷線檢測
- **RdpGLWidget 類別**：使用 OpenGL GPU 加速的影像顯示組件
- **共享記憶體 (SHM)**：用於高效能影像資料傳輸
- **memoryview 零複製技術**：避免不必要的記憶體複製

### 鍵盤掃描碼對應

應用程式支援完整的鍵盤掃描碼對應，包括：

- 修飾鍵（Shift、Ctrl、Alt、Win）
- 功能鍵（F1-F12）
- 導航鍵（方向鍵、Home、End、Page Up/Down）
- 特殊鍵（Enter、Tab、Esc、Backspace）

## 輸入處理機制

### 滑鼠處理

滑鼠事件透過 PySide6 的回調函數處理，支援：
- 左鍵點擊/釋放
- 右鍵點擊/釋放
- 滑鼠移動
- 雙擊事件

### 鍵盤處理

鍵盤事件透過 PySide6 監聽，並根據按鍵事件進行處理。
支援延伸鍵碼處理，確保特殊按鍵正確傳遞至遠端主機。

## 視窗管理

應用程式使用 PySide6 的 QOpenGLWidget 進行 GPU 加速渲染，提供流暢的影像顯示體驗。

## 記憶體管理

使用共享記憶體機制和 memoryview 零複製技術進行影像資料傳輸，確保高效能串流。

## 設計考量

- **效能優化**：GPU 加速渲染和零複製記憶體管理
- **穩定性**：妥善處理連線異常和視窗關閉事件
- **相容性**：支援常見的鍵盤掃描碼對應
- **即時性**：移除不必要的延遲，確保即時響應

## 已知問題

- 在某些系統配置下可能存在游標顯示問題
- 特定鍵盤佈局可能需要調整掃描碼對應

## 授權

本專案採用 MIT 授權條款，詳見 LICENSE 檔案。

## 貢獻

歡迎提交 Issue 和 Pull Request。請參考 CONTRIBUTING.md 瞭解詳細貢獻指南。

## 更新日誌

請參考 CHANGELOG.md 瞭解版本更新資訊。