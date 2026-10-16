# AutoTest Tool — AI & CFG-Driven Unit Test Generator

Hệ thống ứng dụng **Trí tuệ nhân tạo (AI/LLM)** kết hợp phân tích **Đồ thị luồng điều khiển (Control Flow Graph - CFG)** và **Cây cú pháp trừu tượng (AST)** để tự động sinh unit test, thực thi kiểm thử và đo lường độ bao phủ mã nguồn (Branch & Statement Coverage) cho các dự án Python.

---

## 🚀 Tính năng nổi bật

- **Phân tích cú pháp tĩnh (AST) & Dựng CFG**:
  - Quét cấu trúc dự án Python và phân tích chi tiết các hàm, class, tham số và phụ thuộc.
  - Xây dựng đồ thị luồng điều khiển (Control Flow Graph - CFG) trực quan, xác định các nhánh rẽ nhánh (True/False, Loop, Exception) và tính toán độ phức tạp Cyclomatic (Cyclomatic Complexity).
- **Sinh Unit Test tự động bằng AI (LLM)**:
  - Tích hợp mô hình AI mạnh mẽ (**Google Gemini 2.5 Flash / Pro** và **Ollama / Qwen2.5-Coder** chạy local).
  - Tự động nhận diện các hàm bên ngoài (requests, database, OS, file I/O...) để tự động sinh mock/patch phù hợp.
  - Sinh test case bao phủ đầy đủ các biên kiểm thử và các nhánh rẽ của CFG.
- **Thực thi kiểm thử & Đo lường Code Coverage**:
  - Tự động chạy bộ kiểm thử bằng `pytest` trong môi trường cô lập.
  - Sử dụng `coverage.py` với cờ `--branch` để đo chính xác cả **Statement Coverage** và **Branch Coverage**.
- **Báo cáo trực quan (Reporting & Visualization)**:
  - Giao diện Web tương tác trực quan hóa đồ thị CFG với thư viện **Vis.js Network**.
  - Xuất báo cáo HTML và JSON chi tiết kết quả test (Pass/Fail) và các dòng/nhánh mã nguồn chưa được kiểm thử.
- **Hỗ trợ cả Web Dashboard & CLI**:
  - Giao diện Web hiện đại (FastAPI backend + Vanilla JS/CSS Dark theme).
  - Giao diện dòng lệnh CLI chuyên nghiệp với thư viện `Rich` (bảng thông tin, tiến trình sinh test sinh động).

---

## 🛠️ Công nghệ sử dụng

- **Ngôn ngữ chính**: Python 3.10+
- **Backend & API**: FastAPI, Uvicorn, Pydantic
- **AI & LLM**: Google Generative AI (Gemini SDK), Ollama API
- **Testing & Coverage**: Pytest, Coverage.py (Branch Coverage)
- **Frontend & Visualization**: HTML5, Vanilla CSS3, JavaScript (ES6+), Vis.js Network
- **CLI Utilities**: Rich, Argparse

---

## 📦 Cài đặt & Hướng dẫn sử dụng

### 1. Cài đặt môi trường
```bash
# Clone repository
git clone https://github.com/nguyenvanchienn/toolskiemthupython.git
cd toolskiemthupython

# Tạo và kích hoạt môi trường ảo (khuyến nghị)
python -m venv venv
# Trên Windows:
venv\Scripts\activate
# Trên Linux/macOS:
source venv/bin/activate

# Cài đặt các thư viện cần thiết
pip install -r requirements.txt
```

### 2. Cấu hình API Key
Tạo file `.env` hoặc thiết lập biến môi trường:
```bash
GEMINI_API_KEY="your_google_gemini_api_key_here"
# (Tùy chọn) Cấu hình Ollama nếu chạy AI local:
USE_OLLAMA="true"
OLLAMA_API_URL="http://localhost:11434/api/generate"
OLLAMA_MODEL="qwen2.5-coder:7b"
```

### 3. Khởi chạy ứng dụng

#### Cách 1: Giao diện Web Dashboard (Khuyến nghị)
```bash
python -m uvicorn api:app --reload --port 8000
```
Truy cập trình duyệt tại: `http://localhost:8000` để sử dụng giao diện trực quan hóa CFG và sinh test.

#### Cách 2: Giao diện Dòng lệnh (CLI)
```bash
python main.py
```
Hoặc chỉ định đường dẫn project cần kiểm thử:
```bash
python main.py --path /duong/dan/project/python
```

---

## 👥 Tác giả
- **Nguyễn Văn Chiến**
- GitHub: [@nguyenvanchienn](https://github.com/nguyenvanchienn)
