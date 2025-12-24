"""
HỆ THỐNG NHẬN DIỆN BỆNH CÂY CÀ CHUA
Tất cả chức năng chụp ảnh đều trả về JSON với results chi tiết
"""

# ====================== PHẦN 1: IMPORT THƯ VIỆN ======================
import os
import cv2
import time
import json
import threading
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, render_template, Response, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from werkzeug.utils import secure_filename
import schedule
import atexit

# Import các module custom
from utils.camera import Camera
from utils.detector import DiseaseDetector
from utils.sensor import DHT11Sensor

# ====================== PHẦN 2: KHỞI TẠO FLASK APP ======================
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'tomato_disease_detection_secret_2025'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['CAPTURE_FOLDER'] = 'captures'
app.config['DAILY_CAPTURE_FOLDER'] = 'daily_captures'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Tạo các thư mục nếu chưa tồn tại
for folder in ['UPLOAD_FOLDER', 'CAPTURE_FOLDER', 'DAILY_CAPTURE_FOLDER']:
    os.makedirs(app.config[folder], exist_ok=True)

# Khởi tạo WebSocket
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ====================== PHẦN 3: KHỞI TẠO CÁC COMPONENT ======================
camera = Camera()
detector = DiseaseDetector('model.tflite', 'labels.txt')
sensor = DHT11Sensor(pin=17)

# ====================== PHẦN 4: BIẾN TOÀN CỤC ======================
camera_lock = threading.Lock()

# Trạng thái hệ thống
current_status = {
    "disease_detected": False,
    "disease_name": "Không phát hiện bệnh",
    "confidence": 0,
    "temperature": 0,
    "humidity": 0,
    "last_update": "",
    "system_status": "Đang khởi động...",
    "notification_threshold": 0.6,
    "daily_capture_enabled": True,
    "next_daily_capture": "",
    "last_daily_capture": "",
    "latest_analysis": {
        "type": "none",
        "disease_name": "Chưa có dữ liệu",
        "confidence": 0,
        "timestamp": "",
        "source": "none"
    }
}

# Biến cho daily capture
last_capture_date = None
daily_capture_thread = None
# Lưu kết quả chụp định kỳ gần nhất (để trả JSON khi client yêu cầu)
last_daily_response = None
daily_response_lock = threading.Lock()

# DANH SÁCH CÁC BỆNH CẦN CẢNH BÁO
DISEASE_ALERTS = [
    "bacterial_spot", "early_blight", "late_blight", 
    "leaf_mold", "septoria_leaf_spot", "spider_mites", 
    "target_spot", "yellow_leaf_curl_virus", "mosaic_virus"
]

# CÁC TRẠNG THÁI KHÔNG PHẢI BỆNH
HEALTHY_STATES = ["healthy", "no disease", "normal", "khỏe mạnh", "lành mạnh"]

# ====================== PHẦN 5: HÀM TẠO VIDEO STREAM ======================
def generate_frames():
    """Tạo video stream KHÔNG CÓ nhận diện real-time"""
    def _make_placeholder(msg="NO CAMERA"):
        f = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(f, msg, (30, 220), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        ret, buffer = cv2.imencode('.jpg', f)
        return buffer.tobytes() if ret else b''

    # Ensure the generator is resilient to runtime errors: always yield at least
    # one frame (placeholder) and catch exceptions during streaming so the WSGI
    # server doesn't observe a write before start_response.
    try:
        yielded_once = False
        while True:
            try:
                with camera_lock:
                    frame = camera.get_frame()
                    if frame is None:
                        frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(frame, "WEBCAM STREAM", (50, 200), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                        cv2.putText(frame, "Chỉ hiển thị video thô", (100, 250), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 1)
                        cv2.putText(frame, "Nhận diện: Chụp ảnh định kỳ & thủ công", (50, 300), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)

                    frame_resized = cv2.resize(frame, (640, 480))
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cv2.putText(frame_resized, f"Live: {timestamp}", (10, 30), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                    ret, buffer = cv2.imencode('.jpg', frame_resized)
                    if not ret:
                        frame_bytes = _make_placeholder("ENCODE ERROR")
                    else:
                        frame_bytes = buffer.tobytes()

                yielded_once = True
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

            except Exception as inner_e:
                print(f"[STREAM ERROR] Streaming frame failed: {inner_e}")
                # Yield a placeholder frame so the client gets a valid JPEG
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + _make_placeholder("STREAM ERROR") + b'\r\n')
                time.sleep(1)

    except GeneratorExit:
        # Client disconnected gracefully
        return
    except Exception as e:
        print(f"[STREAM GENERATOR ERROR] Unexpected error in generator: {e}")
        # Ensure we yield a final placeholder so WSGI has sent headers
        try:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + _make_placeholder("FATAL ERROR") + b'\r\n')
        except Exception:
            pass
        return

# ====================== PHẦN 6: HÀM PHÂN TÍCH ẢNH CHUNG ======================
def analyze_image(image, source="manual"):
    """
    Phân tích ảnh và trả về kết quả chi tiết dạng JSON
    """
    try:
        # Phân tích ảnh bằng model
        processed_frame, results = detector.detect(image)
        
        if results is None:
            return {
                'success': False,
                'class_name': 'Không phát hiện',
                'confidence': 0.0,
                'confidence_percent': '0%',
                'description': 'Không thể phân tích ảnh',
                'type': 'unknown',
                'severity': 'none',
                'color': 'gray'
            }
        
        # Phân loại kết quả
        disease_name = results['class_name'].lower()
        confidence = float(results['confidence'])
        
        # Kiểm tra xem có phải healthy không
        is_healthy = any(healthy in disease_name for healthy in HEALTHY_STATES)
        is_disease = any(disease in disease_name for disease in DISEASE_ALERTS)
        
        if is_healthy:
            results['type'] = 'healthy'
            results['description'] = '✅ Lá cây khỏe mạnh, không có dấu hiệu bệnh'
            results['recommendation'] = 'Tiếp tục chăm sóc bình thường'
            results['severity'] = 'none'
            results['color'] = 'success'
            results['icon'] = 'fa-check-circle'
            
        elif is_disease:
            results['type'] = 'disease'
            results['description'] = f'⚠️ PHÁT HIỆN BỆNH: {results["class_name"]}'
            
            # Xác định mức độ nghiêm trọng
            if confidence > 0.8:
                results['severity'] = 'high'
                results['recommendation'] = '🚨 CẦN XỬ LÝ NGAY: Cách ly cây và sử dụng thuốc đặc trị'
                results['color'] = 'danger'
                results['icon'] = 'fa-exclamation-triangle'
            elif confidence > 0.6:
                results['severity'] = 'medium'
                results['recommendation'] = '⚠️ CẦN THEO DÕI: Xử lý bằng thuốc thích hợp'
                results['color'] = 'warning'
                results['icon'] = 'fa-exclamation-circle'
            else:
                results['severity'] = 'low'
                results['recommendation'] = 'ℹ️ THEO DÕI: Kiểm tra lại sau 1-2 ngày'
                results['color'] = 'info'
                results['icon'] = 'fa-info-circle'
                
        else:
            results['type'] = 'unknown'
            results['description'] = 'ℹ️ Phát hiện bất thường trên lá cây'
            results['recommendation'] = 'Theo dõi thêm và tham khảo chuyên gia'
            results['severity'] = 'low'
            results['color'] = 'info'
            results['icon'] = 'fa-question-circle'
        
        # Thêm thông tin phân tích
        results['analysis_time'] = datetime.now().strftime("%H:%M:%S")
        results['image_size'] = f"{image.shape[1]}x{image.shape[0]}"
        results['source'] = source
        results['success'] = True
        
        return results
        
    except Exception as e:
        print(f"[ANALYSIS ERROR] Lỗi phân tích ảnh: {e}")
        return {
            'success': False,
            'class_name': 'Lỗi phân tích',
            'confidence': 0.0,
            'confidence_percent': '0%',
            'description': f'Lỗi khi phân tích ảnh: {str(e)}',
            'type': 'error',
            'severity': 'none',
            'color': 'error',
            'icon': 'fa-times-circle'
        }

# ====================== PHẦN 7: CHỤP ẢNH ĐỊNH KỲ ======================
def perform_daily_capture():
    """
    Chụp ảnh và phân tích định kỳ mỗi ngày
    Trả về kết quả chi tiết qua WebSocket
    """
    global last_capture_date, current_status
    
    today = datetime.now().date()
    
    # Kiểm tra xem hôm nay đã chụp chưa
    if last_capture_date == today:
        print(f"[DAILY CAPTURE] Đã chụp ảnh hôm nay ({today})")
        return
    
    try:
        print(f"[DAILY CAPTURE] Bắt đầu chụp ảnh định kỳ ngày {today}")
        
        with camera_lock:
            frame = camera.get_frame()
            if frame is None:
                error_result = {
                    'success': False,
                    'error': 'Không thể truy cập camera',
                    'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S"),
                    'message': 'Lỗi: Camera không khả dụng'
                }
                socketio.emit('daily_capture_result', error_result)
                return
            
            # Tạo tên file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"daily_{timestamp}.jpg"
            filepath = os.path.join(app.config['DAILY_CAPTURE_FOLDER'], filename)
            
            # Lưu ảnh
            cv2.imwrite(filepath, frame)
            print(f"[DAILY CAPTURE] Đã lưu ảnh: {filename}")
            
            # PHÂN TÍCH ẢNH
            results = analyze_image(frame, source="daily_capture")
            
            # Tạo kết quả trả về đầy đủ
            response_data = {
                'success': True,
                'filename': filename,
                'path': f'/daily_captures/{filename}',
                'results': results,
                'timestamp': timestamp,
                'analysis_time': datetime.now().strftime("%H:%M:%S"),
                'message': 'Đã hoàn thành chụp ảnh định kỳ hàng ngày',
                'source': 'daily_capture'
            }

            # Lưu kết quả chụp định kỳ gần nhất (thread-safe)
            try:
                with daily_response_lock:
                    globals()['last_daily_response'] = response_data
            except Exception:
                pass
            
            # Cập nhật trạng thái hệ thống
            current_status['last_daily_capture'] = timestamp
            current_status['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Cập nhật kết quả phân tích mới nhất
            current_status['latest_analysis'] = {
                "type": results['type'],
                "disease_name": results['class_name'],
                "confidence": results['confidence'],
                "timestamp": timestamp,
                "source": "daily_capture"
            }
            
            if results['type'] == 'disease':
                current_status['disease_detected'] = True
                current_status['disease_name'] = results['class_name']
                current_status['confidence'] = results['confidence']
                current_status['system_status'] = f"⚠️ Phát hiện bệnh từ chụp định kỳ"
            else:
                current_status['disease_detected'] = False
                current_status['system_status'] = "🌱 Không phát hiện bệnh"
            
            # Cập nhật ngày chụp cuối
            last_capture_date = today
            
            # Cập nhật lịch chụp tiếp theo
            next_capture_time = datetime.now() + timedelta(days=1)
            next_capture_time = next_capture_time.replace(hour=8, minute=0, second=0)
            current_status['next_daily_capture'] = next_capture_time.strftime("%Y-%m-%d %H:%M")
            
            # Gửi kết quả chi tiết qua WebSocket (JSON đầy đủ)
            socketio.emit('daily_capture_result', response_data)
            
            # Gửi cập nhật trạng thái
            socketio.emit('status_update', current_status)
            
            # Nếu phát hiện bệnh và vượt ngưỡng, gửi cảnh báo
            threshold = current_status.get('notification_threshold', 0.6)
            if (results['type'] == 'disease' and 
                results['confidence'] > threshold):
                
                socketio.emit('disease_alert', {
                    'type': 'warning',
                    'title': 'CẢNH BÁO TỰ ĐỘNG HÀNG NGÀY',
                    'message': f"Phát hiện: {results['class_name']} ({results['confidence']:.1%})",
                    'disease': results['class_name'],
                    'confidence': results['confidence'],
                    'timestamp': timestamp,
                    'source': 'daily_capture',
                    'severity': results.get('severity', 'medium'),
                    'full_results': response_data  # Gửi cả kết quả đầy đủ
                })
                
                print(f"[DAILY CAPTURE ALERT] Phát hiện bệnh: {results['class_name']}")
            
            print(f"[DAILY CAPTURE] Hoàn thành: {results['class_name']} ({results['confidence']:.1%})")
            return response_data
            
    except Exception as e:
        print(f"[DAILY CAPTURE ERROR] Lỗi: {e}")
        error_result = {
            'success': False,
            'error': f'Lỗi khi chụp ảnh định kỳ: {str(e)}',
            'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S"),
            'message': 'Có lỗi xảy ra khi chụp ảnh định kỳ'
        }
        # Lưu kết quả lỗi làm kết quả gần nhất
        try:
            with daily_response_lock:
                globals()['last_daily_response'] = error_result
        except Exception:
            pass
        socketio.emit('daily_capture_result', error_result)
        return error_result

def schedule_daily_capture():
    """Lên lịch chụp ảnh hàng ngày"""
    global daily_capture_thread
    
    # Lên lịch chụp mỗi ngày lúc 8:00 sáng
    schedule.every().day.at("08:00").do(perform_daily_capture)
    
    # TEST: Chụp ngay khi khởi động
    schedule.every(2).minutes.do(perform_daily_capture)  # TEST: 2 phút
    
    print("[SCHEDULER] Đã lên lịch chụp ảnh hàng ngày lúc 8:00")
    
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    daily_capture_thread = threading.Thread(target=run_scheduler, daemon=True)
    daily_capture_thread.start()

# ====================== PHẦN 8: LUỒNG ĐỌC CẢM BIẾN ======================
def sensor_reader():
    """Luồng độc lập đọc cảm biến DHT11"""
    time.sleep(2)
    
    while True:
        try:
            temp, humidity = sensor.read()
            
            if temp is not None and humidity is not None:
                current_status['temperature'] = temp
                current_status['humidity'] = humidity
                current_status['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                socketio.emit('sensor_update', {
                    'temperature': temp,
                    'humidity': humidity,
                    'timestamp': current_status['last_update']
                })
                
                if temp > 35 or humidity > 85:
                    current_status['system_status'] = "🌡️ Cảnh báo: Điều kiện môi trường không tối ưu"
                elif not current_status['disease_detected']:
                    current_status['system_status'] = "🌱 Hệ thống hoạt động bình thường"
                
                socketio.emit('status_update', current_status)
                
        except Exception as e:
            print(f"[ERROR] Lỗi đọc cảm biến: {e}")
        
        time.sleep(10)

# ====================== PHẦN 9: CÁC ROUTE API (TRẢ VỀ JSON ĐẦY ĐỦ) ======================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/capture', methods=['POST'])
def capture_image():
    """
    Chụp ảnh thủ công và phân tích
    TRẢ VỀ: JSON với kết quả chi tiết
    """
    try:
        with camera_lock:
            frame = camera.get_frame()
            if frame is None:
                return jsonify({
                    'success': False,
                    'error': 'Không thể truy cập camera',
                    'message': 'Kiểm tra kết nối camera và thử lại'
                }), 400
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"manual_{timestamp}.jpg"
            filepath = os.path.join(app.config['CAPTURE_FOLDER'], filename)
            
            cv2.imwrite(filepath, frame)
            print(f"[MANUAL CAPTURE] Đã lưu ảnh: {filename}")
            
            # PHÂN TÍCH ẢNH VÀ TRẢ VỀ KẾT QUẢ CHI TIẾT
            results = analyze_image(frame, source="manual_capture")
            
            # Tạo response data đầy đủ
            response_data = {
                'success': True,
                'filename': filename,
                'path': f'/captures/{filename}',
                'results': results,
                'timestamp': timestamp,
                'analysis_time': datetime.now().strftime("%H:%M:%S"),
                'message': 'Chụp ảnh và phân tích thành công!',
                'source': 'manual_capture'
            }
            
            # Cập nhật trạng thái hệ thống
            current_status['latest_analysis'] = {
                "type": results['type'],
                "disease_name": results['class_name'],
                "confidence": results['confidence'],
                "timestamp": timestamp,
                "source": "manual_capture"
            }
            
            if results['type'] == 'disease':
                current_status['disease_detected'] = True
                current_status['disease_name'] = results['class_name']
                current_status['confidence'] = results['confidence']
                current_status['system_status'] = f"⚠️ Phát hiện bệnh từ ảnh chụp"
            else:
                current_status['disease_detected'] = False
                current_status['system_status'] = "🌱 Không phát hiện bệnh"
            
            current_status['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Gửi cập nhật qua WebSocket
            socketio.emit('status_update', current_status)
            
            # Kiểm tra ngưỡng để gửi thông báo
            threshold = current_status.get('notification_threshold', 0.6)
            if (results['type'] == 'disease' and 
                results['confidence'] > threshold):
                
                socketio.emit('disease_alert', {
                    'type': 'warning',
                    'title': 'PHÁT HIỆN BỆNH TỪ ẢNH CHỤP THỦ CÔNG',
                    'message': f"{results['class_name']} - Độ tin cậy: {results['confidence']:.1%}",
                    'disease': results['class_name'],
                    'confidence': results['confidence'],
                    'timestamp': timestamp,
                    'source': 'manual_capture',
                    'severity': results.get('severity', 'medium'),
                    'full_results': response_data  # Gửi cả kết quả đầy đủ
                })
            
            print(f"[MANUAL CAPTURE RESULT] {results['class_name']} ({results['confidence']:.1%})")
            return jsonify(response_data)
            
    except Exception as e:
        print(f"[ERROR] Lỗi khi chụp ảnh: {e}")
        return jsonify({
            'success': False,
            'error': f'Lỗi hệ thống: {str(e)}',
            'message': 'Có lỗi xảy ra khi xử lý ảnh'
        }), 500

@app.route('/daily_capture_now', methods=['POST'])
def daily_capture_now():
    """
    Chụp ảnh định kỳ ngay lập tức
    TRẢ VỀ: JSON với kết quả chi tiết
    """
    try:
        # Thực hiện chụp ảnh và nhận kết quả
        result = perform_daily_capture()
        
        if result and result.get('success'):
            return jsonify(result)
        else:
            return jsonify({
                'success': False,
                'message': 'Đang thực hiện chụp ảnh định kỳ...',
                'status': 'processing'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Có lỗi xảy ra khi chụp ảnh định kỳ'
        }), 500


@app.route('/get_last_daily_result')
def get_last_daily_result():
    """
    Trả về kết quả JSON của lần chụp định kỳ gần nhất (nếu có)
    """
    try:
        with daily_response_lock:
            resp = globals().get('last_daily_response')

        if resp is None:
            return jsonify({
                'success': False,
                'message': 'Chưa có kết quả chụp định kỳ nào'
            }), 404

        return jsonify(resp)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Lỗi khi lấy kết quả chụp định kỳ gần nhất'
        }), 500

@app.route('/get_daily_capture_info')
def get_daily_capture_info():
    """
    Lấy thông tin chụp ảnh định kỳ
    TRẢ VỀ: JSON với thông tin đầy đủ
    """
    return jsonify({
        'success': True,
        'daily_capture_enabled': current_status['daily_capture_enabled'],
        'next_daily_capture': current_status['next_daily_capture'],
        'last_daily_capture': current_status['last_daily_capture'],
        'latest_analysis': current_status['latest_analysis'],
        'notification_threshold': current_status['notification_threshold'],
        'system_status': current_status['system_status']
    })

@app.route('/toggle_daily_capture', methods=['POST'])
def toggle_daily_capture():
    """
    Bật/tắt chụp ảnh định kỳ
    TRẢ VỀ: JSON với kết quả
    """
    try:
        data = request.get_json()
        enabled = data.get('enabled', True)
        
        current_status['daily_capture_enabled'] = enabled
        
        if enabled:
            next_capture_time = datetime.now() + timedelta(days=1)
            next_capture_time = next_capture_time.replace(hour=8, minute=0, second=0)
            current_status['next_daily_capture'] = next_capture_time.strftime("%Y-%m-%d %H:%M")
            
            message = 'Đã bật chụp ảnh định kỳ hàng ngày lúc 8:00'
        else:
            current_status['next_daily_capture'] = ''
            message = 'Đã tắt chụp ảnh định kỳ hàng ngày'
        
        socketio.emit('status_update', current_status)
        
        return jsonify({
            'success': True,
            'message': message,
            'enabled': enabled,
            'next_capture': current_status['next_daily_capture']
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Có lỗi xảy ra khi thay đổi cài đặt'
        }), 500

@app.route('/upload', methods=['POST'])
def upload_image():
    """
    Upload ảnh và phân tích
    TRẢ VỀ: JSON với kết quả chi tiết
    """
    if 'file' not in request.files:
        return jsonify({
            'success': False,
            'error': 'Không có file được chọn',
            'message': 'Vui lòng chọn file ảnh trước khi upload'
        }), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({
            'success': False,
            'error': 'Không có file được chọn',
            'message': 'Vui lòng chọn file ảnh trước khi upload'
        }), 400
    
    try:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        print(f"[UPLOAD] Đã lưu file: {filename}")
        
        image = cv2.imread(filepath)
        if image is None:
            return jsonify({
                'success': False,
                'error': 'Không thể đọc file ảnh',
                'message': 'File không phải là ảnh hợp lệ hoặc đã bị hỏng'
            }), 400
        
        # PHÂN TÍCH ẢNH VÀ TRẢ VỀ KẾT QUẢ CHI TIẾT
        results = analyze_image(image, source="upload")
        
        # Tạo response data đầy đủ
        response_data = {
            'success': True,
            'filename': filename,
            'path': f'/uploads/{filename}',
            'results': results,
            'analysis_details': {
                'image_size': f"{image.shape[1]}x{image.shape[0]}",
                'model_used': 'TensorFlow Lite',
                'analysis_time': datetime.now().strftime("%H:%M:%S"),
                'confidence_threshold': f'{current_status["notification_threshold"]*100}%'
            },
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'message': 'Phân tích ảnh thành công!',
            'source': 'upload'
        }
        
        # Cập nhật trạng thái hệ thống
        current_status['latest_analysis'] = {
            "type": results['type'],
            "disease_name": results['class_name'],
            "confidence": results['confidence'],
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "source": "upload"
        }
        
        if results['type'] == 'disease':
            current_status['disease_detected'] = True
            current_status['disease_name'] = results['class_name']
            current_status['confidence'] = results['confidence']
            current_status['system_status'] = f"⚠️ Phát hiện bệnh từ upload"
        else:
            current_status['disease_detected'] = False
            current_status['system_status'] = "🌱 Không phát hiện bệnh"
        
        current_status['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Gửi cập nhật qua WebSocket
        socketio.emit('status_update', current_status)
        
        # Kiểm tra ngưỡng để gửi thông báo
        threshold = current_status.get('notification_threshold', 0.6)
        if (results['type'] == 'disease' and 
            results['confidence'] > threshold):
            
            socketio.emit('disease_alert', {
                'type': 'warning',
                'title': 'PHÂN TÍCH ẢNH UPLOAD',
                'message': f"{results['class_name']} ({results['confidence']:.1%})",
                'disease': results['class_name'],
                'confidence': results['confidence'],
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'source': 'upload',
                'severity': results.get('severity', 'medium'),
                'full_results': response_data  # Gửi cả kết quả đầy đủ
            })
        
        print(f"[UPLOAD RESULT] {results['class_name']} ({results['confidence']:.1%})")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"[ERROR] Lỗi khi upload ảnh: {e}")
        return jsonify({
            'success': False,
            'error': f'Lỗi xử lý ảnh: {str(e)}',
            'message': 'Có lỗi xảy ra khi xử lý file ảnh'
        }), 500

@app.route('/update_threshold', methods=['POST'])
def update_threshold():
    """
    Cập nhật ngưỡng tin cậy
    TRẢ VỀ: JSON với kết quả
    """
    try:
        data = request.get_json()
        new_threshold = float(data.get('threshold', 0.6))
        
        if 0 <= new_threshold <= 1:
            current_status['notification_threshold'] = new_threshold
            print(f"[SYSTEM] Đã cập nhật ngưỡng tin cậy: {new_threshold*100}%")
            
            socketio.emit('status_update', current_status)
            
            return jsonify({
                'success': True,
                'message': f'Đã cập nhật ngưỡng tin cậy: {new_threshold*100}%',
                'threshold': new_threshold,
                'threshold_percent': f'{new_threshold*100}%'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Ngưỡng phải từ 0 đến 1',
                'message': 'Giá trị ngưỡng không hợp lệ'
            }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Có lỗi xảy ra khi cập nhật ngưỡng'
        }), 500

@app.route('/get_status')
def get_status():
    """
    Lấy trạng thái hệ thống
    TRẢ VỀ: JSON với thông tin đầy đủ
    """
    current_status['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({
        'success': True,
        'data': current_status,
        'system_info': {
            'camera_status': 'Hoạt động' if camera.running else 'Lỗi',
            'model_loaded': detector.model_loaded,
            'sensor_connected': sensor.dht_device is not None,
            'labels_count': len(detector.labels) if detector.labels else 0,
            'stream_mode': 'Video thô (không nhận diện real-time)',
            'daily_capture_mode': 'Hoạt động' if current_status['daily_capture_enabled'] else 'Tắt',
            'server_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    })

@app.route('/get_sensor_data')
def get_sensor_data():
    """
    Đọc cảm biến ngay lập tức
    TRẢ VỀ: JSON với dữ liệu cảm biến
    """
    try:
        temp, humidity = sensor.read()
        return jsonify({
            'success': True,
            'temperature': temp if temp is not None else 0,
            'humidity': humidity if humidity is not None else 0,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'environment_status': 'Tối ưu' if temp <= 35 and humidity <= 85 else 'Cảnh báo',
            'message': 'Đã cập nhật dữ liệu cảm biến'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Có lỗi xảy ra khi đọc cảm biến'
        }), 500

# ====================== PHẦN 10: CÁC ROUTE PHỤC VỤ FILE ======================

@app.route('/captures/<filename>')
def serve_capture(filename):
    return send_from_directory(app.config['CAPTURE_FOLDER'], filename)

@app.route('/daily_captures/<filename>')
def serve_daily_capture(filename):
    return send_from_directory(app.config['DAILY_CAPTURE_FOLDER'], filename)

@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/get_daily_captures')
def get_daily_captures():
    """
    Lấy danh sách ảnh chụp định kỳ
    TRẢ VỀ: JSON với danh sách ảnh
    """
    try:
        captures = []
        for filename in sorted(os.listdir(app.config['DAILY_CAPTURE_FOLDER']), reverse=True):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                filepath = os.path.join(app.config['DAILY_CAPTURE_FOLDER'], filename)
                captures.append({
                    'filename': filename,
                    'path': f'/daily_captures/{filename}',
                    'size': os.path.getsize(filepath),
                    'created': datetime.fromtimestamp(os.path.getctime(filepath)).strftime("%Y-%m-%d %H:%M")
                })
        
        return jsonify({
            'success': True,
            'count': len(captures),
            'captures': captures[:10],
            'message': f'Đã tìm thấy {len(captures)} ảnh chụp định kỳ'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Có lỗi xảy ra khi đọc danh sách ảnh'
        }), 500

@app.route('/get_manual_captures')
def get_manual_captures():
    """
    Lấy danh sách ảnh chụp thủ công
    TRẢ VỀ: JSON với danh sách ảnh
    """
    try:
        captures = []
        for filename in sorted(os.listdir(app.config['CAPTURE_FOLDER']), reverse=True):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                filepath = os.path.join(app.config['CAPTURE_FOLDER'], filename)
                captures.append({
                    'filename': filename,
                    'path': f'/captures/{filename}',
                    'size': os.path.getsize(filepath),
                    'created': datetime.fromtimestamp(os.path.getctime(filepath)).strftime("%Y-%m-%d %H:%M")
                })
        
        return jsonify({
            'success': True,
            'count': len(captures),
            'captures': captures[:6],
            'message': f'Đã tìm thấy {len(captures)} ảnh chụp thủ công'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Có lỗi xảy ra khi đọc danh sách ảnh'
        }), 500

# ====================== PHẦN 11: WEBSOCKET HANDLERS ======================

@socketio.on('connect')
def handle_connect():
    print(f'[WEBSOCKET] Client connected: {request.sid}')
    emit('status_update', current_status)
    emit('welcome', {
        'success': True,
        'message': 'Kết nối thành công đến hệ thống nhận diện bệnh cây cà chua',
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'system_status': current_status['system_status']
    })

@socketio.on('disconnect')
def handle_disconnect():
    print(f'[WEBSOCKET] Client disconnected: {request.sid}')

@socketio.on('request_update')
def handle_update_request():
    emit('status_update', current_status)

@socketio.on('update_threshold')
def handle_update_threshold(data):
    try:
        new_threshold = float(data.get('threshold', 0.6))
        if 0 <= new_threshold <= 1:
            current_status['notification_threshold'] = new_threshold
            emit('threshold_updated', {
                'success': True,
                'threshold': new_threshold,
                'message': f'Ngưỡng tin cậy đã cập nhật: {new_threshold*100}%'
            })
    except Exception as e:
        print(f"[ERROR] Lỗi cập nhật ngưỡng: {e}")
        emit('threshold_updated', {
            'success': False,
            'error': str(e),
            'message': 'Có lỗi khi cập nhật ngưỡng'
        })


# Global exception handler to ensure any uncaught exceptions return JSON
@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception('Unhandled exception: %s', error)
    try:
        return jsonify({
            'success': False,
            'error': str(error),
            'message': 'Internal server error'
        }), 500
    except Exception:
        # In case jsonify itself fails
        return ('Internal server error', 500)

# ====================== PHẦN 12: KHỞI CHẠY ỨNG DỤNG ======================

def cleanup():
    print("\n[SYSTEM] Đang dừng hệ thống...")
    camera.release()
    sensor.cleanup()
    print("[SYSTEM] Đã giải phóng tài nguyên")

if __name__ == '__main__':
    atexit.register(cleanup)
    
    sensor_thread = threading.Thread(target=sensor_reader, daemon=True)
    sensor_thread.start()
    print("[SYSTEM] Đã khởi động thread đọc cảm biến")
    
    schedule_daily_capture()
    
    next_capture_time = datetime.now() + timedelta(days=1)
    next_capture_time = next_capture_time.replace(hour=8, minute=0, second=0)
    current_status['next_daily_capture'] = next_capture_time.strftime("%Y-%m-%d %H:%M")
    
    print("=" * 70)
    print("🌱 HỆ THỐNG NHẬN DIỆN BỆNH CÂY CÀ CHUA - JSON RESPONSE")
    print("=" * 70)
    print(f"📁 Model: {detector.model_path}")
    print(f"📊 Số lớp: {len(detector.labels) if detector.labels else 0}")
    print(f"🌡️  Cảm biến: GPIO{sensor.pin}")
    print(f"📷 Camera: Index {camera.camera_index}")
    print(f"🎯 Video Stream: KHÔNG NHẬN DIỆN REAL-TIME")
    print(f"📅 Chụp ảnh định kỳ: HÀNG NGÀY lúc 8:00 (TEST: 2 phút)")
    print(f"📅 Lần chụp tiếp theo: {current_status['next_daily_capture']}")
    print(f"🎯 Ngưỡng tin cậy: {current_status['notification_threshold']*100}%")
    print(f"📤 Tất cả API đều trả về JSON với results chi tiết")
    print(f"🌐 Web Interface: http://0.0.0.0:5000")
    print("=" * 70)
    
    try:
        socketio.run(app, 
                    host='0.0.0.0',
                    port=5000,
                    debug=True,
                    use_reloader=False,
                    allow_unsafe_werkzeug=True)
    
    except KeyboardInterrupt:
        print("\n[SYSTEM] Nhận tín hiệu dừng...")
    except Exception as e:
        print(f"[ERROR] Lỗi khởi động server: {e}")