import argparse
import os
import sys
import glob

# ── Kiểm tra rich ──────────────────────────────────────────────────────────
try:
    # pyrefly: ignore [missing-import]
    from rich.console import Console
    # pyrefly: ignore [missing-import]
    from rich.panel import Panel
    # pyrefly: ignore [missing-import]
    from rich.table import Table
    # pyrefly: ignore [missing-import]
    from rich.prompt import Prompt, Confirm
    # pyrefly: ignore [missing-import]
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    # pyrefly: ignore [missing-import]
    from rich.text import Text
    # pyrefly: ignore [missing-import]
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console() if HAS_RICH else None


# ── Tiện ích in ────────────────────────────────────────────────────────────
def print_banner():
    if HAS_RICH:
        console.print()
        console.print(Panel.fit(
            "[bold cyan]  AutoTest Tool[/bold cyan]  [dim]v2.0[/dim]\n"
            "[dim]Tự động sinh & chạy unit test bằng AI (Gemini)[/dim]",
            border_style="cyan", padding=(0, 2)
        ))
        console.print()
    else:
        print("\n=== AutoTest Tool v2.0 ===")
        print("Tự động sinh & chạy unit test bằng AI (Gemini)\n")


def print_step(icon, msg, color="yellow"):
    if HAS_RICH:
        console.print(f"[{color}]{icon}[/{color}] {msg}")
    else:
        print(f"{icon} {msg}")


def print_ok(msg):
    print_step("✓", msg, "green")


def print_err(msg):
    print_step("✗", msg, "red")


def print_info(msg):
    print_step("•", msg, "cyan")


# ── Hàm chọn file ──────────────────────────────────────────────────────────
def pick_file_interactive():
    """Hiển thị danh sách file .py trong thư mục và để user chọn."""
    # Loại trừ các file hệ thống của tool
    SYSTEM_FILES = {
        "main.py", "api.py", "analyzer.py", "ai_generator.py",
        "executor.py", "reporter.py", "cfg_analyzer.py",
        "fix.py", "list_models.py", "cfg_viewer.html"
    }

    py_files = [
        f for f in glob.glob("*.py")
        if os.path.basename(f) not in SYSTEM_FILES
        and not os.path.basename(f).startswith("test_")
        and not os.path.basename(f).startswith("uploaded_")
        and not os.path.basename(f).startswith("cfg_test_")
    ]

    # Thêm cả file trong thư mục con phổ biến
    for subdir in ["src", "app", "lib", "code", "source"]:
        if os.path.isdir(subdir):
            py_files += glob.glob(f"{subdir}/*.py")

    if not py_files:
        if HAS_RICH:
            console.print(
                "[yellow]  Không tìm thấy file .py nào trong thư mục hiện tại.[/yellow]\n"
                "[dim]Hãy chạy tool từ thư mục chứa code của bạn,[/dim]\n"
                "[dim]hoặc dùng: [/dim][cyan]python main.py path/to/your_file.py[/cyan]"
            )
        else:
            print("Không tìm thấy file .py nào. Dùng: python main.py <file.py>")
        return None

    if HAS_RICH:
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Tên file", style="white")
        table.add_column("Kích thước", style="dim", justify="right")

        for i, f in enumerate(py_files, 1):
            size = os.path.getsize(f)
            size_str = f"{size:,} bytes" if size < 10_000 else f"{size//1024} KB"
            table.add_row(str(i), f, size_str)

        console.print(table)
        console.print()

        choice = Prompt.ask(
            "[cyan]Nhập số thứ tự file cần test[/cyan] [dim](hoặc nhập đường dẫn trực tiếp)[/dim]",
            default="1"
        )
    else:
        for i, f in enumerate(py_files, 1):
            print(f"  {i}. {f}")
        choice = input("\nChọn số thứ tự (hoặc đường dẫn): ").strip() or "1"

    # Phân giải lựa chọn
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(py_files):
            return py_files[idx]
        print_err("Số thứ tự không hợp lệ.")
        return None
    elif os.path.exists(choice):
        return choice
    else:
        print_err(f"Không tìm thấy file: {choice}")
        return None


# ── Luồng CLI chính ─────────────────────────────────────────────────────────
def run_cli(target_file: str, model_name: str = None):
    from analyzer import analyze_python_file
    from ai_generator import generate_test_cases
    from executor import run_test_file
    from reporter import generate_report

    print_banner()

    # ── Bước 1: Kiểm tra file ──
    if not os.path.exists(target_file):
        print_err(f"Không tìm thấy file: '{target_file}'")
        return

    print_info(f"File mục tiêu: [bold]{target_file}[/bold]" if HAS_RICH else f"File: {target_file}")
    console.print() if HAS_RICH else print()

    # ── Bước 2: Phân tích tĩnh ──
    print_step("①", "Phân tích cấu trúc code...", "yellow")

    result = analyze_python_file(target_file)

    if result["status"] == "success":
        fn = result["functions_count"]
        cl = result["classes_count"]
        if HAS_RICH:
            console.print(
                f"   [green]✓[/green] Tìm thấy [bold]{fn}[/bold] hàm"
                f"{f' và [bold]{cl}[/bold] lớp' if cl else ''}"
                f"  [dim]— Không có lỗi cú pháp[/dim]"
            )
        else:
            print(f"   ✓ {fn} hàm, {cl} lớp — OK")
    elif result["status"] == "syntax_error":
        print_err(f"Lỗi cú pháp: {result['message']}")
        if HAS_RICH:
            console.print("[dim]  Hãy sửa lỗi cú pháp trước khi chạy tool.[/dim]")
        return
    else:
        print_err(f"Lỗi phân tích: {result['message']}")
        return

    console.print() if HAS_RICH else print()

    # ── Bước 3: AI sinh test ──
    print_step("②", "Đang gọi AI sinh test case...  [dim](có thể mất 30-90 giây)[/dim]" if HAS_RICH
               else "Đang gọi AI sinh test case (30–90 giây)...", "yellow")

    if HAS_RICH:
        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            transient=True, console=console
        ) as progress:
            task = progress.add_task("  AI đang suy nghĩ...", total=None)
            ai_result = generate_test_cases(target_file, model_name)
    else:
        ai_result = generate_test_cases(target_file, model_name)

    if ai_result["status"] != "success":
        print_err(f"AI gặp lỗi: {ai_result['message']}")
        if "Thiếu biến môi trường" in ai_result["message"] or "Lỗi gọi Gemini" in ai_result["message"]:
            if HAS_RICH:
                console.print(Panel(
                    "[bold]Cần cấu hình Gemini API Key trước:[/bold]\n"
                    "  Trong PowerShell/Terminal, chạy:\n"
                    "  [cyan]$env:GEMINI_API_KEY=\"your_api_key_here\"[/cyan]\n"
                    "  Sau đó chạy lại tool.",
                    title="Hướng dẫn", border_style="yellow"
                ))
            else:
                print("Cần cấu hình biến môi trường GEMINI_API_KEY trước khi chạy tool.")
        return

    test_file_name = f"test_{os.path.basename(target_file)}"
    with open(test_file_name, "w", encoding="utf-8") as f:
        f.write(ai_result["test_code"])

    # Đếm số test được sinh
    test_count = ai_result["test_code"].count("def test_")
    print_ok(f"Đã sinh [bold]{test_count}[/bold] test case  →  {test_file_name}" if HAS_RICH
             else f"   ✓ Sinh {test_count} test case → {test_file_name}")

    console.print() if HAS_RICH else print()

    # ── Bước 4: Chạy test ──
    print_step("③", "Đang chạy test với pytest...", "yellow")
    exec_result = run_test_file(test_file_name, source_file_path=target_file)

    status = exec_result["status"]
    output = exec_result.get("output", "")

    # Đếm PASSED / FAILED từ output
    passed_n = output.count(" PASSED")
    failed_n = output.count(" FAILED") + output.count(" ERROR")

    if status == "passed":
        if HAS_RICH:
            console.print(Panel.fit(
                f"[bold green] TẤT CẢ PASS — {passed_n}/{passed_n} test[/bold green]\n"
                "[dim]Code của bạn vượt qua toàn bộ test case![/dim]",
                border_style="green"
            ))
        else:
            print(f"   PASS {passed_n}/{passed_n} test")
    elif status == "failed":
        if HAS_RICH:
            console.print(Panel.fit(
                f"[bold red] CÓ TEST THẤT BẠI — {failed_n} lỗi / {passed_n + failed_n} test[/bold red]\n"
                "[dim]Xem chi tiết trong báo cáo HTML bên dưới.[/dim]",
                border_style="red"
            ))
        else:
            print(f"   FAIL {failed_n}/{passed_n + failed_n} test")
    else:
        print_err("Lỗi khi chạy pytest (có thể do code test bị lỗi cú pháp)")

    # Chi tiết output (rút gọn)
    if HAS_RICH:
        console.print()
        lines = output.strip().splitlines()
        # Chỉ hiển thị các dòng PASSED/FAILED và summary
        relevant = [l for l in lines if any(k in l for k in ["PASSED", "FAILED", "ERROR", "passed", "failed", "error", "==="])]
        short_out = "\n".join(relevant[-20:])  # tối đa 20 dòng
        if short_out:
            console.print(f"[dim]{short_out}[/dim]")
    else:
        print(output[-2000:] if len(output) > 2000 else output)

    if exec_result.get("error_log"):
        if HAS_RICH:
            console.print(f"[dim red]{exec_result['error_log'][-500:]}[/dim red]")
        else:
            print(exec_result["error_log"][-500:])

    console.print() if HAS_RICH else print()

    # ── Bước 5: Tạo báo cáo ──
    print_step("④", "Đang tạo báo cáo HTML...", "yellow")
    try:
        html_path = generate_report(target_file, test_file_name, exec_result)
        abs_path = os.path.abspath(html_path)
        print_ok(f"Báo cáo: [link=file://{abs_path}]{abs_path}[/link]" if HAS_RICH
                 else f"   ✓ Báo cáo: {abs_path}")

        # Hỏi có muốn mở báo cáo không
        if HAS_RICH:
            console.print()
            open_it = Confirm.ask("  [cyan]Mở báo cáo trong trình duyệt?[/cyan]", default=True)
        else:
            open_it = input("Mở báo cáo? (Y/n): ").strip().lower() != "n"

        if open_it:
            import webbrowser
            webbrowser.open(f"file://{abs_path}")

    except Exception as e:
        print_err(f"Không thể tạo báo cáo: {e}")

    console.print() if HAS_RICH else print()


# ── Menu chính ───────────────────────────────────────────────────────────────
def main_menu():
    """Hiển thị menu chính khi không có tham số."""
    print_banner()

    if HAS_RICH:
        console.print("[bold]Chọn chế độ:[/bold]\n")
        console.print("  [cyan bold]1[/cyan bold]  CLI — Phân tích file Python (nhanh, không cần server)")
        console.print("  [cyan bold]2[/cyan bold]  Web — Giao diện đồ thị CFG + test trên trình duyệt")
        console.print("  [cyan bold]3[/cyan bold]  Thoát\n")
        choice = Prompt.ask("[cyan]Lựa chọn[/cyan]", choices=["1", "2", "3"], default="1")
    else:
        print("1. CLI - phân tích file Python")
        print("2. Web - giao diện trình duyệt")
        print("3. Thoát")
        choice = input("Chọn (1-3): ").strip() or "1"

    if choice == "3":
        print_info("Tạm biệt!")
        return

    if choice == "2":
        if HAS_RICH:
            console.print()
            console.print("[green]Đang khởi động web server...[/green]")
            console.print("[dim]Truy cập:[/dim] [cyan bold]http://127.0.0.1:8000[/cyan bold]")
            console.print("[dim]CFG viewer:[/dim] [cyan]http://127.0.0.1:8000/cfg[/cyan]")
            console.print("[dim]Nhấn Ctrl+C để dừng[/dim]\n")
        else:
            print("Khởi động server tại http://127.0.0.1:8000 ...")
        # pyrefly: ignore [missing-import]
        import uvicorn
        uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
        return

    # Chế độ CLI
    console.print() if HAS_RICH else print()

    if HAS_RICH:
        console.print("[bold]File Python cần test:[/bold]")
        console.print("[dim]Danh sách file trong thư mục hiện tại:[/dim]\n")
    else:
        print("Chọn file để test:")

    target = pick_file_interactive()
    if target:
        console.print() if HAS_RICH else print()
        
        if HAS_RICH:
            console.print("[bold]Đang tải danh sách model Gemini...[/bold]")
        else:
            print("Đang tải danh sách model Gemini...")
            
        from ai_generator import get_available_models
        models = get_available_models()
        
        if HAS_RICH:
            console.print("\n[bold]Chọn model Gemini:[/bold]")
            for i, m in enumerate(models, 1):
                desc = " (Mặc định)" if m == "gemini-2.5-flash" else ""
                console.print(f"  [cyan bold]{i}[/cyan bold]  {m}{desc}")
                
            choices = [str(i) for i in range(1, len(models)+1)]
            default_choice = str(models.index("gemini-2.5-flash") + 1) if "gemini-2.5-flash" in models else "1"
            m_choice = Prompt.ask("[cyan]Lựa chọn model[/cyan]", choices=choices, default=default_choice)
        else:
            print("\nChọn model Gemini:")
            for i, m in enumerate(models, 1):
                desc = " (Mặc định)" if m == "gemini-2.5-flash" else ""
                print(f"{i}. {m}{desc}")
                
            default_choice = str(models.index("gemini-2.5-flash") + 1) if "gemini-2.5-flash" in models else "1"
            m_choice = input(f"Chọn (1-{len(models)}) [{default_choice}]: ").strip() or default_choice
            
        selected_model = models[int(m_choice) - 1]
        
        console.print() if HAS_RICH else print()
        run_cli(target, selected_model)


# ── Entry point ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="AutoTest Tool — Tự động sinh unit test bằng AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ví dụ:\n  python main.py              # Chạy menu tương tác\n  python main.py mycode.py    # Phân tích file trực tiếp\n  python main.py --web        # Khởi động web server"
    )
    parser.add_argument("file_path", nargs="?", help="Đường dẫn file .py cần test")
    parser.add_argument("--web", action="store_true", help="Khởi động Web UI")
    args = parser.parse_args()

    if args.web:
        if HAS_RICH:
            console.print("[green]Khởi động web server tại http://127.0.0.1:8000 ...[/green]")
            console.print("[dim]CFG viewer: http://127.0.0.1:8000/cfg[/dim]")
            console.print("[dim]Nhấn Ctrl+C để dừng[/dim]\n")
        # pyrefly: ignore [missing-import]
        import uvicorn
        uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
    elif args.file_path:
        print_banner()
        run_cli(args.file_path)
    else:
        main_menu()


if __name__ == "__main__":
    main()
