@echo off
REM ===== Build di RouteRewind per Windows =====
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller pillow || goto :err

REM Leaflet e motore delle mappe offline in locale: servono per funzionare senza Internet
if not exist web\leaflet mkdir web\leaflet
curl -L -o web\leaflet\leaflet.js  https://unpkg.com/leaflet@1.9.4/dist/leaflet.js
curl -L -o web\leaflet\leaflet.css https://unpkg.com/leaflet@1.9.4/dist/leaflet.css
if not exist web\leaflet\images mkdir web\leaflet\images
if not exist web\lib mkdir web\lib
curl -L -o web\lib\protomaps-leaflet.js https://unpkg.com/protomaps-leaflet@5.1.0/dist/protomaps-leaflet.js
for %%f in (layers.png layers-2x.png marker-icon.png marker-icon-2x.png marker-shadow.png) do curl -L -o web\leaflet\images\%%f https://unpkg.com/leaflet@1.9.4/dist/images/%%f

pyinstaller RouteRewind.spec --noconfirm --clean || goto :err
echo.
echo Fatto: dist\RouteRewind\RouteRewind.exe
goto :eof
:err
echo ERRORE durante la build.
exit /b 1
