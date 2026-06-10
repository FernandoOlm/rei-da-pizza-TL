"""Cliente Groq — IA do estagiário com contexto do VPS."""
import json
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from utils.logger import get_logger

log = get_logger(__name__)

_client = Groq(api_key=GROQ_API_KEY)

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


async def ask_ai(user_message: str, vps_context: dict | None = None) -> str:
    """
    Envia uma pergunta para o Groq com contexto opcional do VPS.
    
    Args:
        user_message: Mensagem do usuário
        vps_context: Dicionário com dados atuais do VPS (processos, memória, etc.)
    
    Returns:
        Resposta da IA como string
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if vps_context:
        context_str = (
            "=== CONTEXTO ATUAL DO VPS ===\n"
            f"{json.dumps(vps_context, ensure_ascii=False, indent=2)}\n"
            "=== FIM DO CONTEXTO ===\n\n"
        )
        messages.append({
            "role": "user",
            "content": context_str + user_message,
        })
    else:
        messages.append({"role": "user", "content": user_message})

    try:
        response = _client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )
        return response.choices[0].message.content or "🤔 Não consegui gerar uma resposta."
    except Exception as e:
        log.error(f"Erro ao chamar Groq API: {e}")
        return f"❌ Erro ao consultar IA: {str(e)}"


async def analyze_vps(processes: list[dict], sys_info: dict) -> str:
    """Análise completa do VPS pela IA com todo o contexto."""
    context = {
        "processos_pm2": processes,
        "sistema": sys_info,
    }
    prompt = (
        "Analise o estado atual do meu VPS com base nos dados acima. "
        "Identifique problemas, riscos e dê recomendações prioritárias."
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
