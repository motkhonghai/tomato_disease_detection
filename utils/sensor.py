import time
import board
import adafruit_dht
from threading import Lock

class DHT11Sensor:
    def __init__(self, pin=17):
        """
        Khởi tạo cảm biến DHT11 cho Raspberry Pi OS 64-bit
        pin: GPIO pin number (GPIO17)
        """
        self.pin = pin
        self.dht_device = None
        self.lock = Lock()
        self.last_temp = None
        self.last_humidity = None
        self.init_sensor()
        
    def init_sensor(self):
        """Khởi tạo cảm biến"""
        try:
            # Sử dụng GPIO number thay vì board pin
            # Trên Raspberry Pi OS 64-bit, sử dụng cách này
            if self.pin == 17:
                self.dht_device = adafruit_dht.DHT11(board.D17)
            elif self.pin == 4:
                self.dht_device = adafruit_dht.DHT11(board.D4)
            else:
                # Fallback: thử với số GPIO trực tiếp
                try:
                    self.dht_device = adafruit_dht.DHT11(self.pin)
                except:
                    # Thử với board pin
                    pin_map = {
                        17: board.D17,
                        4: board.D4,
                        18: board.D18,
                        27: board.D27,
                        22: board.D22,
                        23: board.D23,
                        24: board.D24,
                        25: board.D25
                    }
                    if self.pin in pin_map:
                        self.dht_device = adafruit_dht.DHT11(pin_map[self.pin])
                    else:
                        self.dht_device = adafruit_dht.DHT11(board.D17)  # Mặc định
                        
            print(f"DHT11 initialized on GPIO{self.pin}")
            # Thử đọc lần đầu
            time.sleep(2)
            self.read()
            
        except Exception as e:
            print(f"Lỗi khởi tạo DHT11: {e}")
            print("Trying alternative method with use_pulseio=False...")
            try:
                # Phương pháp thay thế
                self.dht_device = adafruit_dht.DHT11(board.D17, use_pulseio=False)
                print("DHT11 initialized with use_pulseio=False")
            except Exception as e2:
                print(f"Vẫn lỗi khởi tạo DHT11: {e2}")
                self.dht_device = None
    
    def read(self):
        """Đọc nhiệt độ và độ ẩm - xử lý lỗi RuntimeError"""
        if self.dht_device is None:
            return self.last_temp, self.last_humidity
            
        with self.lock:
            for attempt in range(3):  # Thử 3 lần
                try:
                    # Thử đọc dữ liệu
                    temperature = self.dht_device.temperature
                    humidity = self.dht_device.humidity
                    
                    # Kiểm tra dữ liệu hợp lệ
                    if (temperature is not None and 0 <= temperature <= 50 and
                        humidity is not None and 20 <= humidity <= 90):
                        
                        self.last_temp = temperature
                        self.last_humidity = humidity
                        print(f"DHT11: {temperature}°C, {humidity}%")
                        return temperature, humidity
                        
                except RuntimeError as e:
                    # Lỗi phổ biến với DHT11, bỏ qua và thử lại
                    if attempt < 2:  # Không in lỗi ở lần thử cuối
                        print(f"DHT11 attempt {attempt+1} failed: {e}")
                    time.sleep(1)
                    continue
                except Exception as e:
                    print(f"Lỗi khác khi đọc DHT11: {e}")
                    time.sleep(1)
                    continue
            
            # Nếu sau 3 lần vẫn lỗi, trả về giá trị cuối cùng
            print("DHT11: Using last known values after 3 failed attempts")
            return self.last_temp, self.last_humidity
    
    def cleanup(self):
        """Dọn dẹp tài nguyên"""
        if self.dht_device:
            try:
                self.dht_device.exit()
            except:
                pass