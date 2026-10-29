@echo off
setlocal
set "CHALLENGE_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "CHALLENGE_PYTHON=%~dp0.venv\Scripts\python.exe"
set "CHALLENGE_FAILED=0"

call :generate "challenges\stopsign-directions\directions.py"
call :generate "challenges\note_abgerissen\note_abgerissen.py"
call :generate "challenges\parking_converter\parking_converter.py"
call :generate "challenges\amenity_nursing_home\amenity_nursing_home.py"
call :generate "challenges\nursing_home_for\nursing_home_for.py"
call :generate "challenges\social_workshop\generate.py"
call :generate "challenges\add_objects_to_stop_area\generate.py"
call :generate "challenges\imgur404\imgur_404_image.py"
exit /b %CHALLENGE_FAILED%

:generate
echo Running %~1
"%CHALLENGE_PYTHON%" "%~dp0%~1"
if errorlevel 1 set "CHALLENGE_FAILED=1"
exit /b 0
