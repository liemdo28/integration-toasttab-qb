"""
Double-click file này để mở app — không hiện cửa sổ đen (console).
"""
from pathlib import Path
import importlib.util
import traceback


def _show_error(message: str):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Toast → QuickBooks Sync", message)
        root.destroy()
    except Exception:
        pass


def main():
    app_file = Path(__file__).with_name("toast_qb_app.py")
    try:
        spec = importlib.util.spec_from_file_location("toast_qb_app_local", app_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Không thể load app file: {app_file}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.main()
    except Exception as exc:
        err = (
            f"Không thể mở ứng dụng\n\n"
            f"{exc}\n\n"
            f"{traceback.format_exc()}"
        )
        _show_error(err)


if __name__ == "__main__":
    main()
