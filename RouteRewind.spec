# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller RouteRewind.spec --noconfirm
block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('web', 'web'), ('assets', 'assets')],
    hiddenimports=['main_window', 'splash', 'parsers', 'report', 'track',
                   'offline', 'offline_ui', 'pmtiles_extract',
                   'pdfplumber', 'openpyxl', 'docx', 'dateutil', 'xlrd'],
    excludes=['tkinter', 'pandas', 'numpy.tests', 'matplotlib', 'tzdata'],
    cipher=block_cipher,
)
# Le cartelle QML di Qt non servono (l'interfaccia usa i widget): toglierle riduce il
# pacchetto di centinaia di file ed evita nomi di file non accettati da MakeAppx.
a.datas = [d for d in a.datas if not d[0].replace('\\', '/').startswith('PySide6/qml/')]
a.binaries = [b for b in a.binaries if not b[0].replace('\\', '/').startswith('PySide6/qml/')]
# Il modello vuoto di python-docx contiene "[Content_Types].xml", nome riservato nei
# pacchetti MSIX. L'app legge soltanto file Word esistenti, quindi il modello non serve.
a.datas = [d for d in a.datas if '[Content_Types]' not in d[0]]
# Anche i nomi con "+" (es. tzdata/zoneinfo/Etc/GMT+1) non sono accettati da MakeAppx;
# l'app usa il fuso orario di Windows e non ha bisogno del database tzdata.
a.datas = [d for d in a.datas if '+' not in d[0] and not d[0].replace('\\', '/').startswith('tzdata/')]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='RouteRewind',
    icon='assets/icon.ico',
    console=False,
    version='packaging/version_info.txt',
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name='RouteRewind')
