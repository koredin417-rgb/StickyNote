@echo off
chcp 65001 >nul
if not exist "%~dp0runtime\python.exe" (
  echo 압축을 먼저 푼 다음, 풀린 폴더에서 다시 실행해 주세요.
  pause
  exit /b 1
)
fltmc >nul 2>&1 && goto install
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs -ErrorAction Stop; exit 0 } catch { exit 1 }"
if not errorlevel 1 exit /b
echo 관리자 권한 없이 설치합니다. (내 사용자 폴더에 설치되므로 그대로 쓸 수 있습니다)
:install
"%~dp0runtime\python.exe" "%~dp0app\install.py"
