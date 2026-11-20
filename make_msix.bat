@echo off
REM ===== Crea il pacchetto MSIX da caricare su Partner Center =====
REM Prerequisiti: build.bat eseguito; Windows SDK installato (makeappx.exe);
REM AppxManifest.xml compilato con i dati di Partner Center.
cd /d "%~dp0"
set SRC=dist\RouteRewind
if not exist %SRC%\RouteRewind.exe ( echo Esegui prima build.bat & exit /b 1 )
copy /y packaging\AppxManifest.xml %SRC%\AppxManifest.xml
xcopy /e /i /y packaging\Assets %SRC%\Assets
for /f "delims=" %%i in ('dir /b /s "%ProgramFiles(x86)%\Windows Kits\10\bin\*makeappx.exe" ^| findstr x64') do set MAKEAPPX=%%i
if "%MAKEAPPX%"=="" ( echo makeappx.exe non trovato: installa il Windows SDK & exit /b 1 )
"%MAKEAPPX%" pack /d %SRC% /p dist\RouteRewind.msix /o
echo.
echo Pacchetto pronto: dist\RouteRewind.msix  (lo Store lo firma al momento della pubblicazione)
