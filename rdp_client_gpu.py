import sys
import ctypes
import time
import mmap
import struct
from ctypes import windll

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QImage, QPainter

# --- 使用者設定 ---
RDP_IP = "127.0.0.2"
RDP_PORT = 3389
RDP_USER = "Admin1"
RDP_PASS = ""

# --- 效能關鍵設定 ---
RDP_WIDTH = 800
RDP_HEIGHT = 600

# 色彩深度 (Bits Per Pixel)
# 32 = 高畫質 (佔頻寬)
# 24 = 標準
# 16 = 高效能 (顏色會有輕微色帶，但頻寬減半，遊戲推薦)
# 15 = 舊系統用
RDP_COLOR = 16 

# --- DLL 設定 ---
dll_path = "./libs/RdpBridge.dll"
try:
    rdp = ctypes.CDLL(dll_path)
except OSError:
    print(f"錯誤: 找不到 {dll_path}")
    sys.exit(1)

# 1. 修改 argtypes：現在有 7 個參數 (最後三個是 int: width, height, color)
rdp.rdpb_connect.argtypes = [
    ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, 
    ctypes.c_int, ctypes.c_int, ctypes.c_int
]
rdp.rdpb_connect.restype = ctypes.c_void_p
# ... (其他定義不變) ...
rdp.rdpb_step.argtypes = [ctypes.c_void_p]
rdp.rdpb_step.restype = ctypes.c_int
rdp.rdpb_send_scancode.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
rdp.rdpb_send_mouse.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
rdp.rdpb_free.argtypes = [ctypes.c_void_p]

SHM_NAME = "Local\\RdpBridgeMem"
HEADER_SIZE = 16

class RdpBackend:
    # 2. 建構子接收 color_depth
    def __init__(self, ip, port, user, password, width, height, color_depth):
        print(f"[RDP] 正在連線到 {ip} ...")
        print(f"      解析度: {width}x{height}, 色彩: {color_depth}-bit")
        
        # 3. 傳遞參數給 C DLL
        self.instance = rdp.rdpb_connect(
            ip.encode(), port, user.encode(), password.encode(), 
            width, height, color_depth
        )
        
        if not self.instance:
            raise Exception("RDP 連線失敗！")
        
        print("[RDP] 連線成功！")
        self.last_sent_x = -1
        self.last_sent_y = -1
        self.shm = mmap.mmap(-1, 1024, tagname=SHM_NAME)
        self.shm_size = 1024

    # ... (其餘 backend 方法完全不需要改) ...
    # 為什麼不需要改 memoryview 計算？
    # 因為 C 語言雖然用 16-bit 傳輸，但在內部還是轉成了 32-bit (BGRA) 寫入共享記憶體
    # 這樣 Python 端的 QImage 處理邏輯可以保持最簡單且最高效。
    
    def step(self): return rdp.rdpb_step(self.instance)
    def check_new_frame(self, last_fid):
        self.shm.seek(0)
        buf = self.shm.read(HEADER_SIZE)
        w, h, s, fid = struct.unpack('IIII', buf)
        if w > 0 and fid != last_fid: return True, w, h, s, fid
        return False, 0, 0, 0, last_fid
    def get_memory_view(self, width, height):
        required_size = HEADER_SIZE + (width * height * 4)
        if self.shm_size < required_size:
            self.shm.close()
            self.shm = mmap.mmap(-1, required_size, tagname=SHM_NAME)
            self.shm_size = required_size
        self.shm.seek(HEADER_SIZE)
        mv = memoryview(self.shm)
        return mv[HEADER_SIZE : HEADER_SIZE + (width * height * 4)]
    def send_mouse(self, flags, x, y):
        self.last_sent_x = x; self.last_sent_y = y
        rdp.rdpb_send_mouse(self.instance, flags, x, y)
    def send_scancode(self, scancode, is_down, is_extended):
        flag_val = (1 if is_down else 0) | (2 if is_extended else 0)
        rdp.rdpb_send_scancode(self.instance, scancode, flag_val)
    def close(self):
        if self.instance: rdp.rdpb_free(self.instance); self.instance = None
        if self.shm: self.shm.close()

# ... (HeartbeatThread 保持不變) ...
class HeartbeatThread(QThread):
    connection_lost = Signal()
    def __init__(self, backend): super().__init__(); self.backend = backend; self.running = True
    def run(self):
        while self.running:
            if self.backend.step() == 0: self.connection_lost.emit(); break
    def stop(self): self.running = False; self.wait()

# ... (RdpGLWidget 保持不變) ...
class RdpGLWidget(QOpenGLWidget):
    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.current_image = None
        self.last_fid = 0
        self.current_mv = None 
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_frame)
        self.timer.start(0)

        # --- 新增防手震 (Debounce) 設定 ---
        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True) # 只執行一次
        self.debounce_timer.timeout.connect(self.send_delayed_release) # 時間到才真的放開
        
        # 設定防手震時間 (毫秒)
        # 建議值：50ms ~ 100ms
        # 如果還是會斷，請把這個數字調大；如果覺得點擊反應變慢，請調小
        self.DEBOUNCE_DELAY = 50 
        
        # 暫存放開時的座標
        self.pending_release_x = 0
        self.pending_release_y = 0
    def check_frame(self):
        try:
            has_new, w, h, s, fid = self.backend.check_new_frame(self.last_fid)
            if has_new:
                self.last_fid = fid
                mv = self.backend.get_memory_view(w, h)
                self.current_mv = mv 
                self.current_image = QImage(mv, w, h, s, QImage.Format.Format_RGB32)
                self.update()
        except Exception: pass
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self.current_image and not self.current_image.isNull():
            painter.drawImage(0, 0, self.current_image)
    def mouseMoveEvent(self, event):
        p = event.position(); self.backend.send_mouse(0, int(p.x()), int(p.y()))
    def mousePressEvent(self, event):
        p = event.position(); f = {Qt.MouseButton.LeftButton:1, Qt.MouseButton.RightButton:3}.get(event.button(), 0)
        if f: self.backend.send_mouse(f, int(p.x()), int(p.y()))
    def mouseReleaseEvent(self, event):
        p = event.position(); f = {Qt.MouseButton.LeftButton:2, Qt.MouseButton.RightButton:4}.get(event.button(), 0)
        if f: self.backend.send_mouse(f, int(p.x()), int(p.y()))
    def send_delayed_release(self):
        # --- 這是真的要放開了 ---
        # 只有當計時器跑完都沒有被"再次按下"打斷時，才會執行這裡
        self.backend.send_mouse(4, self.pending_release_x, self.pending_release_y) # 4 = Right Up
    def mouseDoubleClickEvent(self, event):
        p = event.position()
        if event.button() == Qt.MouseButton.LeftButton: self.backend.send_mouse(2, int(p.x()), int(p.y())); self.backend.send_mouse(1, int(p.x()), int(p.y()))
    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        if event.key() == Qt.Key.Key_End and (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self.backend.send_scancode(0x1D, True, False); self.backend.send_scancode(0x38, True, False); self.backend.send_scancode(0x53, True, True); QThread.msleep(50); self.backend.send_scancode(0x53, False, True); self.backend.send_scancode(0x38, False, False); self.backend.send_scancode(0x1D, False, False); return
        scancode, is_extended = self._map_key(event); 
        if scancode > 0: self.backend.send_scancode(scancode, True, is_extended)
    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        scancode, is_extended = self._map_key(event)
        if scancode > 0: self.backend.send_scancode(scancode, False, is_extended)
    def _map_key(self, event):
        vk = event.nativeVirtualKey()
        if vk > 0:
            scancode = windll.user32.MapVirtualKeyW(vk, 0)
            is_extended = event.key() in [Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Insert, Qt.Key.Key_Delete, Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown, Qt.Key.Key_Meta, Qt.Key.Key_AltGr]
            return scancode, is_extended
        return 0, False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PyQt6 RDP Ultimate ({RDP_WIDTH}x{RDP_HEIGHT} @ {RDP_COLOR}bit)")
        self.resize(RDP_WIDTH, RDP_HEIGHT)
        
        try:
            # 4. 傳入 RDP_COLOR
            self.backend = RdpBackend(RDP_IP, RDP_PORT, RDP_USER, RDP_PASS, RDP_WIDTH, RDP_HEIGHT, RDP_COLOR)
        except Exception as e:
            QMessageBox.critical(self, "連線錯誤", str(e))
            sys.exit(1)

        self.rdp_widget = RdpGLWidget(self.backend)
        self.setCentralWidget(self.rdp_widget)

        self.heartbeat = HeartbeatThread(self.backend)
        self.heartbeat.connection_lost.connect(self.on_disconnect)
        self.heartbeat.start()

    def on_disconnect(self):
        self.heartbeat.stop()
        QMessageBox.warning(self, "斷線", "遠端連線已中斷。")
        self.close()

    def closeEvent(self, event):
        if hasattr(self, 'heartbeat'): self.heartbeat.stop()
        if hasattr(self, 'backend'): self.backend.close()
        event.accept()

if __name__ == "__main__":
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())