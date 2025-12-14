# 貢獻指南

感謝您有興趣為 RDP Client 專案做出貢獻！本指南將幫助您了解如何參與此專案。

## 環境設定

在開始貢獻之前，請確保您的開發環境已正確設定：

1. 安裝 Python 3.7 或更高版本
2. 安装 Microsoft Visual C++ Redistributable (VC++ Runtime)
   - 下載並安裝適用於 Visual Studio 2015-2022 的 Visual C++ Redistributable
   - 下載連結：https://aka.ms/vc14/vc_redist.x64.exe
   - 資訊來源：https://learn.microsoft.com/zh-tw/cpp/windows/latest-supported-vc-redist?view=msvc-170
3. 克隆專案到本機：
   ```bash
   git clone https://github.com/yourusername/rdp_client.git
   ```
4. 安裝依賴套件：
   ```bash
   pip install -r requirements.txt
   ```
5. 確保 FreeRDP 相關 DLL 檔案存在於專案根目錄

## 編碼規範

### Python 程式碼
- 遵循 PEP 8 編碼風格
- 使用有意義的變數名稱
- 保持函數簡潔，避免過長
- 每行程式碼不超過 120 字元

### 注釋和文件字符串
- 為所有公共函數和類別添加適當的文件字符串
- 在複雜邏輯處添加說明性注釋
- 使用繁體中文撰寫注釋

## 貢獻流程

### 回報問題 (Issues)
1. 檢查是否已有相似問題被回報
2. 提供詳細的再現步驟
3. 包含錯誤訊息和環境資訊
4. 標註適當的標籤

### 功能請求 (Feature Requests)
1. 描述您想要的功能
2. 解釋該功能的用途和價值
3. 提供可能的實作建議

### 提交拉取請求 (Pull Requests)
1. Fork 此專案
2. 建立新的分支 (`git checkout -b feature/AmazingFeature`)
3. 提交您的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 開啟拉取請求

## 開發指南

### 測試變更
在提交更改前，請確保：
- 修正了所有語法錯誤
- 測試了功能是否正常運作
- 檢查了跨平台相容性

### 設計原則
- 保持代碼可讀性和可維護性
- 遵循既有的程式碼結構和風格
- 確保效能優化
- 重視使用者體驗

## 專案結構

```
rdp_client/
├── rdp_client_gpu.py      # 主要應用程式邏輯 (使用 PySide6 和 OpenGL GPU 加速)
├── requirements.txt       # Python 依賴套件清單
├── README.md             # 專案說明文件
├── LICENSE               # 授權條款
├── CHANGELOG.md          # 更新日誌
└── CONTRIBUTING.md       # 貢獻指南
```

## 專門領域說明

### RDP 通訊協定
- 使用 FreeRDP 3.x 作為底層通訊庫
- 透過 RdpBridge.dll 與原生 RDP 實作互動
- 使用共享記憶體進行高效能影像傳輸

### GPU 加速渲染
- 使用 PySide6 的 QOpenGLWidget 進行硬體加速顯示
- 實現零複製記憶體管理，使用 memoryview 避免不必要的記憶體複製
- 高效能影像渲染，提升串流體驗

### 輸入處理
- 滑鼠事件透過 PySide6 處理
- 鍵盤事件透過 PySide6 監聽
- 實作完整的掃描碼對應表

## 需要協助的地方

我們特別歡迎以下方面的貢獻：
- 改善跨平台相容性
- 優化效能表現
- 增強錯誤處理機制
- 改善使用者介面體驗
- 扩展鍵盤佈局支援
- 完善測試案例
- GPU 加速和零複製記憶體管理的優化

## 社群準則

- 尊重所有貢獻者和使用者
- 保持友善和專業的態度
- 積極提供建設性的回饋
- 遵守開放原始碼精神

## 聯絡方式

如有疑問，請透過 GitHub Issues 聯絡我們。

再次感謝您的貢獻！