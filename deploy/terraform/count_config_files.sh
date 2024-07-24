#!/bin/bash
find ./../../config -name 'config-*.json'  | wc -l | jq -nR 'inputs | {"files": (.|tonumber|tostring)}'
