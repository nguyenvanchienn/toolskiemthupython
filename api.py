import os
import shutil
import uuid
import zipfile
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, UploadFile, File
# pyrefly: ignore [missing-import]
from fastapi.responses import HTMLResponse
# pyrefly: ignore [missing-import]
from fastapi.staticfiles import StaticFiles
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
# pyrefly: ignore [missing-import]
from project_scanner import scan_project
# pyrefly: ignore [missing-import]
from analyzer import extract_ast_summary
# pyrefly: ignore [missing-import]
from cfg_analyzer import build_cfg
from ai_generator import generate_test_for_function
from executor import run_test_file
from reporter import generate_report

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.makedirs(os.path.join(BASE_DIR, "reports"), exist_ok=True)
app.mount("/reports", StaticFiles(directory=os.path.join(BASE_DIR, "reports")), name="reports")

os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

UPLOADS_DIR = os.path.join(BASE_DIR, "uploads_projects")
os.makedirs(UPLOADS_DIR, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def read_index():
    index_path = os.path.join(BASE_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse(
            f"<h1>Không tìm thấy index.html</h1><p>Đã tìm tại: {index_path}</p>",
            status_code=500,
        )
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()

class FolderReq(BaseModel): folder_path: str
class FileReq(BaseModel):
    file_path: str
    model: str = "gemini-2.5-flash"
class FuncReq(BaseModel):
    file_path: str
    func_name: str
    model: str = "gemini-2.5-flash"
class DeleteReq(BaseModel):
    project_id: str
    file_path: str

@app.post("/api/scan-project")
async def scan_project_api(req: FolderReq):
    return scan_project(req.folder_path)


def _safe_extract_zip(zip_path: str, dest_dir: str):
    """Giải nén an toàn, chặn Zip Slip (path traversal qua ../ hoặc đường dẫn tuyệt đối)."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_path = os.path.join(dest_dir, member.filename)
            abs_dest = os.path.abspath(dest_dir)
            abs_member = os.path.abspath(member_path)
            if not (abs_member == abs_dest or abs_member.startswith(abs_dest + os.sep)):
                raise ValueError(f"File không an toàn trong zip: {member.filename}")
        zf.extractall(dest_dir)


@app.post("/api/upload-zip")
async def upload_zip(file: UploadFile = File(...)):
    filename = file.filename.lower()
    if not (filename.endswith(".zip") or filename.endswith(".py")):
        return {"status": "error", "message": "Chỉ hỗ trợ file .zip hoặc .py"}

    project_id = uuid.uuid4().hex[:12]
    project_dir = os.path.join(UPLOADS_DIR, project_id)
    os.makedirs(project_dir, exist_ok=True)
    file_path = os.path.join(project_dir, file.filename)

    try:
        content = await file.read()
        # Giới hạn 50MB để tránh upload quá lớn làm treo server
        if len(content) > 50 * 1024 * 1024:
            return {"status": "error", "message": "File quá lớn (tối đa 50MB)."}

        with open(file_path, "wb") as f:
            f.write(content)

        if filename.endswith(".zip"):
            _safe_extract_zip(file_path, project_dir)
            try:
                os.remove(file_path)
            except OSError:
                pass

            # Nếu zip chỉ chứa 1 thư mục gốc duy nhất, dùng thư mục đó làm root để tránh
            # lồng thêm 1 cấp không cần thiết (ví dụ zip "myproject.zip" chứa "myproject/...")
            entries = [e for e in os.listdir(project_dir) if not e.startswith("__MACOSX")]
            if len(entries) == 1 and os.path.isdir(os.path.join(project_dir, entries[0])):
                project_dir = os.path.join(project_dir, entries[0])

        result = scan_project(project_dir)
        
        if result.get("file_count", 0) == 0:
            import shutil
            shutil.rmtree(project_dir, ignore_errors=True)
            return {"status": "error", "message": "File tải lên không chứa code Python nào hợp lệ!"}
            
        result["project_id"] = project_id
        result["root_dir"] = project_dir
        return result

    except zipfile.BadZipFile:
        return {"status": "error", "message": "File zip bị lỗi hoặc không hợp lệ."}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Lỗi xử lý file: {e}"}

@app.post("/api/file-detail")
async def file_detail(req: FileReq):
    return extract_ast_summary(req.file_path)

@app.post("/api/cfg")
async def get_cfg(req: FuncReq):
    return build_cfg(req.file_path, req.func_name)

@app.post("/api/test-file")
async def test_file_api(req: FileReq):
    from ai_generator import generate_test_cases
    ai_result = generate_test_cases(req.file_path, req.model)
    if ai_result["status"] != "success":
        return ai_result

    base = os.path.splitext(os.path.basename(req.file_path))[0]
    test_file = os.path.join(os.path.dirname(req.file_path), f"test_{base}.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write(ai_result["test_code"])

    exec_result = run_test_file(test_file, source_file_path=req.file_path)
    html_path = generate_report(req.file_path, test_file, exec_result)

    return {
        "status": "success",
        "test_code": ai_result["test_code"],
        "exec_result": exec_result,
        "report_url": f"/{html_path}",
    }

@app.post("/api/test-function")
async def test_function(req: FuncReq):
    ai_result = generate_test_for_function(req.file_path, req.func_name, req.model)
    if ai_result["status"] != "success":
        return ai_result
        
    test_file = os.path.join(os.path.dirname(req.file_path), f"test_{req.func_name}_{os.path.basename(req.file_path)}")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write(ai_result["test_code"])
        
    exec_result = run_test_file(test_file, source_file_path=req.file_path)
    html_path = generate_report(req.file_path, test_file, exec_result, func_name=req.func_name)
    
    return {
        "status": "success",
        "test_code": ai_result["test_code"],
        "exec_result": exec_result,
        "report_url": f"/{html_path}"
    }

@app.post("/api/delete-file")
async def delete_file(req: DeleteReq):
    try:
        if os.path.exists(req.file_path):
            os.remove(req.file_path)
            
        project_dir = os.path.join(UPLOADS_DIR, req.project_id)
        # Nếu đang ở trong project zip, ta tìm lại thư mục gốc
        if not os.path.exists(project_dir):
            # Fallback nếu đường dẫn là thư mục thực tế
            project_dir = os.path.dirname(req.file_path)
            
        result = scan_project(project_dir)
        result["project_id"] = req.project_id
        result["root_dir"] = project_dir
        return result
    except Exception as e:
        return {"status": "error", "message": f"Không thể xóa file: {e}"}

@app.get("/api/models")
async def get_models():
    from ai_generator import get_available_models
    return {"status": "success", "models": get_available_models()}

if __name__ == "__main__":
    # pyrefly: ignore [missing-import]
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000)