"""
Diagnostica: se MakeAppx rifiuta il pacchetto senza dire quale file, cerca il file
colpevole per bisezione (crea pacchetti di prova con metà dei file alla volta).
Uso: python tools/find_bad_msix_file.py "<percorso makeappx.exe>" dist/RouteRewind
"""
import os
import shutil
import subprocess
import sys
import tempfile

makeappx, src = sys.argv[1], sys.argv[2]
always = {"AppxManifest.xml", "RouteRewind.exe"}
files = []
for root, _, names in os.walk(src):
    for n in names:
        rel = os.path.relpath(os.path.join(root, n), src)
        if rel not in always and not rel.startswith("Assets" + os.sep):
            files.append(rel)
files.sort()
print("File da verificare:", len(files), flush=True)


def ok(subset) -> bool:
    tmp = tempfile.mkdtemp()
    try:
        d = os.path.join(tmp, "pkg")
        shutil.copytree(os.path.join(src, "Assets"), os.path.join(d, "Assets"))
        for a in always:
            shutil.copy2(os.path.join(src, a), os.path.join(d, a))
        for rel in subset:
            dst = os.path.join(d, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(src, rel), dst)
        r = subprocess.run([makeappx, "pack", "/o", "/d", d, "/p", os.path.join(tmp, "t.msix")],
                           capture_output=True, text=True)
        return r.returncode == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if ok([]):
    print("Pacchetto minimo (manifest, exe, Assets): OK", flush=True)
else:
    print("Anche il pacchetto minimo fallisce: il problema è nel manifest o nell'exe", flush=True)
    sys.exit(0)

bad = files
while len(bad) > 1:
    half = bad[: len(bad) // 2]
    bad = half if not ok(half) else bad[len(bad) // 2:]
    print(f"Restano {len(bad)} file sospetti", flush=True)
if bad and not ok(bad):
    print("FILE RIFIUTATO DA MAKEAPPX:", bad[0], "dimensione", os.path.getsize(os.path.join(src, bad[0])), flush=True)
else:
    print("Nessun singolo file colpevole: il problema dipende da una combinazione di file", flush=True)
