"""Disc selection keeps playlist identity when embedded rows move."""

from types import SimpleNamespace
import os
import unittest

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtWidgets import QApplication, QPlainTextEdit, QTableWidget, QTableWidgetItem, QToolButton

from src.core import MPLS_INFO_LABELS, REMUX_LABELS
from src.runtime.gui_runtime_classes.disc_table_widget import DiscTableWidget
from src.runtime.gui_runtime_split.configuration_and_modes import ConfigurationModesMixin
from src.runtime.gui_runtime_split.remux_and_episode_layout import RemuxEpisodeLayoutMixin


class DiscSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_move_and_uncheck_keep_editors_attached_to_the_selected_disc(self):
        table = DiscTableWidget()
        table.blockSignals(True)
        table.setColumnCount(4)
        table.setRowCount(3)
        for row, folder in enumerate(('/disc-a', '/disc-b', '/disc-c')):
            item = QTableWidgetItem(folder)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            table.setItem(row, 0, item)
            playlists = QTableWidget(1, len(MPLS_INFO_LABELS))
            playlists.setItem(0, 0, QTableWidgetItem('00001.mpls'))
            main = QToolButton()
            main.setCheckable(True)
            main.setChecked(True)
            playlists.setCellWidget(0, MPLS_INFO_LABELS.index('main'), main)
            table.setCellWidget(row, 2, playlists)
            table.setCellWidget(row, 3, QPlainTextEdit(folder + ' edited command'))
            table.setRowHeight(row, 30)
        table.sync_selection()
        table.blockSignals(False)
        table.setCurrentCell(0, 0)
        changes = []
        table.discsChanged.connect(lambda: changes.append(True))
        event = SimpleNamespace(
            source=lambda: table,
            position=lambda: QPointF(10, 1000),
            ignore=lambda: None,
            setDropAction=lambda action: None,
            accept=lambda: None,
        )
        table.dropEvent(event)
        self.app.processEvents()
        self.assertEqual([table.item(row, 0).text() for row in range(3)],
                         ['/disc-b', '/disc-c', '/disc-a'])
        self.assertEqual([table.cellWidget(row, 3).toPlainText() for row in range(3)],
                         ['/disc-b edited command', '/disc-c edited command', '/disc-a edited command'])
        table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(table.cellWidget(0, 2).isEnabled())
        owner = SimpleNamespace(table1=table)
        selected = ConfigurationModesMixin.get_selected_mpls_no_ext(owner)
        self.assertEqual(selected, [
            (folder, os.path.normpath(folder + '/BDMV/PLAYLIST/00001'))
            for folder in ('/disc-c', '/disc-a')
        ])
        self.assertEqual(len(changes), 2)

        outputs = QTableWidget(6, len(REMUX_LABELS))
        bdmv_col = REMUX_LABELS.index('bdmv_index')
        output_col = REMUX_LABELS.index('output_name')
        for row in range(6):
            folder = ('/disc-a', '/disc-b', '/disc-c')[row // 2]
            item = QTableWidgetItem(str(row // 2 + 1))
            item.setData(Qt.ItemDataRole.UserRole, os.path.normpath(folder + '/BDMV/PLAYLIST/00001'))
            outputs.setItem(row, bdmv_col, item)
            outputs.setItem(row, output_col, QTableWidgetItem(f'{folder} edited episode {row % 2 + 1}'))
        owner.table2 = outputs
        owner.get_selected_function_id = lambda: 3
        owner.get_selected_mpls_no_ext = lambda: ConfigurationModesMixin.get_selected_mpls_no_ext(owner)
        owner._bdmv_index_for_table1_folder_norm = lambda path: (
            RemuxEpisodeLayoutMixin._bdmv_index_for_table1_folder_norm(owner, path))
        RemuxEpisodeLayoutMixin._align_output_rows_to_selected_discs(owner)
        self.assertEqual([outputs.item(row, output_col).text() for row in range(outputs.rowCount())], [
            f'{folder} edited episode {episode}'
            for folder in ('/disc-c', '/disc-a') for episode in (1, 2)
        ])
        self.assertEqual([outputs.item(row, bdmv_col).text() for row in range(outputs.rowCount())],
                         ['2', '2', '3', '3'])
        table.horizontalHeader().sectionClicked.emit(0)
        self.assertEqual([table.item(row, 0).text() for row in range(3)],
                         ['/disc-a', '/disc-b', '/disc-c'])
        table.horizontalHeader().sectionClicked.emit(0)
        self.assertEqual([table.item(row, 0).text() for row in range(3)],
                         ['/disc-c', '/disc-b', '/disc-a'])
        self.assertEqual(table.item(1, 0).checkState(), Qt.CheckState.Unchecked)
        outputs.close()
        outputs.deleteLater()
        table.close()
        table.deleteLater()
