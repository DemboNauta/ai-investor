#!/bin/bash
DIR=/root/ai-investor
BACKUP_DIR=$DIR/backups
DATE=$(date -u +%Y-%m-%d)
DEST=$BACKUP_DIR/$DATE

mkdir -p "$DEST"

cp $DIR/portfolio_moderate.json   "$DEST/" 2>/dev/null
cp $DIR/portfolio_aggressive.json "$DEST/" 2>/dev/null
cp $DIR/portfolio_degen.json      "$DEST/" 2>/dev/null
cp $DIR/history_moderate.json     "$DEST/" 2>/dev/null
cp $DIR/history_aggressive.json   "$DEST/" 2>/dev/null
cp $DIR/history_degen.json        "$DEST/" 2>/dev/null
cp $DIR/memory_moderate.md        "$DEST/" 2>/dev/null
cp $DIR/memory_aggressive.md      "$DEST/" 2>/dev/null
cp $DIR/memory_degen.md           "$DEST/" 2>/dev/null
cp $DIR/chat_history.db           "$DEST/" 2>/dev/null
cp $DIR/subscribers.db            "$DEST/" 2>/dev/null
cp $DIR/alert_state.json          "$DEST/" 2>/dev/null

find $BACKUP_DIR -maxdepth 1 -mindepth 1 -type d -mtime +7 -exec rm -rf {} +

echo "[backup] $DATE -- $(ls $DEST | wc -l) archivos en $DEST"
