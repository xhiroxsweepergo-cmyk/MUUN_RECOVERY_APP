@echo off
cd /d "%~dp0"
echo === Verificando SHA-256 del motor ===
py -3 -c "import hashlib;h=hashlib.sha256(open('bin/recovery-tool.exe','rb').read()).hexdigest().upper();exp=open('bin/recovery-tool.exe.sha256').read().split()[0].upper();print('calculado:',h);print('esperado :',exp);print('OK' if h==exp else 'MISMATCH')"
echo.
echo === Ejecutando pruebas ===
py -3 -m unittest discover -s tests -v
pause
