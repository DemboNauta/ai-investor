#!/bin/bash
crontab -r
{ echo "0  * * * * cd /root/ai-investor && /root/ai-investor/venv/bin/python run_once.py moderate   >> /root/ai-investor/logs/moderate.log   2>&1"
echo "5  * * * * cd /root/ai-investor && /root/ai-investor/venv/bin/python run_once.py aggressive >> /root/ai-investor/logs/aggressive.log 2>&1"
echo "10 * * * * cd /root/ai-investor && /root/ai-investor/venv/bin/python run_once.py degen      >> /root/ai-investor/logs/degen.log      2>&1"; } | crontab -
mkdir -p /root/ai-investor/logs
echo "Cron actualizado:"
crontab -l
