"""
config.py — Configurações centrais do Gestor Financeiro Multi-Perfil.
Lê credenciais do Supabase de st.secrets (Streamlit Cloud) ou fallback para
variáveis de ambiente / valores padrão.
"""

import streamlit as st
from supabase import create_client, Client

# -------------------------------------------------------------
# CREDENCIAIS SUPABASE
# -------------------------------------------------------------
# Prioridade: st.secrets > valores padrão (para dev local)
# Em produção, configure .streamlit/secrets.toml ou env vars no Streamlit Cloud.

def _get_secret(key: str, default: str = "") -> str:
    """Lê uma chave de st.secrets com fallback."""
    try:
        return st.secrets["supabase"][key]
    except (KeyError, FileNotFoundError):
        return default


SUPABASE_URL: str = _get_secret("url", "https://aqcptekeoyjadchwtfwh.supabase.co/rest/v1/")
SUPABASE_ANON_KEY: str = _get_secret("anon_key", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFxY3B0ZWtlb3lqYWRjaHd0ZndoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk3NTU3NTcsImV4cCI6MjEwNTMzMTc1N30.wAwBSZrNLes91d5w4VFkJRpfVebovKPQkcKYilgd1E8")

_PLACEHOLDER_URL = "https://SEU_PROJETO.supabase.co"
_PLACEHOLDER_KEY = "SUA_ANON_KEY_AQUI"


def _validar_credenciais():
    """Interrompe o app com uma mensagem clara se as credenciais reais
    do Supabase não foram configuradas (evita erros de DNS confusos)."""
    if SUPABASE_URL == _PLACEHOLDER_URL or SUPABASE_ANON_KEY == _PLACEHOLDER_KEY:
        st.error(
            "⚠️ **Credenciais do Supabase não configuradas.**\n\n"
            "Crie o arquivo `.streamlit/secrets.toml` (local) ou configure "
            "os *Secrets* do seu app no Streamlit Cloud com:\n\n"
            "```toml\n[supabase]\n"
            "url = \"https://SEU-ID-REAL.supabase.co\"\n"
            "anon_key = \"sua-anon-key-aqui\"\n```\n\n"
            "Esses valores ficam em **Project Settings → API** no painel do Supabase."
        )
        st.stop()


_validar_credenciais()


# -------------------------------------------------------------
# CLIENTE SUPABASE (singleton cacheado)
# -------------------------------------------------------------
@st.cache_resource
def get_supabase_client() -> Client:
    """Retorna o cliente Supabase cacheado para toda a sessão."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# -------------------------------------------------------------
# CATEGORIAS DE GASTO
# -------------------------------------------------------------
CATEGORIAS: list[str] = [
    "Alimentação",
    "Transporte",
    "Lazer",
    "Moradia",
    "Saúde",
    "Educação",
    "Vestuário",
    "Assinaturas",
    "Presentes",
    "Outros",
]

# -------------------------------------------------------------
# TIPOS DE GASTO
# -------------------------------------------------------------
TIPOS_GASTO: list[str] = [
    "Momentâneo (À vista)",
    "Fixo Recorrente",
    "Parcelado Cartão",
]

TIPOS_RENDA: list[str] = [
    "Principal",
    "Extra",
    "Conjunta",
]

NATUREZAS: list[str] = [
    "Essencial",
    "Não Essencial",
]

DESTINOS: list[str] = [
    "Pessoal",
    "Namorada / Casal",
    "Casa / Família",
]

# -------------------------------------------------------------
# PALETA DE CORES (usada nos gráficos Plotly)
# -------------------------------------------------------------
COLORS = {
    "primary":      "#1B998B",   # verde-água principal
    "secondary":    "#2D3047",   # azul-escuro
    "accent":       "#FF6B6B",   # vermelho-coral (alertas)
    "success":      "#06D6A0",   # verde sucesso
    "warning":      "#FFD166",   # amarelo aviso
    "info":         "#118AB2",   # azul informação
    "bg_card":      "#FFFFFF",
    "bg_dark":      "#0E1117",
    "text_primary": "#FAFAFA",
    "text_muted":   "#8D99AE",
}

# Sequência de cores para gráficos
CHART_PALETTE: list[str] = [
    "#1B998B", "#FF6B6B", "#FFD166", "#118AB2",
    "#06D6A0", "#EF476F", "#073B4C", "#F78C6B",
    "#83C5BE", "#264653",
]

# -------------------------------------------------------------
# PERFIS-MEMBRO (cartão compartilhado, sem login próprio)
# -------------------------------------------------------------
# Cores e emojis sugeridos ao cadastrar um novo membro (ex: filhos,
# cônjuge, familiares) que usam o mesmo cartão mas não têm conta.
MEMBER_COLORS: list[str] = [
    "#1B998B", "#118AB2", "#FF6B6B", "#FFD166",
    "#EF476F", "#06D6A0", "#F78C6B", "#83C5BE",
]

MEMBER_EMOJIS: list[str] = [
    "🙂", "👤", "👧", "👦", "👩", "👨", "🧑", "👵",
    "👴", "🐶", "🐱", "🎓", "💼", "🏠",
]

# -------------------------------------------------------------
# APP CONFIG
# -------------------------------------------------------------
APP_TITLE = "🛡️ Painel Financeiro"
APP_ICON = "💳"
APP_LAYOUT = "wide"
