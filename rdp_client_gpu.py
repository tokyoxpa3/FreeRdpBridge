import sys
import ctypes
import time
import mmap
import struct
from ctypes import windll, wintypes

# 導入對話視窗類別
from rdp_dialog import RDPLoginDialog

# --- Windows API 定義 (保持不變) ---
user32 = ctypes.windll.user32
KERNEL32 = ctypes.windll.kernel32
KERNEL32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
KERNEL32.GetModuleHandleW.restype = wintypes.HINSTANCE
KERNEL32.GetLastError.restype = wintypes.DWORD
WAIT_OBJECT_0 = 0x00000000
INFINITE = 0xFFFFFFFF
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_LWIN = 0x5B
VK_RWIN = 0x5C

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))
    ]

LowLevelKeyboardProc = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_longlong

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox,
    QSystemTrayIcon, QMenu
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QThread, Signal, QTimer

from OpenGL.GL import (
    glGenTextures, glBindTexture, glTexImage2D, glTexSubImage2D,
    glTexParameteri, glClear, glClearColor,
    glBegin, glEnd, glTexCoord2f, glVertex2f, glEnable, glDisable,
    GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, 
    GL_LINEAR, GL_RGBA, GL_BGRA, GL_UNSIGNED_BYTE, GL_COLOR_BUFFER_BIT, GL_QUADS
)

# --- 默認設定 ---
DEFAULT_CONFIG = {
    'server': "192.168.1.201",
    'port': 3389,
    'username': "Admin1",
    'password': "password",
    'width': 800,
    'height': 600,
    'color_depth': 16
}

# --- DLL 設定 ---
dll_path = "./libs/rdp/RdpBridge.dll"
try:
    rdp = ctypes.CDLL(dll_path)
except OSError:
    print(f"錯誤: 找不到 {dll_path}")
    sys.exit(1)

# 定義 C 函數簽章
rdp.rdpb_connect.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
rdp.rdpb_connect.restype = ctypes.c_void_p
rdp.rdpb_step.argtypes = [ctypes.c_void_p]
rdp.rdpb_step.restype = ctypes.c_int
rdp.rdpb_send_scancode.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
rdp.rdpb_send_mouse.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
rdp.rdpb_free.argtypes = [ctypes.c_void_p]
rdp.rdpb_get_shm_name.argtypes = [ctypes.c_void_p]
rdp.rdpb_get_shm_name.restype = ctypes.c_char_p
rdp.rdpb_sync_locks.argtypes = [ctypes.c_void_p, ctypes.c_int]
rdp.rdpb_get_event_name.argtypes = [ctypes.c_void_p]
rdp.rdpb_get_event_name.restype = ctypes.c_char_p

HEADER_SIZE = 16

# --- 用於管理多視窗的全局列表 ---
active_windows = []

class FrameWatcherThread(QThread):
    new_frame_signal = Signal()
    def __init__(self, event_name):
        super().__init__()
        self.h_event = KERNEL32.OpenEventW(0x00100000 | 0x0002, False, event_name)
        self.running = True
    def run(self):
        if not self.h_event: return
        while self.running:
            result = KERNEL32.WaitForSingleObject(self.h_event, 500)
            if result == WAIT_OBJECT_0:
                self.new_frame_signal.emit()
    def stop(self):
        self.running = False
        self.wait()

class GlobalKeyboardHook:
    def __init__(self, rdp_widget):
        self.rdp_widget = rdp_widget
        self.hook = None
        self._callback = LowLevelKeyboardProc(self.hook_callback)
    def install(self):
        h_instance = KERNEL32.GetModuleHandleW(None)
        if not h_instance: h_instance = 0
        self.hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._callback, h_instance, 0)
    def uninstall(self):
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
    def hook_callback(self, nCode, wParam, lParam):
        if nCode == 0:
            try:
                kb = KBDLLHOOKSTRUCT.from_address(lParam)
                vk_code = kb.vkCode
                if vk_code in [VK_LWIN, VK_RWIN]:
                    active_hwnd = user32.GetForegroundWindow()
                    target_hwnd = int(self.rdp_widget.window().winId())
                    if active_hwnd == target_hwnd:
                        is_down = wParam in [WM_KEYDOWN, WM_SYSKEYDOWN]
                        scancode = 0x5B if vk_code == VK_LWIN else 0x5C
                        self.rdp_widget.backend.send_scancode(scancode, is_down, True)
                        return 1
            except: pass
        return user32.CallNextHookEx(self.hook, nCode, wParam, lParam)

class RdpBackend:
    def __init__(self, ip, port, user, password, width, height, color_depth):
        self.instance = rdp.rdpb_connect(ip.encode(), port, user.encode(), password.encode(), width, height, color_depth)
        if not self.instance: raise Exception("RDP 連線失敗！")
        self.shm_name = rdp.rdpb_get_shm_name(self.instance).decode('utf-8')
        self.event_name = rdp.rdpb_get_event_name(self.instance).decode('utf-8')
        self.MAX_SHM_SIZE = 16 + (1920 * 1080 * 4)
        self.shm = mmap.mmap(-1, self.MAX_SHM_SIZE, tagname=self.shm_name)
        self.shm_size = self.MAX_SHM_SIZE
        self.base_ptr = ctypes.cast(ctypes.addressof(ctypes.c_char.from_buffer(self.shm)), ctypes.c_void_p).value
    def step(self): return rdp.rdpb_step(self.instance) if self.instance else 0
    def check_new_frame(self, last_fid):
        if not self.shm: return False, 0, 0, 0, last_fid
        self.shm.seek(0)
        buf = self.shm.read(HEADER_SIZE)
        if len(buf) < HEADER_SIZE: return False, 0, 0, 0, last_fid
        w, h, s, fid = struct.unpack('IIII', buf)
        return (w > 0 and fid != last_fid), w, h, s, fid
    def get_shm_address(self): return self.base_ptr
    def send_mouse(self, flags, x, y): 
        if self.instance: rdp.rdpb_send_mouse(self.instance, flags, x, y)
    def send_scancode(self, scancode, is_down, is_extended):
        if not self.instance: return
        flag_val = (1 if is_down else 0) | (2 if is_extended else 0)
        rdp.rdpb_send_scancode(self.instance, scancode, flag_val)
    def sync_locks(self, num_lock, caps_lock, scroll_lock):
        if not self.instance: return
        flags = 0
        if scroll_lock: flags |= 1
        if num_lock:    flags |= 2
        if caps_lock:   flags |= 4
        rdp.rdpb_sync_locks(self.instance, flags)
    def close(self):
        if self.instance: rdp.rdpb_free(self.instance); self.instance = None
        if self.shm: self.shm.close(); self.shm = None

class HeartbeatThread(QThread):
    connection_lost = Signal()
    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.running = True
    def run(self):
        while self.running:
            if self.backend.step() == 0:
                self.connection_lost.emit()
                break
    def stop(self): self.running = False; self.wait()

class RdpGLWidget(QOpenGLWidget):
    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.last_fid = 0
        self.texture_id = None
        self.tex_width = 0
        self.tex_height = 0
        self.is_ui_visible = True
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.watcher = FrameWatcherThread(self.backend.event_name)
        self.watcher.new_frame_signal.connect(self.check_frame)
        self.watcher.start()
        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self.send_delayed_release)
        self.pending_release_button = 0

    def initializeGL(self):
        self.texture_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.texture_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glBindTexture(GL_TEXTURE_2D, 0)

    def paintGL(self):
        glClearColor(0, 0, 0, 1)
        glClear(GL_COLOR_BUFFER_BIT)
        if not self.texture_id or self.tex_width == 0: return
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.texture_id)
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(-1, 1)
        glTexCoord2f(1, 0); glVertex2f(1, 1)
        glTexCoord2f(1, 1); glVertex2f(1, -1)
        glTexCoord2f(0, 1); glVertex2f(-1, -1)
        glEnd()
        glBindTexture(GL_TEXTURE_2D, 0)
        glDisable(GL_TEXTURE_2D)

    def check_frame(self):
        if not self.backend.shm: return
        has_new, w, h, s, fid = self.backend.check_new_frame(self.last_fid)
        if has_new:
            self.last_fid = fid
            if not self.is_ui_visible: return
            base_addr = self.backend.get_shm_address()
            pixel_data_ptr = base_addr + 16
            self.makeCurrent()
            glBindTexture(GL_TEXTURE_2D, self.texture_id)
            data_ptr = ctypes.c_void_p(pixel_data_ptr)
            if w != self.tex_width or h != self.tex_height:
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_BGRA, GL_UNSIGNED_BYTE, data_ptr)
                self.tex_width, self.tex_height = w, h
            else:
                glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_BGRA, GL_UNSIGNED_BYTE, data_ptr)
            glBindTexture(GL_TEXTURE_2D, 0)
            self.update()

    def mouseMoveEvent(self, event): self.backend.send_mouse(0, int(event.position().x()), int(event.position().y()))
    def mousePressEvent(self, event):
        f = {Qt.MouseButton.LeftButton: 1, Qt.MouseButton.RightButton: 3, Qt.MouseButton.MiddleButton: 7}.get(event.button(), 0)
        if f: self.backend.send_mouse(f, int(event.position().x()), int(event.position().y()))
    def mouseReleaseEvent(self, event):
        f = {Qt.MouseButton.LeftButton: 2, Qt.MouseButton.RightButton: 4, Qt.MouseButton.MiddleButton: 8}.get(event.button(), 0)
        if f:
            self.pending_release_x, self.pending_release_y = int(event.position().x()), int(event.position().y())
            self.pending_release_button = f
            self.debounce_timer.start(50)
    def send_delayed_release(self):
        if self.pending_release_button:
            self.backend.send_mouse(self.pending_release_button, self.pending_release_x, self.pending_release_y)
            self.pending_release_button = 0
    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        self.backend.send_mouse(5 if angle > 0 else 6, int(event.position().x()), int(event.position().y()))
    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        scancode, is_extended = self._map_key(event)
        if scancode > 0: self.backend.send_scancode(scancode, True, is_extended)
    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        scancode, is_extended = self._map_key(event)
        if scancode > 0: self.backend.send_scancode(scancode, False, is_extended)
    def update_lock_state(self):
        num = (windll.user32.GetKeyState(0x90) & 0x0001) != 0
        caps = (windll.user32.GetKeyState(0x14) & 0x0001) != 0
        scroll = (windll.user32.GetKeyState(0x91) & 0x0001) != 0
        self.backend.sync_locks(num, caps, scroll)
    def _map_key(self, event):
        vk = event.nativeVirtualKey()
        if vk > 0:
            sc = windll.user32.MapVirtualKeyW(vk, 0)
            ext = event.key() in [Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Insert, Qt.Key.Key_Delete, Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown]
            return sc, ext
        return 0, False
    def closeEvent(self, event): self.watcher.stop(); super().closeEvent(event)

class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle(f"RDP: {config['server']} ({config['width']}x{config['height']})")
        self.resize(config['width'], config['height'])
        self.is_rdp_visible = True

        try:
            self.backend = RdpBackend(
                config['server'], config['port'], config['username'], config['password'],
                config['width'], config['height'], config['color_depth']
            )
        except Exception as e:
            QMessageBox.critical(self, "連線錯誤", str(e))
            self.backend = None
            return

        self.rdp_widget = RdpGLWidget(self.backend)
        self.setCentralWidget(self.rdp_widget)
        self.kb_hook = GlobalKeyboardHook(self.rdp_widget)
        self.kb_hook.install()
        self.heartbeat = HeartbeatThread(self.backend)
        self.heartbeat.connection_lost.connect(self.on_disconnect)
        self.heartbeat.start()
        
        self.setup_tray()
        QTimer.singleShot(1000, self.rdp_widget.update_lock_state)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QApplication.style().StandardPixmap.SP_ComputerIcon))
        
        tray_menu = QMenu()
        
        # [新增] 新建連線選項
        new_conn_action = QAction("新建連線...", self)
        new_conn_action.triggered.connect(self.on_new_connection)
        
        show_action = QAction("顯示視窗", self)
        show_action.triggered.connect(self.show_rdp)
        hide_action = QAction("隱藏視窗", self)
        hide_action.triggered.connect(self.hide_rdp)
        
        quit_action = QAction("結束所有連線", self)
        quit_action.triggered.connect(QApplication.instance().quit)

        tray_menu.addAction(new_conn_action)
        tray_menu.addSeparator()
        tray_menu.addAction(show_action)
        tray_menu.addAction(hide_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_new_connection(self):
        """開啟對話框並建立新的 RDP 視窗"""
        dialog = RDPLoginDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if data:
                new_win = MainWindow(data)
                new_win.show()
                active_windows.append(new_win) # 保持引用防止被回收

    def on_tray_activated(self, reason):
        if reason in [QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick]:
            if self.isVisible(): self.hide_rdp()
            else: self.show_rdp()

    def hide_rdp(self):
        self.rdp_widget.is_ui_visible = False
        self.hide()
        self.is_rdp_visible = False

    def show_rdp(self):
        self.show(); self.activateWindow()
        self.rdp_widget.is_ui_visible = True
        self.is_rdp_visible = True

    def on_disconnect(self):
        self.heartbeat.stop()
        QMessageBox.warning(self, "斷線", f"與 {self.config['server']} 的連線已中斷。")
        self.close()

    def closeEvent(self, event):
        if hasattr(self, 'kb_hook'): self.kb_hook.uninstall()
        if hasattr(self, 'heartbeat'): self.heartbeat.stop()
        if hasattr(self, 'backend'): self.backend.close()
        if hasattr(self, 'tray_icon'): self.tray_icon.hide()
        # 從列表中移除自己
        if self in active_windows:
            active_windows.remove(self)
        event.accept()

if __name__ == "__main__":
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) # 即使視窗都關閉也保持托盤運行

    # 啟動時顯示對話框
    dialog = RDPLoginDialog()
    if dialog.exec():
        config = dialog.get_data()
        window = MainWindow(config)
        window.show()
        active_windows.append(window)
        sys.exit(app.exec())
    else:
        sys.exit(0)