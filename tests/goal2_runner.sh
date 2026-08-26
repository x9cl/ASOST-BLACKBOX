#!/usr/bin/env bash
# Goal 2 cycle runner — waits 10 min, then runs extraction/composition improvement cycle
sleep 600
cd /opt/data/projects/assost
assost-main/.venv/bin/python tests/goal2_cycle.py 2>&1
