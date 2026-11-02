# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G0-B: editor SQL nativo de QGIS (ver README.md). Uso: python editor_probe.py en el Python de QGIS"""
import os, sys, json
os.environ["QT_QPA_PLATFORM"]="offscreen"
from qgis.core import QgsApplication, Qgis
app=QgsApplication([], True); app.initQgis()
out={"qgis": Qgis.version()}
from qgis.PyQt.QtCore import QT_VERSION_STR
out["qt"]=QT_VERSION_STR
try:
    from qgis.gui import QgsCodeEditorSQL
    e=QgsCodeEditorSQL()
    out["QgsCodeEditorSQL"]=True
    base=[c.__name__ for c in type(e).__mro__][:5]; out["mro"]=base
    text="-- ñandú\nCREATE TABLE t AS SELECT 1;\nSELECT * FROM t;"
    e.setText(text)
    out["roundtrip"]= e.text()==text
    # selección y cursor (API QScintilla)
    e.setSelection(1,0,1,10); out["selectedText"]=e.selectedText()
    e.setCursorPosition(2,3); out["cursor"]=list(e.getCursorPosition())
    out["positionFromLineIndex(2,0)"]=e.positionFromLineIndex(2,0)
    # QScintilla trabaja en bytes UTF-8: comparar con offset en caracteres
    out["char_offset_line2"]=len("-- ñandú\nCREATE TABLE t AS SELECT 1;\n")
    out["byte_offset_line2"]=len("-- ñandú\nCREATE TABLE t AS SELECT 1;\n".encode())
    for m in ["setFieldNames","setLineNumbersVisible","setFoldingVisible","clearWarnings","addWarning","setLanguage","language"]:
        out[m]=hasattr(e,m)
    try: e.addWarning(1,"prueba"); out["addWarning_ok"]=True
    except Exception as ex: out["addWarning_ok"]=repr(ex)
except Exception as ex:
    out["QgsCodeEditorSQL"]=repr(ex)
print(json.dumps(out, ensure_ascii=False, indent=1))
