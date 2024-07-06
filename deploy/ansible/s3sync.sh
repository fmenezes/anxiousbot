#!/bin/bash
current_dir=$(dirname "$0")

aws s3 sync "$current_dir/../../data" "s3://$S3BUCKET" --exclude .gitkeep
ls -la "$current_dir/../../data" | grep -v "$(date +%Y-%m-%d).csv" | grep -v .gitkeep | xargs rm -rf
