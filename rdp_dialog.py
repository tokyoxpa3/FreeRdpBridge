from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QFormLayout, QSpinBox, 
                               QCheckBox, QComboBox, QMessageBox)

class RDPLoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RDP 連線設定")
        self.resize(350, 250)
        
        self.result_data = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.ip_input = QLineEdit("127.0.0.2")
        self.user_input = QLineEdit("Admin")
        self.pwd_input = QLineEdit("")
        self.pwd_input.setEchoMode(QLineEdit.Password)
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(3389)
        
        # [修改] 解析度改為下拉選單
        self.res_input = QComboBox()
        # 加入您指定的解析度列表
        resolutions = ["800 x 600", "1024 x 768", "1366 x 768", "1600 x 900", "1920 x 1080"]
        self.res_input.addItems(resolutions)
        self.res_input.setEditable(True) # 允許手動輸入其他解析度
        self.res_input.setCurrentText("800 x 600") # 預設值 (更常見的解析度)
        
        # 色彩深度
        self.color_input = QComboBox()
        self.color_input.addItems(["16", "24", "32"])
        self.color_input.setCurrentText("16") # 預設高品質 (從16改為32)

        # 加入表單
        form.addRow("伺服器 IP:", self.ip_input)
        form.addRow("通訊埠 (Port):", self.port_input)
        form.addRow("使用者名稱:", self.user_input)
        form.addRow("密碼:", self.pwd_input)
        
        form.addRow("解析度:", self.res_input) # 改用單一欄位
        form.addRow("色彩深度 (Bit):", self.color_input)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("連線")
        btn_ok.clicked.connect(self.accept_data)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def accept_data(self):
        # [修改] 解析寬高
        res_text = self.res_input.currentText().lower()
        try:
            # 支援 1024x768, 1024*768, 1024 768 等格式
            import re
            parts = re.split(r'[x\*\s,]+', res_text.strip())
            if len(parts) >= 2:
                width = int(parts[0])
                height = int(parts[1])
            else:
                raise ValueError
        except Exception:
            QMessageBox.warning(self, "格式錯誤", "解析度格式錯誤 (範例: 1024x768)")
            return

        self.result_data = {
            'server': self.ip_input.text(),
            'port': self.port_input.value(),
            'username': self.user_input.text(),
            'password': self.pwd_input.text(),
            'width': width,
            'height': height,
            'color_depth': int(self.color_input.currentText())
        }
        self.accept()

    def get_data(self):
        return self.result_data