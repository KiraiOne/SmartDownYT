#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SmartDownYT — ыңғайлы GUI интерфейсі бар YouTube-тен видео үзінділерін жүктейтін бағдарлама.
`С.Б. Біріншіден ікпейды екен егер мұндай һүйнә бар болса, ал мұндай һүйнә жүз пайыз бар.
`Айтқым келгені, ойбай сұмдық нәрсе ойлап таптым деген ойда салмаймын, іштерің өртенбесін һүйнә нәрсені сонша әдемілеп һүйнә емес нәрсе сияқты қылдырып жазып қойыпты деп!
`Ойыма не келеді, нені пайдалы әрі қызық деп ойлағанның бәрін жасап сала берем, оның үстіне СЕКСен пайызы ЖИ-мен жасалған
`С.Б. бұрын бәрін орысша жасағам, қазір просто соларды қазақшаға аударып қайта салып жатырмын, аяқ астынан қайтадан патриот болып кеттім
`С.Б. бұл бөлік бүккіл жерде болады!
`С.Б. С.Б. - деген "Скрипт бойынша"



Мүмкіндіктері:
  * сілтемені қоясыз — атауы, ұзақтығы және қолжетімді ажыратылымдықтары жүктеледі;
  * екі жылжытқыш ролик таңдалған кесіндіні кеседі (уақытты қолмен енгізуге де болады);
  * жүктеудің екі режимі:
      QUICK — тек қажетті үзіндіні бірден жүктеу (yt-dlp download_ranges)
      SAFE  — толық роликті жүктеп, ffmpeg арқылы өзіміз кесеміз (QUICK істен шықса — автоматты түрде қосылады)
  * тек дыбысын (mp3) бөлек жүктеп алуға болады;
  * прогресс/жылдамдық/ETA және барлық әрекеттер журналы (лог).

Қажетті кітапханалар мен құралдар:
    pip install yt-dlp
    ffmpeg жүйенің PATH жолында болуы тиіс:
        Windows -> winget install Gyan.FFmpeg
        macOS   -> brew install ffmpeg
        Linux   -> sudo apt install ffmpeg

Іске қосу:
    python smartdownyt.py

---
автор: kirai (KiraiSpace)
kirai.space
"""

import os
import re
import sys
import glob
import queue
import shutil
import subprocess
import tempfile
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import yt_dlp
    from yt_dlp.utils import download_range_func
except ImportError:
    print("yt-dlp табылмады. Орнату үшін: pip install yt-dlp")
    sys.exit(1)


APP_NAME = "SmartDownYT"
APP_AUTHOR = "kirai.kz / KiraiSpace"


# --------------------------------------------------------------------------- #
#  Көмекші функциялар
# --------------------------------------------------------------------------- #

def sec_to_hms(total_sec: float) -> str:
    """1234 -> '00:20:34'"""
    total_sec = int(max(0, total_sec))
    hh, rest = divmod(total_sec, 3600)
    mm, ss = divmod(rest, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def hms_to_sec(raw: str) -> int:
    """'01:23:45' / '23:45' / '45' -> секундтар. Мәтін қате болса -> ValueError."""
    raw = raw.strip().replace(",", ":").replace(".", ":")
    if not raw:
        raise ValueError("бос жол")
    chunks = [c for c in raw.split(":") if c != ""]
    if len(chunks) > 3 or not all(c.isdigit() for c in chunks):
        raise ValueError("бұл уақыт форматына ұқсамайды")
    nums = [int(c) for c in chunks]
    while len(nums) < 3:
        nums.insert(0, 0)
    hh, mm, ss = nums
    return hh * 3600 + mm * 60 + ss


def clean_filename(raw: str) -> str:
    """Windows/ext4 қолдамайтын таңбаларды файл атауынан тазалау."""
    raw = re.sub(r'[\\/:*?"<>|\n\r\t]', "_", raw)
    return raw.strip(" .")[:120] or "kirai_clip"


def find_ffmpeg():
    return shutil.which("ffmpeg")


def hidden_console_kwargs():
    """Windows-та ffmpeg шақырғанда қара консоль терезесі көрінбеуі үшін."""
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def exec_ffmpeg(argv):
    """ffmpeg-ті іске қосу, нәтижесінде (қайтару_коды, stderr_соңы) береді."""
    proc = subprocess.run(
        [find_ffmpeg()] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **hidden_console_kwargs(),
    )
    tail = proc.stderr.decode("utf-8", "replace")
    return proc.returncode, "\n".join(tail.strip().splitlines()[-12:])


# --------------------------------------------------------------------------- #
#  Негізгі терезе
# --------------------------------------------------------------------------- #

class SmartDownYT(tk.Tk):

    QUICK_MODE = "Жылдам (үзіндіні бірден жүктеу)"
    SAFE_MODE = "Сенімді (толық жүктеп, кейін кесу)"

    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — by kirai")
        self.geometry("790x680")
        self.minsize(720, 640)

        # сессия күйі
        self.vid_len = 0            # видео ұзақтығы, сек
        self.meta = None            # yt-dlp ақпараты
        self.res_list = []          # қолжетімді кадр биіктіктерінің тізімі
        self.working = False        # фонда тапсырма орындалып жатыр
        self.abort_flag = False     # пайдаланушы "Бас тарту" батырмасын басты
        self.lock_ui = False        # Scale колбэктеріндегі рекурсиядан қорғау
        self.pipe = queue.Queue()   # фондық ағыннан хабарламалар арнасы
        self.save_dir = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))

        # жылжытқыштар тура өз command функциясынан өзгертілмейді,
        # керісінше айнымалыларға байланған (TclError қатесін болдырмау үшін)
        self.pos_from = tk.DoubleVar(value=0)
        self.pos_to = tk.DoubleVar(value=0)

        self._draw_ui()
        self.after(100, self._drain_pipe)
        self._probe_ffmpeg()

    # ----------------------------- интерфейсті құрастыру ------------------------ #

    def _draw_ui(self):
        pad = dict(padx=10, pady=6)

        link_box = ttk.LabelFrame(self, text="Видеоға сілтеме")
        link_box.pack(fill="x", **pad)

        self.link_var = tk.StringVar()
        link_entry = ttk.Entry(link_box, textvariable=self.link_var)
        link_entry.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=10)
        link_entry.bind("<Return>", lambda e: self.grab_info())

        self.btn_grab = ttk.Button(link_box, text="Ақпаратты жүктеу", command=self.grab_info)
        self.btn_grab.pack(side="left", padx=(0, 10), pady=10)

        self.headline_var = tk.StringVar(value="Әлі ештеңе жүктелген жоқ")
        ttk.Label(self, textvariable=self.headline_var, wraplength=740,
                  font=("TkDefaultFont", 10, "bold")).pack(fill="x", padx=12)

        # --- үзінді ---
        clip_box = ttk.LabelFrame(self, text="Қажетті үзінді")
        clip_box.pack(fill="x", **pad)
        clip_box.columnconfigure(1, weight=1)

        ttk.Label(clip_box, text="Басы").grid(row=0, column=0, padx=(10, 6), pady=(10, 2), sticky="w")
        self.from_slider = ttk.Scale(clip_box, from_=0, to=1, orient="horizontal",
                                     variable=self.pos_from, command=self._on_from_move)
        self.from_slider.grid(row=0, column=1, sticky="ew", pady=(10, 2))
        self.from_txt = tk.StringVar(value="00:00:00")
        entry_from = ttk.Entry(clip_box, textvariable=self.from_txt, width=10, justify="center")
        entry_from.grid(row=0, column=2, padx=10, pady=(10, 2))
        entry_from.bind("<Return>", lambda e: self._on_time_typed("from"))
        entry_from.bind("<FocusOut>", lambda e: self._on_time_typed("from"))

        ttk.Label(clip_box, text="Соңы").grid(row=1, column=0, padx=(10, 6), pady=(2, 10), sticky="w")
        self.to_slider = ttk.Scale(clip_box, from_=0, to=1, orient="horizontal",
                                   variable=self.pos_to, command=self._on_to_move)
        self.to_slider.grid(row=1, column=1, sticky="ew", pady=(2, 10))
        self.to_txt = tk.StringVar(value="00:00:00")
        entry_to = ttk.Entry(clip_box, textvariable=self.to_txt, width=10, justify="center")
        entry_to.grid(row=1, column=2, padx=10, pady=(2, 10))
        entry_to.bind("<Return>", lambda e: self._on_time_typed("to"))
        entry_to.bind("<FocusOut>", lambda e: self._on_time_typed("to"))

        self.clip_len_var = tk.StringVar(value="Үзінді ұзақтығы: 00:00:00")
        ttk.Label(clip_box, textvariable=self.clip_len_var).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 8))

        quick_btns = ttk.Frame(clip_box)
        quick_btns.grid(row=3, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 10))
        ttk.Button(quick_btns, text="Толық видеоны таңдау", command=self._pick_whole).pack(side="left")
        ttk.Button(quick_btns, text="Басын нөлге қою",
                   command=lambda: self._set_from(0)).pack(side="left", padx=6)

        # --- баптаулар ---
        opts_box = ttk.LabelFrame(self, text="Баптаулар")
        opts_box.pack(fill="x", **pad)
        opts_box.columnconfigure(4, weight=1)

        ttk.Label(opts_box, text="Сапасы:").grid(row=0, column=0, padx=(10, 6), pady=(10, 4), sticky="w")
        self.quality_pick = ttk.Combobox(opts_box, state="readonly", width=22,
                                         values=["Ең үздік қолжетімді"])
        self.quality_pick.current(0)
        self.quality_pick.grid(row=0, column=1, pady=(10, 4), sticky="w")

        self.mp3_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts_box, text="Тек дыбыс (mp3)", variable=self.mp3_only,
                        command=self._on_mp3_toggle).grid(row=0, column=2, padx=14, pady=(10, 4))

        self.exact_cut = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts_box, text="Дәл кесу", variable=self.exact_cut)\
            .grid(row=0, column=3, padx=4, pady=(10, 4), sticky="w")

        ttk.Label(opts_box, text="Режим:").grid(row=1, column=0, padx=(10, 6), pady=4, sticky="w")
        self.mode_pick = ttk.Combobox(opts_box, state="readonly", width=34,
                                      values=[self.QUICK_MODE, self.SAFE_MODE])
        self.mode_pick.current(0)
        self.mode_pick.grid(row=1, column=1, columnspan=2, pady=4, sticky="w")

        self.keep_full = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts_box, text="Түпнұсқаны өшірмеу", variable=self.keep_full)\
            .grid(row=1, column=3, padx=4, pady=4, sticky="w")

        ttk.Label(opts_box, text="Сандық:").grid(row=2, column=0, padx=(10, 6), pady=(4, 10), sticky="w")
        ttk.Entry(opts_box, textvariable=self.save_dir).grid(row=2, column=1, columnspan=3,
                                                              sticky="ew", pady=(4, 10))
        ttk.Button(opts_box, text="Шолу…", command=self._pick_folder)\
            .grid(row=2, column=4, padx=10, pady=(4, 10), sticky="w")

        # --- іске қосу ---
        run_row = ttk.Frame(self)
        run_row.pack(fill="x", padx=10)
        self.btn_go = ttk.Button(run_row, text="Үзіндіні жүктеу", command=self.start_download)
        self.btn_go.pack(side="left")
        self.btn_stop = ttk.Button(run_row, text="Бас тарту", command=self._on_abort, state="disabled")
        self.btn_stop.pack(side="left", padx=8)

        self.bar = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.bar.pack(fill="x", padx=12, pady=(10, 2))
        self.state_var = tk.StringVar(value="Пәрменді күтуде")
        ttk.Label(self, textvariable=self.state_var).pack(fill="x", padx=12, anchor="w")

        # --- лог ---
        log_box = ttk.LabelFrame(self, text="Орындалу барысы")
        log_box.pack(fill="both", expand=True, **pad)
        self.log_widget = tk.Text(log_box, height=9, wrap="word", state="disabled")
        self.log_widget.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll = ttk.Scrollbar(log_box, command=self.log_widget.yview)
        scroll.pack(side="right", fill="y", padx=(0, 10), pady=10)
        self.log_widget.configure(yscrollcommand=scroll.set)

    # -------------------------- UI күйі / утилиталар ---------------------- #

    def note(self, text):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", str(text).rstrip() + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _probe_ffmpeg(self):
        path = find_ffmpeg()
        if not path:
            self.note("PATH жолында ffmpeg табылмады — кесу және біріктіру мүмкін емес.")
            return
        try:
            code, tail = exec_ffmpeg(["-version"])
            first_line = tail.splitlines()[0] if tail else ""
            self.note(f"ffmpeg табылды: {path}")
            if first_line:
                self.note(first_line)
        except Exception as e:
            self.note(f"ffmpeg бар сияқты, бірақ іске қосылмай тұр: {e}")

    def _lock_controls(self, busy, allow_abort=False):
        self.working = busy
        state = "disabled" if busy else "normal"
        self.btn_grab.configure(state=state)
        self.btn_go.configure(state=state)
        self.btn_stop.configure(state="normal" if (busy and allow_abort) else "disabled")

    def _from_sec(self):
        return int(round(self.pos_from.get()))

    def _to_sec(self):
        return int(round(self.pos_to.get()))

    def _defer_set(self, var, value):
        """Жылжытқышты өз колбэгінде емес, сәл кейінірек өзгерту."""
        self.lock_ui = True

        def go():
            try:
                var.set(value)
            finally:
                self.lock_ui = False
                self._refresh_time_labels()

        self.after_idle(go)

    def _refresh_time_labels(self):
        self.from_txt.set(sec_to_hms(self._from_sec()))
        self.to_txt.set(sec_to_hms(self._to_sec()))
        span = max(0, self._to_sec() - self._from_sec())
        self.clip_len_var.set(f"Үзінді ұзақтығы: {sec_to_hms(span)}    (жалпы {sec_to_hms(self.vid_len)})")

    def _set_from(self, value):
        value = max(0, min(int(value), self.vid_len))
        if value >= self._to_sec():
            value = max(0, self._to_sec() - 1)
        self.pos_from.set(value)
        self._refresh_time_labels()

    def _set_to(self, value):
        value = max(0, min(int(value), self.vid_len))
        if value <= self._from_sec():
            value = min(self.vid_len, self._from_sec() + 1)
        self.pos_to.set(value)
        self._refresh_time_labels()

    # ------------------------------ колбэктер ---------------------------- #

    def _on_from_move(self, _=None):
        if self.lock_ui or self.vid_len <= 0:
            return
        a, b = self._from_sec(), self._to_sec()
        if a >= b:
            self._defer_set(self.pos_from, max(0, b - 1))
            return
        self._refresh_time_labels()

    def _on_to_move(self, _=None):
        if self.lock_ui or self.vid_len <= 0:
            return
        a, b = self._from_sec(), self._to_sec()
        if b <= a:
            self._defer_set(self.pos_to, min(self.vid_len, a + 1))
            return
        self._refresh_time_labels()

    def _on_time_typed(self, which):
        if self.vid_len <= 0:
            return
        var = self.from_txt if which == "from" else self.to_txt
        try:
            value = hms_to_sec(var.get())
        except ValueError:
            self._refresh_time_labels()
            return
        if which == "from":
            self._set_from(value)
        else:
            self._set_to(value)

    def _pick_whole(self):
        if self.vid_len > 0:
            self.pos_from.set(0)
            self.pos_to.set(self.vid_len)
            self._refresh_time_labels()

    def _on_mp3_toggle(self):
        self.quality_pick.configure(state="disabled" if self.mp3_only.get() else "readonly")

    def _pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.save_dir.get() or os.getcwd())
        if d:
            self.save_dir.set(d)

    def _on_abort(self):
        self.abort_flag = True
        self.state_var.set("Тоқтатылуда…")

    # --------------------------- видео туралы ақпарат ----------------------- #

    def grab_info(self):
        url = self.link_var.get().strip()
        if not url:
            messagebox.showwarning("Бос мән", "Алдымен сілтемені қойыңыз.")
            return
        if self.working:
            return
        self._lock_controls(True)
        self.state_var.set("Видео деректері алынуда…")
        self.headline_var.set("Бір сәт…")
        threading.Thread(target=self._meta_worker, args=(url,), daemon=True).start()

    def _meta_worker(self, url):
        try:
            opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                meta = ydl.extract_info(url, download=False)
            if meta.get("_type") == "playlist":
                items = [e for e in meta.get("entries", []) if e]
                if not items:
                    raise RuntimeError("Плейлист бос.")
                meta = items[0]
                self.pipe.put(("log", "Плейлистке ұқсайды — бірінші видео алынады."))
            self.pipe.put(("meta", meta))
        except Exception as e:
            self.pipe.put(("fail", f"Деректерді алу мүмкін болмады: {e}"))

    def _render_meta(self, meta):
        self.meta = meta
        self.vid_len = int(meta.get("duration") or 0)
        title = meta.get("title", "Атаусыз")
        author = meta.get("uploader", "")
        self.headline_var.set(f"{title}   —   {author}   [{sec_to_hms(self.vid_len)}]")

        if self.vid_len <= 0:
            self.note("Ұзақтығы белгісіз (тікелей трансляция болуы мүмкін) — кесу мүмкін емес.")
            self.vid_len = 0

        top = max(1, self.vid_len)
        self.lock_ui = True
        try:
            self.from_slider.configure(to=top)
            self.to_slider.configure(to=top)
            self.pos_from.set(0)
            self.pos_to.set(top)
        finally:
            self.lock_ui = False
        self._refresh_time_labels()

        heights = set()
        for f in meta.get("formats", []):
            if f.get("vcodec") not in (None, "none") and f.get("height"):
                heights.add(int(f["height"]))
        self.res_list = sorted(heights, reverse=True)
        picks = ["Ең үздік қолжетімді"] + [f"{h}p" for h in self.res_list]
        self.quality_pick.configure(values=picks)
        self.quality_pick.current(0)

        self.note(f"Жүктелді: {title}")
        self.note("Қолжетімді ажыратылымдықтар: " + (", ".join(f"{h}p" for h in self.res_list) or "дерек жоқ"))
        self.state_var.set("Жүктеуге дайын")

    # ------------------------------ жүктеу ----------------------------- #

    def start_download(self):
        if self.working:
            return
        url = self.link_var.get().strip()
        if not url:
            messagebox.showwarning("Бос мән", "Алдымен сілтемені қойыңыз.")
            return
        if not find_ffmpeg():
            messagebox.showerror("ffmpeg табылмады",
                                 "PATH ішінде ffmpeg болмаса кесу және біріктіру мүмкін емес.\n"
                                 "Оны орнатып, бағдарламаны қайта қосыңыз.")
            return
        out_dir = self.save_dir.get().strip()
        if not out_dir:
            messagebox.showwarning("Сандық", "Сатау орнын көрсетіңіз.")
            return
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Сандық", f"Қапшықты құру мүмкін болмады:\n{e}")
            return

        t0 = self._from_sec()
        t1 = self._to_sec()
        whole_thing = (self.vid_len == 0) or (t0 == 0 and t1 >= self.vid_len)
        if not whole_thing and t1 <= t0:
            messagebox.showwarning("Үзінді", "Соңы басынан кейін болуы керек.")
            return

        picked = self.quality_pick.get()
        height = int(picked[:-1]) if picked.endswith("p") and picked[:-1].isdigit() else None

        base = clean_filename((self.meta or {}).get("title", "clip"))
        tail = "" if whole_thing else f"_{sec_to_hms(t0).replace(':', '-')}_{sec_to_hms(t1).replace(':', '-')}"

        self.abort_flag = False
        self.bar["value"] = 0
        self._lock_controls(True, allow_abort=True)
        self.state_var.set("Жүктелуде…")
        self.note(f"--- Басталуы: {sec_to_hms(t0)} — {sec_to_hms(t1)}"
                  f"{'' if height is None else f', {height}p'}"
                  f"{', тек дыбыс' if self.mp3_only.get() else ''} ---")

        threading.Thread(
            target=self._dl_worker,
            args=(url, out_dir, base + tail, t0, t1, whole_thing, height,
                  self.mp3_only.get(), self.exact_cut.get(),
                  self.mode_pick.get(), self.keep_full.get()),
            daemon=True,
        ).start()

    # --- прогресс хуктары ---

    def _hook_progress(self, d):
        if self.abort_flag:
            raise yt_dlp.utils.DownloadError("Пайдаланушы тоқтатты")
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0
            speed = d.get("speed") or 0
            eta = d.get("eta")
            line = (f"{pct:5.1f}%   "
                    f"{done / 1048576:.1f} / {(total / 1048576) if total else 0:.1f} МБ   "
                    f"{speed / 1048576:.2f} МБ/с   "
                    f"қалды {eta if eta is not None else '?'} с")
            self.pipe.put(("progress", (pct, line)))
        elif d.get("status") == "finished":
            self.pipe.put(("progress", (100, "ffmpeg арқылы өңделуде…")))

    def _hook_post(self, d):
        if d.get("status") == "started":
            self.pipe.put(("state", f"ffmpeg: {d.get('postprocessor', '')}…"))

    # --- yt-dlp баптауларын жинау ---

    def _ydl_opts(self, outtmpl, mp3_only, height):
        if mp3_only:
            fmt = "bestaudio/best"
        elif height:
            fmt = (f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
                   f"bestvideo[height<={height}]+bestaudio/"
                   f"best[height<={height}]/best")
        else:
            fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"

        opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._hook_progress],
            "postprocessor_hooks": [self._hook_post],
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 4,
            # қосымша клиент кейбір видеолардағы HTTP 403 қатесінде көмектеседі
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "http_headers": {
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0.0.0 Safari/537.36"),
            },
        }
        if mp3_only:
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            opts["merge_output_format"] = "mp4"
        return opts

    # --- жұмысшы ағын ---

    def _dl_worker(self, url, out_dir, base_name, t0, t1, whole_thing, height,
                   mp3_only, exact_cut, mode, keep_full):
        try:
            if whole_thing:
                outtmpl = os.path.join(out_dir, base_name + ".%(ext)s")
                with yt_dlp.YoutubeDL(self._ydl_opts(outtmpl, mp3_only, height)) as ydl:
                    ydl.download([url])
                self.pipe.put(("ok", out_dir))
                return

            if mode == self.QUICK_MODE:
                try:
                    self._dl_segment(url, out_dir, base_name, t0, t1,
                                     height, mp3_only, exact_cut)
                    self.pipe.put(("ok", out_dir))
                    return
                except yt_dlp.utils.DownloadError as e:
                    if self.abort_flag:
                        raise
                    self.pipe.put(("log", f"Жылдам режим сәтсіз аяқталды: {e}"))
                    self.pipe.put(("log", "Сенімді режимге ауысу: толық жүктеліп, кейін кесіледі."))

            self._dl_full_and_trim(url, out_dir, base_name, t0, t1,
                                   height, mp3_only, exact_cut, keep_full)
            self.pipe.put(("ok", out_dir))

        except yt_dlp.utils.DownloadError as e:
            if self.abort_flag:
                self.pipe.put(("stopped", None))
            else:
                self.pipe.put(("fail", f"Жүктеу қатесі: {e}"))
        except Exception as e:
            if self.abort_flag:
                self.pipe.put(("stopped", None))
            else:
                self.pipe.put(("fail", f"Қате: {e}\n{traceback.format_exc(limit=2)}"))

    def _dl_segment(self, url, out_dir, base_name, t0, t1, height, mp3_only, exact_cut):
        """QUICK режимі: yt-dlp тек қажетті аралықты өзі жүктейді."""
        self.pipe.put(("state", "Тек қажетті үзінді жүктелуде…"))
        outtmpl = os.path.join(out_dir, base_name + ".%(ext)s")
        opts = self._ydl_opts(outtmpl, mp3_only, height)
        opts["download_ranges"] = download_range_func(None, [(t0, t1)])
        opts["force_keyframes_at_cuts"] = bool(exact_cut)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    def _dl_full_and_trim(self, url, out_dir, base_name, t0, t1,
                          height, mp3_only, exact_cut, keep_full):
        """SAFE режимі: видеоны уақытша қапшыққа толық жүктеп, ffmpeg арқылы жергілікті кесеміз."""
        scratch = tempfile.mkdtemp(prefix="smartdownyt_", dir=out_dir)
        try:
            self.pipe.put(("state", "Толық видео жүктелуде…"))
            outtmpl = os.path.join(scratch, "raw.%(ext)s")
            with yt_dlp.YoutubeDL(self._ydl_opts(outtmpl, mp3_only, height)) as ydl:
                ydl.download([url])

            found = [f for f in glob.glob(os.path.join(scratch, "*")) if os.path.isfile(f)]
            if not found:
                raise RuntimeError("Жүктелген файл уақытша қапшықтан табылмады.")
            src = max(found, key=os.path.getsize)
            ext = os.path.splitext(src)[1] or (".mp3" if mp3_only else ".mp4")

            if self.abort_flag:
                raise yt_dlp.utils.DownloadError("Пайдаланушы тоқтатты")

            dst = os.path.join(out_dir, base_name + ext)
            n = 1
            while os.path.exists(dst):
                dst = os.path.join(out_dir, f"{base_name} ({n}){ext}")
                n += 1

            self.pipe.put(("progress", (100, "Үзінді ffmpeg арқылы кесілуде…")))
            span = t1 - t0

            if exact_cut and not mp3_only:
                # дәл кесу: қайта кодтау, нақты секциядан бастау
                argv = ["-y", "-ss", str(t0), "-i", src, "-t", str(span),
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst]
            else:
                # жақын орналасқан негізгі кадрлар бойынша жылдам кесу (қайта кодтаусыз)
                argv = ["-y", "-ss", str(t0), "-i", src, "-t", str(span), "-c", "copy", dst]

            code, tail = exec_ffmpeg(argv)
            if code != 0 and exact_cut and not mp3_only:
                self.pipe.put(("log", f"Қайта кодтау сәтсіз аяқталды (код {code}), қайта кодтаусыз байқап көремін."))
                if tail:
                    self.pipe.put(("log", tail))
                argv = ["-y", "-ss", str(t0), "-i", src, "-t", str(span), "-c", "copy", dst]
                code, tail = exec_ffmpeg(argv)

            if code != 0:
                raise RuntimeError(f"ffmpeg қайтарған код {code}.\n{tail}")

            if keep_full:
                kept = os.path.join(out_dir, base_name + "_full" + ext)
                shutil.move(src, kept)
                self.pipe.put(("log", f"Түпнұсқа сақталды: {kept}"))
            self.pipe.put(("log", f"Дайын үзінді: {dst}"))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    # --------------------------- хабарламалар кезегін талдау ------------------------- #

    def _drain_pipe(self):
        try:
            while True:
                kind, payload = self.pipe.get_nowait()

                if kind == "meta":
                    self._render_meta(payload)
                    self._lock_controls(False)
                elif kind == "progress":
                    pct, line = payload
                    self.bar["value"] = pct
                    self.state_var.set(line)
                elif kind == "state":
                    self.state_var.set(payload)
                elif kind == "log":
                    self.note(payload)
                elif kind == "ok":
                    self.bar["value"] = 100
                    self.state_var.set("Дайын")
                    self.note(f"Сақталған орын: {payload}")
                    self._lock_controls(False)
                    messagebox.showinfo("Дайын", f"Жүктеу аяқталды.\n{payload}")
                elif kind == "stopped":
                    self.bar["value"] = 0
                    self.state_var.set("Тоқтатылды")
                    self.note("Жүктеу тоқтатылды.")
                    self._lock_controls(False)
                elif kind == "fail":
                    self.bar["value"] = 0
                    self.state_var.set("Қате")
                    self.note(payload)
                    if self.headline_var.get() == "Бір сәт…":
                        self.headline_var.set("Әлі ештеңе жүктелген жоқ")
                    self._lock_controls(False)
                    messagebox.showerror("Қате", str(payload)[:600])
        except queue.Empty:
            pass
        self.after(120, self._drain_pipe)


if __name__ == "__main__":
    app = SmartDownYT()
    app.mainloop()
