import numpy as np
import cv2
from PIL import Image
import tensorflow as tf

class DiseaseDetector:
    def __init__(self, model_path, labels_path):
        self.model_path = model_path
        self.labels = self.load_labels(labels_path)
        self.interpreter = tf.lite.Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        
        self.input_shape = self.input_details[0]['shape']
        self.input_height = self.input_shape[1]
        self.input_width = self.input_shape[2]
        
        self.model_loaded = True
        print(f"Model loaded: {model_path}")
        print(f"Input shape: {self.input_shape}")
        print(f"Number of classes: {len(self.labels)}")
    
    def load_labels(self, path):
        """Đọc file labels.txt"""
        with open(path, 'r', encoding='utf-8') as f:
            labels = [line.strip() for line in f.readlines()]
        print(f"Loaded {len(labels)} labels: {labels}")
        return labels
    
    def preprocess_image(self, image):
        """Tiền xử lý ảnh cho model"""
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image_resized = cv2.resize(image_rgb, (self.input_width, self.input_height))
        image_normalized = image_resized.astype(np.float32) / 255.0
        image_expanded = np.expand_dims(image_normalized, axis=0)
        return image_expanded
    
    def detect(self, image):
        """Nhận diện bệnh từ ảnh"""
        try:
            input_data = self.preprocess_image(image)
            
            self.interpreter.set_tensor(self.input_details[0]['index'], input_data)
            self.interpreter.invoke()
            
            output_data = self.interpreter.get_tensor(self.output_details[0]['index'])
            predictions = output_data[0]
            
            class_id = np.argmax(predictions)
            confidence = predictions[class_id]
            
            if class_id < len(self.labels):
                class_name = self.labels[class_id]
            else:
                class_name = f"Class_{class_id}"
            
            # Kiểm tra xem class_name có trong 5 loại hợp lệ không
            valid_classes = ['healthy', 'powdery_mildew', 'Late_blight', 'Septoria_leaf_spot', 'Tomato_mosaic_virus']
            is_valid_class = any(valid_class.lower() in class_name.lower() for valid_class in valid_classes)
            
            if not is_valid_class:
                # Nếu không phải 5 loại hợp lệ, gán là "Không xác định"
                class_name = "Không xác định"
                confidence = 0.0
            
            processed_image = self.draw_results(image, class_name, confidence)
            
            return processed_image, {
                'class_id': int(class_id),
                'class_name': class_name,
                'confidence': float(confidence),
                'confidence_percent': f"{confidence * 100:.2f}%",
                'is_valid_class': is_valid_class
            }
            
        except Exception as e:
            print(f"Lỗi nhận diện: {e}")
            return image, None
    
    def draw_results(self, image, class_name, confidence):
        """Vẽ kết quả nhận diện lên ảnh"""
        display_image = image.copy()
        
        overlay = display_image.copy()
        cv2.rectangle(overlay, (0, 0), (display_image.shape[1], 70), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, display_image, 0.4, 0, display_image)
        
        result_text = f"{class_name}: {confidence*100:.1f}%"
        
        if confidence > 0.7:
            color = (0, 0, 255)
        elif confidence > 0.4:
            color = (0, 165, 255)
        else:
            color = (0, 255, 0)
        
        cv2.putText(display_image, result_text, (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        
        cv2.putText(display_image, "Tomato Disease Detection", (10, 60),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        return display_image