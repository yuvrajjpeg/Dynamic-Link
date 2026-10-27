#!/bin/zsh
cd -- "${0:A:h}" || exit 1
python3 install.py
printf '\nPress Return to close.\n'
read -r
