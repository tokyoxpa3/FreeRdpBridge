import sys
import ctypes
import time
import mmap
import struct
from ctypes import windll

# 導入 Windows API
KERNEL32 = ctypes.windll.kernel32
WAIT_OBJECT_0 = 0x00000000
INFINITE = 0xFFFFFFFF

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QThread, Signal, QTimer

# --- [關鍵] 導入 OpenGL 常數 ---
from OpenGL.GL import (
    glGenTextures, glBindTexture, glTexImage2D, glTexSubImage2D,
    glTexParameteri, glClear, glClearColor,
    glBegin, glEnd, glTexCoord2f, glVertex2f, glEnable, glDisable,
    GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, 
    GL_LINEAR, GL_RGBA, GL_BGRA, GL_UNSIGNED_BYTE, GL_COLOR_BUFFER_BIT, GL_QUADS
)

# --- 使用者設定 ---
# 為了測試多視窗，您可以在此腳本啟動時從命令列參數讀取不同設定，
# 或是直接在程式碼中修改。
RDP_IP = "127.0.0.2"
RDP_PORT = 3389
RDP_USER = "Admin"
RDP_PASS = ""

# --- 效能關鍵設定 ---
RDP_WIDTH = 800
RDP_HEIGHT = 600
RDP_COLOR = 16 

# --- DLL 設定 ---
dll_path = "./libs/rdp/RdpBridge.dll"
try:
    rdp = ctypes.CDLL(dll_path)
except OSError:
    print(f"錯誤: 找不到 {dll_path}")
    sys.exit(1)

# 定義 C 函數簽章
rdp.rdpb_connect.argtypes = [
    ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, 
    ctypes.c_int, ctypes.c_int, ctypes.c_int
]
rdp.rdpb_connect.restype = ctypes.c_void_p

rdp.rdpb_step.argtypes = [ctypes.c_void_p]
rdp.rdpb_step.restype = ctypes.c_int

rdp.rdpb_send_scancode.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
rdp.rdpb_send_mouse.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]

rdp.rdpb_free.argtypes = [ctypes.c_void_p]

# [新增] 定義獲取 SHM 名稱的函數
rdp.rdpb_get_shm_name.argtypes = [ctypes.c_void_p]
rdp.rdpb_get_shm_name.restype = ctypes.c_char_p

# [新增] 定義同步鍵盤鎖定狀態的函數
rdp.rdpb_sync_locks.argtypes = [ctypes.c_void_p, ctypes.c_int]

# [新增] 定義獲取事件名稱的函數
rdp.rdpb_get_event_name.argtypes = [ctypes.c_void_p]
rdp.rdpb_get_event_name.restype = ctypes.c_char_p

# 標頭大小固定為 4 個 uint32
HEADER_SIZE = 16

class FrameWatcherThread(QThread):
    new_frame_signal = Signal()

    def __init__(self, event_name):
        super().__init__()
        # 打開由 C 端建立的命名事件
        self.h_event = KERNEL32.OpenEventW(0x00100000 | 0x0002, False, event_name)
        self.running = True

    def run(self):
        if not self.h_event:
            print("[Watcher] 錯誤: 無法開啟事件句柄")
            return
            
        while self.running:
            # 這裡會讓執行緒進入「極低功耗睡眠」，直到 C 端呼叫 SetEvent
            result = KERNEL32.WaitForSingleObject(self.h_event, 500) # 每 500ms 醒來檢查一次 running 狀態
            if result == WAIT_OBJECT_0:
                self.new_frame_signal.emit()

    def stop(self):
        self.running = False
        self.wait()

class RdpBackend:
    def __init__(self, ip, port, user, password, width, height, color_depth):
        print(f"[RDP] 正在連線到 {ip}:{port} ...")
        print(f"      解析度: {width}x{height}, 色彩: {color_depth}-bit")
        
        # 建立連線實例
        self.instance = rdp.rdpb_connect(
            ip.encode(), port, user.encode(), password.encode(),
            width, height, color_depth
        )
        
        if not self.instance:
            raise Exception("RDP 連線失敗！")
        
        # [關鍵修改] 獲取該實例唯一的共享記憶體名稱
        # C 返回的是 const char* (bytes)，需要 decode 成 string 給 mmap 用
        shm_name_bytes = rdp.rdpb_get_shm_name(self.instance)
        self.shm_name = shm_name_bytes.decode('utf-8')
        
        # [新增] 獲取事件名稱
        self.event_name = rdp.rdpb_get_event_name(self.instance).decode('utf-8')
        
        print(f"[RDP] 連線成功！共享記憶體名稱: {self.shm_name}, 事件名稱: {self.event_name}")
        
        self.last_sent_x = -1
        self.last_sent_y = -1
        
        # [修正] 必須匹配 C 端的最大分配空間，避免 OpenGL 讀取越界
        # 16 (Header) + 1920 * 1080 * 4 (Max Pixel Data)
        self.MAX_SHM_SIZE = 16 + (1920 * 1080 * 4)
        
        # 直接開到最大，這只是虛擬地址空間，不會真的吃掉 8MB 物理內存，直到用到它
        self.shm = mmap.mmap(-1, self.MAX_SHM_SIZE, tagname=self.shm_name)
        self.shm_size = self.MAX_SHM_SIZE
        
        # [新增] 預先轉換好 ctypes 指標，避免每幀重複建立
        self._ptr_type = ctypes.POINTER(ctypes.c_char)
        self.base_ptr = ctypes.cast(ctypes.addressof(ctypes.c_char.from_buffer(self.shm)), ctypes.c_void_p).value

    def step(self):
        if not self.instance: return 0
        return rdp.rdpb_step(self.instance)

    def check_new_frame(self, last_fid):
        if not self.shm: return False, 0, 0, 0, last_fid
        
        self.shm.seek(0)
        # 讀取標頭 (width, height, stride, frameId)
        try:
            buf = self.shm.read(HEADER_SIZE)
            if len(buf) < HEADER_SIZE: return False, 0, 0, 0, last_fid
            
            w, h, s, fid = struct.unpack('IIII', buf)
            
            # 如果有寬度且 FrameID 變更，代表有新畫面
            if w > 0 and fid != last_fid:
                return True, w, h, s, fid
        except Exception:
            pass
            
        return False, 0, 0, 0, last_fid

    def get_shm_address(self):
        return self.base_ptr

    def get_memory_view(self, width, height):
        # 計算需要的總大小
        required_size = HEADER_SIZE + (width * height * 4)
        
        # 如果現有對應空間不足，重新對應
        if self.shm_size < required_size:
            print(f"[RDP] 擴大共享記憶體對應: {self.shm_size} -> {required_size}")
            self.shm.close()
            # [關鍵修改] 這裡也要使用 self.shm_name
            self.shm = mmap.mmap(-1, required_size, tagname=self.shm_name)
            self.shm_size = required_size
            
        self.shm.seek(HEADER_SIZE)
        # 取得 memoryview 以避免複製資料
        mv = memoryview(self.shm)
        # 切片回傳像素資料部分
        return mv[HEADER_SIZE : HEADER_SIZE + (width * height * 4)]

    def send_mouse(self, flags, x, y):
        if not self.instance: return
        self.last_sent_x = x
        self.last_sent_y = y
        rdp.rdpb_send_mouse(self.instance, flags, x, y)

    def send_scancode(self, scancode, is_down, is_extended):
        if not self.instance: return
        # 組合 flag: bit 0 = down/up, bit 1 = extended
        flag_val = (1 if is_down else 0) | (2 if is_extended else 0)
        rdp.rdpb_send_scancode(self.instance, scancode, flag_val)

    def sync_locks(self, num_lock, caps_lock, scroll_lock):
        """
        同步鍵盤鎖定狀態
        RDP 協定旗標: Scroll=1, Num=2, Caps=4
        """
        if not self.instance: return
        
        flags = 0
        if scroll_lock: flags |= 1
        if num_lock:    flags |= 2
        if caps_lock:   flags |= 4
        
        rdp.rdpb_sync_locks(self.instance, flags)

    def close(self):
        if self.instance:
            rdp.rdpb_free(self.instance)
            self.instance = None
        if self.shm:
            self.shm.close()
            self.shm = None

class HeartbeatThread(QThread):
    connection_lost = Signal()
    
    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.running = True

    def run(self):
        while self.running:
            # 呼叫 C 的 step 函數，如果不返回 1 則代表斷線
            if self.backend.step() == 0:
                self.connection_lost.emit()
                break
            # 這裡不需要 sleep，因為 C 內部的 step 包含了等待事件
            
    def stop(self):
        self.running = False
        self.wait()

class RdpGLWidget(QOpenGLWidget):
    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.last_fid = 0
        self.texture_id = None
        self.tex_width = 0
        self.tex_height = 0
        
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # 1. 移除原本的 self.timer.timeout.connect(self.check_frame)
        # self.timer.start(1) <- 刪掉或改為處理其他低頻任務
        # self.timer = QTimer(self)  # 移除原本的 timer
        # self.timer.timeout.connect(self.check_frame)
        # self.timer.start(1) # 改為 1ms 避免過度占用
        
        # 2. 啟動事件監聽執行緒
        self.watcher = FrameWatcherThread(self.backend.event_name)
        self.watcher.new_frame_signal.connect(self.check_frame) # 當事件觸發時才執行 check_frame
        self.watcher.start()
        
        # 滑鼠 Debounce 邏輯 (保留)
        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self.send_delayed_release)
        self.DEBOUNCE_DELAY = 50
        self.pending_release_button = 0
        self.pending_release_x = 0
        self.pending_release_y = 0

    def initializeGL(self):
        # 建立 Texture
        self.texture_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.texture_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glBindTexture(GL_TEXTURE_2D, 0)

    def paintGL(self):
        """完全使用 OpenGL 渲染，不使用 QPainter 避免衝突"""
        glClearColor(0, 0, 0, 1)
        glClear(GL_COLOR_BUFFER_BIT)

        if not self.texture_id or self.tex_width == 0:
            return

        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.texture_id)
        
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(-1, 1)   # 左上
        glTexCoord2f(1, 0); glVertex2f(1, 1)    # 右上
        glTexCoord2f(1, 1); glVertex2f(1, -1)   # 右下
        glTexCoord2f(0, 1); glVertex2f(-1, -1)  # 左下
        glEnd()
        
        glBindTexture(GL_TEXTURE_2D, 0)
        glDisable(GL_TEXTURE_2D)

    def check_frame(self):
        if not self.backend.shm: return
        
        try:
            has_new, w, h, s, fid = self.backend.check_new_frame(self.last_fid)
            if has_new:
                self.last_fid = fid
                
                # 獲取原始地址 (整數)
                base_addr = self.backend.get_shm_address()
                # 加上 Header 偏移
                pixel_data_ptr = base_addr + 16
                
                self.makeCurrent()
                glBindTexture(GL_TEXTURE_2D, self.texture_id)
                
                # 將整數地址包裝成 c_void_p 傳給 OpenGL
                data_ptr = ctypes.c_void_p(pixel_data_ptr)
                
                if w != self.tex_width or h != self.tex_height:
                    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_BGRA, GL_UNSIGNED_BYTE, data_ptr)
                    self.tex_width = w
                    self.tex_height = h
                else:
                    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_BGRA, GL_UNSIGNED_BYTE, data_ptr)
                
                glBindTexture(GL_TEXTURE_2D, 0)
                self.update()
        except Exception as e:
            print(f"Update Error: {e}")

    # 保留滑鼠/鍵盤事件代碼 (從之前的程式碼複製過來)
    def mouseMoveEvent(self, event):
        p = event.position()
        self.backend.send_mouse(0, int(p.x()), int(p.y()))

    def mousePressEvent(self, event):
        p = event.position()
        # 1=Left, 3=Right
        f = {
            Qt.MouseButton.LeftButton: 1,
            Qt.MouseButton.RightButton: 3,
            Qt.MouseButton.MiddleButton: 7  # 新增這一行
        }.get(event.button(), 0)
        if f:
            # 如果有待處理的釋放事件，先取消它 (視為連續操作)
            if self.debounce_timer.isActive():
                self.debounce_timer.stop()
            self.backend.send_mouse(f, int(p.x()), int(p.y()))

    def mouseReleaseEvent(self, event):
        p = event.position()
        # 2=Left Up, 4=Right Up
        f = {
            Qt.MouseButton.LeftButton: 2,
            Qt.MouseButton.RightButton: 4,
            Qt.MouseButton.MiddleButton: 8  # 新增這一行
        }.get(event.button(), 0)
        if f:
            # 不立即發送，而是啟動 Timer
            self.pending_release_x = int(p.x())
            self.pending_release_y = int(p.y())
            self.pending_release_button = f
            self.debounce_timer.start(self.DEBOUNCE_DELAY)

    def send_delayed_release(self):
        # Timer 時間到，發送釋放信號
        if self.pending_release_button:
            self.backend.send_mouse(self.pending_release_button, self.pending_release_x, self.pending_release_y)
            self.pending_release_button = 0

    def mouseDoubleClickEvent(self, event):
        # 雙擊時強制發送釋放與再按下，確保邏輯清晰
        if self.debounce_timer.isActive():
            self.debounce_timer.stop()
            self.send_delayed_release()
            
        p = event.position()
        if event.button() == Qt.MouseButton.LeftButton:
            self.backend.send_mouse(2, int(p.x()), int(p.y())) # Up
            self.backend.send_mouse(1, int(p.x()), int(p.y())) # Down
    
    def wheelEvent(self, event):
        # 獲取滾動角度 (Y軸)
        angle = event.angleDelta().y()
        
        # 取得當前滑鼠位置 (雖然滾輪事件本身不需要座標，但 RDP 協議通常會帶上)
        p = event.position()
        x, y = int(p.x()), int(p.y())

        if angle > 0:
            # 向上滾動 -> 傳送 flag 5
            self.backend.send_mouse(5, x, y)
        elif angle < 0:
            # 向下滾動 -> 傳送 flag 6
            self.backend.send_mouse(6, x, y)

    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        # 如果按下的是 NumLock 鍵 (Qt.Key.Key_NumLock)，除了發送 Scancode，也要更新狀態
        if event.key() == Qt.Key.Key_NumLock:
            # 讓 OS 處理一下狀態切換，稍後發送 Sync
            QTimer.singleShot(100, self.update_lock_state)
            
        # Ctrl+Alt+End 發送 CAD
        if event.key() == Qt.Key.Key_End and (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self.send_ctrl_alt_del()
            return
            
        scancode, is_extended = self._map_key(event)
        if scancode > 0:
            self.backend.send_scancode(scancode, True, is_extended)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        scancode, is_extended = self._map_key(event)
        if scancode > 0:
            self.backend.send_scancode(scancode, False, is_extended)

    def focusInEvent(self, event):
        self.update_lock_state()
        super().focusInEvent(event)

    def update_lock_state(self):
        """讀取本地 Windows 鍵盤狀態並同步到遠端"""
        # VK_NUMLOCK = 0x90, VK_CAPITAL = 0x14, VK_SCROLL = 0x91
        # GetKeyState return low-order bit is 1 if toggled
        num_lock = (windll.user32.GetKeyState(0x90) & 0x0001) != 0
        caps_lock = (windll.user32.GetKeyState(0x14) & 0x0001) != 0
        scroll_lock = (windll.user32.GetKeyState(0x91) & 0x0001) != 0
        
        # print(f"Syncing Locks: Num={num_lock}, Caps={caps_lock}")
        self.backend.sync_locks(num_lock, caps_lock, scroll_lock)

    def send_ctrl_alt_del(self):
        # 手動發送序列
        cmds = [
            (0x1D, True, False), (0x38, True, False), (0x53, True, True), # Press
            (0x53, False, True), (0x38, False, False), (0x1D, False, False) # Release
        ]
        for code, down, ext in cmds:
            self.backend.send_scancode(code, down, ext)
            QThread.msleep(10)

    def _map_key(self, event):
        vk = event.nativeVirtualKey()
        if vk > 0:
            scancode = windll.user32.MapVirtualKeyW(vk, 0)
            is_extended = event.key() in [
                Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
                Qt.Key.Key_Insert, Qt.Key.Key_Delete, Qt.Key.Key_Home, Qt.Key.Key_End,
                Qt.Key.Key_PageUp, Qt.Key.Key_PageDown, Qt.Key.Key_Meta, Qt.Key.Key_AltGr
            ]
            return scancode, is_extended
        return 0, False

    # 記得在關閉時停止執行緒
    def closeEvent(self, event):
        self.watcher.stop()
        super().closeEvent(event)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"RDP Client - {RDP_IP} ({RDP_WIDTH}x{RDP_HEIGHT})")
        
        # 調整視窗大小 (包含邊框)
        self.resize(RDP_WIDTH, RDP_HEIGHT)
        
        try:
            self.backend = RdpBackend(RDP_IP, RDP_PORT, RDP_USER, RDP_PASS, RDP_WIDTH, RDP_HEIGHT, RDP_COLOR)
        except Exception as e:
            QMessageBox.critical(self, "連線錯誤", str(e))
            # 這裡如果不 exit，可以允許主程式繼續跑其他視窗
            # 但如果是單一視窗模式則需要退出
            # sys.exit(1) 
            self.backend = None

        if self.backend:
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
        if hasattr(self, 'heartbeat') and self.heartbeat:
            self.heartbeat.stop()
        if hasattr(self, 'backend') and self.backend:
            self.backend.close()
        event.accept()

if __name__ == "__main__":
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    app = QApplication(sys.argv)
    
    # 支援多視窗的示範：
    # 如果您想要一次開兩個連線，可以實例化兩個 MainWindow
    # win1 = MainWindow()
    # win1.show()
    
    # 目前預設單一視窗行為
    window = MainWindow()
    if window.backend:
        window.show()
        
        # 程式啟動後，延遲一點時間進行第一次同步 (確保 RDP 連線已完全建立)
        QTimer.singleShot(1000, window.rdp_widget.update_lock_state)
        
        sys.exit(app.exec())
    else:
        sys.exit(1)