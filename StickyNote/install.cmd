@echo off
chcp 65001 >nul
if not exist "%~dp0runtime\python.exe" (
  echo 압축을 먼저 푼 다음, 풀린 폴더에서 다시 실행해 주세요.
  pause
  exit /b 1
)
fltmc >nul 2>&1 || (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs } catch { Write-Host '관리자 권한을 받지 못해 설치하지 않았습니다.'; Start-Sleep 4 }"
  exit /b
)
"%~dp0runtime\python.exe" "%~dp0app\install.py"
