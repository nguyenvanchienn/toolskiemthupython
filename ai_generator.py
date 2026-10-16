import os
import re
import ast
import requests
# pyrefly: ignore [missing-import]
import google.generativeai as genai

# ─── Config ───────────────────────────────────────────────────────────────────
def _load_env_file():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

_load_env_file()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL",   "gemini-2.5-flash")

_EXTERNAL_PREFIXES = (
    "requests", "httpx", "aiohttp", "urllib",
    "open", "builtins",
    "subprocess", "os.system", "os.popen",
    "socket", "ssl", "smtplib", "ftplib",
    "sqlite3", "psycopg2", "pymysql", "cx_Oracle",
    "pymongo", "motor", "redis", "elasticsearch",
    "boto3", "botocore", "azure", "google.cloud",
    "kafka", "pika", "celery",
    "pathlib.Path.open", "pathlib.Path.read", "pathlib.Path.write",
    "time.sleep", "datetime.now", "datetime.utcnow",
    "shutil", "tempfile",
)

def get_available_models() -> list[str]:
    if not GEMINI_API_KEY:
        return ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-2.5-pro"]
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        models = genai.list_models()
        return [m.name.replace("models/", "") for m in models if "generateContent" in m.supported_generation_methods]
    except Exception:
        return ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-2.5-pro"]


def _is_external(call_name: str) -> bool:
    return any(call_name == p or call_name.startswith(p + ".") for p in _EXTERNAL_PREFIXES)


# ─── Phần 1: AST summary cho 1 hàm cụ thể ─────────────────────────────────────

def _format_func(fn: dict, module_imports: list = None) -> str:
    module_imports = module_imports or []
    sig_parts = []
    for a in fn.get("args", []):
        if a["name"] in ("self", "cls"):
            continue
        part = a["name"]
        if "type" in a:
            part += f": {a['type']}"
        if "default" in a:
            part += f" = {a['default']}"
        sig_parts.append(part)

    prefix = "async " if fn.get("is_async") else ""
    sig = f"{prefix}def {fn['name']}({', '.join(sig_parts)})"
    if fn.get("return_type"):
        sig += f" -> {fn['return_type']}"

    lines = [sig]
    if fn.get("docstring"):
        lines.append(f"  docstring: {fn['docstring'][:150]}")

    raises_list = fn.get("raises") or []
    if raises_list:
        clean = [r.split("(")[0].strip() for r in raises_list if r.split("(")[0].strip()]
        lines.append(f"  raises: {', '.join(clean)}")
    else:
        lines.append("  raises: (none)")

    returns = fn.get("returns") or []
    if returns:
        lines.append(f"  explicit_returns: {', '.join(returns[:8])}")
    elif fn.get("has_value_return"):
        lines.append("  explicit_returns: <value>")
    else:
        lines.append("  explicit_returns: (none)")
    lines.append(f"  has_value_return: {bool(fn.get('has_value_return'))}")

    all_calls = fn.get("calls") or []
    stdout_calls = {"print", "console.print", "print_step", "print_ok", "print_err", "print_info"}
    if fn.get("name", "").startswith("print") or any(c in stdout_calls or c.endswith(".print") for c in all_calls):
        lines.append("  likely_side_effect: stdout/console output")
    ext_calls = [c for c in all_calls if _is_external(c)]
    int_calls = [c for c in all_calls if not _is_external(c) and ("." in c or len(c) > 4)][:6]

    lines.append(f"  external_calls_MUST_MOCK: {', '.join(ext_calls[:8])}" if ext_calls
                 else "  external_calls: (none)")
    if int_calls:
        lines.append(f"  internal_calls_DO_NOT_MOCK: {', '.join(int_calls)}")

    return "\n".join(lines)


def _find_function_info(ast_info: dict, func_name: str) -> dict:
    for fn in ast_info.get("functions", []):
        if fn["name"] == func_name:
            return fn
    for cls in ast_info.get("classes", []):
        for m in cls.get("methods", []):
            if m["name"] == func_name:
                return m
    return {}


# ─── Phần 2: CFG → liệt kê các đường đi (path) cần test ───────────────────────

def _cfg_paths_text(cfg: dict) -> str:
    """
    Biến CFG (nodes/edges) thành danh sách path dạng text, mỗi path là một
    chuỗi nhãn cạnh (True/False/Loop/Iterate/Done/Exception) từ ENTRY tới EXIT.
    Dùng DFS giới hạn độ sâu để tránh path nổ số mũ với loop lồng nhau.
    """
    if cfg.get("status") != "success":
        return "(Không lấy được CFG — sinh test theo AST summary thông thường.)"

    nodes = {n["id"]: n for n in cfg["nodes"]}
    adj = {}
    for e in cfg["edges"]:
        adj.setdefault(e["from"], []).append(e)

    entry_id = next((n["id"] for n in cfg["nodes"] if n["type"] == "entry"), None)
    exit_id = next((n["id"] for n in cfg["nodes"] if n["type"] == "exit"), None)
    if not entry_id:
        return "(CFG rỗng.)"

    paths = []
    MAX_PATHS = 12
    MAX_STEPS = 25

    def dfs(node_id, trail, edge_labels, visited_loop_back):
        if len(paths) >= MAX_PATHS or len(trail) > MAX_STEPS:
            return
        node_type = nodes.get(node_id, {}).get("type")
        outgoing = adj.get(node_id, [])
        # Điểm cuối của 1 path: chạm EXIT, hoặc node return/raise (không có cạnh ra tiếp —
        # return/raise luôn kết thúc nhánh thực thi ngay tại đó trong _CFGBuilder).
        if node_id == exit_id or (node_type in ("return", "exception") and not outgoing):
            paths.append(list(edge_labels))
            return
        if not outgoing:
            paths.append(list(edge_labels))
            return
        for e in outgoing:
            to = e["to"]
            lbl = e.get("label", "")
            # tránh lặp vô hạn: mỗi back-edge (Loop/Next) chỉ đi 1 lần trong path mẫu
            loop_key = (e["from"], e["to"], lbl)
            if lbl in ("Loop", "Next") and loop_key in visited_loop_back:
                # đại diện cho "thoát loop ngay" — không đi tiếp nhánh lặp lại nữa
                continue
            new_visited = visited_loop_back | ({loop_key} if lbl in ("Loop", "Next") else set())
            dfs(to, trail + [to], edge_labels + ([lbl] if lbl else []), new_visited)

    dfs(entry_id, [entry_id], [], set())

    if not paths:
        return "(CFG không có node return/exit — kiểm tra lại.)"
    if len(paths) == 1 and not paths[0]:
        return "(Hàm tuyến tính, chỉ có 1 đường thực thi duy nhất — không có nhánh rẽ.)"

    lines = [f"Tổng số node CFG: {len(nodes)}, số nhánh rẽ độc lập cần test: {len(paths)}"]
    for i, p in enumerate(paths, 1):
        path_desc = " → ".join(p) if p else "(thẳng, không rẽ nhánh)"
        lines.append(f"  PATH {i}: {path_desc}")
    return "\n".join(lines)


def get_cfg_for_function(file_path: str, func_name: str) -> dict:
    from cfg_analyzer import build_cfg
    return build_cfg(file_path, func_name)


# ─── Phần 3: Import injection ──────────────────────────────────────────────────

def _fix_imports(code: str, module_name: str, source_dir: str) -> str:
    code = re.sub(r'^\s*(?:from|import)\s+[<\[{].*?[>\]}].*$', '', code, flags=re.MULTILINE)
    code = re.sub(
        rf'^\s*(?:from\s+{re.escape(module_name)}\s+import\s+\*|import\s+{re.escape(module_name)})\s*$',
        '', code, flags=re.MULTILINE,
    )
    code = re.sub(r'^\s*import\s+(sys|os|asyncio|unittest|requests)\s*$', '', code, flags=re.MULTILINE)
    code = re.sub(r'^\s*from\s+unittest(?:\.\w+)*\s+import\s+.*$', '', code, flags=re.MULTILINE)

    header = (
        "import sys\n"
        "import os\n"
        "import asyncio\n"
        "import unittest\n"
        "from unittest.mock import patch, MagicMock, mock_open, AsyncMock, call, PropertyMock\n"
        f"sys.path.insert(0, r'{source_dir}')\n"
        f"from {module_name} import *\n"
        "\n"
    )
    return header + code.strip() + "\n"


# ─── Phần 4: Prompt — sinh test cho TOÀN FILE hoặc 1 HÀM, luôn kèm CFG paths ──

def _build_prompt_whole_file(ast_info: dict, ast_summary: str) -> str:
    module_name = os.path.splitext(os.path.basename(ast_info.get("_file_path", "module.py")))[0]
    source_code = ast_info["source_code"]
    class_name = f"Test{module_name.capitalize()}"
    return _PROMPT_TEMPLATE.format(
        ast_summary=ast_summary,
        cfg_section="(Sinh test cho toàn file — xem CFG riêng từng hàm trong AST summary trên nếu cần.)",
        source_code=source_code,
        class_name=class_name,
    )


def _build_prompt_single_function(file_path: str, func_name: str, fn_info: dict,
                                   ast_summary_one: str, source_code: str) -> str:
    module_name = os.path.splitext(os.path.basename(file_path))[0]
    class_name = f"Test{func_name.capitalize()}"
    cfg = get_cfg_for_function(file_path, func_name)
    cfg_text = _cfg_paths_text(cfg)
    cfg_section = (
        f"Hàm mục tiêu: {func_name}\n"
        f"Control Flow Graph (CFG) — mỗi PATH dưới đây BẮT BUỘC phải có ít nhất 1 test case tương ứng:\n"
        f"{cfg_text}\n"
    )
    return _PROMPT_TEMPLATE.format(
        ast_summary=ast_summary_one,
        cfg_section=cfg_section,
        source_code=source_code,
        class_name=class_name,
    )


_PROMPT_TEMPLATE = r"""
Role: Senior Python QA Engineer.
Task: Generate a complete unit test suite for the provided source code.

OUTPUT CONTRACT (STRICT):

Return ONLY valid Python code.

Start exactly with: class {class_name}(unittest.TestCase):

NO markdown, NO comments, NO explanations, NO imports, NO placeholders.

Every test must contain real, executable Arrange-Act-Assert code.

CORE RULES:

Source of Truth: Source code > CFG > AST. Never infer behavior from names.

For every if/elif/else branch, generate at least one test case that executes that branch.

Mocking Policy: - Mock ONLY external dependencies (IO, Network, Database, OS calls).

NEVER mock internal methods/logic.

Use unittest.mock.patch or mock_open.

For file operations, always specify encoding='utf-8'.

Execution Trace: - Before writing assertions, manually trace the execution path.

Inputs MUST satisfy all conditions for the targeted branch.

Assert based on observable side effects (mock calls, state change) or explicit return values.

Exception Handling: Only use assertRaises if the source code explicitly contains a raise statement.

Coverage Targets: 100% statement and branch coverage. Cover every CFG path.

DECISION TABLE:

Pure functions: Assert return value.

Branching/Validation: Test valid, invalid, boundary, and empty inputs.

IO/Prints: Patch sys.stdout or builtins.open and assert calls/content.

Side effects: Assert the state change or external mock call.

Void functions: Assert side effects, not return values.

INPUTS:

AST Summary: {ast_summary}

CFG Coverage Target: {cfg_section}

Source Code: {source_code}

Generate the test suite now.

"""


# ─── Phần 5: AST summary helpers (toàn file / 1 hàm) ──────────────────────────

def _build_ast_summary_whole(ast_info: dict) -> str:
    lines = []
    module_imports = ast_info.get("imports", [])
    if module_imports:
        lines.append("=== IMPORTS ===")
        lines.extend(f"  {imp}" for imp in module_imports)
    if ast_info.get("functions"):
        lines.append("\n=== TOP-LEVEL FUNCTIONS ===")
        for fn in ast_info["functions"]:
            lines.append(_format_func(fn, module_imports))
            lines.append("")
    if ast_info.get("classes"):
        lines.append("\n=== CLASSES ===")
        for cls in ast_info["classes"]:
            bases = f"({', '.join(cls['bases'])})" if cls.get("bases") else ""
            lines.append(f"class {cls['name']}{bases}:")
            if cls.get("docstring"):
                lines.append(f"  docstring: {cls['docstring'][:150]}")
            for m in cls.get("methods", []):
                lines.append(_format_func(m, module_imports))
                lines.append("")
    return "\n".join(lines)


# ─── Phần 6: Entry points ──────────────────────────────────────────────────────

def generate_test_cases(file_path: str, model_name: str = None) -> dict:
    """Sinh test cho TOÀN FILE (mọi hàm/class)."""
    try:
        from analyzer import extract_ast_summary
        ast_info = extract_ast_summary(file_path)
        ast_info["_file_path"] = file_path

        module_name = os.path.splitext(os.path.basename(file_path))[0]
        source_dir = os.path.abspath(os.path.dirname(file_path))

        ast_summary = _build_ast_summary_whole(ast_info)
        prompt = _build_prompt_whole_file(ast_info, ast_summary)

        return _call_gemini_and_clean(prompt, module_name, source_dir, file_path, model_name)

    except FileNotFoundError:
        return {"status": "error", "message": f"Không tìm thấy file: {file_path}"}
    except SyntaxError as e:
        return {"status": "error", "message": f"File nguồn có lỗi cú pháp: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Lỗi không xác định: {type(e).__name__}: {e}"}


def generate_test_for_function(file_path: str, func_name: str, model_name: str = None) -> dict:
    """Sinh test cho 1 HÀM cụ thể, bắt buộc bao phủ mọi PATH trong CFG của hàm đó."""
    try:
        from analyzer import extract_ast_summary
        ast_info = extract_ast_summary(file_path)
        fn_info = _find_function_info(ast_info, func_name)
        if not fn_info:
            return {"status": "error", "message": f"Không tìm thấy hàm '{func_name}' trong file."}

        ast_summary_one = _format_func(fn_info, ast_info.get("imports", []))
        module_name = os.path.splitext(os.path.basename(file_path))[0]
        source_dir = os.path.abspath(os.path.dirname(file_path))

        prompt = _build_prompt_single_function(
            file_path, func_name, fn_info, ast_summary_one, ast_info["source_code"]
        )
        return _call_gemini_and_clean(prompt, module_name, source_dir, file_path, model_name)

    except FileNotFoundError:
        return {"status": "error", "message": f"Không tìm thấy file: {file_path}"}
    except SyntaxError as e:
        return {"status": "error", "message": f"File nguồn có lỗi cú pháp: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Lỗi không xác định: {type(e).__name__}: {e}"}


def _call_gemini_and_clean(prompt: str, module_name: str, source_dir: str, file_path: str, model_name: str = None) -> dict:
    if not GEMINI_API_KEY:
        return {"status": "error", "message": "Thiếu biến môi trường GEMINI_API_KEY."}

    genai.configure(api_key=GEMINI_API_KEY)
    
    system_instruction = (
        "Return only valid Python unittest code. "
        "No markdown, no explanations, no summaries, no placeholder comments."
    )
    
    try:
        model = genai.GenerativeModel(
            model_name=model_name or GEMINI_MODEL,
            system_instruction=system_instruction,
            generation_config={"temperature": 0.0, "max_output_tokens": 8192}
        )
        response = model.generate_content(prompt, stream=True)
        generated_text = ""
        for chunk in response:
            try:
                if chunk.text:
                    generated_text += chunk.text
            except Exception:
                pass
        
        # DEBUG: Log raw output
        with open(os.path.join(source_dir, "raw_gemini_output.txt"), "w", encoding="utf-8") as debug_file:
            debug_file.write(generated_text)
            
    except Exception as e:
        return {"status": "error", "message": f"Lỗi gọi Gemini API: {e}"}

    if not generated_text:
        return {"status": "error", "message": "Gemini trả về kết quả rỗng."}

    final_code, validation_error = _clean_and_validate_response(
        generated_text, module_name, source_dir, file_path
    )
    if not validation_error:
        return {"status": "success", "test_code": final_code}

    retry_prompt = (
        prompt
        + "\n\nYour previous answer was invalid and would fail pytest.\n"
        + f"Validation error: {validation_error}\n"
        + "Rewrite the test code from scratch. Pay attention to functions that print "
          "or have no explicit return value: test stdout/side effects, not a string return.\n"
    )
    
    try:
        response = model.generate_content(retry_prompt)
        generated_text = response.text
    except Exception as e:
        return {"status": "error", "message": validation_error}

    final_code, retry_error = _clean_and_validate_response(
        generated_text, module_name, source_dir, file_path
    )
    if retry_error:
        return {"status": "error", "message": retry_error}
    return {"status": "success", "test_code": final_code}


def _clean_and_validate_response(generated_text: str, module_name: str, source_dir: str, file_path: str):
    cleaned = _clean_generated_test_code(generated_text)
    if not cleaned.strip():
        return "", "Cannot extract Python test code from AI output."

    final_code = _fix_imports(cleaned, module_name, source_dir)
    validation_error = _validate_generated_tests(final_code, file_path)
    return final_code, validation_error


def _clean_generated_test_code(generated_text: str) -> str:
    cleaned = re.sub(r'```(?:python)?\s*', '', generated_text, flags=re.IGNORECASE)
    cleaned = re.sub(r'```\s*', '', cleaned)

    match = re.search(
        r'^(class\s+\w+\s*\(\s*unittest\.TestCase\s*\)\s*:)',
        cleaned,
        flags=re.MULTILINE,
    )
    if not match:
        match = re.search(r'^(class\s+\w+\s*\([^)]*\)\s*:)', cleaned, flags=re.MULTILINE)
    if match:
        cleaned = cleaned[match.start():]

    # Removed truncation logic to prevent accidental chopping of code

    # We no longer strip TODOs or ... here so that they get caught by validation properly
    # instead of creating empty function bodies that cause SyntaxError.

    return cleaned.strip()


def _validate_generated_tests(code: str, source_file_path: str = None) -> str | None:
    banned_tokens = [
        "## Summary",
        "Code Overview:",
        "Testing Rules:",
        "Additional tests covering",
        "TODO",
    ]
    lowered = code.lower()
    for token in banned_tokens:
        if token.lower() in lowered:
            return f"AI output contains non-test text: {token}"

    try:
        tree = compile(code, "<generated_tests>", "exec", ast.PyCF_ONLY_AST)
    except SyntaxError as e:
        return f"AI output is not valid Python: line {e.lineno}: {e.msg}"

    test_methods = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    if not test_methods:
        return "AI output does not contain any test_ methods."
    semantic_error = _validate_no_value_return_assertions(tree, source_file_path)
    if semantic_error:
        return semantic_error
    return None


def _validate_no_value_return_assertions(test_tree: ast.AST, source_file_path: str = None) -> str | None:
    if not source_file_path or not os.path.exists(source_file_path):
        return None

    no_value_return_funcs = _source_functions_without_value_return(source_file_path)
    if not no_value_return_funcs:
        return None

    assigned_calls = {}
    for node in ast.walk(test_tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func_name = _called_function_name(node.value)
            if func_name in no_value_return_funcs:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned_calls[target.id] = func_name

    for node in ast.walk(test_tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_assert_equal_call(node):
            continue
        if len(node.args) < 2:
            continue

        left, right = node.args[0], node.args[1]
        func_name = None
        if isinstance(left, ast.Name):
            func_name = assigned_calls.get(left.id)
        elif isinstance(left, ast.Call):
            called = _called_function_name(left)
            if called in no_value_return_funcs:
                func_name = called

        if func_name and not _is_none_literal(right):
            return (
                f"Generated test asserts a non-None return value for '{func_name}', "
                "but the source function has no explicit return value. Test stdout, "
                "mock calls, or assertIsNone instead."
            )
    return None


def _source_functions_without_value_return(source_file_path: str) -> set:
    with open(source_file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    funcs = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_value_return = any(
            isinstance(child, ast.Return) and child.value is not None
            for child in ast.walk(node)
        )
        if not has_value_return:
            funcs.add(node.name)
    return funcs


def _called_function_name(call_node: ast.Call) -> str:
    func = call_node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_assert_equal_call(call_node: ast.Call) -> bool:
    func = call_node.func
    return isinstance(func, ast.Attribute) and func.attr in {"assertEqual", "assertEquals"}


def _is_none_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None
