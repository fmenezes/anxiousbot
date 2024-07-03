#!/bin/bash
current_dir=$(dirname "$0")
aws s3 sync "$current_dir/../../data" "s3://$S3BUCKET" --exclude .gitkeep
