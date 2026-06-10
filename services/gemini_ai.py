"""Cliente Gemini — IA principal do Ferdinando com suporte a texto, geração de imagem e fallback de chaves de API."""
import json
import io
import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_TEXT_MODEL
from utils.logger import get_logger

log = get_logger(__name__)

# Lista de chaves disponíveis fornecidas pelo usuário para fallback automático
_keys = [
    GEMINI_API_KEY,
    "AIzaSyB6dd_4PncavGdgGquiBYjTl3o8XRQzLps",
    "AQ.Ab8RN6IZizAKHmabHixfAyPezUW6HXjnxUD8vJtv6-cAVWRB0Q"
]

# Filtra chaves repetidas e nulas preservando a ordem
API_KEYS = []
for k in _keys:
    if k and k.strip() and k not in API_KEYS:
        API_KEYS.append(k.strip())

if not API_KEYS:
    API_KEYS = [""]

# Configuração inicial (padrão)
genai.configure(api_key=API_KEYS[0])

SYSTEM_PROMPT = """Você é o "Ferdinando Monitor", estagiário de TI dedicado e inteligente.
Seu trabalho é monitorar o VPS do seu chefe e manter tudo funcionando perfeitamente.

Seu estilo:
- Comunicação em português brasileiro
- Descontraído mas profissional — como um bom estagiário
- Proativo: sempre oferece soluções e próximos passos
- Honesto: se não sabe algo, diz claramente
- NUNCA toma ações sem confirmar com o chefe primeiro
- Usa emojis com moderação para deixar as mensagens mais amigáveis

Quando receber dados do VPS, analise e apresente:
1. O que está normal ✅
2. O que precisa de atenção ⚠️
3. O que está crítico 🚨
4. Suas recomendações de ação

Seja conciso e direto. Evite jargões desnecessários."""


def _get_text_model():
    return genai.GenerativeModel(
        model_name=GEMINI_TEXT_MODEL,
        system_instruction=SYSTEM_PROMPT,
    )


async def ask_ai(user_message: str, vps_context: dict | None = None) -> str:
    """
    Envia uma pergunta ao Gemini com contexto opcional do VPS.
    Tenta usar as chaves disponíveis sequencialmente caso ocorra algum erro na primeira.

    Args:
        user_message: Mensagem do usuário
        vps_context: Dicionário com dados atuais do VPS (processos, memória, etc.)

    Returns:
        Resposta da IA como string
    """
    prompt = user_message
    if vps_context:
        context_str = (
            "=== CONTEXTO ATUAL DO VPS ===\n"
            f"{json.dumps(vps_context, ensure_ascii=False, indent=2)}\n"
            "=== FIM DO CONTEXTO ===\n\n"
        )
        prompt = context_str + user_message

    last_error = None
    for key in API_KEYS:
        try:
            # Configura a chave dinamicamente para esta tentativa
            genai.configure(api_key=key)
            model = _get_text_model()
            response = model.generate_content(prompt)
            return response.text or "🤔 Não consegui gerar uma resposta."
        except Exception as e:
            last_error = e
            log.warning(f"Erro ao usar chave Gemini ({key[:8]}...): {e}")
            continue

    log.error(f"Todas as chaves de API da Gemini falharam. Último erro: {last_error}")
    return f"❌ Erro ao consultar IA: {str(last_error)}"


async def analyze_vps(processes: list[dict], sys_info: dict) -> str:
    """Análise completa do VPS pela IA com todo o contexto."""
    context = {
        "processos_pm2": processes,
        "sistema": sys_info,
    }
    prompt = (
        "Analise o estado atual do meu VPS com base nos dados acima. "
        "Identifique problemas, risks e dê recomendações prioritárias."
    )
    return await ask_ai(prompt, vps_context=context)


async def suggest_cleanup(process: dict) -> str:
    """IA sugere ação de limpeza para um processo específico."""
    context = {"processo": process}
    prompt = (
        f"O processo '{process['name']}' está consumindo {process['memory_mb']:.1f} MB "
        f"com status '{process['status']}' e {process['restarts']} restarts. "
        "Explique brevemente o que pode estar causando isso e se devo limpar os logs ou reiniciar."
    )
    return await ask_ai(prompt, vps_context=context)


async def generate_image(prompt: str) -> io.BytesIO | None:
    """
    Gera uma imagem usando o Gemini.
    Tenta usar as chaves disponíveis sequencialmente caso ocorra algum erro.

    Args:
        prompt: Descrição da imagem a ser gerada

    Returns:
        BytesIO com PNG gerado, ou None em caso de falha
    """
    last_error = None
    for key in API_KEYS:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel("gemini-2.0-flash-preview-image-generation")
            response = model.generate_content(
                contents=prompt,
                generation_config={
                    "response_modalities": ["IMAGE", "TEXT"]
                },
            )

            for candidate in response.candidates:
                for part in candidate.content.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and inline.data:
                        buf = io.BytesIO(inline.data)
                        buf.seek(0)
                        return buf
            log.warning(f"Chave Gemini ({key[:8]}...) não retornou nenhuma imagem")
        except Exception as e:
            last_error = e
            log.warning(f"Erro ao gerar imagem com chave ({key[:8]}...): {e}")
            continue

    log.error(f"Todas as chaves falharam ao gerar imagem. Último erro: {last_error}")
    return None
