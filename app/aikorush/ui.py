"""La fenêtre d'AikoRush."""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import __version__
from .jobs import Options, Result, Runner, needed_space
from .probe import Clip, assign_names, clean_camera, find_media, fmt_duration, probe
from .theme import ACCENT, ON_ACCENT, css, theme

COLS = ["", "Fichier", "Caméra", "Tourné le", "Durée", "Nouveau nom"]


class Bridge(QObject):
    """Relaie vers l'interface ce qui se passe dans les fils de travail."""
    scanned = Signal(list)
    scan_progress = Signal(int, int)
    progress = Signal(float, str)
    finished = Signal(object)


def human_size(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024 or unit == "To":
            return f"{n:.0f} {unit}" if unit in ("o", "Ko") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)


class DropArea(QFrame):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("dropArea")
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        big = QLabel("Glisse un dossier de rushs ici")
        big.setObjectName("dropTitle")
        big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        small = QLabel("ou clique pour le choisir · carte SD, disque ou dossier, sous-dossiers compris")
        small.setObjectName("hint")
        small.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(big)
        lay.addWidget(small)
        lay.addStretch(1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        self.clicked.emit()

    def set_hot(self, on: bool):
        self.setProperty("hot", on)
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AikoRush")
        self.resize(940, 640)
        self.setMinimumSize(780, 520)
        self.setAcceptDrops(True)

        self.clips: list[Clip] = []
        self.sources: list[Path] = []
        self.out_dir: Path | None = None
        self.runner: Runner | None = None
        self.last_result: Result | None = None
        self.bridge = Bridge()
        self.bridge.scanned.connect(self._scanned)
        self.bridge.scan_progress.connect(lambda i, n: self.status.setText(f"Analyse des rushs… {i}/{n}"))
        self.bridge.progress.connect(self._progress)
        self.bridge.finished.connect(self._finished)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        head = QHBoxLayout()
        title = QLabel("AikoRush")
        title.setObjectName("title")
        sub = QLabel("Préparation des rushs")
        sub.setObjectName("hint")
        self.add_btn = QPushButton("Ajouter un dossier…")
        self.add_btn.setObjectName("ghost")
        self.add_btn.clicked.connect(self._choose_folder)
        self.clear_btn = QPushButton("Vider")
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.clicked.connect(self._clear)
        head.addWidget(title)
        head.addSpacing(10)
        head.addWidget(sub)
        head.addStretch(1)
        head.addWidget(self.add_btn)
        head.addWidget(self.clear_btn)
        root.addLayout(head)

        self.stack = QStackedWidget()
        self.drop = DropArea()
        self.drop.clicked.connect(self._choose_folder)
        self.stack.addWidget(self.drop)

        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(12)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.SelectedClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 34)
        for i in (2, 3, 4):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.itemChanged.connect(self._item_changed)
        pl.addWidget(self.table, 1)

        opts = QFrame()
        opts.setObjectName("card")
        og = QVBoxLayout(opts)
        og.setContentsMargins(14, 10, 14, 10)
        og.setSpacing(8)
        row1 = QHBoxLayout()
        row1.setSpacing(22)
        self.cb_copy = QCheckBox("Copier et renommer")
        self.cb_proxy = QCheckBox("Proxys ProRes")
        self.cb_audio = QCheckBox("Audio séparé (WAV)")
        self.cb_sil = QCheckBox("Repérer les silences")
        for cb in (self.cb_copy, self.cb_proxy, self.cb_audio, self.cb_sil):
            cb.setChecked(True)
            cb.toggled.connect(self._refresh_summary)
            row1.addWidget(cb)
        row1.addStretch(1)
        self.cb_copy.setToolTip("Copie tes rushs dans « Rushs/ » avec un nom date_caméra_numéro. Les originaux ne bougent pas.")
        self.cb_proxy.setToolTip("ProRes Proxy 1080p max, dans « Rushs/Proxy/ » : DaVinci Resolve les relie tout seul.")
        self.cb_audio.setToolTip("L'audio de chaque vidéo en WAV 48 kHz / 24 bits, dans « Audio/ ».")
        self.cb_sil.setToolTip("Marqueurs dans une timeline Resolve + liste des silences (CSV et rapport).")
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        lab = QLabel("Un silence, c'est en dessous de")
        lab.setObjectName("hint")
        self.sp_db = QSpinBox()
        self.sp_db.setRange(-70, -10)
        self.sp_db.setValue(-35)
        self.sp_db.setSuffix(" dB")
        self.sp_db.setFixedWidth(118)
        self.sp_db.setToolTip("En dessous de ce niveau, c'est considéré comme du silence.")
        lab2 = QLabel("pendant au moins")
        lab2.setObjectName("hint")
        self.sp_min = QDoubleSpinBox()
        self.sp_min.setRange(0.3, 10)
        self.sp_min.setDecimals(1)
        self.sp_min.setSingleStep(0.5)
        self.sp_min.setValue(1.0)
        self.sp_min.setSuffix(" s")
        self.sp_min.setFixedWidth(100)
        self.sp_min.setToolTip("Durée minimale d'un silence pour être repéré.")
        for w in (lab, self.sp_db, lab2, self.sp_min):
            row2.addWidget(w)
        row2.addStretch(1)
        self.sil_row = [lab, self.sp_db, lab2, self.sp_min]
        self.cb_sil.toggled.connect(lambda on: [w.setEnabled(on) for w in self.sil_row])
        og.addLayout(row1)
        og.addLayout(row2)
        pl.addWidget(opts)

        dest = QHBoxLayout()
        dl = QLabel("Dossier de sortie")
        dl.setObjectName("hint")
        self.dest_label = QLabel("—")
        self.dest_label.setObjectName("path")
        change = QPushButton("Changer…")
        change.setObjectName("ghost")
        change.clicked.connect(self._choose_dest)
        dest.addWidget(dl)
        dest.addWidget(self.dest_label, 1)
        dest.addWidget(change)
        pl.addLayout(dest)
        self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        root.addWidget(self.bar)

        foot = QHBoxLayout()
        self.status = QLabel(f"AikoRush {__version__}")
        self.status.setObjectName("hint")
        self.open_btn = QPushButton("Ouvrir le dossier")
        self.open_btn.setObjectName("ghost")
        self.open_btn.clicked.connect(self._open_output)
        self.cancel_btn = QPushButton("Annuler")
        self.cancel_btn.setObjectName("ghost")
        self.cancel_btn.clicked.connect(self._cancel)
        self.go_btn = QPushButton("Préparer")
        self.go_btn.setObjectName("primary")
        self.go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.go_btn.clicked.connect(self._start)
        foot.addWidget(self.status, 1)
        foot.addWidget(self.open_btn)
        foot.addWidget(self.cancel_btn)
        foot.addWidget(self.go_btn)
        root.addLayout(foot)

        self.apply_theme()
        self._set_state("empty")

    # ------------------------------------------------------------ thème

    def apply_theme(self):
        t = theme()
        self.setStyleSheet(f"""
            QWidget {{ background: {css(t['bg'])}; color: {css(t['text'])}; font-size: 13px; }}
            QLabel {{ background: transparent; }}
            QLabel#title {{ font-size: 18px; font-weight: 700; }}
            QLabel#hint {{ color: {css(t['subtext'])}; font-size: 12px; }}
            QLabel#path {{ color: {css(t['text'])}; font-size: 12px; }}
            QLabel#dropTitle {{ font-size: 17px; font-weight: 600; }}
            QFrame#dropArea {{ background: {css(t['surface'])}; border: 1.5px dashed {css(t['line'])};
                              border-radius: 16px; }}
            QFrame#dropArea[hot="true"] {{ border: 2px solid {css(ACCENT)}; }}
            QFrame#card {{ background: {css(t['surface'])}; border: 1px solid {css(t['line'])}; border-radius: 10px; }}
            QFrame#card QWidget {{ background: transparent; }}
            QTableWidget {{ background: {css(t['bg'])}; border: 1px solid {css(t['line'])}; border-radius: 10px;
                            gridline-color: transparent; }}
            QTableWidget::item {{ border-bottom: 1px solid {css(t['line'])}; padding: 0 6px; }}
            QHeaderView::section {{ background: {css(t['bg'])}; color: {css(t['subtext'])}; border: none;
                                   border-bottom: 1px solid {css(t['line'])}; padding: 6px; font-size: 11px;
                                   font-weight: 600; }}
            QPushButton#primary {{ background: {css(ACCENT)}; color: {css(ON_ACCENT)}; border: none; border-radius: 8px;
                                  padding: 9px 18px; font-weight: 700; }}
            QPushButton#primary:disabled {{ background: {css(t['surface'])}; color: {css(t['subtext'])}; }}
            QPushButton#ghost {{ background: transparent; color: {css(t['text'])}; border: 1px solid {css(t['line'])};
                                border-radius: 8px; padding: 7px 14px; }}
            QPushButton#ghost:hover {{ border-color: {css(ACCENT)}; }}
            QProgressBar {{ background: {css(t['surface'])}; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {css(ACCENT)}; border-radius: 2px; }}
            QCheckBox {{ background: transparent; spacing: 7px; }}
            QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1.5px solid {css(t['subtext'])}; }}
            QCheckBox::indicator:checked {{ background: {css(ACCENT)}; border-color: {css(ACCENT)};
                                           image: none; }}
            QCheckBox:disabled {{ color: {css(t['subtext'])}; }}
            QSpinBox, QDoubleSpinBox {{ background: {css(t['bg'])}; border: 1px solid {css(t['line'])};
                                       border-radius: 6px; padding: 3px 6px; }}
        """)

    # ------------------------------------------------------------ états

    def _set_state(self, state: str):
        self.state = state
        running = state in ("scanning", "running")
        self.stack.setCurrentIndex(0 if state == "empty" else 1)
        self.add_btn.setVisible(state not in ("empty",))
        self.clear_btn.setVisible(state in ("ready", "done"))
        self.add_btn.setEnabled(not running)
        self.cancel_btn.setVisible(state == "running")
        self.open_btn.setVisible(state == "done" and self.out_dir is not None)
        self.go_btn.setVisible(state != "empty")
        self.go_btn.setEnabled(state in ("ready", "done") and any(c.selected for c in self.clips))
        self.table.setEnabled(not running)
        for w in (self.cb_copy, self.cb_proxy, self.cb_audio, self.cb_sil):
            w.setEnabled(not running)
        if state == "empty":
            self.bar.setValue(0)
            self.status.setText(f"AikoRush {__version__}")

    # ------------------------------------------------------------ ajout de rushs

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and self.state not in ("scanning", "running"):
            e.acceptProposedAction()
            self.drop.set_hot(True)

    def dragLeaveEvent(self, _):
        self.drop.set_hot(False)

    def dropEvent(self, e):
        self.drop.set_hot(False)
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.add_sources(paths)

    def _choose_folder(self):
        if self.state in ("scanning", "running"):
            return
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier de rushs")
        if folder:
            self.add_sources([Path(folder)])

    def add_sources(self, paths: list[Path]):
        self.sources += paths
        if self.out_dir is None:
            first = paths[0]
            base = first if first.is_dir() else first.parent
            self.out_dir = base.parent / f"{base.name} - AikoRush"
        self._set_state("scanning")
        self.stack.setCurrentIndex(1)
        known = {c.path for c in self.clips}

        def work():
            files = [f for f in find_media(paths) if f not in known]
            if self.out_dir is not None:
                files = [f for f in files if self.out_dir not in f.parents]
            out = []
            for i, f in enumerate(files, 1):
                self.bridge.scan_progress.emit(i, len(files))
                out.append(probe(f))
            self.bridge.scanned.emit(out)

        threading.Thread(target=work, daemon=True).start()

    def _scanned(self, new: list):
        self.clips += new
        assign_names(self.clips)
        self._fill_table()
        if not self.clips:
            QMessageBox.information(self, "AikoRush", "Aucune vidéo ni aucun audio trouvé dans ce dossier.")
            self._clear()
            return
        self._set_state("ready")
        self._refresh_summary()

    def _clear(self):
        self.clips, self.sources, self.out_dir, self.last_result = [], [], None, None
        self.table.setRowCount(0)
        self._set_state("empty")

    # ------------------------------------------------------------ tableau

    def _fill_table(self):
        self.table.blockSignals(True)
        t = theme()
        clips = sorted(self.clips, key=lambda c: (c.created, c.path.name))
        self.clips = clips
        self.table.setRowCount(len(clips))
        for r, c in enumerate(clips):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked if c.selected else Qt.CheckState.Unchecked)
            if c.error:
                check.setFlags(Qt.ItemFlag.NoItemFlags)
            name = QTableWidgetItem(c.path.name + (f"  — {c.error}" if c.error else ""))
            name.setToolTip(str(c.path))
            cam = QTableWidgetItem(c.camera)
            cam.setToolTip("Double-clic pour changer le nom de la caméra")
            date = QTableWidgetItem(c.created.strftime("%d/%m/%Y %H:%M"))
            kind = "🎙 " if c.kind == "audio" else ""
            dur = QTableWidgetItem(kind + fmt_duration(c.duration))
            new = QTableWidgetItem(c.new_name + c.path.suffix if c.selected else "—")
            for col, item in enumerate((check, name, cam, date, dur, new)):
                if col not in (0, 2):
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if not c.selected:
                    item.setForeground(t["subtext"])
                self.table.setItem(r, col, item)
            self.table.item(r, 5).setForeground(t["accent_text"] if c.selected else t["subtext"])
        self.table.blockSignals(False)

    def _item_changed(self, item: QTableWidgetItem):
        r, col = item.row(), item.column()
        if r >= len(self.clips):
            return
        c = self.clips[r]
        if col == 0:
            c.selected = item.checkState() == Qt.CheckState.Checked
        elif col == 2:
            c.camera = clean_camera(item.text())
        else:
            return
        assign_names(self.clips)
        self._fill_table()
        self._refresh_summary()

    def _options(self) -> Options:
        return Options(copy=self.cb_copy.isChecked(), proxy=self.cb_proxy.isChecked(),
                       audio=self.cb_audio.isChecked(), silences=self.cb_sil.isChecked(),
                       threshold_db=self.sp_db.value(), min_silence=self.sp_min.value())

    def _refresh_summary(self):
        if self.state not in ("ready", "done"):
            return
        sel = [c for c in self.clips if c.selected]
        need = needed_space(self.clips, self._options())
        total = sum(c.duration for c in sel)
        self.go_btn.setText(f"Préparer {len(sel)} rush{'s' if len(sel) > 1 else ''}")
        self.go_btn.setEnabled(bool(sel) and any(
            (self.cb_copy.isChecked(), self.cb_proxy.isChecked(), self.cb_audio.isChecked(), self.cb_sil.isChecked())))
        self.status.setText(f"{len(sel)} fichier(s) · {fmt_duration(total)} · environ {human_size(need)} à écrire")
        fm = QFontMetrics(self.dest_label.font())
        self.dest_label.setText(fm.elidedText(str(self.out_dir), Qt.TextElideMode.ElideMiddle, 560))
        self.dest_label.setToolTip(str(self.out_dir))

    def _choose_dest(self):
        folder = QFileDialog.getExistingDirectory(self, "Où ranger les rushs préparés ?",
                                                  str(self.out_dir.parent if self.out_dir else Path.home()))
        if folder:
            self.out_dir = Path(folder)
            self._refresh_summary()

    # ------------------------------------------------------------ traitement

    def _start(self):
        opt = self._options()
        assert self.out_dir is not None
        need = needed_space(self.clips, opt)
        probe_dir = self.out_dir
        while not probe_dir.exists() and probe_dir.parent != probe_dir:
            probe_dir = probe_dir.parent
        try:
            free = shutil.disk_usage(probe_dir).free
        except OSError:
            free = need + 1
        if free < need:
            ans = QMessageBox.warning(
                self, "AikoRush",
                f"Il faut environ {human_size(need)} et il reste {human_size(free)} sur ce disque.\n\n"
                "Continuer quand même ?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._set_state("running")
        self.bar.setValue(0)
        self.runner = Runner(self.clips, opt, self.out_dir,
                             progress=lambda f, txt: self.bridge.progress.emit(f, txt),
                             finished=lambda r: self.bridge.finished.emit(r))
        self.runner.start()

    def _progress(self, f: float, text: str):
        self.bar.setValue(int(f * 1000))
        self.status.setText(f"{int(f * 100)} % · {text}")

    def _cancel(self):
        if self.runner:
            self.runner.cancel()
            self.status.setText("Annulation…")

    def _finished(self, result: Result):
        self.last_result = result
        self.runner = None
        cancelled = result.errors[:1] == ["Annulé"]
        n_sil = sum(len(v) for v in result.silences.values())
        if cancelled:
            self.status.setText("Annulé. Ce qui était terminé est conservé.")
        else:
            msg = f"✓ Terminé : {result.done} rush{'s' if result.done > 1 else ''} préparé{'s' if result.done > 1 else ''}"
            if self.cb_sil.isChecked():
                msg += f" · {n_sil} silence{'s' if n_sil > 1 else ''} repéré{'s' if n_sil > 1 else ''}"
            if result.errors:
                msg += f" · {len(result.errors)} problème(s), voir Lisez-moi.txt"
            self.status.setText(msg)
            self.bar.setValue(1000)
        self._set_state("done")
        self._refresh_summary_after_done()

    def _refresh_summary_after_done(self):
        sel = [c for c in self.clips if c.selected]
        self.go_btn.setText(f"Relancer ({len(sel)})")

    def _open_output(self):
        if self.out_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.out_dir)))

    def closeEvent(self, e):
        if self.state == "running":
            ans = QMessageBox.question(self, "AikoRush", "Un traitement est en cours. Arrêter et quitter ?")
            if ans != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            if self.runner:
                self.runner.cancel()
        e.accept()
