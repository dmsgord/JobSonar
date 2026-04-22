#!/bin/bash
set -e

PROJECT_DIR="/root/JobSonar"
SYSTEMD_DIR="/etc/systemd/system"

echo "=== Останавливаем screen-сессии ==="
screen -X -S hr quit 2>/dev/null || true
screen -X -S analyst quit 2>/dev/null || true
screen -X -S sales quit 2>/dev/null || true
screen -X -S recruiter quit 2>/dev/null || true
screen -X -S monitor quit 2>/dev/null || true

echo "=== Копируем service-файлы ==="
for service in jobsonar-hr jobsonar-analyst jobsonar-sales jobsonar-recruiter jobsonar-monitor; do
    cp "$PROJECT_DIR/systemd/$service.service" "$SYSTEMD_DIR/"
    echo "  Скопирован: $service.service"
done

echo "=== Перезагружаем systemd ==="
systemctl daemon-reload

echo "=== Включаем автозапуск и стартуем ==="
for service in jobsonar-hr jobsonar-analyst jobsonar-sales jobsonar-recruiter jobsonar-monitor; do
    systemctl enable $service
    systemctl start $service
    echo "  Запущен: $service"
done

echo ""
echo "=== Готово! Статус ==="
systemctl status jobsonar-* --no-pager
