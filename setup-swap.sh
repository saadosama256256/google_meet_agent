#!/bin/bash
# setup-swap.sh
# يشغل مرة واحدة على السيرفر (يحتاج صلاحيات root/sudo)
# بيضيف swap file 2GB كطبقة أمان لو الرام خلصت أثناء التسجيل

set -e

SWAP_SIZE="2G"
SWAP_FILE="/swapfile"

if swapon --show | grep -q "$SWAP_FILE"; then
    echo "✅ Swap file موجود بالفعل:"
    swapon --show
    exit 0
fi

echo "⏳ بننشئ swap file بحجم $SWAP_SIZE ..."
fallocate -l $SWAP_SIZE $SWAP_FILE || dd if=/dev/zero of=$SWAP_FILE bs=1M count=2048
chmod 600 $SWAP_FILE
mkswap $SWAP_FILE
swapon $SWAP_FILE

# نخليه ثابت بعد أي إعادة تشغيل للسيرفر
if ! grep -q "$SWAP_FILE" /etc/fstab; then
    echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
fi

# نضبط swappiness منخفضة عشان النظام يستخدم الرام الأساسية الأول
# ويلجأ للـ swap بس وقت الضرورة (أداء أفضل)
sysctl vm.swappiness=10
if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
    echo "vm.swappiness=10" >> /etc/sysctl.conf
fi

echo "✅ تم. حالة الـ Swap الحالية:"
swapon --show
free -h
