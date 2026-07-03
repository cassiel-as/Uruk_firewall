@echo off
REM URUK Trinity Console - Windows .exe build script
REM 跑之前先 pip install pyinstaller

echo Building URUK Trinity Console standalone .exe...

pip install pyinstaller --quiet

pyinstaller ^
  --onefile ^
  --windowed ^
  --name "URUK Trinity" ^
  --add-data "static;static" ^
  --add-data "config;config" ^
  --add-data "data;data" ^
  --hidden-import "uvicorn.logging" ^
  --hidden-import "uvicorn.protocols" ^
  --hidden-import "uvicorn.protocols.http" ^
  --hidden-import "uvicorn.protocols.http.auto" ^
  --hidden-import "uvicorn.protocols.websockets" ^
  --hidden-import "uvicorn.protocols.websockets.auto" ^
  --hidden-import "uvicorn.lifespan" ^
  --hidden-import "uvicorn.lifespan.on" ^
  desktop_launcher.py

echo.
echo Done. Check dist\URUK Trinity.exe
echo Note: First run may be slow (Windows Defender scan).
pause
