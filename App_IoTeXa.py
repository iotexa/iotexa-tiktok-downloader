import os
import re
import sys
import shutil
import queue
import threading
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import yt_dlp


TIKTOK_RE = re.compile(r"^https?://(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/", re.IGNORECASE)


class IoTeXaTikTokDownloader:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("IoTeXa - TikTok Downloader")
        self.root.geometry("780x360")
        self.root.resizable(False, False)
        self.root.configure(bg="#ffffff")

        self.output_folder = Path.cwd()
        self.is_busy = False

        self.ui_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

        self._setup_style()
        self._build_ui()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_ui_queue()

    # ----------------- UI -----------------

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg_main = "#ffffff"
        bg_card = "#f5f5f5"
        fg_text = "#222222"
        accent = "#ff9800"

        style.configure("Main.TFrame", background=bg_main)
        style.configure("Card.TFrame", background=bg_card)

        style.configure("TLabel", background=bg_card, foreground=fg_text, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=bg_card, foreground="#666666", font=("Segoe UI", 9))
        style.configure("Subtitle.TLabel", background=bg_main, foreground="#777777", font=("Segoe UI", 10))

        style.configure("TButton", padding=6, font=("Segoe UI", 9))
        style.configure("Accent.TButton", padding=9, font=("Segoe UI", 10, "bold"))

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#dddddd",
            bordercolor="#dddddd",
            background=accent,
            lightcolor=accent,
            darkcolor=accent,
        )

    def _build_ui(self):
        # Header
        header = ttk.Frame(self.root, style="Main.TFrame", padding=(16, 10))
        header.pack(fill="x")

        logo = tk.Frame(header, bg="#ffffff")
        logo.pack(side="left", anchor="w")

        tk.Label(logo, text="IoT", fg="#ff9800", bg="#ffffff", font=("Segoe UI", 24, "bold")).pack(side="left")
        tk.Label(logo, text="eXa", fg="#000000", bg="#ffffff", font=("Segoe UI", 24, "bold")).pack(side="left")

        ttk.Label(
            header,
            text="TikTok-only • Descarga y salida MP4 compatible",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(16, 0), anchor="s")

        # Card
        card = ttk.Frame(self.root, style="Card.TFrame", padding=16)
        card.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        ttk.Label(card, text="URL del video TikTok:").grid(row=0, column=0, columnspan=3, sticky="w")

        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(card, textvariable=self.url_var, width=95)
        self.url_entry.grid(row=1, column=0, columnspan=3, pady=6, sticky="we")

        ttk.Label(card, text="Carpeta de destino:").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.folder_label_var = tk.StringVar(value=str(self.output_folder))
        ttk.Label(card, textvariable=self.folder_label_var, foreground="#888888").grid(
            row=3, column=0, columnspan=2, sticky="w"
        )

        self.choose_folder_btn = ttk.Button(card, text="Elegir carpeta...", command=self.choose_folder)
        self.choose_folder_btn.grid(row=3, column=2, sticky="e")

        # Opciones (minimal, pero útiles)
        opts = tk.Frame(card, bg="#f5f5f5")
        opts.grid(row=4, column=0, columnspan=3, sticky="we", pady=(10, 0))

        self.open_folder_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            opts,
            text="Abrir carpeta al finalizar",
            variable=self.open_folder_var,
            bg="#f5f5f5",
        ).pack(anchor="w")

        # Botones
        btns = tk.Frame(card, bg="#f5f5f5")
        btns.grid(row=5, column=0, columnspan=3, sticky="we", pady=(12, 0))

        self.download_btn = ttk.Button(btns, text="Descargar", style="Accent.TButton", command=self.on_download)
        self.download_btn.pack(side="left", padx=(0, 10))

        self.clear_btn = ttk.Button(btns, text="Limpiar", command=self.clear_form)
        self.clear_btn.pack(side="left")

        # Progreso y estado
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(card, maximum=100, variable=self.progress_var)
        self.progress.grid(row=6, column=0, columnspan=3, sticky="we", pady=(12, 0))

        self.status_var = tk.StringVar(value="Listo.")
        ttk.Label(card, textvariable=self.status_var, style="Status.TLabel").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        card.columnconfigure(0, weight=1)
        self.url_entry.focus_set()

    # ----------------- Queue UI (Thread-safe) -----------------

    def _post(self, kind: str, payload: object = None):
        self.ui_queue.put((kind, payload))

    def _poll_ui_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()

                if kind == "status":
                    self.status_var.set(str(payload))

                elif kind == "progress":
                    try:
                        self.progress_var.set(float(payload))
                    except Exception:
                        pass

                elif kind == "done":
                    self._set_busy(False)
                    final_path = str(payload)
                    messagebox.showinfo("Completado", f"Listo ✅\nArchivo final:\n{final_path}")
                    if self.open_folder_var.get():
                        self._open_folder(Path(final_path).parent)

                elif kind == "error":
                    self._set_busy(False)
                    messagebox.showerror("Error", str(payload))

        except queue.Empty:
            pass

        self.root.after(120, self._poll_ui_queue)

    def _set_busy(self, busy: bool):
        self.is_busy = busy
        state = "disabled" if busy else "normal"
        self.download_btn.config(state=state)
        self.clear_btn.config(state=state if busy else "normal")
        self.choose_folder_btn.config(state=state)
        self.url_entry.config(state=state)

    # ----------------- Actions -----------------

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=str(self.output_folder))
        if folder:
            self.output_folder = Path(folder)
            self.folder_label_var.set(str(self.output_folder))

    def clear_form(self):
        if self.is_busy:
            return
        self.url_var.set("")
        self.progress_var.set(0.0)
        self.status_var.set("Listo.")
        self.url_entry.focus_set()

    def on_close(self):
        if self.is_busy:
            if not messagebox.askyesno("Salir", "Hay una descarga en curso.\n¿Seguro que quieres salir?"):
                return
        self.root.destroy()

    def on_download(self):
        if self.is_busy:
            return

        url = self.url_var.get().strip()
        if not url or not TIKTOK_RE.match(url):
            messagebox.showwarning(
                "URL inválida",
                "Pega un link válido de TikTok.\nEj: https://www.tiktok.com/@usuario/video/...",
            )
            return

        self._set_busy(True)
        self.progress_var.set(0.0)
        self.status_var.set("Iniciando...")

        t = threading.Thread(target=self._worker_download, args=(url,), daemon=True)
        t.start()

    # ----------------- Worker -----------------

    def _worker_download(self, url: str):
        """
        Descarga TikTok (single video) y entrega SIEMPRE un MP4 compatible:
        - Intenta bajar MP4 si existe.
        - Si el resultado viene en HEVC/H.265, convierte a H.264 MP4 usando FFmpeg.
        """
        try:
            self._post("status", "Conectando a TikTok...")

            # Nombre seguro + id. Evita caracteres raros en Windows.
            outtmpl = str(self.output_folder / "tiktok_%(id)s_%(title).120B.%(ext)s")

            # Preferimos MP4 si hay. Si no, baja el mejor disponible.
            ydl_opts = {
                "outtmpl": outtmpl,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "retries": 5,
                "socket_timeout": 30,
                "windowsfilenames": True,
                "progress_hooks": [self._progress_hook],
                "format": "best[ext=mp4]/best",
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_path = Path(ydl.prepare_filename(info))

            if not downloaded_path.exists():
                downloaded_path = self._find_latest_file(self.output_folder)

            if not downloaded_path or not downloaded_path.exists():
                raise RuntimeError("No se pudo determinar el archivo descargado.")

            self._post("status", f"Descargado: {downloaded_path.name}")

            # Convertir si hace falta (HEVC -> H.264 MP4)
            ffmpeg = self._find_ffmpeg()
            if not ffmpeg:
                raise RuntimeError(
                    "Falta FFmpeg para garantizar MP4 compatible.\n\n"
                    "Solución PRO: pon ffmpeg.exe (y ffprobe.exe) en la MISMA carpeta que tu .exe.\n"
                    "O instala FFmpeg en Windows (PATH)."
                )

            vcodec = self._probe_video_codec(downloaded_path, ffmpeg)
            if vcodec and ("hevc" in vcodec.lower() or "h265" in vcodec.lower()):
                self._post("status", "HEVC detectado → Convirtiendo a MP4 H.264...")
                final_path = self._convert_to_h264(downloaded_path, ffmpeg)
            else:
                # Si no pudimos detectar codec, igual podemos asegurar compatibilidad convirtiendo.
                # Pero para no re-encodear sin necesidad, solo convertimos si detectamos HEVC.
                # (Si quieres “siempre convertir”, te lo cambio.)
                final_path = downloaded_path

                # Si el contenedor no es .mp4, lo pasamos a mp4 H.264 igual (por compatibilidad).
                if final_path.suffix.lower() != ".mp4":
                    self._post("status", "No es MP4 → Convirtiendo a MP4 H.264...")
                    final_path = self._convert_to_h264(downloaded_path, ffmpeg)

            self._post("progress", 100.0)
            self._post("done", str(final_path))

        except Exception as e:
            self._post("error", e)

    # ----------------- yt-dlp hooks -----------------

    def _progress_hook(self, d: dict):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0

            percent = 0.0
            if total:
                percent = (downloaded * 100.0) / float(total)
                percent = max(0.0, min(100.0, percent))
                self._post("progress", percent)

            speed = d.get("speed")
            eta = d.get("eta")

            msg = f"Descargando... {percent:.1f}%"
            if speed:
                msg += f" | Vel.: {self._format_speed(speed)}"
            if eta is not None:
                msg += f" | ETA: {self._format_eta(eta)}"
            self._post("status", msg)

        elif d.get("status") == "finished":
            self._post("status", "Descarga finalizada. Preparando...")

    @staticmethod
    def _format_speed(bps: float) -> str:
        kb = bps / 1024.0
        if kb < 1024:
            return f"{kb:.1f} KB/s"
        return f"{kb/1024.0:.2f} MB/s"

    @staticmethod
    def _format_eta(sec: int) -> str:
        s = int(sec)
        m = s // 60
        r = s % 60
        h = m // 60
        m = m % 60
        return f"{h}:{m:02d}:{r:02d}" if h else f"{m}:{r:02d}"

    # ----------------- FFmpeg helpers -----------------

    def _find_ffmpeg(self) -> str | None:
        # 1) PATH (si el usuario lo instaló)
        ff = shutil.which("ffmpeg")
        if ff:
            return ff

        # 2) MISMA carpeta del .exe (esto es lo que quieres para tu PRO)
        exe_dir = Path(sys.executable).resolve().parent
        cand = exe_dir / "ffmpeg.exe"
        if cand.exists():
            return str(cand)

        # 3) Carpeta del .py (modo dev)
        script_dir = Path(__file__).resolve().parent
        cand2 = script_dir / "ffmpeg.exe"
        if cand2.exists():
            return str(cand2)

        return None

    def _probe_video_codec(self, path: Path, ffmpeg_path: str) -> str | None:
        # Preferimos ffprobe (si lo tienes junto al exe)
        ffprobe = shutil.which("ffprobe")

        if not ffprobe:
            exe_dir = Path(sys.executable).resolve().parent
            cand = exe_dir / "ffprobe.exe"
            if cand.exists():
                ffprobe = str(cand)

        if not ffprobe:
            return None

        try:
            cmd = [
                ffprobe,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=nw=1:nk=1",
                str(path),
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            return out.strip() if out else None
        except Exception:
            return None

    def _convert_to_h264(self, src: Path, ffmpeg_path: str) -> Path:
        """
        Convierte a MP4 H.264 (muy buena calidad) y deja el original intacto.
        CRF 18 = alta calidad (mínima pérdida perceptible normalmente).
        """
        dst = src.with_name(src.stem + "_MP4_H264.mp4")
        if dst.exists():
            try:
                dst.unlink()
            except Exception:
                pass

        cmd = [
            ffmpeg_path,
            "-y",
            "-i", str(src),
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(dst),
        ]

        self._post("status", "Convirtiendo… (puede tardar)")
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0:
            tail = (p.stderr or "")[-900:]
            raise RuntimeError("FFmpeg falló al convertir.\n\n" + tail)

        return dst

    # ----------------- misc -----------------

    def _find_latest_file(self, folder: Path) -> Path | None:
        files = sorted(folder.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None

    def _open_folder(self, folder: Path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # type: ignore
            elif sys.platform == "darwin":
                subprocess.run(["open", str(folder)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = IoTeXaTikTokDownloader(root)
    root.mainloop()
