#!/bin/bash

# ============================================================
#   DEPLOY SCRIPT — trio_kanto
#   Executa na raiz da VPS automaticamente
# ============================================================

set -e  # Para o script se qualquer comando falhar

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║        DEPLOY — trio_kanto               ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Ir para a raiz do usuário ──────────────────────────
cd ~
echo "📂 Diretório atual: $(pwd)"

# ── 2. Git Clone ──────────────────────────────────────────
echo ""
echo "🔄 Clonando repositório..."
git clone git@github.com:Ferdinandobot/trio_kanto.git

# ── 3. Entrar no diretório ────────────────────────────────
cd trio_kanto
echo "📂 Entrando em: $(pwd)"

# ── 4. Criar arquivo .env ─────────────────────────────────
echo ""
echo "📝 Criando arquivo .env..."

cat > .env << 'EOF'
GROQ_API_KEY=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
ROOT_ID=554792671477
SALT_SECRETO=uma_frase_aleatoria_para_seguranca
DASHBOARD_WEBHOOK_URL=https://project--9a6fe77a-f1e3-41a8-8fab-fdcad12687e3.lovable.app/api/public/webhook
DASHBOARD_API_KEY=ferdinando_secret
EOF

echo "✅ Arquivo .env criado com sucesso!"

# ── 5. Instalar dependências ──────────────────────────────
echo ""
echo "📦 Rodando npm install..."
npm install
echo "✅ Dependências instaladas!"

# ── 6. Iniciar com PM2 ───────────────────────────────────
echo ""
echo "🚀 Iniciando trio_kanto com PM2..."
pm2 start src/core/index.js --name trio_kanto
echo "✅ trio_kanto iniciado no PM2!"

# ── 7. Salvar configuração PM2 ────────────────────────────
pm2 save
echo "✅ Configuração PM2 salva!"

# ── 8. Aguardar QR Code ───────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  📱 AGUARDANDO QR CODE — escaneie com o WhatsApp"
echo "═══════════════════════════════════════════════════════"
echo ""
pm2 logs trio_kanto --lines 100
