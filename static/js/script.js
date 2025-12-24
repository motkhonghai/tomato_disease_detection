// ===== GLOBAL VARIABLES =====
let socket;
let startTime = Date.now();
let systemUptimeInterval;
let currentThreshold = 0.6;
let activeNotification = null;
let dailyCaptureEnabled = true;

// ===== NOTIFICATION SYSTEM =====
function showNotification(title, message, type = 'info', duration = 5000) {
    const container = document.getElementById('notificationContainer');
    
    if (activeNotification) {
        container.removeChild(activeNotification);
        activeNotification = null;
    }
    
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    
    const icons = {
        'warning': 'fa-exclamation-triangle',
        'success': 'fa-check-circle',
        'error': 'fa-times-circle',
        'info': 'fa-info-circle'
    };
    
    notification.innerHTML = `
        <div class="notification-header">
            <div class="notification-title">
                <i class="fas ${icons[type]}"></i>
                <span>${title}</span>
            </div>
            <button class="notification-close" onclick="this.parentElement.parentElement.remove()">
                <i class="fas fa-times"></i>
            </button>
        </div>
        <div class="notification-content">
            <p>${message}</p>
        </div>
        <div class="notification-progress"></div>
    `;
    
    container.appendChild(notification);
    activeNotification = notification;
    
    setTimeout(() => notification.classList.add('show'), 10);
    
    setTimeout(() => {
        if (notification.parentNode) {
            notification.classList.remove('show');
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                    activeNotification = null;
                }
            }, 500);
        }
    }, duration);
}

// ===== DISPLAY ANALYSIS RESULT =====
function displayAnalysisResult(data) {
    // Xóa kết quả cũ nếu có
    const oldResult = document.getElementById('analysisResult');
    if (oldResult) {
        oldResult.remove();
    }
    
    // Tạo container mới
    const leftColumn = document.querySelector('.left-column');
    const resultDiv = document.createElement('div');
    resultDiv.id = 'analysisResult';
    resultDiv.className = 'analysis-result-container';
    
    const sourceText = data.source === 'manual_capture' ? 'Chụp thủ công' : 
                      data.source === 'daily_capture' ? 'Chụp định kỳ' : 
                      data.source === 'upload' ? 'Upload ảnh' : 'Phân tích';
    
    let resultHtml = `
        <div class="analysis-card ${data.results.type}">
            <div class="analysis-header">
                <h3><i class="fas fa-search"></i> KẾT QUẢ PHÂN TÍCH</h3>
                <div class="analysis-source">
                    <span class="source-badge ${data.source}">${sourceText}</span>
                    <small>${data.timestamp}</small>
                </div>
            </div>
            <div class="analysis-body">
    `;
    
    if (!data.results.success) {
        resultHtml += `
                <div class="result-item error">
                    <i class="fas fa-exclamation-circle"></i>
                    <span class="value">${data.results.description || data.message || 'Có lỗi xảy ra'}</span>
                </div>
        `;
    } else {
        resultHtml += `
                <div class="result-item">
                    <span class="label"><i class="fas fa-tag"></i> Loại phát hiện:</span>
                    <span class="value ${data.results.type}">
                        <i class="fas ${data.results.icon || 'fa-question-circle'}"></i>
                        ${data.results.class_name}
                    </span>
                </div>
                <div class="result-item">
                    <span class="label"><i class="fas fa-chart-line"></i> Độ tin cậy:</span>
                    <span class="value confidence">${(data.results.confidence * 100).toFixed(1)}%</span>
                </div>
                <div class="result-item">
                    <span class="label"><i class="fas fa-info-circle"></i> Mô tả:</span>
                    <span class="value description">${data.results.description}</span>
                </div>
        `;
        
        if (data.results.recommendation) {
            resultHtml += `
                <div class="result-item">
                    <span class="label"><i class="fas fa-lightbulb"></i> Khuyến nghị:</span>
                    <span class="value recommendation">${data.results.recommendation}</span>
                </div>
            `;
        }
        
        resultHtml += `
                <div class="result-item">
                    <span class="label"><i class="fas fa-image"></i> Ảnh:</span>
                    <span class="value">
                        <a href="${data.path}" target="_blank" class="image-link">
                            <i class="fas fa-external-link-alt"></i> Xem ảnh gốc
                        </a>
                    </span>
                </div>
        `;
    }
    
    resultHtml += `
            </div>
            <div class="analysis-footer">
                <small><i class="fas fa-clock"></i> Thời gian phân tích: ${data.analysis_time || '--'}</small>
                <small><i class="fas fa-server"></i> Model: TensorFlow Lite</small>
            </div>
        </div>
    `;
    
    resultDiv.innerHTML = resultHtml;
    
    // Chèn sau video container
    const videoContainer = document.querySelector('.video-container');
    if (videoContainer && videoContainer.nextSibling) {
        videoContainer.parentNode.insertBefore(resultDiv, videoContainer.nextSibling);
    } else {
        leftColumn.appendChild(resultDiv);
    }
    
    // Cập nhật dashboard
    updateLatestResult(data);
    
    // Scroll đến kết quả
    setTimeout(() => {
        resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 300);
}

// ===== UPDATE LATEST RESULT IN DASHBOARD =====
function updateLatestResult(data) {
    if (!data || !data.results) return;
    
    const diseaseName = document.getElementById('latestResult');
    const diseaseConfidence = document.getElementById('latestConfidence');
    const diseaseTimestamp = document.getElementById('latestTimestamp');
    const diseaseStatus = document.getElementById('diseaseStatus');
    const diseaseDetails = document.getElementById('diseaseDetails');
    
    if (!diseaseName || !diseaseConfidence || !diseaseTimestamp || !diseaseStatus) return;
    
    if (data.results.success && data.results.type === 'disease' && data.results.confidence > currentThreshold) {
        // Có bệnh
        diseaseStatus.innerHTML = `
            <div class="status-indicator disease">
                <i class="fas fa-exclamation-triangle"></i>
                <span>PHÁT HIỆN: ${data.results.class_name}</span>
            </div>
        `;
        diseaseName.textContent = data.results.class_name;
        diseaseConfidence.textContent = `${(data.results.confidence * 100).toFixed(1)}%`;
        diseaseTimestamp.textContent = data.timestamp || '--';
        
        if (diseaseDetails) diseaseDetails.classList.add('visible');
        
    } else if (data.results.success && data.results.type === 'healthy') {
        // Khỏe mạnh
        diseaseStatus.innerHTML = `
            <div class="status-indicator healthy">
                <i class="fas fa-check-circle"></i>
                <span>KHÔNG PHÁT HIỆN BỆNH</span>
            </div>
        `;
        diseaseName.textContent = data.results.class_name;
        diseaseConfidence.textContent = `${(data.results.confidence * 100).toFixed(1)}%`;
        diseaseTimestamp.textContent = data.timestamp || '--';
        
        if (diseaseDetails) diseaseDetails.classList.add('visible');
        
    } else {
        // Không có dữ liệu hoặc lỗi
        diseaseStatus.innerHTML = `
            <div class="status-indicator healthy">
                <i class="fas fa-check-circle"></i>
                <span>ĐANG THEO DÕI</span>
            </div>
        `;
        diseaseName.textContent = data.results?.class_name || 'Chưa có dữ liệu';
        diseaseConfidence.textContent = data.results?.confidence ? `${(data.results.confidence * 100).toFixed(1)}%` : '--';
        diseaseTimestamp.textContent = data.timestamp || '--';
        
        if (diseaseDetails) diseaseDetails.classList.remove('visible');
    }
}

// ===== THRESHOLD CONTROL =====
function updateThreshold(value) {
    const percent = parseInt(value) / 100;
    currentThreshold = percent;
    
    document.getElementById('thresholdValue').textContent = `${value}%`;
    
    fetch('/update_threshold', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ threshold: percent })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log(`✅ Đã cập nhật ngưỡng: ${data.threshold_percent}`);
            showNotification('THÀNH CÔNG', data.message, 'success', 3000);
            
            if (socket && socket.connected) {
                socket.emit('update_threshold', { threshold: percent });
            }
        } else {
            showNotification('LỖI', data.message || 'Không thể cập nhật ngưỡng', 'error');
        }
    })
    .catch(error => {
        console.error('Lỗi cập nhật ngưỡng:', error);
        showNotification('LỖI', 'Không thể kết nối đến server', 'error');
    });
}

// ===== DAILY CAPTURE FUNCTIONS =====
function getDailyCaptureInfo() {
    fetch('/get_daily_capture_info')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                dailyCaptureEnabled = data.daily_capture_enabled;
                
                const statusElement = document.getElementById('dailyCaptureStatus');
                if (data.daily_capture_enabled) {
                    statusElement.innerHTML = '<i class="fas fa-check-circle" style="color:#4CAF50"></i> Đang hoạt động';
                    statusElement.style.color = '#4CAF50';
                } else {
                    statusElement.innerHTML = '<i class="fas fa-pause-circle" style="color:#FF9800"></i> Đã tắt';
                    statusElement.style.color = '#FF9800';
                }
                
                document.getElementById('nextCaptureTime').textContent = data.next_daily_capture || '--';
                document.getElementById('lastCaptureTime').textContent = data.last_daily_capture || '--';
                
                if (data.latest_analysis && data.latest_analysis.type !== 'none') {
                    updateLatestResult({
                        results: data.latest_analysis,
                        timestamp: data.last_daily_capture
                    });
                }
            }
        })
        .catch(error => {
            console.error('Lỗi lấy thông tin daily capture:', error);
            document.getElementById('dailyCaptureStatus').innerHTML = 
                '<i class="fas fa-exclamation-circle" style="color:#F44336"></i> Lỗi kết nối';
        });
}

function toggleDailyCapture(enabled) {
    fetch('/toggle_daily_capture', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ enabled: enabled })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification(
                'THÔNG BÁO',
                data.message,
                enabled ? 'success' : 'info',
                3000
            );
            getDailyCaptureInfo();
        } else {
            showNotification('LỖI', data.message || 'Không thể thay đổi cài đặt', 'error');
        }
    })
    .catch(error => {
        console.error('Lỗi toggle daily capture:', error);
        showNotification('LỖI', 'Không thể kết nối đến server', 'error');
    });
}

async function triggerDailyCapture() {
    try {
        showNotification(
            'CHỤP ẢNH ĐỊNH KỲ',
            'Đang thực hiện chụp ảnh định kỳ...',
            'info',
            2000
        );
        
        const response = await fetch('/daily_capture_now', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Hiển thị kết quả phân tích
            displayAnalysisResult(data);
            
            showNotification(
                'CHỤP ẢNH ĐỊNH KỲ',
                `Hoàn thành: ${data.results.class_name} (${(data.results.confidence * 100).toFixed(1)}%)`,
                data.results.type === 'disease' ? 'warning' : 'success',
                5000
            );
            
            // Làm mới thông tin
            setTimeout(() => {
                getDailyCaptureInfo();
                loadDailyCaptures();
            }, 1000);
            
        } else if (data.status === 'processing') {
            showNotification('THÔNG BÁO', data.message, 'info');
        } else {
            showNotification('LỖI', data.message || 'Có lỗi xảy ra', 'error');
        }
    } catch (error) {
        console.error('Lỗi trigger daily capture:', error);
        showNotification('LỖI', 'Không thể kết nối đến server', 'error');
    }
}

// ===== LOAD CAPTURES =====
function loadDailyCaptures() {
    fetch('/get_daily_captures')
        .then(response => response.json())
        .then(data => {
            const grid = document.getElementById('dailyCapturesGrid');
            if (!grid) return;
            
            grid.innerHTML = '';
            
            if (data.success && data.captures && data.captures.length > 0) {
                data.captures.forEach(capture => {
                    const img = document.createElement('img');
                    img.src = capture.path;
                    img.className = 'capture-thumb';
                    img.alt = capture.filename;
                    img.title = 'Ảnh chụp định kỳ - Click để xem';
                    img.onclick = () => window.open(capture.path, '_blank');
                    grid.appendChild(img);
                });
            } else {
                grid.innerHTML = '<p class="no-data">Chưa có ảnh chụp định kỳ</p>';
            }
        })
        .catch(error => {
            console.error('Load daily captures error:', error);
            const grid = document.getElementById('dailyCapturesGrid');
            if (grid) {
                grid.innerHTML = '<p class="error">Không thể tải danh sách ảnh</p>';
            }
        });
}

function loadManualCaptures() {
    fetch('/get_manual_captures')
        .then(response => response.json())
        .then(data => {
            const grid = document.getElementById('manualCapturesGrid');
            if (!grid) return;
            
            grid.innerHTML = '';
            
            if (data.success && data.captures && data.captures.length > 0) {
                data.captures.forEach(capture => {
                    const img = document.createElement('img');
                    img.src = capture.path;
                    img.className = 'capture-thumb';
                    img.alt = capture.filename;
                    img.title = 'Ảnh chụp thủ công - Click để xem';
                    img.onclick = () => window.open(capture.path, '_blank');
                    grid.appendChild(img);
                });
            } else {
                grid.innerHTML = '<p class="no-data">Chưa có ảnh chụp thủ công</p>';
            }
        })
        .catch(error => {
            console.error('Load manual captures error:', error);
            const grid = document.getElementById('manualCapturesGrid');
            if (grid) {
                grid.innerHTML = '<p class="error">Không thể tải danh sách ảnh</p>';
            }
        });
}

// ===== WEBSOCKET HANDLERS =====
function initSocket() {
    socket = io({
        transports: ['websocket', 'polling'],
        reconnect: true,
        timeout: 10000
    });

    socket.on('connect', () => {
        console.log('✅ Connected to WebSocket');
        updateConnectionStatus(true);
        socket.emit('request_update');
    });

    socket.on('disconnect', () => {
        console.log('❌ Disconnected');
        updateConnectionStatus(false);
    });

    socket.on('status_update', (data) => {
        updateDashboard(data);
    });

    socket.on('disease_alert', (data) => {
        console.log('⚠️ Disease alert received:', data);
        
        if (data.confidence > currentThreshold) {
            showNotification(
                data.title || 'PHÁT HIỆN BỆNH!',
                data.message,
                'warning',
                8000
            );
        }
        
        // Nếu có full_results, hiển thị chi tiết
        if (data.full_results) {
            updateLatestResult(data.full_results);
        }
    });

    socket.on('sensor_update', (data) => {
        updateSensorDisplay(data);
    });

    socket.on('daily_capture_result', (data) => {
        console.log('📅 Daily capture result:', data);
        
        if (data.success) {
            // Hiển thị kết quả chi tiết
            displayAnalysisResult(data);
            
            showNotification(
                'CHỤP ẢNH ĐỊNH KỲ',
                `Đã hoàn thành: ${data.results.class_name}`,
                data.results.type === 'disease' ? 'warning' : 'success',
                5000
            );
            
            loadDailyCaptures();
        } else {
            showNotification('LỖI', data.message || 'Có lỗi xảy ra', 'error');
        }
    });

    socket.on('threshold_updated', (data) => {
        if (data.success) {
            console.log('🎯 Threshold updated:', data.threshold);
            currentThreshold = data.threshold;
            document.getElementById('thresholdValue').textContent = `${data.threshold * 100}%`;
            document.getElementById('thresholdSlider').value = data.threshold * 100;
            showNotification('THÀNH CÔNG', data.message, 'success', 3000);
        }
    });

    socket.on('welcome', (data) => {
        console.log('👋 Welcome message:', data.message);
    });
}

// ===== DASHBOARD FUNCTIONS =====
function updateDashboard(data) {
    // System status
    if (data.system_status) {
        const statusIcon = document.querySelector('#systemStatus .status-icon');
        const statusText = document.querySelector('#systemStatus span');
        
        if (data.disease_detected) {
            statusIcon.style.color = '#ff9800';
            statusIcon.className = 'fas fa-exclamation-triangle status-icon';
        } else {
            statusIcon.style.color = '#4CAF50';
            statusIcon.className = 'fas fa-circle status-icon';
        }
        
        statusText.textContent = data.system_status;
    }
    
    // Sensor data
    if (data.temperature !== undefined && data.humidity !== undefined) {
        document.getElementById('temperatureValue').textContent = `${data.temperature}°C`;
        document.getElementById('humidityValue').textContent = `${data.humidity}%`;
        document.getElementById('sensorTimestamp').textContent = data.last_update || '--';
    }
    
    // Update threshold
    if (data.notification_threshold !== undefined) {
        currentThreshold = data.notification_threshold;
        document.getElementById('thresholdValue').textContent = `${data.notification_threshold * 100}%`;
        document.getElementById('thresholdSlider').value = data.notification_threshold * 100;
    }
    
    // Update daily capture info
    if (data.next_daily_capture) {
        document.getElementById('nextCaptureTime').textContent = data.next_daily_capture;
    }
    if (data.last_daily_capture) {
        document.getElementById('lastCaptureTime').textContent = data.last_daily_capture;
    }
    
    const statusElement = document.getElementById('dailyCaptureStatus');
    if (data.daily_capture_enabled) {
        statusElement.innerHTML = '<i class="fas fa-check-circle" style="color:#4CAF50"></i> Đang hoạt động';
        statusElement.style.color = '#4CAF50';
    } else {
        statusElement.innerHTML = '<i class="fas fa-pause-circle" style="color:#FF9800"></i> Đã tắt';
        statusElement.style.color = '#FF9800';
    }
    
    // Update latest result
    if (data.latest_analysis && data.latest_analysis.type !== 'none') {
        updateLatestResult({
            results: data.latest_analysis,
            timestamp: data.last_daily_capture
        });
    }
}

function updateSensorDisplay(data) {
    document.getElementById('temperatureValue').textContent = `${data.temperature}°C`;
    document.getElementById('humidityValue').textContent = `${data.humidity}%`;
    document.getElementById('sensorTimestamp').textContent = data.timestamp || '--';
}

// ===== IMAGE FUNCTIONS =====
async function captureImage() {
    try {
        showNotification(
            'CHỤP ẢNH',
            'Đang chụp ảnh và phân tích...',
            'info',
            2000
        );
        
        const response = await fetch('/capture', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Hiển thị kết quả phân tích chi tiết
            displayAnalysisResult(data);
            
            const diseaseName = data.results.class_name;
            const confidence = data.results.confidence;
            
            if (data.results.type === 'disease' && confidence > currentThreshold) {
                showNotification(
                    'PHÂN TÍCH ẢNH CHỤP',
                    `${diseaseName} (${(confidence * 100).toFixed(1)}%)`,
                    'warning',
                    8000
                );
            } else if (data.results.type === 'healthy') {
                showNotification(
                    'KẾT QUẢ PHÂN TÍCH',
                    'Lá cây khỏe mạnh',
                    'success',
                    5000
                );
            }
            
            loadManualCaptures();
            
        } else {
            showNotification('LỖI', data.message || `Không thể chụp ảnh: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Capture error:', error);
        showNotification('LỖI', 'Không thể kết nối đến server', 'error');
    }
}

async function uploadImage() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];
    
    if (!file) {
        showNotification('THÔNG BÁO', 'Vui lòng chọn ảnh trước', 'info');
        return;
    }
    
    if (file.size > 10 * 1024 * 1024) {
        showNotification('LỖI', 'Ảnh quá lớn (tối đa 10MB)', 'error');
        return;
    }
    
    const reader = new FileReader();
    reader.onload = function(e) {
        document.getElementById('uploadPreview').innerHTML = `
            <div class="upload-preview-content">
                <img src="${e.target.result}" alt="Preview">
                <p class="loading"><i class="fas fa-spinner fa-spin"></i> Đang phân tích...</p>
            </div>
        `;
    };
    reader.readAsDataURL(file);
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Hiển thị kết quả phân tích chi tiết
            displayAnalysisResult(data);
            
            const diseaseName = data.results.class_name;
            const confidence = data.results.confidence;
            
            if (data.results.type === 'disease' && confidence > currentThreshold) {
                showNotification(
                    'PHÂN TÍCH ẢNH UPLOAD',
                    `${diseaseName} (${(confidence * 100).toFixed(1)}%)`,
                    'warning',
                    8000
                );
            } else if (data.results.type === 'healthy') {
                showNotification(
                    'KẾT QUẢ PHÂN TÍCH',
                    'Lá cây khỏe mạnh',
                    'success',
                    5000
                );
            }
            
        } else {
            document.getElementById('uploadPreview').innerHTML = 
                `<div class="upload-preview-content error">Lỗi: ${data.message || data.error}</div>`;
            showNotification('LỖI', data.message || `Upload thất bại: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Upload error:', error);
        document.getElementById('uploadPreview').innerHTML = 
            `<div class="upload-preview-content error">Lỗi kết nối: ${error.message}</div>`;
        showNotification('LỖI', 'Không thể kết nối đến server', 'error');
    }
}

// ===== OTHER FUNCTIONS =====
async function updateSensorData() {
    try {
        const response = await fetch('/get_sensor_data');
        const data = await response.json();
        
        if (data.success) {
            updateSensorDisplay(data);
            console.log('✅ Đã cập nhật dữ liệu cảm biến');
        } else {
            showNotification('LỖI', data.message || 'Không thể đọc cảm biến', 'error');
        }
    } catch (error) {
        console.error('Sensor update error:', error);
        showNotification('LỖI', 'Không thể kết nối đến server', 'error');
    }
}

function toggleFullscreen() {
    const videoWrapper = document.querySelector('.video-wrapper');
    
    if (!document.fullscreenElement) {
        if (videoWrapper.requestFullscreen) {
            videoWrapper.requestFullscreen();
        }
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen();
        }
    }
}

function updateTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString('vi-VN');
    const dateString = now.toLocaleDateString('vi-VN');
    document.getElementById('currentTime').textContent = `${dateString} ${timeString}`;
}

function updateUptime() {
    const uptimeMs = Date.now() - startTime;
    const hours = Math.floor(uptimeMs / (1000 * 60 * 60));
    const minutes = Math.floor((uptimeMs % (1000 * 60 * 60)) / (1000 * 60));
    document.getElementById('uptime').textContent = `${hours}h ${minutes}m`;
}

function updateConnectionStatus(connected) {
    const statusElement = document.getElementById('connectionStatus');
    if (connected) {
        statusElement.innerHTML = '<i class="fas fa-wifi"></i> Đã kết nối';
        statusElement.style.color = '#4CAF50';
    } else {
        statusElement.innerHTML = '<i class="fas fa-wifi-slash"></i> Mất kết nối';
        statusElement.style.color = '#f44336';
    }
}

function setupDragDrop() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    
    if (uploadArea) {
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });
        
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            
            if (e.dataTransfer.files.length) {
                fileInput.files = e.dataTransfer.files;
                uploadImage();
            }
        });
    }
}

// ===== INITIALIZATION =====
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 System initialized');
    
    initSocket();
    setupDragDrop();
    
    updateTime();
    setInterval(updateTime, 1000);
    
    updateUptime();
    systemUptimeInterval = setInterval(updateUptime, 60000);
    
    setTimeout(() => {
        getDailyCaptureInfo();
        loadDailyCaptures();
        loadManualCaptures();
        updateSensorData();
        
        document.getElementById('systemStatus').innerHTML = 
            '<i class="fas fa-circle status-icon" style="color:#4CAF50"></i>' +
            '<span>Hệ thống sẵn sàng</span>';
    }, 2000);
    
    window.addEventListener('beforeunload', (e) => {
        if (socket && socket.connected) {
            socket.disconnect();
        }
    });
});