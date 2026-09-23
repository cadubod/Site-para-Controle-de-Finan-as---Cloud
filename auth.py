"""
auth.py — Módulo de autenticação e gerenciamento de perfis.
Usa Supabase Auth (email + senha) com session_state do Streamlit e persistência de Cookies.
"""

import streamlit as st
import extra_streamlit_components as stx
from config import get_supabase_client

# ──────────────────────────────────────────────
# GERENCIADOR DE COOKIES
# ──────────────────────────────────────────────
@st.cache_resource(experimental_allow_widgets=True)
def get_cookie_manager():
    return stx.CookieManager()

cookie_manager = get_cookie_manager()

# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def _sb():
    """Atalho para obter o cliente Supabase."""
    return get_supabase_client()

def get_current_user() -> dict | None:
    """Retorna o dicionário do usuário logado, lendo da sessão ou do Cookie."""
    user = st.session_state.get("user")
    if user:
        return user
        
    # Se não estiver no session_state, tenta ler o cookie do navegador
    token = cookie_manager.get("sb_token")
    refresh = cookie_manager.get("sb_refresh")
    
    if token and refresh:
        try:
            # Tenta reconstruir a sessão do Supabase silenciosamente usando o token salvo
            res = _sb().auth.set_session(token, refresh)
            if res and res.user:
                st.session_state["user"] = {
                    "id": res.user.id,
                    "email": res.user.email,
                    "access_token": res.session.access_token,
                    "refresh_token": res.session.refresh_token,
                }
                _load_profile(res.user.id)
                return st.session_state["user"]
        except Exception:
            # Se o token for inválido ou tiver expirado, limpa o cookie quebrado
            cookie_manager.delete("sb_token")
            cookie_manager.delete("sb_refresh")
            
    return None

def get_profile() -> dict | None:
    """Retorna o perfil do usuário logado (de profiles)."""
    return st.session_state.get("profile")

def is_authenticated() -> bool:
    return get_current_user() is not None

# ──────────────────────────────────────────────
# LOGIN
# ──────────────────────────────────────────────

def _do_login(email: str, password: str) -> bool:
    """Autentica via Supabase, carrega profile e grava no cookie."""
    try:
        res = _sb().auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
        user = res.user
        session = res.session
        st.session_state["user"] = {
            "id": user.id,
            "email": user.email,
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
        }
        
        # SALVA NO COOKIE DO NAVEGADOR (Válido por 30 dias)
        cookie_manager.set("sb_token", session.access_token, max_age=30 * 24 * 60 * 60)
        cookie_manager.set("sb_refresh", session.refresh_token, max_age=30 * 24 * 60 * 60)
        
        _load_profile(user.id)
        return True
    except Exception as e:
        err = str(e).lower()
        if "email not confirmed" in err:
            st.error("📧 Este e-mail ainda não foi confirmado no Supabase.")
        elif "invalid login credentials" in err:
            st.error("❌ E-mail ou senha incorretos.")
        else:
            st.error(f"Erro ao entrar: {e}")
        return False

def _load_profile(user_id: str):
    """Busca o profile do usuário na tabela profiles."""
    try:
        res = _sb().table("profiles").select("*").eq("id", user_id).single().execute()
        st.session_state["profile"] = res.data
    except Exception:
        st.session_state["profile"] = {
            "id": user_id,
            "display_name": "",
            "avatar_url": "",
            "joint_account_id": None,
        }

# ──────────────────────────────────────────────
# REGISTRO
# ──────────────────────────────────────────────

def _do_register(email: str, password: str, display_name: str) -> bool:
    """Cria conta via Supabase Auth."""
    try:
        res = _sb().auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {"display_name": display_name},
            },
        })
        if res.user:
            st.success("✅ Conta criada! Faça login para continuar.")
            return True
        else:
            st.warning("Verifique seu e-mail para confirmar o cadastro.")
            return True
    except Exception as e:
        err = str(e)
        if "already registered" in err.lower():
            st.error("❌ Este e-mail já está cadastrado.")
        elif "password" in err.lower():
            st.error("❌ A senha deve ter pelo menos 6 caracteres.")
        else:
            st.error(f"Erro ao cadastrar: {err}")
        return False

# ──────────────────────────────────────────────
# LOGOUT
# ──────────────────────────────────────────────

def logout():
    """Limpa sessão, apaga os cookies e redireciona para login."""
    try:
        _sb().auth.sign_out()
    except Exception:
        pass
        
    # Destrói os cookies
    cookie_manager.delete("sb_token")
    cookie_manager.delete("sb_refresh")
    
    for key in ["user", "profile"]:
        st.session_state.pop(key, None)
    st.rerun()

# ──────────────────────────────────────────────
# CONTA CONJUNTA
# ──────────────────────────────────────────────

def create_joint_account(nome: str) -> dict | None:
    try:
        res = _sb().table("joint_accounts").insert({"nome": nome}).execute()
        if res.data:
            ja = res.data[0]
            user_id = get_current_user()["id"]
            _sb().table("profiles").update({"joint_account_id": ja["id"]}).eq("id", user_id).execute()
            _load_profile(user_id)
            return ja
    except Exception as e:
        st.error(f"Erro ao criar conta conjunta: {e}")
    return None

def join_joint_account(invite_code: str) -> bool:
    try:
        res = _sb().table("joint_accounts").select("*").eq("invite_code", invite_code.strip().lower()).execute()
        if not res.data:
            st.error("❌ Código de convite inválido.")
            return False

        ja = res.data[0]
        user_id = get_current_user()["id"]
        _sb().table("profiles").update({"joint_account_id": ja["id"]}).eq("id", user_id).execute()
        _load_profile(user_id)
        st.success(f"✅ Você entrou na conta conjunta '{ja['nome']}'!")
        return True
    except Exception as e:
        st.error(f"Erro ao ingressar: {e}")
        return False

def leave_joint_account() -> bool:
    try:
        user_id = get_current_user()["id"]
        _sb().table("profiles").update({"joint_account_id": None}).eq("id", user_id).execute()
        _load_profile(user_id)
        return True
    except Exception as e:
        st.error(f"Erro ao sair da conta: {e}")
        return False

def get_joint_members() -> list[dict]:
    profile = get_profile()
    if not profile or not profile.get("joint_account_id"):
        return []
    try:
        res = _sb().table("profiles").select("*").eq("joint_account_id", profile["joint_account_id"]).execute()
        return res.data or []
    except Exception:
        return []

def get_joint_account_info() -> dict | None:
    profile = get_profile()
    if not profile or not profile.get("joint_account_id"):
        return None
    try:
        res = _sb().table("joint_accounts").select("*").eq("id", profile["joint_account_id"]).single().execute()
        return res.data
    except Exception:
        return None

def update_display_name(new_name: str) -> bool:
    try:
        user_id = get_current_user()["id"]
        _sb().table("profiles").update({"display_name": new_name}).eq("id", user_id).execute()
        _load_profile(user_id)
        return True
    except Exception as e:
        st.error(f"Erro ao atualizar nome: {e}")
        return False

# ──────────────────────────────────────────────
# PERFIS-MEMBRO (cartão compartilhado, sem login)
# ──────────────────────────────────────────────

def get_members(include_inactive: bool = False) -> list[dict]:
    try:
        query = _sb().table("membros").select("*").order("nome")
        if not include_inactive:
            query = query.eq("ativo", True)
        res = query.execute()
        return res.data or []
    except Exception:
        return []

def create_member(nome: str, emoji: str = "🙂", cor: str = "#1B998B") -> dict | None:
    try:
        user_id = get_current_user()["id"]
        res = _sb().table("membros").insert({
            "owner_id": user_id,
            "nome": nome.strip(),
            "emoji": emoji,
            "cor": cor,
        }).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"Erro ao criar perfil: {e}")
        return None

def update_member(member_id: str, **fields) -> bool:
    try:
        _sb().table("membros").update(fields).eq("id", member_id).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao atualizar perfil: {e}")
        return False

def delete_member(member_id: str) -> bool:
    try:
        _sb().table("membros").delete().eq("id", member_id).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao remover perfil: {e}")
        return False

# ──────────────────────────────────────────────
# TELA DE AUTH (Login + Cadastro)
# ──────────────────────────────────────────────

def show_auth_page():
    st.markdown("""
    <div class="auth-container">
        <div class="auth-title">💳 Gestor Financeiro</div>
        <div class="auth-subtitle">Controle suas finanças com inteligência</div>
    </div>
    """, unsafe_allow_html=True)

    tab_login, tab_register = st.tabs(["🔐 Entrar", "📝 Criar Conta"])

    with tab_login:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("E-mail", placeholder="seu@email.com")
            password = st.text_input("Senha", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Entrar", use_container_width=True)

            if submitted:
                if not email or not password:
                    st.warning("Preencha todos os campos.")
                else:
                    if _do_login(email.strip(), password):
                        st.rerun()

    with tab_register:
        with st.form("register_form", clear_on_submit=True):
            reg_name = st.text_input("Nome de exibição", placeholder="Como quer ser chamado(a)?")
            reg_email = st.text_input("E-mail", placeholder="seu@email.com", key="reg_email")
            reg_pass = st.text_input("Senha (mín. 6 caracteres)", type="password", placeholder="••••••••", key="reg_pass")
            reg_pass2 = st.text_input("Confirmar Senha", type="password", placeholder="••••••••", key="reg_pass2")
            reg_btn = st.form_submit_button("Criar Conta", use_container_width=True)

            if reg_btn:
                if not reg_name or not reg_email or not reg_pass:
                    st.warning("Preencha todos os campos.")
                elif reg_pass != reg_pass2:
                    st.error("As senhas não coincidem.")
                elif len(reg_pass) < 6:
                    st.error("A senha deve ter pelo menos 6 caracteres.")
                else:
                    _do_register(reg_email.strip(), reg_pass, reg_name.strip())
