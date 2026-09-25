"""
===============================================================================
Desktop Document Translator GUI Application Module
===============================================================================

Purpose:
    Provides a desktop GUI application using CustomTkinter for translating
    documents (PDF, DOCX, PPTX, XLSX, images, Markdown, text, HTML) and raw text
    snippets. Integrates with Gemini AI models and Google Translate, featuring
    asynchronous background process isolation, streaming log console, and
    persistent configuration management.

Usage:
    # Launch GUI directly:
    python backend/main.py

Prerequisites & Dependencies:
    - CustomTkinter (pip install customtkinter)
    - Python 3.10+
===============================================================================
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import queue
import sys
import threading
from tkinter import filedialog, messagebox
from typing import Any, Optional

import customtkinter as ctk

# Ensure backend directory and project root are discoverable in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(backend_dir)
for p in [project_root, backend_dir, current_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from backend.engines.translator import GeminiTranslator, GoogleTransTranslator
except ImportError:
    try:
        from backend.engines import GeminiTranslator, GoogleTransTranslator
    except ImportError:
        from backend.translator import GeminiTranslator, GoogleTransTranslator

try:
    from backend.desktop.gui_wrapper import run_translation_process
except ImportError:
    try:
        from backend.gui_wrapper import run_translation_process
    except ImportError:
        from gui_wrapper import run_translation_process

try:
    from backend.core.logger_config import setup_logging
except ImportError:
    try:
        from backend.core import setup_logging
    except ImportError:
        try:
            from backend.logger_config import setup_logging
        except ImportError:
            setup_logging = lambda name: logging.getLogger(name)

logger = setup_logging("gui_app")

# =============================================================================
# ENVIRONMENT & THEME CONFIGURATION
# =============================================================================

ctk.set_appearance_mode("System")  # Options: "System", "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue", "green", "dark-blue"


# =============================================================================
# DESKTOP APPLICATION CONTROLLER CLASS
# =============================================================================

class App(ctk.CTk):
    """
    Primary CustomTkinter Desktop Application Window.
    Controls settings persistence, file selection, background multiprocessing,
    live progress bars, and log console streaming.
    """

    def __init__(self) -> None:
        super().__init__()

        # --- Window Setup ---
        self.title("Document Translator")
        self.geometry("700x800")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Reactive UI Variables ---
        self.file_path: Optional[str] = None
        self.target_lang = ctk.StringVar(value="Japanese")
        self.provider_var = ctk.StringVar(value="Gemini 3.1 Pro Preview")
        self.api_key_var = ctk.StringVar(value="")

        self.process: Optional[multiprocessing.Process] = None
        self.log_queue: Optional[Any] = None
        self.result_queue: Optional[Any] = None

        # --- Initialization ---
        self.load_settings()
        self._create_widgets()

    # -------------------------------------------------------------------------
    # Configuration & State Persistence
    # -------------------------------------------------------------------------

    def load_settings(self) -> None:
        """Loads API key from Secret Manager, preferences from GCS / OS temp cache."""
        try:
            from backend.core.cloud_secrets import get_gemini_api_key
            api_key = get_gemini_api_key()
            if api_key:
                self.api_key_var.set(api_key)
        except Exception as err:
            logger.debug(f"Failed to resolve API key from Secret Manager: {err}")

        try:
            from backend.core.cloud_storage import load_cloud_state
            data = load_cloud_state("document-translator/config.json", default={})
            if isinstance(data, dict):
                if "provider" in data:
                    self.provider_var.set(data["provider"])
                if "target_lang" in data:
                    self.target_lang.set(data["target_lang"])
                if "api_key" in data and not self.api_key_var.get():
                    self.api_key_var.set(data["api_key"])
        except Exception as err:
            logger.warning(f"Failed to load cloud settings: {err}")

    def save_settings(self) -> None:
        """Persists current user preferences to GCS and OS temp cache (never local workspace)."""
        data = {
            "provider": self.provider_var.get(),
            "target_lang": self.target_lang.get(),
        }
        try:
            from backend.core.cloud_storage import save_cloud_state
            save_cloud_state("document-translator/config.json", data)
        except Exception as err:
            logger.warning(f"Failed to persist settings to cloud: {err}")

    # -------------------------------------------------------------------------
    # UI Construction & Widget Assembly
    # -------------------------------------------------------------------------

    def _create_widgets(self) -> None:
        """Builds header, shared settings panel, and tabbed document/text view."""
        # 1. Header Banner
        self.header = ctk.CTkLabel(self, text="Document Translator", font=ctk.CTkFont(size=24, weight="bold"))
        self.header.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")

        # 2. Settings Panel
        self.settings_frame = ctk.CTkFrame(self)
        self.settings_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        self.settings_frame.grid_columnconfigure(1, weight=1)

        # Target Language Selector
        self.lbl_lang = ctk.CTkLabel(self.settings_frame, text="Target Language:")
        self.lbl_lang.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        languages = [
            "Japanese", "English", "Chinese", "Spanish", "French",
            "German", "Korean", "Italian", "Portuguese", "Russian"
        ]
        self.combo_lang = ctk.CTkComboBox(self.settings_frame, values=languages, variable=self.target_lang)
        self.combo_lang.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        # Provider / Model Selector
        self.lbl_provider = ctk.CTkLabel(self.settings_frame, text="Model:")
        self.lbl_provider.grid(row=1, column=0, padx=10, pady=5, sticky="w")

        default_models = [
            "Gemini 3.1 Pro Preview",
            "Gemini 3.1 Flash-Lite Preview",
            "Gemini 3 Flash",
            "Gemini 2.5 Pro",
            "Gemini 2.5 Flash",
            "Gemini 2.5 Flash-Lite",
            "Google Translate (Free)",
        ]
        self.combo_provider = ctk.CTkComboBox(
            self.settings_frame,
            values=default_models,
            command=self.update_api_field_state,
            variable=self.provider_var,
        )
        self.combo_provider.grid(row=1, column=1, padx=(10, 5), pady=5, sticky="ew")

        # Refresh Models Button
        self.btn_refresh = ctk.CTkButton(self.settings_frame, text="↻", width=30, command=self.refresh_models)
        self.btn_refresh.grid(row=1, column=2, padx=(0, 10), pady=10)

        # API Key Field
        self.lbl_api_key = ctk.CTkLabel(self.settings_frame, text="API Key:")
        self.lbl_api_key.grid(row=2, column=0, padx=10, pady=5, sticky="w")

        self.entry_api_key = ctk.CTkEntry(
            self.settings_frame,
            placeholder_text="Enter your Gemini API Key",
            textvariable=self.api_key_var,
            show="*",
        )
        self.entry_api_key.grid(row=2, column=1, padx=(10, 5), pady=5, sticky="ew")

        # 3. Tabview (Document vs Text)
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.tabview.add("Document")
        self.tabview.add("Text")

        self._setup_document_tab()
        self._setup_text_tab()
        self.update_api_field_state()

    def _setup_document_tab(self) -> None:
        """Constructs widgets inside the Document translation tab."""
        tab = self.tabview.tab("Document")
        tab.grid_columnconfigure(0, weight=1)

        # File Selection Frame
        self.file_frame = ctk.CTkFrame(tab)
        self.file_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.file_frame.grid_columnconfigure(1, weight=1)

        self.btn_select_file = ctk.CTkButton(self.file_frame, text="Select File", command=self.select_file)
        self.btn_select_file.grid(row=0, column=0, padx=10, pady=10)

        self.lbl_file_path = ctk.CTkLabel(self.file_frame, text="No file selected", text_color="gray")
        self.lbl_file_path.grid(row=0, column=1, padx=10, pady=10, sticky="w")

        # Action Buttons
        self.btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.btn_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.btn_frame.grid_columnconfigure(0, weight=1)
        self.btn_frame.grid_columnconfigure(1, weight=1)

        self.btn_translate = ctk.CTkButton(
            self.btn_frame,
            text="Translate Document",
            command=self.start_translation,
            height=40,
        )
        self.btn_translate.grid(row=0, column=0, padx=5, pady=0, sticky="ew")

        self.btn_stop = ctk.CTkButton(
            self.btn_frame,
            text="Stop",
            command=self.stop_translation,
            height=40,
            fg_color="#D32F2F",
            hover_color="#B71C1C",
            state="disabled",
        )
        self.btn_stop.grid(row=0, column=1, padx=5, pady=0, sticky="ew")

        # Status & Progress Bar
        self.progress_bar = ctk.CTkProgressBar(tab)
        self.progress_bar.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        self.progress_bar.set(0)

        self.lbl_status = ctk.CTkLabel(tab, text="Ready", text_color="gray")
        self.lbl_status.grid(row=3, column=0, padx=10, pady=5)

        # Real-time Log Console
        self.log_console = ctk.CTkTextbox(tab, height=150, font=("Consolas", 12))
        self.log_console.grid(row=4, column=0, padx=10, pady=10, sticky="nsew")
        self.log_console.insert("0.0", "--- Ready ---\n")
        self.log_console.configure(state="disabled")

    def _setup_text_tab(self) -> None:
        """Constructs widgets inside the plain text translation tab."""
        tab = self.tabview.tab("Text")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_rowconfigure(4, weight=1)

        # Source Text Box
        self.lbl_source = ctk.CTkLabel(tab, text="Source Text:", font=ctk.CTkFont(weight="bold"))
        self.lbl_source.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")

        self.txt_source = ctk.CTkTextbox(tab, height=200, font=("Inter", 13))
        self.txt_source.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nsew")
        self.txt_source.insert("0.0", "Enter text to translate here...")

        # Translate Trigger
        self.btn_translate_text = ctk.CTkButton(
            tab,
            text="Translate Now",
            command=self.start_text_translation,
            height=40,
            font=ctk.CTkFont(weight="bold"),
        )
        self.btn_translate_text.grid(row=2, column=0, padx=10, pady=10)

        # Target Text Box
        self.lbl_target = ctk.CTkLabel(tab, text="Translation:", font=ctk.CTkFont(weight="bold"))
        self.lbl_target.grid(row=3, column=0, padx=10, pady=(10, 0), sticky="w")

        self.txt_target = ctk.CTkTextbox(tab, height=200, font=("Inter", 13), fg_color="#2B2B2B")
        self.txt_target.grid(row=4, column=0, padx=10, pady=(5, 10), sticky="nsew")
        self.txt_target.configure(state="disabled")

    # -------------------------------------------------------------------------
    # Model Discovery & Dynamic Population
    # -------------------------------------------------------------------------

    def refresh_models(self) -> None:
        """Queries the Gemini API for updated models in a background thread."""
        api_key = self.api_key_var.get().strip()
        if not api_key:
            try:
                from backend.core.cloud_secrets import get_gemini_api_key
                resolved = get_gemini_api_key()
                if resolved:
                    api_key = resolved
                    self.api_key_var.set(resolved)
            except Exception:
                pass

        if not api_key:
            messagebox.showwarning("Warning", "Please enter an API Key first.")
            return

        self.btn_refresh.configure(state="disabled", text="...")

        def _fetch() -> None:
            try:
                models = GeminiTranslator.list_available_models(api_key)
                if models:
                    model_names = [m["name"] if isinstance(m, dict) else str(m) for m in models]
                    new_values = model_names + ["Google Translate (Free)"]
                    self.after(0, lambda: self._update_combo_values(new_values))
                else:
                    self.after(0, lambda: messagebox.showerror("Error", "No models found or invalid API key."))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to fetch models: {exc}"))
            finally:
                self.after(0, lambda: self.btn_refresh.configure(state="normal", text="↻"))

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_combo_values(self, values: list[str]) -> None:
        """Applies newly fetched model list to the combobox widget."""
        self.combo_provider.configure(values=values)
        if self.provider_var.get() not in values:
            self.provider_var.set(values[0])
        messagebox.showinfo("Success", f"Found {len(values) - 1} Gemini models.")

    def update_api_field_state(self, choice: Optional[str] = None) -> None:
        """Enables/disables the API key input based on the chosen translation provider."""
        selection = self.combo_provider.get()
        if "Google" in selection:
            self.entry_api_key.configure(state="disabled")
        else:
            self.entry_api_key.configure(state="normal")

    # -------------------------------------------------------------------------
    # Document Translation Process Lifecycle
    # -------------------------------------------------------------------------

    def select_file(self) -> None:
        """Displays open file dialog and records selected document path."""
        filename = filedialog.askopenfilename(filetypes=[
            ("All Supported Documents", "*.pptx *.ppt *.xlsx *.xls *.docx *.pdf *.png *.jpg *.jpeg *.webp *.txt *.md *.csv *.json *.html *.htm"),
            ("PDF Documents", "*.pdf"),
            ("Images", "*.png *.jpg *.jpeg *.webp"),
            ("Word Files", "*.docx"),
            ("PowerPoint Files", "*.pptx *.ppt"),
            ("Excel Files", "*.xlsx *.xls"),
            ("Text & Markdown", "*.txt *.md *.csv *.json *.html *.htm"),
        ])
        if filename:
            self.file_path = filename
            self.lbl_file_path.configure(text=os.path.basename(filename), text_color="white")
            self.lbl_status.configure(text="File selected. Ready to translate.")
            self.log_message(f"Selected file: {filename}")

    def log_message(self, message: str) -> None:
        """Appends a log message safely to the console widget."""
        self.after(0, lambda: self._append_log(message))

    def _append_log(self, message: str) -> None:
        self.log_console.configure(state="normal")
        self.log_console.insert("end", f"{message}\n")
        self.log_console.see("end")
        self.log_console.configure(state="disabled")

    def start_translation(self) -> None:
        """Validates settings and launches isolated worker process for document translation."""
        self.save_settings()

        if not self.file_path:
            messagebox.showerror("Error", "Please select a document file first.")
            return

        provider_selection = self.combo_provider.get()
        api_key = self.api_key_var.get().strip()
        if not api_key:
            try:
                from backend.core.cloud_secrets import get_gemini_api_key
                resolved = get_gemini_api_key()
                if resolved:
                    api_key = resolved
                    self.api_key_var.set(resolved)
            except Exception:
                pass

        if "Google" not in provider_selection and not api_key:
            messagebox.showerror("Error", "Gemini provider requires an API Key.")
            return

        # UI State transition
        self.btn_translate.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.lbl_status.configure(text="Translating... Please wait.", text_color="yellow")
        self.log_message(f"Starting translation with {provider_selection}...")

        # Multiprocessing Setup
        self.log_queue = multiprocessing.Queue()
        self.result_queue = multiprocessing.Queue()

        self.process = multiprocessing.Process(
            target=run_translation_process,
            args=(
                self.file_path,
                self.target_lang.get(),
                provider_selection,
                api_key,
                self.log_queue,
                self.result_queue,
            ),
        )
        self.process.start()
        self.after(100, self.check_queues)

    def stop_translation(self) -> None:
        """Terminates active translation worker process upon user request."""
        if self.process and self.process.is_alive():
            self.log_message("Force stopping translation process...")
            self.btn_stop.configure(text="Stopping...", state="disabled")
            self.update_idletasks()

            self.process.terminate()
            self.process.join()
            self.on_translation_cancelled()

    def check_queues(self) -> None:
        """Polls IPC queues for streaming log messages and final success/error signals."""
        # Drain log queue
        if self.log_queue:
            try:
                while True:
                    record = self.log_queue.get_nowait()
                    if record[0] == "LOG":
                        self._append_log(record[1])
            except queue.Empty:
                pass

        # Check result status
        if self.result_queue:
            try:
                result = self.result_queue.get_nowait()
                if result[0] == "SUCCESS":
                    self.on_translation_success(result[1], result[2] if len(result) > 2 else "needs_review", result[3] if len(result) > 3 else "")
                    return
                elif result[0] == "ERROR":
                    self.on_translation_error(result[1])
                    return
            except queue.Empty:
                pass

        # Check for abnormal worker termination
        if self.process and not self.process.is_alive():
            self.progress_bar.stop()
            exit_code = self.process.exitcode
            if exit_code != 0:
                self.log_message(f"Process ended unexpectedly (Exit Code: {exit_code})")
                self._reset_ui()
                self.lbl_status.configure(text="Process stopped.", text_color="red")
            return

        if self.process and self.process.is_alive():
            self.after(100, self.check_queues)

    def on_translation_success(self, output_path: str, quality_status: str = "needs_review", report_path: str = "") -> None:
        """Handles successful translation completion."""
        self._reset_ui()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(1.0)
        label = "Passed quality checks" if quality_status == "passed" else "Needs review"
        self.lbl_status.configure(text=f"{label}: {os.path.basename(output_path)}", text_color="green" if quality_status == "passed" else "orange")
        messagebox.showinfo(label, f"File saved to:\n{output_path}\n\nQuality report:\n{report_path}")

    def on_translation_error(self, error_msg: str) -> None:
        """Handles translation failure and displays error message."""
        self._reset_ui()
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Error occurred.", text_color="red")
        messagebox.showerror("Translation Error", f"An error occurred:\n{error_msg}")

    def on_translation_cancelled(self) -> None:
        """Resets UI after user cancels translation."""
        self._reset_ui()
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Translation cancelled.", text_color="orange")
        self.log_message("Translation cancelled by user (Force Stop).")

    # -------------------------------------------------------------------------
    # Text Snippet Translation Lifecycle
    # -------------------------------------------------------------------------

    def start_text_translation(self) -> None:
        """Translates plain text snippet asynchronously in a lightweight background thread."""
        source_text = self.txt_source.get("0.0", "end").strip()
        if not source_text or source_text == "Enter text to translate here...":
            return

        provider_selection = self.combo_provider.get()
        api_key = self.api_key_var.get().strip()
        if not api_key:
            try:
                from backend.core.cloud_secrets import get_gemini_api_key
                resolved = get_gemini_api_key()
                if resolved:
                    api_key = resolved
                    self.api_key_var.set(resolved)
            except Exception:
                pass
        target_lang = self.target_lang.get()

        if "Google" not in provider_selection and not api_key:
            messagebox.showerror("Error", "Gemini provider requires an API Key.")
            return

        self.btn_translate_text.configure(state="disabled", text="Translating...")
        self.txt_target.configure(state="normal")
        self.txt_target.delete("0.0", "end")
        self.txt_target.insert("0.0", "Translating...")
        self.txt_target.configure(state="disabled")

        def _do_translation() -> None:
            try:
                if "Google" in provider_selection:
                    translator: Any = GoogleTransTranslator(target_lang=target_lang)
                else:
                    translator = GeminiTranslator(
                        api_key=api_key,
                        target_lang=target_lang,
                        model_name=provider_selection,
                    )
                result = translator.translate_text(source_text)
                self.after(0, lambda: self._show_text_result(result))
            except Exception as exc:
                self.after(0, lambda: self._show_text_result(f"Error: {exc}"))

        threading.Thread(target=_do_translation, daemon=True).start()

    def _show_text_result(self, result: str) -> None:
        """Presents translated text snippet in the target text widget."""
        self.btn_translate_text.configure(state="normal", text="Translate Text")
        self.txt_target.configure(state="normal")
        self.txt_target.delete("0.0", "end")
        self.txt_target.insert("0.0", result)
        self.txt_target.configure(state="disabled")

    def _reset_ui(self) -> None:
        """Restores action buttons to their default resting state."""
        self.btn_translate.configure(state="normal")
        self.btn_stop.configure(state="disabled", text="Stop")
        self.progress_bar.stop()


# =============================================================================
# APPLICATION ENTRYPOINT
# =============================================================================

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = App()
    app.mainloop()
