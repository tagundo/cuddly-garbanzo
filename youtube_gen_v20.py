# youtube_gen_v20.py

import os, sys, json, shutil, subprocess
from copy import deepcopy
from pathlib import Path
from datetime import datetime

# ---------------- PySide6 imports (auto-install if missing) ----------------
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QGuiApplication
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QMessageBox, QFileDialog,
        QInputDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
        QPushButton, QListWidget, QListWidgetItem, QAbstractItemView,
        QPlainTextEdit, QGroupBox, QLineEdit, QFrame, QScrollArea,
        QCheckBox, QDialog, QTextEdit
    )
except ImportError:
    print("PySide6가 없어 설치를 진행합니다...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PySide6"])
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QGuiApplication
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QMessageBox, QFileDialog,
        QInputDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
        QPushButton, QListWidget, QListWidgetItem, QAbstractItemView,
        QPlainTextEdit, QGroupBox, QLineEdit, QFrame, QScrollArea,
        QCheckBox, QDialog, QTextEdit
    )

from PySide6.QtWidgets import QDialog, QTextEdit

class ImportJsonDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import JSON values")
        self.setMinimumSize(700, 500)
        v = QVBoxLayout(self)
        info = QLabel("JSON 값을 붙여넣거나, 파일에서 불러온 후 Import를 누르세요.")
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText('예) {"songs": {...}, "song_categories": {...}} 또는 곧바로 songs 딕셔너리 형태')
        btns = QHBoxLayout()
        btn_load = QPushButton("Load from file...")
        btn_clear = QPushButton("Clear")
        btn_ok = QPushButton("Import")
        btn_cancel = QPushButton("Cancel")
        btns.addWidget(btn_load)
        btns.addStretch(1)
        btns.addWidget(btn_clear)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        v.addWidget(info)
        v.addWidget(self.edit)
        v.addLayout(btns)

        def on_load():
            fn, _ = QFileDialog.getOpenFileName(self, "Open JSON", "", "JSON (*.json)")
            if not fn:
                return
            try:
                with open(fn, "r", encoding="utf-8-sig") as f:
                    self.edit.setPlainText(f.read())
            except Exception as e:
                QMessageBox.critical(self, "Load error", str(e))

        btn_load.clicked.connect(on_load)
        btn_clear.clicked.connect(lambda: self.edit.clear())
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self.accept)

    def get_text(self) -> str:
        return self.edit.toPlainText()

def _merge_list_unique(base_list, add_list):
    if not isinstance(base_list, list):
        base_list = []
    seen = set(base_list)
    out = list(base_list)
    for x in add_list or []:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out

def merge_data_non_destructive(dst: dict, src: dict) -> dict:
    stats = {
        "songs_added": 0, "groups_added": 0, "characters_added": 0,
        "costumes_added": 0, "mods_added": 0,
        "song_cat_updates": 0, "costume_cat_updates": 0, "char_costume_cat_updates": 0,
        "settings_filled": 0
    }

    for sec, key_stat in [
        ("songs", "songs_added"),
        ("groups", "groups_added"),
        ("characters", "characters_added"),
        ("costumes", "costumes_added"),
        ("mods", "mods_added"),
    ]:
        dst.setdefault(sec, {})
        for k, v in (src.get(sec) or {}).items():
            if k not in dst[sec]:
                dst[sec][k] = v
                stats[key_stat] += 1
            else:
                if isinstance(dst[sec][k], dict) and isinstance(v, dict):
                    for sk, sv in v.items():
                        if sk not in dst[sec][k]:
                            dst[sec][k][sk] = sv

    dst.setdefault("song_categories", {})
    for cat, arr in (src.get("song_categories") or {}).items():
        before = len(dst["song_categories"].get(cat, []))
        dst["song_categories"][cat] = _merge_list_unique(dst["song_categories"].get(cat, []), arr)
        after = len(dst["song_categories"][cat])
        stats["song_cat_updates"] += max(0, after - before)

    dst.setdefault("costume_categories", {})
    for cat, arr in (src.get("costume_categories") or {}).items():
        before = len(dst["costume_categories"].get(cat, []))
        dst["costume_categories"][cat] = _merge_list_unique(dst["costume_categories"].get(cat, []), arr)
        after = len(dst["costume_categories"][cat])
        stats["costume_cat_updates"] += max(0, after - before)

    dst.setdefault("character_costume_categories", {})
    for ch, cmap in (src.get("character_costume_categories") or {}).items():
        dst["character_costume_categories"].setdefault(ch, {})
        for cat, arr in (cmap or {}).items():
            before = len(dst["character_costume_categories"][ch].get(cat, []))
            dst["character_costume_categories"][ch][cat] = _merge_list_unique(
                dst["character_costume_categories"][ch].get(cat, []), arr
            )
            after = len(dst["character_costume_categories"][ch][cat])
            stats["char_costume_cat_updates"] += max(0, after - before)

    dst.setdefault("settings", {})
    for k, v in (src.get("settings") or {}).items():
        if k not in dst["settings"]:
            dst["settings"][k] = v
            stats["settings_filled"] += 1

    return stats

def append_import_log(base_path: str, level: str, message: str, detail: str = ""):
    """
    base_path: 현재 작업 파일 경로(self.data_path)
    같은 폴더에 import.log로 누적 기록
    """
    try:
        p = Path(base_path)
        log_path = p.with_name("import.log")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {message}"
        if detail:
            line += f"\n{detail}"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
# ---------------- Data file path ----------------
DATA_FILE = str(Path(__file__).with_name("youtube_data.json"))

# ---------------- Backup helpers: numbered rotation + atomic write ----------------
def rotate_numbered_backups(json_path: str, max_backups: int = 5):
    """
    Same directory numbered rotation:
      youtube_data_5.json (oldest) removed
      youtube_data_4.json -> _5.json
      ...
      youtube_data_1.json -> _2.json
      youtube_data.json   -> youtube_data_1.json (if exists)
    """
    p = Path(json_path).resolve()

    # 1) delete oldest
    oldest = p.with_name(f"{p.stem}_{max_backups}.json")
    if oldest.exists():
        try:
            oldest.unlink()
        except Exception:
            pass

    # 2) shift: i -> i+1
    for i in range(max_backups - 1, 0, -1):
        src = p.with_name(f"{p.stem}_{i}.json")
        dst = p.with_name(f"{p.stem}_{i+1}.json")
        if src.exists():
            try:
                src.replace(dst)
            except Exception:
                pass

    # 3) create slot 1 from current file (if exists)
    out = None
    if p.exists():
        out = p.with_name(f"{p.stem}_1.json")
        shutil.copy2(p, out)
    return str(out) if out else None  # None if first save (no prior file)

def atomic_write_json(json_path: str, data: dict):
    """
    Write to tmp, flush+fsync, atomic replace to avoid partial writes.
    """
    p = Path(json_path).resolve()
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)

# ---------------- Default data + ensure/migrate ----------------
def get_default_data():
    return {
        "songs": {},
        "groups": {},
        "characters": {},
        "costumes": {},
        "mods": {},
        "song_categories": {"μ's": [], "Aqours": [], "Nijigasaki": [], "Solo": [], "Other": []},
        "costume_categories": {"μ's": [], "Aqours": [], "Nijigasaki": [], "Event": []},
        "character_costume_categories": {},
        "settings": {
            "aspect_ratios": ["16:9", "16:10", "4:3", "21:9"],
            "format_order": ["{playlist}", "{hashtags}", "{japanese}", "{korean}", "{english}"],
            "languages": ["japanese", "korean", "english"],
            "japanese_format": "{song} ({artist}, {mod}, {costume})[{ratio}][スクスタ {type}]",
            "korean_format": "{song} ({artist}, {mod}, {costume})[{ratio}][스쿠스타 {type}]",
            "english_format": "{song} ({artist}, {mod}, {costume})[{ratio}][SIFAS {type}]",
            "keep_mod_selection": False,
            # category-based costume filter
            "enable_costume_category_filter": False,
            "costume_category_whitelist": []
        },
    }

def ensure_data():
    # create if missing
    p = Path(DATA_FILE).resolve()
    if not p.exists():
        atomic_write_json(DATA_FILE, get_default_data())

    # load
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = get_default_data()

    # ensure default keys
    default = get_default_data()
    for k, v in default.items():
        if k not in data:
            data[k] = v
    for k, v in default["settings"].items():
        if k not in data["settings"]:
            data["settings"][k] = v
    if "character_costume_categories" not in data:
        data["character_costume_categories"] = {}

    # migrate old costume_categories["Character"] -> character_costume_categories
    cc = data.get("costume_categories", {})
    if "Character" in cc and isinstance(cc["Character"], dict):
        for ch, lst in cc["Character"].items():
            if not isinstance(lst, list):
                continue
            seen, uniq = set(), []
            for key in lst:
                if key in data.get("costumes", {}) and key not in seen:
                    uniq.append(key)
                    seen.add(key)
            if uniq:
                data["character_costume_categories"].setdefault(ch, {})
                base = data["character_costume_categories"][ch].get("Default", [])
                merged = base + [k for k in uniq if k not in base]
                data["character_costume_categories"][ch]["Default"] = merged
        try:
            del data["costume_categories"]["Character"]
        except Exception:
            pass

    # persist normalized data
    atomic_write_json(DATA_FILE, data)
    return data

def normalize_data(data):
    default = get_default_data()  # 기본 스키마 로드
    out = deepcopy(data) if isinstance(data, dict) else {}
    # 1) 섹션 기본값 채우기
    for k, v in default.items():
        if k not in out:
            out[k] = deepcopy(v)
    # 2) settings 기본키 보정
    s = out.setdefault("settings", {})
    s.setdefault("enable_costume_category_filter", False)
    s.setdefault("costume_category_whitelist", [])
    # 3) 레거시 이관: costume_categories.Character -> character_costume_categories
    cc = out.get("costume_categories", {})
    if isinstance(cc, dict) and "Character" in cc and isinstance(cc["Character"], dict):
        for ch, lst in cc["Character"].items():
            if not isinstance(lst, list):
                continue
            uniq, seen = [], set()
            for key in lst:
                if key in out.get("costumes", {}) and key not in seen:
                    uniq.append(key); seen.add(key)
            base = out.setdefault("character_costume_categories", {}).get(ch, {})
            merged = list(base.get("Default", []))
            for k in uniq:
                if k not in merged:
                    merged.append(k)
            out.setdefault("character_costume_categories", {}).setdefault(ch, {})["Default"] = merged
        try:
            del out["costume_categories"]["Character"]
        except Exception:
            pass
    return out

# ---------------- Editable combo with optional categories ----------------
class EditableComboQt(QWidget):
    """
    A combo with optional category filter (for songs/costumes), CRUD helpers,
    and selection-preserving refresh.
    """
    def __init__(self, label, value_dict, on_update, kind, data, parent=None):
        super().__init__(parent)
        self.value_dict = value_dict
        self.on_update = on_update
        self.kind = kind  # "groups"|"characters"|"songs"|"costumes"
        self.data = data

        root = QVBoxLayout(self)
        title = QLabel(label)
        root.addWidget(title)

        self.category_combo = None
        if kind in ("songs", "costumes"):
            cat_row = QHBoxLayout()
            self.category_combo = QComboBox()
            cat_row.addWidget(QLabel("Category"))
            cat_row.addWidget(self.category_combo)
            root.addLayout(cat_row)
            self.update_categories()
            self.category_combo.currentIndexChanged.connect(self.refresh)

        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setMinimumContentsLength(24)
        row.addWidget(self.combo, 1)

        self.btn_add = QPushButton("+")
        self.btn_edit = QPushButton("✎")
        self.btn_del = QPushButton("✕")
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_edit)
        row.addWidget(self.btn_del)

        if kind in ("songs", "costumes"):
            self.btn_cat = QPushButton("📁")
            row.addWidget(self.btn_cat)

        root.addLayout(row)

        self.btn_add.clicked.connect(self.create_item)
        self.btn_edit.clicked.connect(self.edit_item)
        self.btn_del.clicked.connect(self.delete_item)
        if kind in ("songs", "costumes"):
            self.btn_cat.clicked.connect(self.manage_category)

        self.combo.currentIndexChanged.connect(lambda _: self.on_update())
        self.refresh()

    def get(self):
        return self.combo.currentText().strip()

    def update_categories(self):
        if not self.category_combo:
            return
        cats = ["All"]
        if self.kind == "songs":
            cats += list(self.data["song_categories"].keys())
        else:
            cats += list(self.data["costume_categories"].keys())
        self.category_combo.clear()
        self.category_combo.addItems(cats)

    def _items_from_category(self):
        keys = list(self.value_dict.keys())
        if not self.category_combo:
            return keys
        sel = self.category_combo.currentText()
        if sel == "All" or not sel:
            return keys
        if self.kind == "songs":
            pool = self.data["song_categories"].get(sel, [])
        else:
            pool = self.data["costume_categories"].get(sel, [])
        return [k for k in pool if k in self.value_dict]

    def refresh(self, select_first=True):
        items = self._items_from_category()
        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(items)
        if cur and cur in items:
            self.combo.setCurrentText(cur)
        elif select_first and items:
            self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)

    def _ask_text(self, title, init=""):
        txt, ok = QInputDialog.getText(self, title, title, text=init)
        if not ok:
            return None
        return (txt or "").strip()

    def create_item(self):
        key = self._ask_text("New")
        if not key:
            return
        if key in self.value_dict:
            return

        new = {}
        for f in ("japanese", "korean", "english"):
            v = self._ask_text(f)
            if v is None:
                return
            new[f] = v

        if self.kind in ("groups", "characters"):
            ap = self._ask_text("ArtistPlaylist") or ""
            new["artist_playlist"] = ap
            ht = self._ask_text("tags") or ""
            new["hashtags"] = ht

        if self.kind == "costumes":
            cp = self._ask_text("CostumePlaylist") or ""
            new["costume_playlist"] = cp

        self.value_dict[key] = new

        if self.kind == "songs":
            cats = list(self.data["song_categories"].keys())
            cat = self._ask_text("Category")
            if cat in cats:
                for L in self.data["song_categories"].values():
                    if key in L:
                        L.remove(key)
                self.data["song_categories"][cat].append(key)

        if self.kind == "costumes":
            cat = self._ask_text("Category")
            if cat in self.data["costume_categories"]:
                for L in self.data["costume_categories"].values():
                    if isinstance(L, list) and key in L:
                        L.remove(key)
                self.data["costume_categories"][cat].append(key)
                

        if self.category_combo:
            self.update_categories()
        self.refresh()
        self.on_update()

    def edit_item(self):
        key = self.get()
        if not key:
            return
        item = deepcopy(self.value_dict.get(key, {}))
        if not item:
            return

        new_item = {}
        for f, cur in item.items():
            if f in ("artist_playlist", "costume_playlist", "hashtags"):
                continue
            val = self._ask_text(f, init=str(cur))
            if val is None:
                return
            new_item[f] = val

        if self.kind in ("groups", "characters"):
            ap = self._ask_text("ArtistPlaylist", init=item.get("artist_playlist", "")) or ""
            new_item["artist_playlist"] = ap
            ht = self._ask_text("tags", init=item.get("hashtags", "")) or ""
            new_item["hashtags"] = ht

        if self.kind == "costumes":
            cp = self._ask_text("CostumePlaylist", init=item.get("costume_playlist", "")) or ""
            new_item["costume_playlist"] = cp

        self.value_dict[key] = new_item
        self.refresh(select_first=False)
        self.on_update()

    def delete_item(self):
        key = self.get()
        if not key:
            return
        if QMessageBox.question(self, "Delete", key) != QMessageBox.Yes:
            return
        if key in self.value_dict:
            del self.value_dict[key]
        for L in self.data["song_categories"].values():
            if key in L:
                L.remove(key)
        for d in self.data["costume_categories"].values():
            if isinstance(d, list) and key in d:
                d.remove(key)
        self.refresh()
        self.on_update()



    def refresh(self, select_first=True):
        items = self._items_from_category()

        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(items)
        if cur and cur in items:
            self.combo.setCurrentText(cur)
        elif select_first and items:
            self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)



    def manage_category(self):
        key = self.get()
        if not key:
            return
        if self.kind == "songs":
            cats = list(self.data["song_categories"].keys())
            cat = self._ask_text("Category")
            if cat in cats:
                for L in self.data["song_categories"].values():
                    if key in L:
                        L.remove(key)
                self.data["song_categories"][cat].append(key)
        else:
            cat = self._ask_text("Category")
            if cat in self.data["costume_categories"]:
                for L in self.data["costume_categories"].values():
                    if isinstance(L, list) and key in L:
                        L.remove(key)
                self.data["costume_categories"][cat].append(key)

    def _allowed_costume_categories(self):
        if self.kind != "costumes":
            return None
        s = self.data.get("settings", {})
        if not s.get("enable_costume_category_filter", False):
            return None
        wl = [str(x).strip() for x in s.get("costume_category_whitelist", []) if str(x).strip()]
        return wl or None

    def _costume_in_allowed_categories(self, costume_key, wl):
        if not wl:
            return True
        cc = self.data.get("costume_categories", {})
        for cat in wl:
            arr = cc.get(cat, [])
            if isinstance(arr, list) and costume_key in arr:
                return True
        return False

    def _apply_costume_category_filter(self, keys):
        if self.kind != "costumes":
            return keys
        wl = self._allowed_costume_categories()
        if not wl:
            return keys
        return [k for k in keys if self._costume_in_allowed_categories(k, wl)]

    def refresh(self, select_first=True):
        items = self._items_from_category()
        items = self._apply_costume_category_filter(items)
        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(items)
        if cur and cur in items:
            self.combo.setCurrentText(cur)
        elif select_first and items:
            self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)

# ---------------- Main window ----------------
class YoutubeDescAppQt(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube 설명 생성기 (Qt)")
        # 추가: 현재 작업 파일 경로 상태
        self.data_path = DATA_FILE  # 기본은 스크립트 옆 youtube_data.json

        self.data = ensure_data()
        self.mod_cache = []
        self._charcos_selected = ""  # current selected CharacterCostume

        self._build_menu()
        self._build_ui()
        self.refresh()

        # Size and scroll management
        geo = QGuiApplication.primaryScreen().availableGeometry()
        w = int(geo.width() * 0.9)
        h = int(geo.height() * 0.9)
        self.resize(w, h)
        self.setMaximumSize(geo.width(), geo.height())
        self.setMinimumSize(960, 680)

    # ---------------- Menu ----------------
    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("File")
        act_open = QAction("Open json...", self)
        act_save = QAction("Save", self)
        act_backup = QAction("Backup Data Now", self)
        act_import_values = QAction("Import JSON values...", self)  # 추가
        
        file_menu.addAction(act_open)
        file_menu.addAction(act_save)
        file_menu.addAction(act_backup)
        act_open.triggered.connect(self.open_json)
        act_save.triggered.connect(self.save)
        
        act_backup.triggered.connect(
            lambda: QMessageBox.information(
                self,
                "Backup",
                f"Backup: {rotate_numbered_backups(self.data_path, 5) or 'No previous file'}",
            )
        )
        act_import_values.triggered.connect(self.import_json_values)  # 추가

    # ---------------- UI ----------------
    def _build_ui(self):
        # Build the two-pane layout
        root = QWidget()
        root_layout = QHBoxLayout(root)

        # Left side: Selection/Manage
        left_box = QGroupBox("Selection/Manage")
        left = QVBoxLayout(left_box)

        # Artist Type
        type_row = QHBoxLayout()
        self.atype_combo = QComboBox()
        self.atype_combo.addItems(["groups", "characters"])
        type_row.addWidget(QLabel("Artist Type"))
        type_row.addWidget(self.atype_combo)
        left.addLayout(type_row)

        # Artist selector
        self.artist = EditableComboQt(
            "Artist",
            self.data[self.atype_combo.currentText()],
            self.refresh,
            self.atype_combo.currentText(),
            self.data
        )
        left.addWidget(self.artist)

        # Song selector
        self.song = EditableComboQt(
            "Song",
            self.data["songs"],
            self.refresh,
            "songs",
            self.data
        )
        left.addWidget(self.song)

        # Multi-solo selection (for characters)
        self.solo_box = QGroupBox("Selected Solos")
        vb_solo = QVBoxLayout(self.solo_box)
        self.solo_list = QListWidget()
        self.solo_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        vb_solo.addWidget(self.solo_list)
        solo_btns = QHBoxLayout()
        self.btn_solo_add = QPushButton("Add solo")
        self.btn_solo_del = QPushButton("Remove selected")
        self.btn_solo_clear = QPushButton("Clear")
        solo_btns.addWidget(self.btn_solo_add)
        solo_btns.addWidget(self.btn_solo_del)
        solo_btns.addWidget(self.btn_solo_clear)
        vb_solo.addLayout(solo_btns)
        left.addWidget(self.solo_box)

        self.solo_box.setVisible(self.atype_combo.currentText() == "characters")
        self.btn_solo_add.clicked.connect(self._solo_add)
        self.btn_solo_del.clicked.connect(self._solo_del)
        self.btn_solo_clear.clicked.connect(self._solo_clear)
        self.solo_list.itemSelectionChanged.connect(self.generate)

        # Costume selector (global)
        self.costume = EditableComboQt(
            "Costume",
            self.data["costumes"],
            self.refresh,
            "costumes",
            self.data
        )
        left.addWidget(self.costume)
        btn_no_costume = QPushButton("No Costume")
        btn_no_costume.clicked.connect(lambda: (self.costume.combo.setCurrentIndex(-1), self.refresh()))
        left.addWidget(btn_no_costume)


        # NEW: Costume rarity filter editor
        flt_box = QGroupBox("Costume Filter")
        flt = QVBoxLayout(flt_box)

        self.chk_costume_filter = QCheckBox("Enable category whitelist")
        flt.addWidget(self.chk_costume_filter)

        self.list_costume_cats = QListWidget()
        self.list_costume_cats.setSelectionMode(QAbstractItemView.NoSelection)
        flt.addWidget(self.list_costume_cats, 1)

        btn_save_filter = QPushButton("Save Filter")
        btn_save_filter.clicked.connect(self.save_costume_filter)
        flt.addWidget(btn_save_filter)

        left.addWidget(flt_box)




        # CharacterCostume panel (per-character)
        self.charcos_box = QGroupBox("CharacterCostume (per character)")
        charcos = QVBoxLayout(self.charcos_box)

        # Category row
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("Category"))
        self.charcos_cat_combo = QComboBox()
        cat_row.addWidget(self.charcos_cat_combo, 1)
        self.btn_charcos_cat_add = QPushButton("＋")
        self.btn_charcos_cat_ren = QPushButton("✎")
        self.btn_charcos_cat_del = QPushButton("✕")
        cat_row.addWidget(self.btn_charcos_cat_add)
        cat_row.addWidget(self.btn_charcos_cat_ren)
        cat_row.addWidget(self.btn_charcos_cat_del)
        charcos.addLayout(cat_row)

        # List in category
        self.charcos_list = QListWidget()
        self.charcos_list.setSelectionMode(QAbstractItemView.SingleSelection)
        charcos.addWidget(self.charcos_list)

        sel_row = QHBoxLayout()
        self.btn_charcos_clear_sel = QPushButton("Clear Selection")
        sel_row.addWidget(self.btn_charcos_clear_sel)
        charcos.addLayout(sel_row)

        # Add/remove to category
        add_row = QHBoxLayout()
        self.charcos_add_combo = QComboBox()
        add_row.addWidget(self.charcos_add_combo, 1)
        self.btn_charcos_add = QPushButton("Add to Category")
        self.btn_charcos_remove = QPushButton("Remove from Category")
        add_row.addWidget(self.btn_charcos_add)
        add_row.addWidget(self.btn_charcos_remove)
        charcos.addLayout(add_row)

        left.addWidget(self.charcos_box)

        # Mods
        mod_box = QGroupBox("Mods")
        mod_layout = QVBoxLayout(mod_box)
        self.mods = QListWidget()
        self.mods.setSelectionMode(QAbstractItemView.ExtendedSelection)
        mod_layout.addWidget(self.mods)
        mod_btns = QHBoxLayout()
        btn_add = QPushButton("+")
        btn_edit = QPushButton("✎")
        btn_del = QPushButton("✕")
        mod_btns.addWidget(btn_add)
        mod_btns.addWidget(btn_edit)
        mod_btns.addWidget(btn_del)
        mod_layout.addLayout(mod_btns)
        btn_add.clicked.connect(self.add_mod)
        btn_edit.clicked.connect(self.edit_mod)
        btn_del.clicked.connect(self.del_mod)
        left.addWidget(mod_box)

        # Aspect Ratios
        left.addWidget(self._hline())
        left.addWidget(QLabel("Aspect Ratios"))
        self.ratio = QComboBox()
        left.addWidget(self.ratio)
        btn_edit_ratio = QPushButton("Edit Ratios")
        btn_edit_ratio.clicked.connect(self.edit_ratio)
        left.addWidget(btn_edit_ratio)

        # Video Type
        left.addWidget(self._hline())
        left.addWidget(QLabel("Video Type"))
        self.vtype = QComboBox()
        self.vtype.addItems(["MOD", "MV"])
        left.addWidget(self.vtype)

        # Right side: Preview/Settings
        right_box = QGroupBox("Preview/Settings")
        right = QVBoxLayout(right_box)

        right.addWidget(self._hline())
        lbl_prev = QLabel("Preview")
        font = lbl_prev.font()
        font.setPointSize(12)
        font.setBold(True)
        lbl_prev.setFont(font)
        right.addWidget(lbl_prev)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        right.addWidget(self.out)
        btn_copy = QPushButton("Copy Clipboard")
        btn_copy.clicked.connect(self.copy)
        right.addWidget(btn_copy)

        right.addWidget(self._hline())

        # Line order
        order_box = QGroupBox("Line Order")
        order_layout = QHBoxLayout(order_box)
        self.ol = QListWidget()
        order_layout.addWidget(self.ol, 1)
        ob = QVBoxLayout()
        btn_up = QPushButton("⬆️")
        btn_dn = QPushButton("⬇️")
        btn_sv = QPushButton("💾")
        ob.addWidget(btn_up)
        ob.addWidget(btn_dn)
        ob.addWidget(btn_sv)
        order_layout.addLayout(ob)
        btn_up.clicked.connect(lambda: self.move(-1))
        btn_dn.clicked.connect(lambda: self.move(1))
        btn_sv.clicked.connect(self.save_order)
        right.addWidget(order_box)

        right.addWidget(self._hline())

        # Formats
        ff = QGroupBox("Formats")
        fl = QVBoxLayout(ff)
        self.fes = {}
        for lang in self.data["settings"]["languages"]:
            row = QHBoxLayout()
            row.addWidget(QLabel(lang), 0)
            e = QLineEdit()
            row.addWidget(e, 1)
            self.fes[lang] = e
            fl.addLayout(row)
        btn_fmt_save = QPushButton("Save Formats")
        btn_fmt_save.clicked.connect(self.save_formats)
        fl.addWidget(btn_fmt_save)
        right.addWidget(ff, 1)

        # Assemble root layout
        root_layout.addWidget(left_box, 0)
        root_layout.addWidget(right_box, 1)

        # Wrap central widget in a scroll area (so bottom is always reachable)
        container = QWidget()
        container.setLayout(root_layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        self.setCentralWidget(scroll)

        # Signals
        self.atype_combo.currentIndexChanged.connect(self._on_atype_changed)
        self.vtype.currentIndexChanged.connect(self.generate)
        self.ratio.currentIndexChanged.connect(self.generate)
        self.mods.itemSelectionChanged.connect(self.generate)

        # CharacterCostume signals
        self.charcos_cat_combo.currentIndexChanged.connect(self._refresh_charcos_content)
        self.charcos_list.itemSelectionChanged.connect(self._on_charcos_selected_changed)
        self.btn_charcos_clear_sel.clicked.connect(self._clear_charcos_selection)
        self.btn_charcos_cat_add.clicked.connect(self._charcos_add_category)
        self.btn_charcos_cat_ren.clicked.connect(self._charcos_rename_category)
        self.btn_charcos_cat_del.clicked.connect(self._charcos_delete_category)
        self.btn_charcos_add.clicked.connect(self._charcos_add_to_category)
        self.btn_charcos_remove.clicked.connect(self._charcos_remove_from_category)

    def save_costume_filter(self):
        s = self.data["settings"]
        s["enable_costume_category_filter"] = self.chk_costume_filter.isChecked()
        wl = []
        for i in range(self.list_costume_cats.count()):
            it = self.list_costume_cats.item(i)
            if it.checkState() == Qt.Checked:
                wl.append(it.text())
        s["costume_category_whitelist"] = wl
        self.save()
        self.refresh()

    def _sync_costume_filter_ui(self):
        cats = list(self.data.get("costume_categories", {}).keys())
        s = self.data.get("settings", {})
        wl = set(s.get("costume_category_whitelist", []))

        self.list_costume_cats.blockSignals(True)
        self.list_costume_cats.clear()
        for c in cats:
            it = QListWidgetItem(c)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if c in wl else Qt.Unchecked)
            self.list_costume_cats.addItem(it)
        self.list_costume_cats.blockSignals(False)

        self.chk_costume_filter.blockSignals(True)
        self.chk_costume_filter.setChecked(s.get("enable_costume_category_filter", False))
        self.chk_costume_filter.blockSignals(False)


    def _hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    # ---------------- Events/logic ----------------
    def _on_atype_changed(self):
        at = self.atype_combo.currentText()
        self.artist.value_dict = self.data[at]
        self.artist.kind = at
        if hasattr(self.artist, "update_categories"):
            self.artist.update_categories()
        self.artist.refresh(select_first=True)  # init on type switch
        self.refresh()  # afterwards keep selection in refresh
        self._refresh_solo_box()

    def toggle_keep(self):
        s = self.data["settings"]
        s["keep_mod_selection"] = not s["keep_mod_selection"]
        self.save()
        QMessageBox.information(self, "MOD Keep Toggled", str(s["keep_mod_selection"]))

    def save_mod(self):
        self.mod_cache = [i.text() for i in self.mods.selectedItems()]

    def restore_mod(self):
        if not self.data["settings"].get("keep_mod_selection", False):
            return
        for i in range(self.mods.count()):
            it = self.mods.item(i)
            it.setSelected(it.text() in self.mod_cache)

    # ---------- CharacterCostume helpers ----------
    def _ensure_charcos_min(self, ak):
        cc = self.data["character_costume_categories"].setdefault(ak, {})
        if not cc:
            cc["Default"] = []
        return cc

    def _refresh_charcos_panel(self):
        at = self.atype_combo.currentText()
        ak = self.artist.get()
        enabled = (at == "characters" and bool(ak))
        self.charcos_box.setEnabled(enabled)
        if not enabled:
            self._charcos_selected = ""
            self.charcos_cat_combo.clear()
            self.charcos_list.clear()
            self.charcos_add_combo.clear()
            return

        cc = self._ensure_charcos_min(ak)
        cats = list(cc.keys())
        cur = self.charcos_cat_combo.currentText()
        self.charcos_cat_combo.blockSignals(True)
        self.charcos_cat_combo.clear()
        self.charcos_cat_combo.addItems(cats)
        if cur in cats:
            self.charcos_cat_combo.setCurrentText(cur)
        self.charcos_cat_combo.blockSignals(False)
        self._refresh_charcos_content()

    def _refresh_charcos_content(self):
        at = self.atype_combo.currentText()
        ak = self.artist.get()
        if not (at == "characters" and ak):
            return
        cc = self._ensure_charcos_min(ak)
        cat = self.charcos_cat_combo.currentText() or "Default"
        lst = cc.get(cat, [])

        # list items
        self.charcos_list.blockSignals(True)
        self.charcos_list.clear()
        for k in lst:
            self.charcos_list.addItem(QListWidgetItem(k))
        self.charcos_list.blockSignals(False)




        # candidates (global costumes not in current category)
        s = self.data.get("settings", {})
        use_filter = s.get("enable_costume_category_filter", False)
        wl = [x.strip() for x in s.get("costume_category_whitelist", []) if str(x).strip()] if use_filter else None
        ccats = self.data.get("costume_categories", {})

        def allowed(k):
            if not wl:
                return True
            for c in wl:
                arr = ccats.get(c, [])
                if isinstance(arr, list) and k in arr:
                    return True
            return False

        candidates = []
        for k in self.data["costumes"].keys():
            if k in lst:
                continue
            if allowed(k):
                candidates.append(k)

        self.charcos_add_combo.clear()
        self.charcos_add_combo.addItems(candidates)



    def _on_charcos_selected_changed(self):
        sel = self.charcos_list.selectedItems()
        self._charcos_selected = sel[0].text() if sel else ""
        self.generate()

    def _clear_charcos_selection(self):
        self.charcos_list.clearSelection()
        self._charcos_selected = ""
        self.generate()

    def _charcos_add_category(self):
        at = self.atype_combo.currentText()
        ak = self.artist.get()
        if not (at == "characters" and ak):
            return
        name, ok = QInputDialog.getText(self, "New Category", "Category name")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        cc = self._ensure_charcos_min(ak)
        if name in cc:
            QMessageBox.warning(self, "Exists", "Already exists")
            return
        cc[name] = []
        self.save()
        self._refresh_charcos_panel()
        self.charcos_cat_combo.setCurrentText(name)

    def _charcos_rename_category(self):
        at = self.atype_combo.currentText()
        ak = self.artist.get()
        if not (at == "characters" and ak):
            return
        old = self.charcos_cat_combo.currentText()
        if not old:
            return
        name, ok = QInputDialog.getText(self, "Rename Category", "New name", text=old)
        if not ok:
            return
        name = (name or "").strip()
        if not name or name == old:
            return
        cc = self._ensure_charcos_min(ak)
        if name in cc:
            QMessageBox.warning(self, "Exists", "Already exists")
            return
        cc[name] = cc.pop(old)
        self.save()
        self._refresh_charcos_panel()
        self.charcos_cat_combo.setCurrentText(name)


    def import_json_values(self):
        dlg = ImportJsonDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return

        raw = dlg.get_text().strip()
        if not raw:
            QMessageBox.warning(self, "Import", "입력된 내용이 없습니다.")
            append_import_log(self.data_path, "WARN", "Empty import content")
            return

        # 현재 파일 백업
        rotate_numbered_backups(self.data_path, 5)

        try:
            obj = json.loads(raw)
        except Exception as e:
            QMessageBox.critical(self, "Import", f"JSON 파싱 실패: {e}")
            append_import_log(self.data_path, "ERROR", "JSON parse failed", detail=str(e))
            return

        # 입력이 바로 songs 딕셔너리 형태라면 자동 래핑
        def looks_like_songs_map(d: dict) -> bool:
            if not isinstance(d, dict):
                return False
            # 값들이 언어 3필드를 주로 가진 경우로 간주
            cnt, hit = 0, 0
            for v in list(d.values())[:10]:
                cnt += 1
                if isinstance(v, dict) and any(k in v for k in ("japanese", "korean", "english")):
                    hit += 1
            return cnt > 0 and hit / cnt >= 0.6

        src = obj
        if isinstance(obj, dict) and "songs" not in obj and looks_like_songs_map(obj):
            src = {"songs": obj}

        # normalize_data가 있으면 보강
        try:
            src = normalize_data(src)
        except Exception:
            pass

        # 병합
        try:
            stats = merge_data_non_destructive(self.data, src)
            atomic_write_json(self.data_path, self.data)
            self.refresh()
            msg = (
                "Import 완료\n"
                f"- songs/groups/characters/costumes/mods added: "
                f"{stats['songs_added'] + stats['groups_added'] + stats['characters_added'] + stats['costumes_added'] + stats['mods_added']}\n"
                f"- categories: song +{stats['song_cat_updates']}, costume +{stats['costume_cat_updates']}, char-costume +{stats['char_costume_cat_updates']}\n"
                f"- settings filled: {stats['settings_filled']}"
            )
            QMessageBox.information(self, "Import", msg)
            append_import_log(self.data_path, "INFO", "Import success", detail=msg)
        except Exception as e:
            QMessageBox.critical(self, "Import", f"병합/저장 실패: {e}")
            append_import_log(self.data_path, "ERROR", "Merge/Save failed", detail=str(e))


    def _charcos_delete_category(self):
        at = self.atype_combo.currentText()
        ak = self.artist.get()
        if not (at == "characters" and ak):
            return
        cat = self.charcos_cat_combo.currentText()
        if not cat:
            return
        if QMessageBox.question(self, "Delete Category", cat) != QMessageBox.Yes:
            return
        cc = self._ensure_charcos_min(ak)
        try:
            del cc[cat]
        except Exception:
            pass
        if not cc:
            cc["Default"] = []
        self.save()
        self._refresh_charcos_panel()

    def _charcos_add_to_category(self):
        at = self.atype_combo.currentText()
        ak = self.artist.get()
        if not (at == "characters" and ak):
            return
        cat = self.charcos_cat_combo.currentText() or "Default"
        key = self.charcos_add_combo.currentText().strip()
        if not key:
            return
        cc = self._ensure_charcos_min(ak)
        lst = cc.setdefault(cat, [])
        if key not in lst:
            lst.append(key)
        self.save()
        self._refresh_charcos_content()

    def _charcos_remove_from_category(self):
        at = self.atype_combo.currentText()
        ak = self.artist.get()
        if not (at == "characters" and ak):
            return
        cat = self.charcos_cat_combo.currentText() or "Default"
        sel = self.charcos_list.selectedItems()
        if not sel:
            return
        key = sel[0].text()
        cc = self._ensure_charcos_min(ak)
        lst = cc.setdefault(cat, [])
        if key in lst:
            lst.remove(key)
        self._charcos_selected = ""
        self.save()
        self._refresh_charcos_content()
        self.generate()

    def _refresh_solo_box(self):
        is_char = self.atype_combo.currentText() == "characters"
        self.solo_box.setVisible(is_char)
        if not is_char:
            self.solo_list.clear()

    def _solo_add(self):
        if self.atype_combo.currentText() != "characters":
            return
        k = self.artist.get()
        if not k:
            return
        for i in range(self.solo_list.count()):
            if self.solo_list.item(i).text() == k:
                self.generate()
                return
        self.solo_list.addItem(QListWidgetItem(k))
        self.generate()

    def _solo_del(self):
        sel = self.solo_list.selectedItems()
        for it in sel:
            self.solo_list.takeItem(self.solo_list.row(it))
        self.generate()

    def _solo_clear(self):
        self.solo_list.clear()
        self.generate()

    # ---------- Mods ----------
    def add_mod(self):
        key, ok = QInputDialog.getText(self, "MOD", "Key")
        if not ok:
            return
        key = key.strip()
        if not key or key in self.data["mods"]:
            return

        mi = {}
        for f in ("japanese", "korean", "english"):
            v, ok2 = QInputDialog.getText(self, key, f)
            if not ok2:
                return
            mi[f] = v
        hv = QMessageBox.question(self, "Need Value?", "Need value field?") == QMessageBox.Yes
        mi["has_value"] = hv
        if hv:
            dv, ok3 = QInputDialog.getText(self, "Default", "")
            mi["default_value"] = dv if ok3 else ""
        self.data["mods"][key] = mi
        self.refresh()

    def edit_mod(self):
        sel = self.mods.selectedItems()
        if not sel:
            return
        key = sel[0].text()
        mi = self.data["mods"][key]
        ni = deepcopy(mi)
        for f in ("japanese", "korean", "english"):
            v, ok = QInputDialog.getText(self, key, f, text=mi[f])
            if not ok:
                return
            ni[f] = v
        hv = QMessageBox.question(self, "Need Value?", "Need value field?") == QMessageBox.Yes
        ni["has_value"] = hv
        if hv:
            dv, ok = QInputDialog.getText(self, "Default", "", text=mi.get("default_value", ""))
            ni["default_value"] = dv if ok else ""
        else:
            ni.pop("default_value", None)
        self.data["mods"][key] = ni
        self.refresh()

    def del_mod(self):
        sel = self.mods.selectedItems()
        if not sel:
            return
        key = sel[0].text()
        if QMessageBox.question(self, "Delete", key) != QMessageBox.Yes:
            return
        del self.data["mods"][key]
        self.refresh()

    # ---------- Other UI utilities ----------
    def edit_ratio(self):
        cr = ",".join(self.data["settings"]["aspect_ratios"])
        nr, ok = QInputDialog.getText(self, "Ratios", "Comma-separated", text=cr)
        if ok:
            self.data["settings"]["aspect_ratios"] = [s.strip() for s in nr.split(",") if s.strip()]
            self.refresh()

    def refresh(self):
        self.save_mod()

        # Artist widget (preserve selection; do not force first)
        self.artist.value_dict = self.data[self.atype_combo.currentText()]
        if hasattr(self.artist, "update_categories"):
            self.artist.update_categories()
        self.artist.refresh(select_first=False)

        # Song/Costume widgets
        if hasattr(self.song, "update_categories"):
            self.song.update_categories()
        self.song.refresh(select_first=False)

        if hasattr(self.costume, "update_categories"):
            self.costume.update_categories()
        self.costume.refresh(select_first=False)

        # Mods
        self.mods.clear()
        for k in self.data["mods"]:
            self.mods.addItem(QListWidgetItem(k))
        self.restore_mod()

        # Ratios
        ar = self.data["settings"]["aspect_ratios"]
        self.ratio.blockSignals(True)
        self.ratio.clear()
        self.ratio.addItems(ar)
        if ar and self.ratio.currentIndex() < 0:
            self.ratio.setCurrentIndex(0)
        self.ratio.blockSignals(False)

        # Order
        self.ol.clear()
        for it in self.data["settings"]["format_order"]:
            self.ol.addItem(it)

        # Formats
        for lang, e in self.fes.items():
            e.blockSignals(True)
            e.setText(self.data["settings"].get(f"{lang}_format", ""))
            e.blockSignals(False)

        # CharacterCostume
        self._refresh_solo_box()
        self._refresh_charcos_panel()
        self._refresh_solo_box()



        # Preview
        self._sync_costume_filter_ui()
        self.generate()

    def save_formats(self):
        for lang, e in self.fes.items():
            self.data["settings"][f"{lang}_format"] = e.text()
        self.save()
        self.refresh()

    def move(self, d):
        row = self.ol.currentRow()
        if row < 0:
            return
        new_row = row + d
        if new_row < 0 or new_row >= self.ol.count():
            return
        order = [self.ol.item(i).text() for i in range(self.ol.count())]
        order[row], order[new_row] = order[new_row], order[row]
        self.data["settings"]["format_order"] = order
        self.refresh()
        self.ol.setCurrentRow(new_row)
        self.save()

    def save_order(self):
        self.data["settings"]["format_order"] = [self.ol.item(i).text() for i in range(self.ol.count())]
        self.save()

    # --- 4) 저장(save): self.data_path 기준 백업/저장으로 변경 (검색: def save(self))
    def save(self):
        # 번호 순환 백업 실행 (현재 작업 파일 기준)
        bak = rotate_numbered_backups(self.data_path, max_backups=5)
        try:
            atomic_write_json(self.data_path, self.data)
            print(f"[backup] data: {bak}")
            QMessageBox.information(self, "Backup", f"Backup: {bak or 'No previous file (first save)'}")
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))

    # --- 5) 열기(open_json): ensure_data 제거, normalize_data 사용 + 작업 경로 전환 (검색: def open_json(self))
    def open_json(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open JSON", "", "JSON (*.json)")
        if not fn:
            return
        try:
            # 현재 작업 파일을 먼저 백업
            rotate_numbered_backups(self.data_path, 5)

            # 선택 파일 로드
            with open(fn, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            # 디스크 쓰기 없이 정상화
            normalized = normalize_data(loaded)

            # 작업 데이터/경로 전환
            self.data = normalized
            self.data_path = fn

            # 선택 파일에 원자적 저장(정상화 결과를 반영)
            atomic_write_json(self.data_path, self.data)

            # 화면 갱신
            self.refresh()

        except Exception as e:
            QMessageBox.critical(self, "Open error", str(e))

    # ---------------- Generate output ----------------
    def generate(self):
        at = self.atype_combo.currentText()
        ak = self.artist.get()
        sk = self.song.get()
        sd = self.data["songs"].get(sk, {})
        ck = self.costume.get()
        cd = self.data["costumes"].get(ck, {})
        ar = self.ratio.currentText()
        tp = self.vtype.currentText()
        ms = [it.text() for it in self.mods.selectedItems()]

        # costume playlist
        cpl = (cd.get("costume_playlist") or "").strip()

        # collect artists
        if at == "characters":
            sels = [self.solo_list.item(i).text() for i in range(self.solo_list.count())]
            if not sels and ak:
                sels = [ak]
            ad_list = [self.data["characters"].get(k, {}) for k in sels if k in self.data["characters"]]
            multiple_solo = len(ad_list) >= 2
            apls = [(ad.get("artist_playlist") or "").strip() for ad in ad_list]
            apl = "" if multiple_solo else (apls[0] if apls else "")

            if apl and cpl:
                playlist_line = f"{sels[0]} playlist : {apl} | Costume playlist : {cpl}"
            elif cpl:
                playlist_line = f"Costume playlist : {cpl}"
            elif apl:
                playlist_line = f"{sels[0]} playlist : {apl}"
            else:
                playlist_line = ""

            def artist_str(lng):
                names = []
                for k in sels:
                    d = self.data["characters"].get(k, {})
                    names.append(d.get(lng, k))
                return ", ".join(names)

            extra_ht = " ".join([ad.get("hashtags", "") for ad in ad_list if ad.get("hashtags")])
        else:
            ad = self.data.get("groups", {}).get(ak, {})
            apl = (ad.get("artist_playlist") or "").strip()
            if apl and cpl:
                playlist_line = f"{ak} playlist : {apl} | Costume playlist : {cpl}"
            elif cpl:
                playlist_line = f"Costume playlist : {cpl}"
            elif apl:
                playlist_line = f"{ak} playlist : {apl}"
            else:
                playlist_line = ""
            def artist_str(lng):
                return ad.get(lng, ak)
            extra_ht = ad.get("hashtags", "")

        # mods string (optional)
        def mod_str(lng):
            arr = []
            for m in ms:
                md = self.data["mods"].get(m)
                if not md:
                    continue
                nm = md.get(lng, m)
                if md.get("has_value"):
                    v = md.get("default_value", "")
                    arr.append(f"{nm}({v})" if v else nm)
                else:
                    arr.append(nm)
            return ", ".join(arr)

        # costume localized
        def cos_str(lng):
            nm = cd.get(lng, "")
            if not nm:
                return ""
            if lng == "japanese":
                return f"{nm}衣装"
            if lng == "korean":
                return f"{nm} 의상"
            return f"{nm} Costume"

        # hashtags
        ht = "#スクスタ #SIFAS #스쿠스타 #lovelive #ラブライブ"
        if tp == "MOD":
            ht += " #MOD"
        if extra_ht:
            ht += " " + extra_ht

        vars_map = {
            "playlist": playlist_line,
            "hashtags": ht
        }

        for lng in self.data["settings"]["languages"]:
            fmt = self.data["settings"].get(f"{lng}_format", "")
            mp = {
                "song": sd.get(lng, sk),
                "artist": artist_str(lng),
                "mod": mod_str(lng),
                "costume": cos_str(lng),
                "ratio": f"[{ar}]" if ar else "",
                "type": tp
            }
            try:
                line = fmt.format(**mp)
                line = line.replace("(, ", "(").replace(", )", ")")
                line = line.replace("()", "").replace(", ,", ",").strip()
            except Exception:
                line = "Format Error"
            vars_map[lng] = line

        out_lines = []
        for item in self.data["settings"]["format_order"]:
            key = item.strip("{}")
            if vars_map.get(key):
                out_lines.append(vars_map[key])
        self.out.setPlainText("\n".join(out_lines))

    def copy(self):
        c = self.out.toPlainText().strip()
        if not c:
            return
        QGuiApplication.clipboard().setText(c)
        QMessageBox.information(self, "Copied", "Copied to clipboard")

# ---------------- main ----------------
def main():
    app = QApplication(sys.argv)
    w = YoutubeDescAppQt()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
