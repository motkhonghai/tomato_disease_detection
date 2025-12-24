import cv2
import threading
import time
import numpy as np

class Camera:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.retry_count = 0
        self.max_retries = 5
        self.init_camera()
        
    def init_camera(self):
        """Khởi tạo camera"""
        for i in range(self.max_retries):
            try:
                print(f"Attempting to initialize camera index {self.camera_index}...")
                self.cap = cv2.VideoCapture(self.camera_index)
                
                # Đặt thông số camera
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                
                # Kiểm tra camera có mở được không
                if self.cap.isOpened():
                    # Đọc thử một frame
                    ret, test_frame = self.cap.read()
                    if ret and test_frame is not None:
                        self.running = True
                        print(f"Camera {self.camera_index} initialized successfully")
                        threading.Thread(target=self.update_frame, daemon=True).start()
                        return
                    else:
                        print(f"Camera {self.camera_index} opened but failed to read frame")
                        self.cap.release()
                else:
                    print(f"Failed to open camera index {self.camera_index}")
                
            except Exception as e:
                print(f"Error initializing camera {self.camera_index}: {e}")
            
            # Thử camera index tiếp theo
            self.camera_index = 1 if self.camera_index == 0 else 0
            time.sleep(1)
        
        print("Could not initialize any camera. Using placeholder.")
        self.running = True
        threading.Thread(target=self.update_placeholder, daemon=True).start()
            
    def update_frame(self):
        """Cập nhật frame liên tục từ camera thật"""
        while self.running:
            try:
                if self.cap and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    if ret:
                        with self.lock:
                            self.frame = frame.copy()
                    else:
                        print("Failed to read frame from camera")
                        time.sleep(0.1)
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"Error updating frame: {e}")
                time.sleep(0.1)
    
    def update_placeholder(self):
        """Tạo frame placeholder khi không có camera"""
        while self.running:
            # Tạo frame đen với thông báo
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "Camera Not Available", (120, 220),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.putText(frame, "Please check camera connection", (80, 260),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            # Thêm animation đơn giản
            current_time = time.time()
            circle_size = int(20 + 10 * np.sin(current_time * 2))
            cv2.circle(frame, (320, 350), circle_size, (0, 0, 255), 2)
            
            with self.lock:
                self.frame = frame
            time.sleep(0.1)
    
    def get_frame(self):
        """Lấy frame hiện tại"""
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()
        return None
    
    def release(self):
        """Giải phóng camera"""
        self.running = False
        if self.cap:
            self.cap.release()
            print("Camera released")
            
    def __del__(self):
        self.release()