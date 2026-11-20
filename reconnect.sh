#!/bin/bash
A=/opt/platform-tools/platform-tools/adb
$A disconnect 127.0.0.1:19536 2>&1
$A kill-server 2>&1
sleep 2
$A start-server 2>&1
sleep 1
$A connect 127.0.0.1:19536 2>&1
sleep 4
$A devices
echo "--- shell test ---"
$A -s 127.0.0.1:19536 shell echo CONECTADO 2>&1
