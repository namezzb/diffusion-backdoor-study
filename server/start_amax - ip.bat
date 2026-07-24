@echo off
setlocal

if defined AMAX_SSH_KEY (
  set "KEY_PATH=%AMAX_SSH_KEY%"
) else (
  set "KEY_PATH=%USERPROFILE%\.ssh\amax_key"
)

if not exist "%KEY_PATH%" (
  echo ERROR: SSH key not found: %KEY_PATH%
  echo Set AMAX_SSH_KEY to the external key path and retry.
  exit /b 1
)

start cmd /k "ssh -N -L 80:192.168.88.123:80 -L 443:192.168.88.123:443 -L 1080:192.168.88.123:1080 -L 5678:192.168.88.123:5678 -L 5680:192.168.88.123:5680 -L 7256:192.168.88.123:7256 -L 8000:192.168.88.123:8000 -L 8001:192.168.88.123:8001 -L 8765:192.168.88.123:8765 -L 9999:192.168.88.123:9999 -i "%KEY_PATH%" iipl@hduiipl.cn -p 2123"
start http://127.0.0.1:80

echo ##################################################
echo ########## Welcome to AMAX system of IIPL ########
echo ##################################################
set /p DOCKER_PORT=Please enter your docker SSH port:

start /min cmd /k "ssh -N -L 2222:192.168.88.123:%DOCKER_PORT% -i "%KEY_PATH%" iipl@hduiipl.cn -p 2123"
echo ssh root@127.0.0.1 -p 2222 -t "cd /opt/data/private; exec /bin/bash -l" | clip
echo The SSH command has been copied to your clipboard.
echo Private files path: /opt/data/private
pause
start cmd /k "ssh root@127.0.0.1 -p 2222 -t "cd /opt/data/private; exec /bin/bash -l""
endlocal
