#!/bin/bash
set -e

echo "===================================="
echo "🚀 O'quv Markaz - Deploy Script"
echo "===================================="

GITHUB_USER="abdulloxon2005"

# .env fayl mavjudligini tekshirish
if [ ! -f .env ]; then
    echo "⚠️  .env fayl topilmadi!"
    echo "Avval .env.production ni .env ga nusxalang:"
    echo "  cp .env.production .env"
    echo "Keyin .env fayldagi qiymatlarni o'zgartiring."
    exit 1
fi

# Frontend reponi clone qilish (agar yo'q bo'lsa)
if [ ! -d "../edu_center_platform_frontend" ]; then
    echo "📥 Frontend reponi yuklab olish..."
    git clone https://github.com/$GITHUB_USER/edu_center_platform_frontend.git ../edu_center_platform_frontend
else
    echo "🔄 Frontend reponi yangilash..."
    cd ../edu_center_platform_frontend && git pull && cd -
fi

# Telegram Bot reponi clone qilish (agar yo'q bo'lsa)
if [ ! -d "../edu_center_platform_tg_bot" ]; then
    echo "📥 Telegram Bot reponi yuklab olish..."
    git clone https://github.com/$GITHUB_USER/edu_center_platform_tg_bot.git ../edu_center_platform_tg_bot
else
    echo "🔄 Telegram Bot reponi yangilash..."
    cd ../edu_center_platform_tg_bot && git pull && cd -
fi

echo "📦 Docker imaglarni build qilish..."
docker compose build

echo "🗄️  Xizmatlarni ishga tushirish..."
docker compose up -d

echo ""
echo "✅ Deploy muvaffaqiyatli!"
echo "===================================="
echo "🌐 Frontend:  http://localhost:${APP_PORT:-80}"
echo "📡 API Docs:  http://localhost:${APP_PORT:-80}/api/v1/docs"
echo "🤖 Bot:       Telegram da ishlayapti"
echo "===================================="
echo ""
echo "Foydali buyruqlar:"
echo "  docker compose logs -f          # Loglarni kuzatish"
echo "  docker compose ps               # Xizmatlar holati"
echo "  docker compose down              # To'xtatish"
echo "  docker compose restart backend   # Backendni qayta ishga tushirish"
