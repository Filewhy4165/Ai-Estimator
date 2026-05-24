$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install pip-tools

python -m piptools compile requirements\runtime.in -o requirements\runtime.lock.txt
python -m piptools compile requirements\dev.in -o requirements\dev.lock.txt

Write-Output "Lock files updated."

