from pathlib import Path
import os
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import winsound

from synth_engine import (
    Note, Renderer, Voicebank, load_project, mix_external_audio, note_name,
    read_wav, save_project, write_wav,
)


APP_DIR = Path(__file__).resolve().parent
VOICEBANK_DIR = APP_DIR / "voicebank"
PITCH_MIN = 48
PITCH_MAX = 96
ROW_HEIGHT = 20
BEAT_WIDTH = 56
TOTAL_BEATS = 64
KEY_WIDTH = 72
KEYBOARD_MAP = {
    "z": 72, "s": 73, "x": 74, "d": 75, "c": 76, "v": 77,
    "g": 78, "b": 79, "h": 80, "n": 81, "j": 82, "m": 83,
    ",": 84, "l": 85, ".": 86, ";": 87, "/": 88,
    "q": 84, "2": 85, "w": 86, "3": 87, "e": 88, "r": 89,
    "5": 90, "t": 91, "6": 92, "y": 93, "7": 94, "u": 95, "i": 96,
}


class HanulSynthApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Hanul Synth CVVC — 가산합성 한국어 보컬 편집기")
        self.root.geometry("1240x790")
        self.root.minsize(980, 650)
        self.notes = []
        self.selected = None
        self.selected_set = set()
        self.cursor_beat = 0.0
        self.project_path = None
        self.backing_path = None
        self.lyric_cursor = 0
        self.drag_notes = []
        self.drag_origin_x = 0.0
        self.drag_origin_y = 0.0
        self.drag_moved = False
        self.dirty = False

        if not VOICEBANK_DIR.exists():
            messagebox.showerror(
                "음원 없음",
                f"voicebank 폴더를 찾을 수 없습니다.\n{VOICEBANK_DIR}",
            )
        self.renderer = Renderer(Voicebank(VOICEBANK_DIR))
        self._build_style()
        self._build_menu()
        self._build_ui()
        self._bind_events()
        self._redraw()

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.root.configure(bg="#151821")
        style.configure(".", background="#20242e", foreground="#edf1f7")
        style.configure("TFrame", background="#20242e")
        style.configure("TLabelframe", background="#20242e", foreground="#f4a261")
        style.configure("TLabelframe.Label", background="#20242e", foreground="#f4a261")
        style.configure("TLabel", background="#20242e", foreground="#ffffff", font=("Malgun Gothic", 10))
        style.configure("TCheckbutton", background="#20242e", foreground="#edf1f7")
        style.configure("TButton", padding=7, font=("Malgun Gothic", 10))
        style.map("TButton", background=[("active", "#4a566a")], foreground=[("disabled", "#8b93a1")])
        style.configure(
            "TEntry",
            fieldbackground="#fffdf7",
            foreground="#111318",
            insertcolor="#111318",
            bordercolor="#f0a04b",
            lightcolor="#f0a04b",
            darkcolor="#f0a04b",
            padding=5,
        )
        style.configure(
            "Lyric.TEntry",
            fieldbackground="#fffdf7",
            foreground="#111318",
            insertcolor="#111318",
            bordercolor="#ffad5a",
            font=("Malgun Gothic", 13, "bold"),
            padding=7,
        )
        style.configure(
            "TSpinbox",
            fieldbackground="#fffdf7",
            foreground="#111318",
            insertcolor="#111318",
            arrowcolor="#111318",
        )
        style.configure(
            "TCombobox",
            fieldbackground="#fffdf7",
            background="#fffdf7",
            foreground="#111318",
            arrowcolor="#111318",
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#fffdf7")],
            foreground=[("readonly", "#111318")],
            selectbackground=[("readonly", "#fffdf7")],
            selectforeground=[("readonly", "#111318")],
        )

    def _build_menu(self):
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="새 프로젝트", command=self.new_project, accelerator="Ctrl+N")
        file_menu.add_command(label="열기…", command=self.open_project, accelerator="Ctrl+O")
        file_menu.add_command(label="저장", command=self.save_project, accelerator="Ctrl+S")
        file_menu.add_command(label="다른 이름으로 저장…", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="WAV 내보내기…", command=self.export_wav, accelerator="Ctrl+E")
        file_menu.add_separator()
        file_menu.add_command(label="종료", command=self.root.destroy)
        menu.add_cascade(label="파일", menu=file_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="키보드 안내", command=self.show_help)
        help_menu.add_command(label="합성 원리", command=self.show_synthesis_design)
        help_menu.add_command(label="사인파 성분표 열기", command=self.open_sine_table)
        help_menu.add_command(label="배음 설계표 열기", command=self.open_harmonic_design)
        menu.add_cascade(label="도움말", menu=help_menu)
        self.root.config(menu=menu)

    def _build_ui(self):
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text="BPM").pack(side="left")
        self.bpm = tk.IntVar(value=120)
        ttk.Spinbox(toolbar, from_=40, to=300, width=5, textvariable=self.bpm).pack(side="left", padx=(5, 14))
        ttk.Label(toolbar, text="기본 길이(박)").pack(side="left")
        self.note_length = tk.DoubleVar(value=1.0)
        ttk.Combobox(
            toolbar, width=6, state="readonly", textvariable=self.note_length,
            values=(0.25, 0.5, 1.0, 2.0, 4.0),
        ).pack(side="left", padx=(5, 14))
        ttk.Label(toolbar, text="음색").pack(side="left")
        self.voice_style = tk.StringVar(value="선명한 자신감 여성")
        ttk.Combobox(
            toolbar, width=16, state="readonly", textvariable=self.voice_style,
            values=(
                "선명한 자신감 여성",
                "레이·테토풍 여성",
                "부드러운 여성",
            ),
        ).pack(side="left", padx=(5, 14))
        ttk.Label(toolbar, text="반주 악기").pack(side="left")
        self.instrument = tk.StringVar(value="없음")
        ttk.Combobox(
            toolbar, width=10, state="readonly", textvariable=self.instrument,
            values=("없음", "사인", "톱니", "사각", "벨", "소프트 패드"),
        ).pack(side="left", padx=(5, 14))

        ttk.Button(toolbar, text="▶ 재생", command=self.play).pack(side="left", padx=3)
        ttk.Button(toolbar, text="■ 정지", command=self.stop).pack(side="left", padx=3)
        ttk.Button(toolbar, text="WAV 내보내기", command=self.export_wav).pack(side="left", padx=3)

        settings = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        settings.pack(fill="x")
        ttk.Label(settings, text="배음 사이 잡음").pack(side="left")
        self.noise_level = tk.DoubleVar(value=0.0)
        self.noise_scale = ttk.Scale(settings, from_=0.0, to=0.24, variable=self.noise_level)
        self.noise_scale.pack(side="left", fill="x", expand=True, padx=(8, 12))
        self.noise_text = ttk.Label(settings, text="0%")
        self.noise_text.pack(side="left", padx=(0, 16))
        self.noise_scale.configure(command=self._noise_changed)
        ttk.Label(settings, text="기계음").pack(side="left")
        self.machine_level = tk.DoubleVar(value=0.03)
        self.machine_scale = ttk.Scale(
            settings, from_=0.0, to=1.0, variable=self.machine_level,
            command=self._machine_changed, length=130,
        )
        self.machine_scale.pack(side="left", padx=(8, 8))
        self.machine_text = ttk.Label(settings, text="3%")
        self.machine_text.pack(side="left", padx=(0, 16))
        self.phonology = tk.BooleanVar(value=True)
        self.initial_rule = tk.BooleanVar(value=True)
        ttk.Checkbutton(settings, text="연음·비음화·유음화 보정", variable=self.phonology).pack(side="left", padx=5)
        ttk.Checkbutton(settings, text="두음법칙 보정", variable=self.initial_rule).pack(side="left", padx=5)

        lyric_bar = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        lyric_bar.pack(fill="x")
        ttk.Label(lyric_bar, text="입력 가사").pack(side="left")
        self.lyric_text = tk.StringVar(value="안녕하세요")
        self.lyric_text.trace_add("write", self._lyrics_changed)
        self.lyric_entry = ttk.Entry(lyric_bar, textvariable=self.lyric_text, style="Lyric.TEntry")
        self.lyric_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(
            lyric_bar,
            text="가사 자동 배치 · 공백은 1박 쉼",
            command=self.apply_lyrics,
        ).pack(side="left")

        backing_bar = ttk.LabelFrame(self.root, text="외부 반주 트랙", padding=(8, 5))
        backing_bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(backing_bar, text="WAV 불러오기", command=self.load_backing).pack(side="left")
        ttk.Button(backing_bar, text="반주 제거", command=self.clear_backing).pack(side="left", padx=5)
        self.backing_label = ttk.Label(backing_bar, text="반주 없음", width=38)
        self.backing_label.pack(side="left", padx=(8, 14))
        ttk.Label(backing_bar, text="반주 볼륨").pack(side="left")
        self.backing_volume = tk.DoubleVar(value=0.35)
        ttk.Scale(
            backing_bar, from_=0.0, to=1.0, variable=self.backing_volume,
            length=180,
        ).pack(side="left", padx=8)

        timing_bar = ttk.LabelFrame(self.root, text="타이밍 정리", padding=(8, 5))
        timing_bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(timing_bar, text="빈 박자 최대").pack(side="left")
        self.max_empty_gap = tk.DoubleVar(value=0.25)
        ttk.Combobox(
            timing_bar,
            width=7,
            state="readonly",
            textvariable=self.max_empty_gap,
            values=(0.0, 0.25, 0.5, 1.0, 2.0),
        ).pack(side="left", padx=(8, 12))
        ttk.Button(
            timing_bar,
            text="빈 박자 일괄 줄이기",
            command=self.compact_empty_beats,
        ).pack(side="left")
        ttk.Label(
            timing_bar,
            text="선택한 값보다 긴 빈 구간만 줄입니다.",
        ).pack(side="left", padx=12)

        editor = ttk.Frame(self.root)
        editor.pack(fill="both", expand=True, padx=8)

        self.key_canvas = tk.Canvas(
            editor, width=KEY_WIDTH, bg="#f4f4f2", highlightthickness=0,
            scrollregion=(0, 0, KEY_WIDTH, (PITCH_MAX - PITCH_MIN + 1) * ROW_HEIGHT),
        )
        self.key_canvas.grid(row=0, column=0, sticky="ns")
        self.canvas = tk.Canvas(
            editor, bg="#161a22", highlightthickness=0,
            scrollregion=(0, 0, TOTAL_BEATS * BEAT_WIDTH, (PITCH_MAX - PITCH_MIN + 1) * ROW_HEIGHT),
        )
        self.canvas.grid(row=0, column=1, sticky="nsew")
        vertical = ttk.Scrollbar(editor, orient="vertical", command=self._scroll_y)
        horizontal = ttk.Scrollbar(editor, orient="horizontal", command=self.canvas.xview)
        vertical.grid(row=0, column=2, sticky="ns")
        horizontal.grid(row=1, column=1, sticky="ew")
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.key_canvas.configure(yscrollcommand=vertical.set)
        editor.columnconfigure(1, weight=1)
        editor.rowconfigure(0, weight=1)

        properties = ttk.LabelFrame(self.root, text="선택한 음표", padding=8)
        properties.pack(fill="x", padx=8, pady=8)
        self.selected_label = ttk.Label(properties, text="선택 없음", width=18)
        self.selected_label.pack(side="left")
        ttk.Label(properties, text="가사").pack(side="left")
        self.note_lyric = tk.StringVar(value="아")
        self.note_lyric_entry = ttk.Entry(
            properties, width=9, textvariable=self.note_lyric, style="Lyric.TEntry",
        )
        self.note_lyric_entry.pack(side="left", padx=(5, 12))
        ttk.Label(properties, text="길이").pack(side="left")
        self.selected_length = tk.DoubleVar(value=1.0)
        ttk.Spinbox(properties, from_=0.125, to=16, increment=0.125, width=7, textvariable=self.selected_length).pack(side="left", padx=(5, 12))
        ttk.Label(properties, text="세기").pack(side="left")
        self.selected_velocity = tk.IntVar(value=100)
        ttk.Spinbox(properties, from_=1, to=127, width=5, textvariable=self.selected_velocity).pack(side="left", padx=(5, 12))
        ttk.Label(properties, text="잡음 배율").pack(side="left")
        self.selected_noise = tk.DoubleVar(value=1.0)
        ttk.Spinbox(properties, from_=0, to=2, increment=0.1, width=5, textvariable=self.selected_noise).pack(side="left", padx=(5, 12))
        ttk.Button(properties, text="적용", command=self.apply_note_properties).pack(side="left", padx=3)
        ttk.Button(properties, text="전체 선택", command=self.select_all_notes).pack(side="left", padx=3)
        ttk.Button(properties, text="선택 일괄 삭제", command=self.delete_selected).pack(side="left", padx=3)

        self.status = tk.StringVar(value="Z~M / Q~I 키로 음표 입력 · 빈 피아노롤 클릭으로도 추가")
        ttk.Label(self.root, textvariable=self.status, anchor="w", padding=(10, 4)).pack(fill="x")

    def _bind_events(self):
        self.canvas.bind("<Button-1>", self.canvas_click)
        self.canvas.bind("<B1-Motion>", self.canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.canvas_drag_release)
        self.canvas.bind("<Double-Button-1>", self.canvas_double_click)
        self.canvas.bind("<Button-3>", self.canvas_right_click)
        self.lyric_entry.bind("<Return>", lambda _event: self.apply_lyrics())
        self.note_lyric_entry.bind("<Return>", lambda _event: self.apply_note_properties())
        self.root.bind("<KeyPress>", self.key_press)
        self.root.bind("<F2>", lambda _event: self.edit_selected_lyric())
        self.root.bind("<Delete>", lambda _event: self.delete_selected())
        self.root.bind("<Control-n>", lambda _event: self.new_project())
        self.root.bind("<Control-o>", lambda _event: self.open_project())
        self.root.bind("<Control-s>", lambda _event: self.save_project())
        self.root.bind("<Control-e>", lambda _event: self.export_wav())
        self.root.bind("<Control-a>", lambda _event: self.select_all_notes())

    def _scroll_y(self, *args):
        self.canvas.yview(*args)
        self.key_canvas.yview(*args)

    def _noise_changed(self, _value=None):
        self.noise_text.configure(text=f"{round(self.noise_level.get() * 100)}%")

    def _machine_changed(self, _value=None):
        self.machine_text.configure(text=f"{round(self.machine_level.get() * 100)}%")

    def _lyrics_changed(self, *_args):
        self.lyric_cursor = 0

    def _lyric_items(self):
        items = []
        new_word = True
        pending_rest = False
        for char in self.lyric_text.get():
            if char.isspace():
                if items:
                    new_word = True
                    pending_rest = True
                continue
            if 0xAC00 <= ord(char) <= 0xD7A3:
                lyric = (" " if new_word else "") + char
                items.append((lyric, 1.0 if pending_rest else 0.0))
                new_word = False
                pending_rest = False
        return items

    def _lyric_syllables(self):
        return [lyric for lyric, _rest_before in self._lyric_items()]

    def _pitch_y(self, midi):
        return (PITCH_MAX - midi) * ROW_HEIGHT

    def _midi_from_y(self, y):
        return max(PITCH_MIN, min(PITCH_MAX, PITCH_MAX - int(y // ROW_HEIGHT)))

    def _redraw(self):
        self.canvas.delete("all")
        self.key_canvas.delete("all")
        height = (PITCH_MAX - PITCH_MIN + 1) * ROW_HEIGHT
        for midi in range(PITCH_MAX, PITCH_MIN - 1, -1):
            y = self._pitch_y(midi)
            black = midi % 12 in {1, 3, 6, 8, 10}
            key_fill = "#2b303b" if black else "#ecece8"
            key_text = "#f5f5f5" if black else "#22252b"
            self.key_canvas.create_rectangle(0, y, KEY_WIDTH, y + ROW_HEIGHT, fill=key_fill, outline="#777")
            self.key_canvas.create_text(7, y + ROW_HEIGHT / 2, text=note_name(midi), anchor="w", fill=key_text, font=("Segoe UI", 8))
            row_fill = "#1a1f29" if black else "#202630"
            self.canvas.create_rectangle(0, y, TOTAL_BEATS * BEAT_WIDTH, y + ROW_HEIGHT, fill=row_fill, outline="")
            self.canvas.create_line(0, y, TOTAL_BEATS * BEAT_WIDTH, y, fill="#313946")
        for beat in range(TOTAL_BEATS + 1):
            x = beat * BEAT_WIDTH
            color = "#758195" if beat % 4 == 0 else "#3d4655"
            width = 2 if beat % 4 == 0 else 1
            self.canvas.create_line(x, 0, x, height, fill=color, width=width)
            if beat % 4 == 0:
                self.canvas.create_text(x + 3, 9, text=str(beat + 1), anchor="nw", fill="#98a4b7", font=("Segoe UI", 8))
        cursor_x = self.cursor_beat * BEAT_WIDTH
        self.canvas.create_line(cursor_x, 0, cursor_x, height, fill="#f4a261", width=2, tags="cursor")
        for index, note in enumerate(self.notes):
            x1 = note.start * BEAT_WIDTH
            x2 = (note.start + note.length) * BEAT_WIDTH
            y1 = self._pitch_y(note.midi) + 2
            y2 = y1 + ROW_HEIGHT - 4
            selected = index in self.selected_set
            fill = "#ef6c57" if selected else "#e99542"
            outline = "#ffe1b3" if selected else "#f6bd72"
            self.canvas.create_rectangle(x1 + 1, y1, x2 - 1, y2, fill=fill, outline=outline, width=2 if selected else 1, tags=(f"note-{index}", "note"))
            self.canvas.create_text(x1 + 5, (y1 + y2) / 2, text=note.lyric, anchor="w", fill="#17191e", font=("Malgun Gothic", 9, "bold"), tags=(f"note-{index}", "note"))

    def _note_at(self, x, y):
        beat = x / BEAT_WIDTH
        midi = self._midi_from_y(y)
        for index in range(len(self.notes) - 1, -1, -1):
            note = self.notes[index]
            if note.midi == midi and note.start <= beat <= note.start + note.length:
                return index
        return None

    def canvas_click(self, event):
        self.canvas.focus_set()
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        found = self._note_at(x, y)
        if found is not None:
            additive = bool(event.state & 0x0001 or event.state & 0x0004)
            if additive or found not in self.selected_set:
                self.select_note(found, additive=additive)
            else:
                self.selected = found
            if found in self.selected_set:
                self.drag_origin_x = x
                self.drag_origin_y = y
                self.drag_moved = False
                self.drag_notes = [
                    (self.notes[index], self.notes[index].start, self.notes[index].midi)
                    for index in sorted(self.selected_set)
                    if 0 <= index < len(self.notes)
                ]
            return
        self.drag_notes = []
        beat = round((x / BEAT_WIDTH) * 4) / 4
        midi = self._midi_from_y(y)
        self.insert_note(midi, beat)

    def canvas_drag(self, event):
        if not self.drag_notes:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        raw_beat_delta = (x - self.drag_origin_x) / BEAT_WIDTH
        beat_delta = round(raw_beat_delta * 4) / 4
        origin_midi = self._midi_from_y(self.drag_origin_y)
        target_midi = self._midi_from_y(y)
        midi_delta = target_midi - origin_midi

        earliest_start = min(start for _note, start, _midi in self.drag_notes)
        beat_delta = max(beat_delta, -earliest_start)
        lowest_midi = min(midi for _note, _start, midi in self.drag_notes)
        highest_midi = max(midi for _note, _start, midi in self.drag_notes)
        midi_delta = max(PITCH_MIN - lowest_midi, min(PITCH_MAX - highest_midi, midi_delta))

        for note, original_start, original_midi in self.drag_notes:
            note.start = original_start + beat_delta
            note.midi = original_midi + midi_delta
        self.drag_moved = self.drag_moved or beat_delta != 0 or midi_delta != 0
        self._redraw()
        self.status.set(
            f"음표 {len(self.drag_notes)}개 이동 중 · "
            f"박자 {beat_delta:+g}, 음높이 {midi_delta:+d}"
        )

    def canvas_drag_release(self, _event):
        if not self.drag_notes:
            return
        moved_notes = [note for note, _start, _midi in self.drag_notes]
        moved = self.drag_moved
        self.drag_notes = []
        self.drag_moved = False
        if not moved:
            return
        self.notes.sort(key=lambda item: (item.start, item.midi))
        self.selected_set = {
            self.notes.index(note) for note in moved_notes if note in self.notes
        }
        self.selected = min(self.selected_set) if self.selected_set else None
        self.dirty = True
        self._redraw()
        self.status.set(
            f"음표 {len(moved_notes)}개를 새 음높이·박자 위치로 이동했습니다."
        )

    def canvas_double_click(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        found = self._note_at(x, y)
        if found is not None:
            self.select_note(found)
            self.edit_selected_lyric()
            return "break"

    def canvas_right_click(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        found = self._note_at(x, y)
        if found is not None:
            self.selected = found
            self.selected_set = {found}
            self.delete_selected()

    def insert_note(self, midi, start=None):
        if start is None:
            start = self.cursor_beat
        syllables = self._lyric_syllables()
        automatic_lyric = self.lyric_cursor < len(syllables)
        if automatic_lyric:
            lyric = syllables[self.lyric_cursor]
            self.lyric_cursor += 1
        else:
            lyric = self.note_lyric.get().strip() or "아"
        note = Note(
            start=max(0.0, start),
            length=max(0.125, float(self.note_length.get())),
            midi=midi,
            lyric=lyric,
        )
        self.notes.append(note)
        self.notes.sort(key=lambda item: (item.start, item.midi))
        self.selected = self.notes.index(note)
        self.selected_set = {self.selected}
        self.cursor_beat = note.start + note.length
        self.dirty = True
        self.select_note(self.selected)
        if automatic_lyric:
            self.status.set(
                f"{note_name(midi)} 음표 삽입 · 가사 '{lyric.strip()}' "
                f"자동 입력 ({self.lyric_cursor}/{len(syllables)})"
            )
        else:
            self.status.set(f"{note_name(midi)} · '{lyric}' 음원 자동 삽입")

    def key_press(self, event):
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text, ttk.Entry, ttk.Spinbox, ttk.Combobox)):
            return
        key = event.keysym.lower()
        key = {"comma": ",", "period": ".", "slash": "/", "semicolon": ";"}.get(key, key)
        if key in KEYBOARD_MAP:
            self.insert_note(KEYBOARD_MAP[key])
            return "break"
        if key == "left":
            self.cursor_beat = max(0, self.cursor_beat - 0.25)
            self._redraw()
        elif key == "right":
            self.cursor_beat = min(TOTAL_BEATS, self.cursor_beat + 0.25)
            self._redraw()
        elif key == "space":
            self.play()
            return "break"

    def select_note(self, index, additive=False):
        if not 0 <= index < len(self.notes):
            return
        if additive:
            if index in self.selected_set:
                self.selected_set.remove(index)
            else:
                self.selected_set.add(index)
        else:
            self.selected_set = {index}
        if not self.selected_set:
            self.selected = None
            self.selected_label.configure(text="선택 없음")
            self._redraw()
            return
        self.selected = index if index in self.selected_set else max(self.selected_set)
        note = self.notes[self.selected]
        self.note_lyric.set(note.lyric)
        self.selected_length.set(note.length)
        self.selected_velocity.set(note.velocity)
        self.selected_noise.set(note.noise)
        if len(self.selected_set) == 1:
            label = f"{note_name(note.midi)} / {note.start:g}박"
        else:
            label = f"{len(self.selected_set)}개 선택"
        self.selected_label.configure(text=label)
        self.status.set(
            f"음표 {len(self.selected_set)}개 선택 · Ctrl/Shift+클릭으로 추가·해제"
        )
        self._redraw()

    def edit_selected_lyric(self):
        if self.selected is None or self.selected >= len(self.notes):
            self.status.set("가사를 바꿀 음표를 먼저 선택하세요.")
            return
        note = self.notes[self.selected]
        lyric = simpledialog.askstring(
            "가사 입력",
            f"{note_name(note.midi)} 음표의 가사",
            initialvalue=note.lyric.strip(),
            parent=self.root,
        )
        if lyric is None:
            return
        note.lyric = lyric.strip() or "아"
        self.note_lyric.set(note.lyric)
        self.dirty = True
        self._redraw()
        self.status.set(f"선택 음표 가사를 '{note.lyric}'(으)로 변경했습니다.")

    def apply_note_properties(self):
        if self.selected is None or self.selected >= len(self.notes):
            return
        note = self.notes[self.selected]
        note.lyric = self.note_lyric.get().strip() or "아"
        note.length = max(0.125, float(self.selected_length.get()))
        note.velocity = max(1, min(127, int(self.selected_velocity.get())))
        note.noise = max(0.0, min(2.0, float(self.selected_noise.get())))
        self.dirty = True
        self._redraw()

    def delete_selected(self):
        targets = {
            index for index in self.selected_set if 0 <= index < len(self.notes)
        }
        if not targets and self.selected is not None and self.selected < len(self.notes):
            targets = {self.selected}
        if not targets:
            return
        for index in sorted(targets, reverse=True):
            del self.notes[index]
        self.selected = None
        self.selected_set.clear()
        self.selected_label.configure(text="선택 없음")
        self.dirty = True
        self._redraw()
        self.status.set(f"선택한 음표 {len(targets)}개를 삭제했습니다.")

    def select_all_notes(self):
        if not self.notes:
            self.status.set("선택할 음표가 없습니다.")
            return "break"
        self.selected_set = set(range(len(self.notes)))
        self.selected = 0
        note = self.notes[0]
        self.note_lyric.set(note.lyric)
        self.selected_length.set(note.length)
        self.selected_velocity.set(note.velocity)
        self.selected_noise.set(note.noise)
        self.selected_label.configure(text=f"{len(self.notes)}개 선택")
        self._redraw()
        self.status.set(
            f"전체 음표 {len(self.notes)}개 선택 · Delete로 일괄 삭제"
        )
        return "break"

    def load_backing(self):
        path = filedialog.askopenfilename(
            title="외부 반주 WAV 불러오기",
            filetypes=[("WAV 오디오", "*.wav")],
        )
        if not path:
            return
        try:
            read_wav(path)
        except Exception as error:
            messagebox.showerror("반주 오류", f"WAV를 읽을 수 없습니다.\n{error}")
            return
        self.backing_path = str(Path(path).resolve())
        self.backing_label.configure(text=Path(path).name)
        self.dirty = True
        self.status.set(f"외부 반주를 불러왔습니다: {Path(path).name}")

    def clear_backing(self):
        self.backing_path = None
        self.backing_label.configure(text="반주 없음")
        self.dirty = True
        self.status.set("외부 반주를 제거했습니다.")

    def apply_lyrics(self):
        lyric_items = self._lyric_items()
        if not lyric_items:
            messagebox.showinfo("가사", "한글 가사를 입력하세요.")
            return

        ordered = sorted(self.notes, key=lambda item: (item.start, item.midi))
        assigned_count = min(len(ordered), len(lyric_items))
        cumulative_rest = 0.0
        for index, note in enumerate(ordered):
            if index < len(lyric_items):
                lyric, rest_before = lyric_items[index]
                if rest_before > 0 and index > 0:
                    previous = ordered[index - 1]
                    shifted_start = note.start + cumulative_rest
                    existing_gap = shifted_start - (
                        previous.start + previous.length
                    )
                    cumulative_rest += max(0.0, rest_before - existing_gap)
                note.lyric = lyric
            note.start += cumulative_rest

        created_count = 0
        if len(lyric_items) > len(ordered):
            if ordered:
                last_note = max(ordered, key=lambda item: item.start + item.length)
                next_start = last_note.start + last_note.length
                default_midi = last_note.midi
            else:
                next_start = self.cursor_beat
                default_midi = 72
            default_length = max(0.125, float(self.note_length.get()))
            for lyric, rest_before in lyric_items[len(ordered):]:
                next_start += rest_before
                self.notes.append(
                    Note(
                        start=next_start,
                        length=default_length,
                        midi=default_midi,
                        lyric=lyric,
                        velocity=100,
                        noise=0.0,
                    )
                )
                next_start += default_length
                created_count += 1
            self.notes.sort(key=lambda item: (item.start, item.midi))
            self.cursor_beat = next_start

        self.selected = None
        self.selected_set.clear()
        self.selected_label.configure(text="선택 없음")
        self.lyric_cursor = len(lyric_items)
        self.dirty = True
        self._redraw()
        rest_count = sum(1 for _lyric, rest in lyric_items if rest > 0)
        if created_count:
            self.status.set(
                f"가사 {len(lyric_items)}글자 배치 · 음표 {created_count}개 생성 · "
                f"띄어쓰기 쉼 {rest_count}곳"
            )
        else:
            remaining = max(0, len(ordered) - assigned_count)
            suffix = f" · 남은 음표 {remaining}개는 유지" if remaining else ""
            self.status.set(
                f"가사 {assigned_count}글자 배치 · 띄어쓰기 쉼 {rest_count}곳"
                f"{suffix}."
            )

    def compact_empty_beats(self):
        if not self.notes:
            self.status.set("줄일 빈 박자가 없습니다.")
            return
        maximum_gap = max(0.0, float(self.max_empty_gap.get()))
        ordered = sorted(self.notes, key=lambda item: (item.start, item.midi))
        accumulated_reduction = 0.0
        occupied_end = 0.0
        reduced_gaps = 0
        total_reduction = 0.0

        for note in ordered:
            shifted_start = note.start - accumulated_reduction
            empty_gap = shifted_start - occupied_end
            if empty_gap > maximum_gap:
                reduction = empty_gap - maximum_gap
                accumulated_reduction += reduction
                total_reduction += reduction
                shifted_start -= reduction
                reduced_gaps += 1
            note.start = max(0.0, shifted_start)
            occupied_end = max(occupied_end, note.start + note.length)

        self.notes.sort(key=lambda item: (item.start, item.midi))
        self.selected = None
        self.selected_set.clear()
        self.selected_label.configure(text="선택 없음")
        self.cursor_beat = max(
            (note.start + note.length for note in self.notes), default=0.0
        )
        if reduced_gaps:
            self.dirty = True
            self._redraw()
            self.status.set(
                f"빈 구간 {reduced_gaps}곳을 총 {total_reduction:g}박 줄였습니다 · "
                f"최대 빈 박자 {maximum_gap:g}"
            )
        else:
            self.status.set(
                f"{maximum_gap:g}박보다 긴 빈 구간이 없습니다."
            )

    def _settings(self):
        return {
            "bpm": self.bpm.get(),
            "note_length": self.note_length.get(),
            "instrument": self.instrument.get(),
            "voice_style": self.voice_style.get(),
            "noise_level": self.noise_level.get(),
            "machine_level": self.machine_level.get(),
            "phonology": self.phonology.get(),
            "initial_rule": self.initial_rule.get(),
            "backing_path": self.backing_path or "",
            "backing_volume": self.backing_volume.get(),
            "max_empty_gap": self.max_empty_gap.get(),
        }

    def _apply_settings(self, settings):
        for key, variable in (
            ("bpm", self.bpm), ("note_length", self.note_length),
            ("instrument", self.instrument), ("voice_style", self.voice_style),
            ("noise_level", self.noise_level),
            ("machine_level", self.machine_level),
            ("phonology", self.phonology), ("initial_rule", self.initial_rule),
            ("backing_volume", self.backing_volume),
            ("max_empty_gap", self.max_empty_gap),
        ):
            if key in settings:
                variable.set(settings[key])
        backing_path = settings.get("backing_path") or None
        self.backing_path = backing_path
        self.backing_label.configure(
            text=Path(backing_path).name if backing_path else "반주 없음"
        )
        self._noise_changed()
        self._machine_changed()

    def render_audio(self):
        self.status.set("음원을 결합하고 렌더링하는 중…")
        self.root.update_idletasks()
        try:
            audio = self.renderer.render(
                self.notes,
                bpm=self.bpm.get(),
                noise_level=self.noise_level.get(),
                instrument=self.instrument.get(),
                phonology=self.phonology.get(),
                initial_rule=self.initial_rule.get(),
                machine_level=self.machine_level.get(),
                voice_style=self.voice_style.get(),
            )
            if self.backing_path:
                backing_file = Path(self.backing_path)
                if not backing_file.exists():
                    raise FileNotFoundError(
                        f"외부 반주 파일을 찾을 수 없습니다.\n{backing_file}"
                    )
                backing = read_wav(backing_file)
                audio = mix_external_audio(
                    audio, backing, volume=self.backing_volume.get()
                )
        except Exception as error:
            messagebox.showerror("렌더링 오류", str(error))
            self.status.set("렌더링 실패")
            return None
        self.status.set("렌더링 완료")
        return audio

    def play(self):
        audio = self.render_audio()
        if audio is None:
            return
        preview = Path(tempfile.gettempdir()) / "hanul_synth_preview.wav"
        write_wav(preview, audio)
        winsound.PlaySound(str(preview), winsound.SND_FILENAME | winsound.SND_ASYNC)
        self.status.set("재생 중 · Space 또는 정지 버튼")

    def stop(self):
        winsound.PlaySound(None, winsound.SND_PURGE)
        self.status.set("정지")

    def export_wav(self):
        path = filedialog.asksaveasfilename(
            title="WAV 내보내기", defaultextension=".wav",
            filetypes=[("WAV 오디오", "*.wav")],
        )
        if not path:
            return
        audio = self.render_audio()
        if audio is None:
            return
        write_wav(path, audio)
        self.status.set(f"WAV 저장 완료: {path}")

    def new_project(self):
        self.stop()
        self.notes = []
        self.selected = None
        self.selected_set.clear()
        self.cursor_beat = 0.0
        self.lyric_cursor = 0
        self.project_path = None
        self.backing_path = None
        self.backing_label.configure(text="반주 없음")
        self.dirty = False
        self._redraw()
        self.status.set("새 프로젝트")

    def open_project(self):
        path = filedialog.askopenfilename(
            title="프로젝트 열기", filetypes=[("Hanul Synth 프로젝트", "*.hsp;*.json")],
        )
        if not path:
            return
        try:
            self.notes, settings = load_project(path)
            self._apply_settings(settings)
            self.project_path = path
            self.selected = None
            self.selected_set.clear()
            self.lyric_cursor = 0
            self.cursor_beat = max((note.start + note.length for note in self.notes), default=0.0)
            self.dirty = False
            self._redraw()
            self.status.set(f"프로젝트 열기 완료: {path}")
        except Exception as error:
            messagebox.showerror("열기 오류", str(error))

    def save_project(self):
        if not self.project_path:
            return self.save_project_as()
        try:
            save_project(self.project_path, self.notes, self._settings())
            self.dirty = False
            self.status.set(f"프로젝트 저장 완료: {self.project_path}")
        except Exception as error:
            messagebox.showerror("저장 오류", str(error))

    def save_project_as(self):
        path = filedialog.asksaveasfilename(
            title="프로젝트 저장", defaultextension=".hsp",
            filetypes=[("Hanul Synth 프로젝트", "*.hsp")],
        )
        if not path:
            return
        self.project_path = path
        self.save_project()

    def show_help(self):
        messagebox.showinfo(
            "키보드 안내",
            "Z S X D C V G B H N J M : 도5~시5\n"
            "Q 2 W 3 E R 5 T 6 Y 7 U I : 도6~도7\n"
            "← → : 입력 위치를 1/4박 이동\n"
            "Space : 재생\n"
            "Ctrl/Shift+클릭 : 여러 음표 추가 선택·해제\n"
            "Ctrl+A : 전체 음표 선택\n"
            "Delete : 선택 음표 일괄 삭제\n\n"
            "음표를 누른 채 위·아래로 끌면 음높이가 바뀌고,\n"
            "좌·우로 끌면 1/4박 단위로 위치가 바뀝니다.\n"
            "타이밍 정리의 '빈 박자 일괄 줄이기'는 선택한 값보다\n"
            "긴 빈 구간을 곡 전체에서 한꺼번에 압축합니다.\n"
            "피아노롤 음표는 도·레·미·파·솔·라·시로 표시됩니다.\n"
            "가사 자동 배치는 한글 한 음절을 음표 하나에 넣으며,\n"
            "띄어쓰기는 음표가 없는 1박 쉼으로 배치하고,\n"
            "음표가 부족하면 같은 음높이로 뒤에 자동 생성합니다.\n"
            "가사를 입력한 뒤 키보드나 빈 피아노롤로 음표를 하나씩 넣으면\n"
            "입력할 때마다 다음 가사 음절이 자동으로 들어갑니다.\n"
            "피아노롤의 빈 곳을 클릭해도 음표가 삽입됩니다.\n"
            "외부 반주 트랙에서 WAV를 별도로 불러와 함께 출력할 수 있습니다.",
        )

    def show_synthesis_design(self):
        messagebox.showinfo(
            "합성 원리",
            "인간 음성 녹음 없이 사인파 가산합성으로 만든 CVVC 음원입니다.\n\n"
            "x(t) = Σ Aₖ(t)·sin(2πfₖt + φₖ) + n(t)\n\n"
            "기본음: 440 Hz(A4), MIDI 음정은 그대로 유지\n"
            "배음: 기본음의 1~36배\n"
            "H1~H2 몸통 0.88배\n"
            "H3~H6 전방 공명 1.22배\n"
            "H7~H10 발음 선명도 1.26배\n"
            "H11~H16 밝은 광택 1.14배\n"
            "H17 이상은 점차 감쇠해 금속성을 억제합니다.\n\n"
            "대표 포먼트(Hz)\n"
            "ㅏ: 980 / 1900 / 4050\n"
            "ㅔ: 610 / 3200 / 4450\n"
            "ㅣ: 360 / 3850 / 4700\n\n"
            "실제 음높이는 올리지 않고 높은 배음과 F2·F3를 강조해\n"
            "더 높고 밝게 들리도록 설계했습니다.\n"
            "자음 어택은 강화하지만 필터 잡음은 낮게 제한합니다.\n"
            "CV 음원 399개 + VC 전이 399개 + 받침 전이 147개\n\n"
            "각 WAV에 사용된 주파수·진폭·위상은\n"
            "voicebank/sine_components.csv에 기록되어 있으며,\n"
            "모음별 36개 배음 진폭은 harmonic_design.csv에 있습니다.",
        )

    def open_sine_table(self):
        path = VOICEBANK_DIR / "sine_components.csv"
        if not path.exists():
            messagebox.showerror("파일 없음", str(path))
            return
        os.startfile(path)

    def open_harmonic_design(self):
        path = VOICEBANK_DIR / "harmonic_design.csv"
        if not path.exists():
            messagebox.showerror("파일 없음", str(path))
            return
        os.startfile(path)


def main():
    root = tk.Tk()
    HanulSynthApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
