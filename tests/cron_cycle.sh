#!/usr/bin/env bash
# ASOST dev cycle — quiet when nothing changed
cd /opt/data/projects/assost
OUT=$(assost-main/.venv/bin/python tests/dev_loop.py 1 2>&1 | grep LOOP)
echo "$OUT" | grep -qE "دورة" && echo "$OUT"
