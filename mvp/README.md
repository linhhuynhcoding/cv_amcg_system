# Hướng dẫn thiết lập môi trường và chạy dự án Scan Tài Liệu

Dự án bao gồm script `scanner_mvp.py` để xử lý logic scan tài liệu và giao diện web `app.py` trực quan (xây dựng bằng Streamlit). Dưới đây là hướng dẫn chi tiết để thiết lập môi trường và chạy các file này.

## 1. Yêu cầu hệ thống

- Python 3.6 trở lên.

## 2. Thiết lập môi trường

Khuyến nghị sử dụng môi trường ảo (virtual environment) để tránh xung đột thư viện:

```bash
# Tạo môi trường ảo (tùy chọn)
python -m venv venv

# Kích hoạt môi trường ảo
# Trên Linux/macOS:
source venv/bin/activate
# Trên Windows:
venv\Scripts\activate
```

## 3. Cài đặt các thư viện cần thiết

Dự án yêu cầu các thư viện sau: `opencv-python` (cv2), `numpy`, `Pillow` (PIL), và `streamlit`. Bạn có thể cài đặt chúng bằng `pip`:

```bash
pip install opencv-python numpy Pillow streamlit
```

## 4. Chuẩn bị ảnh đầu vào

Script mặc định đang đọc một file ảnh có tên là `image.png` nằm trong cùng thư mục với script.
Bạn hãy chuẩn bị một bức ảnh chụp tài liệu (có rõ 4 góc) và đặt tên nó là `image.png`, rồi để vào thư mục `mvp`.

*(Bạn cũng có thể mở file `scanner_mvp.py` và sửa tên file ở dòng cuối cùng: `scan_document_to_pdf("image.png", "scanned_result.pdf")` thành tên file ảnh của bạn)*

## 5. Chạy ứng dụng

Bạn có thể trải nghiệm dự án theo 2 cách: qua giao diện web hoặc chạy trực tiếp bằng script.

### Cách 1: Chạy giao diện web bằng Streamlit (Khuyên dùng)

Giao diện web giúp bạn tải ảnh lên và xem trực quan kết quả của từng bước xử lý trong thuật toán (Resize -> Nhị phân hóa -> Dò tìm góc -> Duỗi phẳng -> Xuất PDF).

Từ terminal, hãy chạy lệnh sau:

```bash
streamlit run mvp/app.py
```

Ứng dụng sẽ tự động mở trên trình duyệt của bạn (thường ở địa chỉ `http://localhost:8501`). Tại đây, bạn có thể tải ảnh lên và xem trực tiếp kết quả.

### Cách 2: Chạy trực tiếp script Python

Từ terminal (hoặc command prompt), di chuyển vào thư mục `mvp` và chạy file Python:

```bash
cd mvp
python scanner_mvp.py
```

Nếu thành công, script sẽ in ra:

```text
--- Document Scanner MVP Pipeline ---
Sử dụng hàm: scan_document_to_pdf('input.jpg', 'output.pdf') để chạy thử.
Thành công! Đã lưu tài liệu thành file scanned_result.pdf
```

File PDF kết quả sẽ được tạo ra với tên `scanned_result.pdf` ở cùng thư mục hiện tại.
