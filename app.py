"""
app.py — Painel Financeiro Multi-Perfil
Aplicação principal com autenticação, contas conjuntas, gráficos avançados e UI polida.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime

from config import (
    get_supabase_client, CATEGORIAS, TIPOS_GASTO, TIPOS_RENDA,
    NATUREZAS, DESTINOS, CHART_PALETTE, COLORS,
    MEMBER_COLORS, MEMBER_EMOJIS,
    METODOS_PAGAMENTO, CATEGORIAS_INVESTIMENTO,
    APP_TITLE, APP_ICON, APP_LAYOUT,
)
from styles import inject_css
from auth import (
    is_authenticated, show_auth_page, get_current_user, get_profile,
    logout, get_joint_members, get_joint_account_info,
    create_joint_account, join_joint_account, leave_joint_account,
    update_display_name,
    get_members, create_member, update_member, delete_member,
)

# ──────────────────────────────────────────────
# CONFIGURAÇÃO DA PÁGINA
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Gestor Financeiro Multi-Perfil",
    page_icon=APP_ICON,
    layout=APP_LAYOUT,
    initial_sidebar_state="collapsed",
)

# Injetar CSS customizado
inject_css()

# ──────────────────────────────────────────────
# GUARD DE AUTENTICAÇÃO
# ──────────────────────────────────────────────
if not is_authenticated():
    show_auth_page()
    st.stop()

# Usuário autenticado — pegar dados
user = get_current_user()
profile = get_profile()
user_id = user["id"]
display_name = profile.get("display_name", "Usuário") if profile else "Usuário"

supabase = get_supabase_client()

# ──────────────────────────────────────────────
# FUNÇÕES DE DADOS (CRUD com profile_id)
# ──────────────────────────────────────────────

@st.cache_data(ttl=30)
def carregar_gastos(_user_id: str, mes_filtro: str | None = None) -> pd.DataFrame:
    """Carrega gastos do perfil (e compartilhados da conta conjunta via RLS)."""
    query = supabase.table("gastos").select("*").order("data_registro", desc=True)
    if mes_filtro:
        # Filtra pelo mês selecionado (YYYY-MM)
        start = f"{mes_filtro}-01"
        # Último dia do mês
        year, month = map(int, mes_filtro.split("-"))
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"
        query = query.gte("data_registro", start).lt("data_registro", end)
    res = query.execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def carregar_rendas(_user_id: str) -> pd.DataFrame:
    query = supabase.table("rendas").select("*").order("id", desc=True)
    res = query.execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def carregar_metas(_user_id: str) -> pd.DataFrame:
    query = supabase.table("metas").select("*").order("id")
    res = query.execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def carregar_membros(_user_id: str) -> list[dict]:
    """Perfis-membro (sem login) usados para marcar quem fez a compra
    no cartão compartilhado."""
    return get_members()


@st.cache_data(ttl=30)
def carregar_bancos(_user_id: str) -> pd.DataFrame:
    """Cartões / contas cadastrados (com limite, fechamento e vencimento)."""
    try:
        res = supabase.table("contas_bancos").select("*").order("nome_banco").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def carregar_investimentos(_user_id: str) -> pd.DataFrame:
    """Posições reais da carteira de investimentos/caixinhas."""
    try:
        res = supabase.table("investimentos").select("*").order("id").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def invalidar_cache():
    """Limpa caches de dados para recarregar."""
    carregar_gastos.clear()
    carregar_rendas.clear()
    carregar_metas.clear()
    carregar_membros.clear()
    carregar_bancos.clear()
    carregar_investimentos.clear()


# ──────────────────────────────────────────────
# FILTRO GLOBAL: Mês/Ano
# ──────────────────────────────────────────────
hoje = date.today()
meses_opcoes = []
for delta in range(12):
    m = hoje.month - delta
    y = hoje.year
    while m <= 0:
        m += 12
        y -= 1
    meses_opcoes.append(f"{y}-{m:02d}")

# ──────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────
col_title, col_user = st.columns([4, 1])

with col_title:
    st.title(APP_TITLE)
    st.caption("Sincronização em nuvem • Multi-perfil • Celular & PC")

with col_user:
    st.markdown(f"""
    <div style="text-align:right; padding-top:12px;">
        <span class="badge-info">👤 {display_name}</span>
    </div>
    """, unsafe_allow_html=True)
    if st.button("🚪 Sair", key="btn_logout", use_container_width=True):
        logout()

st.markdown("---")

# ──────────────────────────────────────────────
# VISÃO: Geral / Pessoal / Conta Conjunta
# ──────────────────────────────────────────────
# Só faz sentido oferecer o filtro se o usuário participa de uma conta
# conjunta — do contrário, "Geral" e "Pessoal" seriam idênticos.
ja_info_visao = get_joint_account_info()
visao_atual = "Geral"
if ja_info_visao:
    visao_atual = st.radio(
        "👁️ Visão",
        options=["Geral", "Só o Meu", "Só Conta Conjunta"],
        horizontal=True,
        help="Filtra o painel inteiro: tudo, só o que é seu e privado, ou só o que é compartilhado na conta conjunta.",
    )
    st.markdown("---")


def aplicar_visao(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra um DataFrame (com colunas profile_id/shared) pela Visão selecionada."""
    if df.empty or "profile_id" not in df.columns:
        return df
    if visao_atual == "Só o Meu":
        return df[df["profile_id"] == user_id]
    if visao_atual == "Só Conta Conjunta":
        if "shared" in df.columns:
            return df[df["shared"] == True]  # noqa: E712
        return df[df["profile_id"] != user_id]
    return df


# ──────────────────────────────────────────────
# PERFIS-MEMBRO: mapas auxiliares (nome/emoji/cor)
# ──────────────────────────────────────────────
# "Eu mesmo(a)" representa o dono do login que está lançando o gasto.
# Os demais são perfis sem login (cartão compartilhado): filhos,
# cônjuge, familiares etc.
lista_membros = carregar_membros(user_id)
membro_por_id = {m["id"]: m for m in lista_membros}
opcoes_comprador_form = [f"🙋 Eu ({display_name})"] + [
    f"{m.get('emoji', '🙂')} {m['nome']}" for m in lista_membros
]

# Nomes dos membros da conta conjunta (login próprio), usados quando um
# gasto compartilhado foi lançado por outra pessoa da conta conjunta
joint_members_map = {jm["id"]: jm.get("display_name", "Membro") for jm in get_joint_members()}


def nome_comprador(row) -> str:
    """Resolve quem fez a compra: perfil-membro > dono do login > outro membro da conta conjunta."""
    mid = row.get("membro_id")
    if mid and mid in membro_por_id:
        m = membro_por_id[mid]
        return f"{m.get('emoji', '🙂')} {m['nome']}"
    pid = row.get("profile_id")
    if pid == user_id:
        return f"🙋 {display_name}"
    if pid in joint_members_map:
        return f"👤 {joint_members_map[pid]}"
    return "🙋 Eu"


# ──────────────────────────────────────────────
# FILTROS GLOBAIS
# ──────────────────────────────────────────────
col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 1.6, 2])

with col_f1:
    mes_selecionado = st.selectbox(
        "📅 Mês de Referência",
        options=["Todos"] + meses_opcoes,
        index=1,  # Mês atual por padrão
    )

mes_filtro = mes_selecionado if mes_selecionado != "Todos" else None

with col_f2:
    filtro_categoria = st.multiselect(
        "🏷️ Filtrar por Categoria",
        options=CATEGORIAS,
        default=[],
        placeholder="Todas as categorias",
    )

with col_f3:
    filtro_natureza = st.selectbox(
        "⚡ Natureza",
        options=["Todas", "Essencial", "Não Essencial"],
    )

with col_f4:
    filtro_comprador = st.multiselect(
        "🙋 Filtrar por Pessoa",
        options=opcoes_comprador_form,
        default=[],
        placeholder="Todas as pessoas",
        help="Filtra pelo perfil (com ou sem login) que fez a compra no cartão",
    )

# ──────────────────────────────────────────────
# CARREGAR DADOS
# ──────────────────────────────────────────────
df_gastos = carregar_gastos(user_id, mes_filtro)
df_rendas = carregar_rendas(user_id)
df_metas = carregar_metas(user_id)
df_bancos = carregar_bancos(user_id)
df_investimentos = carregar_investimentos(user_id)

# Aplicar a Visão selecionada (Geral / Só o Meu / Só Conta Conjunta)
df_gastos = aplicar_visao(df_gastos)
df_rendas = aplicar_visao(df_rendas)
df_bancos = aplicar_visao(df_bancos)
df_investimentos = aplicar_visao(df_investimentos)

# Aplicar filtros adicionais
if not df_gastos.empty and filtro_categoria:
    df_gastos = df_gastos[df_gastos["categoria"].isin(filtro_categoria)]
if not df_gastos.empty and filtro_natureza != "Todas":
    df_gastos = df_gastos[df_gastos["natureza"] == filtro_natureza]
if not df_gastos.empty:
    df_gastos["comprador"] = df_gastos.apply(nome_comprador, axis=1)
    if filtro_comprador:
        df_gastos = df_gastos[df_gastos["comprador"].isin(filtro_comprador)]

# ──────────────────────────────────────────────
# CARTÕES / CONTAS: mapa auxiliar
# ──────────────────────────────────────────────
lista_bancos = df_bancos.to_dict("records") if not df_bancos.empty else []
banco_por_id = {b["id"]: b for b in lista_bancos}
opcoes_banco_form = [b["nome_banco"] for b in lista_bancos]

# ──────────────────────────────────────────────
# SIDEBAR: LANÇAMENTOS
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("⚡ Lançamentos")

    # --- Gasto Avulso (Débito / Pix / Dinheiro) ---
    with st.expander("☕ Gasto Avulso (Débito/Pix)", expanded=True):
        with st.form("form_gasto_avulso", clear_on_submit=True):
            desc_av = st.text_input("Descrição", placeholder="Ex: Almoço, Uber", key="desc_av")
            valor_av = st.number_input("Valor (R$)", min_value=0.01, step=5.0, format="%.2f", key="valor_av")
            metodo_av = st.selectbox("Método", [m for m in METODOS_PAGAMENTO if m != "Crédito"], key="metodo_av")

            categoria_av = st.selectbox("Categoria", CATEGORIAS, key="cat_av")
            natureza_av = st.selectbox("Natureza", NATUREZAS, key="nat_av")
            destino_av = st.selectbox("Destino", DESTINOS, key="dest_av")

            quem_comprou_av = st.selectbox(
                "🙋 Quem fez esta compra?", options=opcoes_comprador_form, key="quem_av",
            )

            c_av1, c_av2 = st.columns(2)
            with c_av1:
                data_av = st.date_input("Data", value=date.today(), key="data_av")
            with c_av2:
                shared_av = st.checkbox("Compartilhado", value=False, key="shared_av",
                                        help="Visível para a conta conjunta")

            if st.form_submit_button("💾 Salvar Gasto Avulso", use_container_width=True) and desc_av.strip():
                idx_c = opcoes_comprador_form.index(quem_comprou_av)
                membro_sel = lista_membros[idx_c - 1]["id"] if idx_c > 0 else None
                supabase.table("gastos").insert({
                    "profile_id": user_id,
                    "membro_id": membro_sel,
                    "descricao": desc_av.strip(),
                    "valor": float(valor_av),
                    "valor_total": float(valor_av),
                    "tipo": "Momentâneo (À vista)",
                    "natureza": natureza_av,
                    "destino": destino_av,
                    "categoria": categoria_av,
                    "parcelas": "À vista",
                    "parcelas_pagas": 1,
                    "parcelas_totais": 1,
                    "metodo_pagamento": metodo_av,
                    "is_recorrente": False,
                    "shared": shared_av,
                    "data_registro": str(data_av),
                }).execute()
                st.success("✅ Gasto registrado!")
                invalidar_cache()
                st.rerun()

    # --- Compra no Cartão (Crédito, com parcelamento real) ---
    with st.expander("💳 Compra no Cartão (Crédito)"):
        if not lista_bancos:
            st.info("Cadastre um cartão em '🏦 Cartões & Contas' antes de lançar uma compra no crédito.")
        else:
            with st.form("form_gasto_cartao", clear_on_submit=True):
                desc_cc = st.text_input("Descrição", placeholder="Ex: Notebook, Celular", key="desc_cc")
                valor_cc = st.number_input("Valor da Parcela (R$)", min_value=0.01, step=5.0,
                                           format="%.2f", key="valor_cc",
                                           help="Valor que aparece na fatura todo mês")
                banco_cc = st.selectbox("Cartão", options=opcoes_banco_form, key="banco_cc")

                recorrente_cc = st.checkbox("🔁 Assinatura recorrente (sem data para acabar)", key="rec_cc")
                if not recorrente_cc:
                    c_pc1, c_pc2 = st.columns(2)
                    with c_pc1:
                        p_pagas_cc = st.number_input("Parcela Atual", min_value=1, value=1, step=1, key="p_pagas_cc")
                    with c_pc2:
                        p_total_cc = st.number_input("Total de Parcelas", min_value=1, value=1, step=1, key="p_total_cc")
                else:
                    p_pagas_cc, p_total_cc = 1, 1

                categoria_cc = st.selectbox("Categoria", CATEGORIAS, key="cat_cc")
                natureza_cc = st.selectbox("Natureza", NATUREZAS, key="nat_cc")
                destino_cc = st.selectbox("Destino", DESTINOS, key="dest_cc")

                quem_comprou_cc = st.selectbox(
                    "🙋 Quem fez esta compra?", options=opcoes_comprador_form, key="quem_cc",
                )

                c_cc1, c_cc2 = st.columns(2)
                with c_cc1:
                    data_cc = st.date_input("Data da Compra", value=date.today(), key="data_cc")
                with c_cc2:
                    shared_cc = st.checkbox("Compartilhado", value=False, key="shared_cc",
                                            help="Visível para a conta conjunta")

                if st.form_submit_button("💾 Salvar Compra", use_container_width=True) and desc_cc.strip():
                    banco_id_sel = next(
                        (b["id"] for b in lista_bancos if b["nome_banco"] == banco_cc), None
                    )
                    idx_c2 = opcoes_comprador_form.index(quem_comprou_cc)
                    membro_sel2 = lista_membros[idx_c2 - 1]["id"] if idx_c2 > 0 else None
                    parcelas_txt = "Assinatura" if recorrente_cc else (
                        f"{int(p_pagas_cc)}/{int(p_total_cc)}" if p_total_cc > 1 else "À vista"
                    )
                    supabase.table("gastos").insert({
                        "profile_id": user_id,
                        "membro_id": membro_sel2,
                        "banco_id": banco_id_sel,
                        "descricao": desc_cc.strip(),
                        "valor": float(valor_cc),
                        "valor_total": float(valor_cc) * (1 if recorrente_cc else int(p_total_cc)),
                        "tipo": "Fixo Recorrente" if recorrente_cc else "Parcelado Cartão",
                        "natureza": natureza_cc,
                        "destino": destino_cc,
                        "categoria": categoria_cc,
                        "parcelas": parcelas_txt,
                        "parcelas_pagas": int(p_pagas_cc),
                        "parcelas_totais": int(p_total_cc),
                        "metodo_pagamento": "Crédito",
                        "is_recorrente": recorrente_cc,
                        "shared": shared_cc,
                        "data_registro": str(data_cc),
                    }).execute()
                    st.success("✅ Compra registrada!")
                    invalidar_cache()
                    st.rerun()

    # --- Nova Renda ---
    with st.expander("➕ Nova Renda"):
        with st.form("form_renda", clear_on_submit=True):
            origem = st.text_input("Fonte / Origem", placeholder="Ex: Salário, Freelance")
            valor_renda = st.number_input("Valor Líquido (R$)", min_value=1.0, step=50.0, format="%.2f")
            tipo_r = st.selectbox("Tipo", TIPOS_RENDA)
            mes_ref = st.text_input("Mês Referência", value=f"{hoje.year}-{hoje.month:02d}",
                                    help="Formato: YYYY-MM")
            btn_renda = st.form_submit_button("💾 Salvar Renda", use_container_width=True)
            if btn_renda and origem.strip():
                supabase.table("rendas").insert({
                    "profile_id": user_id,
                    "origem": origem.strip(),
                    "valor": float(valor_renda),
                    "tipo": tipo_r,
                    "mes_ref": mes_ref.strip(),
                }).execute()
                st.success("✅ Renda salva!")
                invalidar_cache()
                st.rerun()

    # --- Cartões & Contas ---
    with st.expander("🏦 Cartões & Contas"):
        st.caption("Cadastre seus cartões para acompanhar limite, fechamento e vencimento da fatura.")
        with st.form("form_novo_banco", clear_on_submit=True):
            nome_banco_novo = st.text_input("Nome do Cartão/Conta", placeholder="Ex: Nubank, Inter")
            limite_novo = st.number_input("Limite de Crédito (R$)", min_value=0.0, step=100.0, format="%.2f")
            c_b1, c_b2 = st.columns(2)
            with c_b1:
                fechamento_novo = st.number_input("Dia do Fechamento", min_value=1, max_value=31, value=1, step=1)
            with c_b2:
                vencimento_novo = st.number_input("Dia do Vencimento", min_value=1, max_value=31, value=10, step=1)
            shared_banco_novo = st.checkbox("Cartão compartilhado", value=False,
                                            help="Visível para a conta conjunta")
            if st.form_submit_button("➕ Adicionar Cartão", use_container_width=True):
                if nome_banco_novo.strip():
                    supabase.table("contas_bancos").insert({
                        "profile_id": user_id,
                        "nome_banco": nome_banco_novo.strip(),
                        "limite_credito": float(limite_novo),
                        "dia_fechamento": int(fechamento_novo),
                        "dia_vencimento": int(vencimento_novo),
                        "shared": shared_banco_novo,
                    }).execute()
                    st.success(f"Cartão '{nome_banco_novo}' cadastrado!")
                    invalidar_cache()
                    st.rerun()
                else:
                    st.warning("Informe um nome para o cartão.")

        if lista_bancos:
            st.markdown("**Excluir cartão:**")
            meus_bancos_ids = [b["id"] for b in lista_bancos if b["profile_id"] == user_id]
            if meus_bancos_ids:
                nomes_por_id = {b["id"]: b["nome_banco"] for b in lista_bancos}
                banco_del = st.selectbox(
                    "Cartão", options=meus_bancos_ids,
                    format_func=lambda i: nomes_por_id.get(i, str(i)), key="banco_del",
                )
                if st.button("🗑️ Remover Cartão", key="btn_del_banco"):
                    supabase.table("contas_bancos").delete().eq("id", banco_del).execute()
                    st.success("Cartão removido.")
                    invalidar_cache()
                    st.rerun()

    # --- Nova Posição na Carteira ---
    with st.expander("📈 Nova Posição (Carteira)"):
        st.caption("Registre um ativo/caixinha real com saldo atual e aporte mensal planejado.")
        with st.form("form_novo_investimento", clear_on_submit=True):
            ativo_novo = st.text_input("Nome do Ativo", placeholder="Ex: Tesouro Selic, Reserva de Emergência")
            categoria_inv_novo = st.selectbox("Categoria", CATEGORIAS_INVESTIMENTO)
            valor_acum_novo = st.number_input("Valor Acumulado Atual (R$)", min_value=0.0, step=50.0, format="%.2f")
            aporte_novo = st.number_input("Aporte Mensal Planejado (R$)", min_value=0.0, step=25.0, format="%.2f")
            taxa_novo = st.number_input("Taxa Anual Estimada (% a.a.)", min_value=0.0, value=10.0, step=0.5)
            shared_inv_novo = st.checkbox("Posição compartilhada", value=False,
                                          help="Visível para a conta conjunta")
            if st.form_submit_button("➕ Adicionar à Carteira", use_container_width=True):
                if ativo_novo.strip():
                    supabase.table("investimentos").insert({
                        "profile_id": user_id,
                        "ativo": ativo_novo.strip(),
                        "categoria": categoria_inv_novo,
                        "valor_acumulado": float(valor_acum_novo),
                        "aporte_mensal_planejado": float(aporte_novo),
                        "taxa_anual_estimada": float(taxa_novo),
                        "shared": shared_inv_novo,
                    }).execute()
                    st.success(f"'{ativo_novo}' adicionado à carteira!")
                    invalidar_cache()
                    st.rerun()
                else:
                    st.warning("Informe um nome para o ativo.")

    # --- Novo Perfil do Cartão (sem login) ---
    with st.expander("👥 Novo Perfil do Cartão"):
        st.caption("Cadastre quem mais usa o cartão compartilhado (filhos, cônjuge, "
                   "familiares) para marcar quem fez cada compra, sem precisar criar login.")
        with st.form("form_membro_rapido", clear_on_submit=True):
            c_m1, c_m2 = st.columns([1, 2])
            with c_m1:
                membro_emoji = st.selectbox("Ícone", MEMBER_EMOJIS, key="quick_emoji")
            with c_m2:
                membro_nome = st.text_input("Nome", placeholder="Ex: Maria, João")
            membro_cor = st.selectbox(
                "Cor", MEMBER_COLORS, key="quick_cor",
                format_func=lambda c: c,
            )
            if st.form_submit_button("➕ Adicionar Perfil", use_container_width=True):
                if membro_nome.strip():
                    if create_member(membro_nome.strip(), membro_emoji, membro_cor):
                        st.success(f"Perfil '{membro_nome}' criado!")
                        invalidar_cache()
                        st.rerun()
                else:
                    st.warning("Informe um nome para o perfil.")

    # --- Teto Casal ---
    st.markdown("---")
    teto_casal = st.number_input(
        "🔒 Teto Mensal Casal (R$)", min_value=0.0, value=300.0, step=25.0,
        help="Alerta quando gastos 'Namorada / Casal' ultrapassarem este valor",
    )

# ──────────────────────────────────────────────
# KPIs / TOTALIZADORES
# ──────────────────────────────────────────────
total_renda = df_rendas["valor"].sum() if not df_rendas.empty else 0.0
total_gastos = df_gastos["valor"].sum() if not df_gastos.empty else 0.0
saldo_livre = total_renda - total_gastos

# Gastos do perfil (meus)
meus_gastos = 0.0
if not df_gastos.empty:
    meus = df_gastos[df_gastos["profile_id"] == user_id]
    meus_gastos = meus["valor"].sum()

gastos_casal = 0.0
if not df_gastos.empty:
    gastos_casal = df_gastos[df_gastos["destino"] == "Namorada / Casal"]["valor"].sum()

# KPI Cards
col1, col2, col3, col4 = st.columns(4)

col1.metric("💰 Renda Total", f"R$ {total_renda:,.2f}")
col2.metric(
    "📉 Despesas",
    f"R$ {total_gastos:,.2f}",
    delta=f"{(total_gastos / total_renda * 100 if total_renda else 0):.1f}% gasto",
    delta_color="inverse",
)

saldo_badge = "badge-positive" if saldo_livre >= 0 else "badge-negative"
col3.metric("🏦 Saldo Disponível", f"R$ {saldo_livre:,.2f}")
col4.metric(
    "💑 Gasto Casal",
    f"R$ {gastos_casal:,.2f}",
    delta=f"Teto: R$ {teto_casal:,.2f}",
    delta_color="normal" if gastos_casal <= teto_casal else "inverse",
)

if teto_casal > 0 and gastos_casal > teto_casal:
    st.warning(f"⚠️ Gastos do casal ultrapassaram o teto em R$ {gastos_casal - teto_casal:,.2f}!")

# Barra de progresso do orçamento
if total_renda > 0:
    pct_orcamento = min(total_gastos / total_renda, 1.0)
    st.markdown(f"**Orçamento consumido: {pct_orcamento * 100:.1f}%**")
    st.progress(pct_orcamento)
    if pct_orcamento > 0.9:
        st.error("🔴 Você já consumiu mais de 90% da renda!")
    elif pct_orcamento > 0.7:
        st.warning("🟡 Atenção: mais de 70% da renda consumida.")

st.markdown("---")

# ──────────────────────────────────────────────
# TABS PRINCIPAIS
# ──────────────────────────────────────────────
tab_gastos, tab_cartoes, tab_graficos, tab_metas, tab_carteira, tab_simulador, tab_perfis = st.tabs([
    "📋 Histórico & Edição",
    "🏦 Cartões & Faturas",
    "📊 Análise Visual",
    "🎯 Caixinhas",
    "💰 Carteira",
    "📈 Projeções",
    "👥 Perfis & Conta Conjunta",
])

# ══════════════════════════════════════════════
# TAB 1: HISTÓRICO E EDIÇÃO
# ══════════════════════════════════════════════
with tab_gastos:
    st.subheader("Despesas Cadastradas")
    if not df_gastos.empty:
        # Resolver nomes dos perfis
        display_cols = ["id", "data_registro", "descricao", "valor", "categoria",
                        "natureza", "destino", "comprador", "metodo_pagamento",
                        "parcelas", "shared"]
        available_cols = [c for c in display_cols if c in df_gastos.columns]
        st.dataframe(
            df_gastos[available_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "valor": st.column_config.NumberColumn("Valor Parcela (R$)", format="R$ %.2f"),
                "shared": st.column_config.CheckboxColumn("Compartilhado"),
                "data_registro": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "comprador": st.column_config.TextColumn("Quem Comprou"),
                "metodo_pagamento": st.column_config.TextColumn("Método"),
            },
        )

        with st.expander("🗑️ Excluir Lançamento"):
            # Só pode excluir gastos próprios
            meus_ids = df_gastos[df_gastos["profile_id"] == user_id]["id"].tolist()
            if meus_ids:
                id_remover = st.selectbox("Selecione o ID do gasto", options=meus_ids)
                if st.button("Confirmar Exclusão", type="primary"):
                    supabase.table("gastos").delete().eq("id", id_remover).execute()
                    st.success(f"Gasto #{id_remover} excluído.")
                    invalidar_cache()
                    st.rerun()
            else:
                st.info("Nenhum gasto seu para excluir.")
    else:
        st.info("🔍 Nenhuma despesa encontrada para o período selecionado.")

    st.markdown("---")

    st.subheader("Rendas Cadastradas")
    if not df_rendas.empty:
        st.dataframe(
            df_rendas[["id", "origem", "valor", "tipo", "mes_ref"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "valor": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f"),
            },
        )
        with st.expander("🗑️ Excluir Renda"):
            meus_renda_ids = df_rendas[df_rendas["profile_id"] == user_id]["id"].tolist() if "profile_id" in df_rendas.columns else df_rendas["id"].tolist()
            if meus_renda_ids:
                id_renda_remover = st.selectbox("Selecione o ID da renda", options=meus_renda_ids)
                if st.button("Remover Renda", type="primary"):
                    supabase.table("rendas").delete().eq("id", id_renda_remover).execute()
                    st.success("Renda removida.")
                    invalidar_cache()
                    st.rerun()
    else:
        st.info("Nenhuma renda cadastrada.")

# ══════════════════════════════════════════════
# TAB CARTÕES & FATURAS
# ══════════════════════════════════════════════
with tab_cartoes:
    st.subheader("🏦 Cartões & Faturas")

    if df_bancos.empty:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-icon">🏦</div>
            <div>Nenhum cartão cadastrado ainda.<br>Use "🏦 Cartões & Contas" no menu lateral para adicionar o primeiro.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Todos os gastos de crédito (sem filtro de mês) para calcular fatura/limite corretamente
        df_gastos_todos = carregar_gastos(user_id, None)
        df_gastos_todos = aplicar_visao(df_gastos_todos)

        hoje_d = date.today()

        for _, banco in df_bancos.iterrows():
            gastos_banco = (
                df_gastos_todos[df_gastos_todos["banco_id"] == banco["id"]]
                if "banco_id" in df_gastos_todos.columns and not df_gastos_todos.empty
                else pd.DataFrame()
            )
            if not gastos_banco.empty:
                gastos_banco = gastos_banco.copy()
                for col, default in [("is_recorrente", False), ("parcelas_pagas", 1), ("parcelas_totais", 1)]:
                    if col not in gastos_banco.columns:
                        gastos_banco[col] = default
                    else:
                        gastos_banco[col] = gastos_banco[col].fillna(default)

            fatura_mes = 0.0
            limite_preso = 0.0
            if not gastos_banco.empty:
                for _, g in gastos_banco.iterrows():
                    valor_p = float(g.get("valor") or 0)
                    if g.get("is_recorrente"):
                        fatura_mes += valor_p
                        limite_preso += valor_p
                    else:
                        pagas = int(g.get("parcelas_pagas") or 1)
                        totais = int(g.get("parcelas_totais") or 1)
                        restantes = max(0, totais - pagas)
                        if restantes > 0:
                            fatura_mes += valor_p
                        limite_preso += restantes * valor_p

            limite = float(banco.get("limite_credito") or 0)
            pct_limite = min(limite_preso / limite, 1.0) if limite > 0 else 0.0

            # Status da fatura (aberta / fechada / atrasada), com base no dia de fechamento/vencimento
            fechamento = int(banco.get("dia_fechamento") or 1)
            vencimento = int(banco.get("dia_vencimento") or 10)
            if hoje_d.day < fechamento:
                status_fatura, status_cor = "🟢 Aberta", "#06D6A0"
            elif hoje_d.day < vencimento:
                status_fatura, status_cor = "🟡 Fechada", "#FFD166"
            else:
                status_fatura, status_cor = "🔴 Vencida", "#FF6B6B"

            with st.container():
                st.markdown(f"""
                <div class="member-card" style="align-items:flex-start; flex-direction:column; gap:6px;">
                    <div style="display:flex; justify-content:space-between; width:100%; align-items:center;">
                        <span class="member-name" style="font-size:1.1rem;">🏦 {banco['nome_banco']}</span>
                        <span style="color:{status_cor}; font-weight:700;">{status_fatura}</span>
                    </div>
                    <div class="member-sub">Fecha dia {fechamento} • Vence dia {vencimento}</div>
                </div>
                """, unsafe_allow_html=True)

                c_cb1, c_cb2, c_cb3 = st.columns(3)
                c_cb1.metric("Fatura deste mês", f"R$ {fatura_mes:,.2f}")
                c_cb2.metric("Comprometido do limite", f"R$ {limite_preso:,.2f}")
                c_cb3.metric("Limite Total", f"R$ {limite:,.2f}" if limite > 0 else "—")

                if limite > 0:
                    st.progress(pct_limite)
                    if pct_limite > 0.9:
                        st.error(f"🔴 Limite quase esgotado: {pct_limite * 100:.0f}% comprometido!")
                    elif pct_limite > 0.7:
                        st.warning(f"🟡 {pct_limite * 100:.0f}% do limite já comprometido.")

                # Divisão da fatura por pessoa (perfis sem login + conta conjunta)
                if not gastos_banco.empty:
                    gastos_banco_view = gastos_banco.copy()
                    gastos_banco_view["comprador"] = gastos_banco_view.apply(nome_comprador, axis=1)
                    split = gastos_banco_view.groupby("comprador")["valor"].sum().reset_index()
                    if len(split) > 1:
                        st.caption("**Divisão da fatura por pessoa:**")
                        cols_split = st.columns(len(split))
                        for i, (_, row_s) in enumerate(split.iterrows()):
                            cols_split[i].metric(row_s["comprador"], f"R$ {row_s['valor']:,.2f}")

                if banco["profile_id"] == user_id:
                    if st.button(f"✅ Registrar Pagamento da Fatura — {banco['nome_banco']}",
                                key=f"pagar_{banco['id']}"):
                        ids_para_pagar = gastos_banco[
                            (~gastos_banco["is_recorrente"])
                            & (gastos_banco["parcelas_pagas"] < gastos_banco["parcelas_totais"])
                        ]["id"].tolist() if not gastos_banco.empty else []
                        for gid in ids_para_pagar:
                            linha = gastos_banco[gastos_banco["id"] == gid].iloc[0]
                            nova_pagas = int(linha["parcelas_pagas"]) + 1
                            nova_parcela_txt = f"{nova_pagas}/{int(linha['parcelas_totais'])}"
                            supabase.table("gastos").update({
                                "parcelas_pagas": nova_pagas,
                                "parcelas": nova_parcela_txt,
                            }).eq("id", int(gid)).execute()
                        st.success("Fatura paga! Parcelas avançadas para o próximo mês.")
                        invalidar_cache()
                        st.rerun()

                st.markdown("---")

# ══════════════════════════════════════════════
# TAB 2: ANÁLISE VISUAL (6+ gráficos)
# ══════════════════════════════════════════════
with tab_graficos:
    if not df_gastos.empty:
        # Configuração padrão de layout Plotly
        layout_cfg = dict(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, sans-serif", color="#FAFAFA"),
            margin=dict(t=50, b=30, l=30, r=30),
        )

        # ── Linha 1: Donut Essencial/Não Essencial + Donut por Destino ──
        st.subheader("📊 Distribuição de Gastos")
        c_g1, c_g2 = st.columns(2)

        with c_g1:
            fig_nat = px.pie(
                df_gastos, names="natureza", values="valor",
                title="Essencial vs. Não Essencial",
                hole=0.5, color_discrete_sequence=CHART_PALETTE,
            )
            fig_nat.update_layout(**layout_cfg)
            fig_nat.update_traces(textinfo="percent+label", pull=[0.03, 0.03])
            st.plotly_chart(fig_nat, use_container_width=True)

        with c_g2:
            fig_dest = px.pie(
                df_gastos, names="destino", values="valor",
                title="Gastos por Destino",
                hole=0.5, color_discrete_sequence=CHART_PALETTE[2:],
            )
            fig_dest.update_layout(**layout_cfg)
            fig_dest.update_traces(textinfo="percent+label", pull=[0.03, 0.03, 0.03])
            st.plotly_chart(fig_dest, use_container_width=True)

        # ── Linha 2: Treemap por Categoria + Barras Top 10 ──
        st.markdown("---")
        st.subheader("🗂️ Categorias e Maiores Gastos")
        c_g3, c_g4 = st.columns(2)

        with c_g3:
            if "categoria" in df_gastos.columns:
                fig_tree = px.treemap(
                    df_gastos, path=["categoria", "descricao"], values="valor",
                    title="Distribuição Hierárquica",
                    color="valor",
                    color_continuous_scale=["#118AB2", "#1B998B", "#06D6A0", "#FFD166", "#FF6B6B"],
                )
                fig_tree.update_layout(**layout_cfg)
                st.plotly_chart(fig_tree, use_container_width=True)
            else:
                st.info("Adicione categorias aos gastos para ver o treemap.")

        with c_g4:
            top10 = df_gastos.nlargest(10, "valor")[["descricao", "valor"]].sort_values("valor")
            fig_top = px.bar(
                top10, x="valor", y="descricao",
                orientation="h",
                title="🏆 Top 10 Maiores Gastos",
                text="valor",
                color="valor",
                color_continuous_scale=["#1B998B", "#FF6B6B"],
            )
            fig_top.update_layout(**layout_cfg, showlegend=False)
            fig_top.update_traces(texttemplate="R$ %{text:,.2f}", textposition="outside")
            st.plotly_chart(fig_top, use_container_width=True)

        # ── Linha 3: Evolução Diária + Gauge de Orçamento ──
        st.markdown("---")
        st.subheader("📈 Evolução e Saúde Financeira")
        c_g5, c_g6 = st.columns(2)

        with c_g5:
            if "data_registro" in df_gastos.columns:
                df_daily = df_gastos.copy()
                df_daily["data_registro"] = pd.to_datetime(df_daily["data_registro"])
                df_daily = df_daily.groupby("data_registro")["valor"].sum().reset_index()
                df_daily = df_daily.sort_values("data_registro")
                df_daily["acumulado"] = df_daily["valor"].cumsum()

                fig_area = px.area(
                    df_daily, x="data_registro", y="acumulado",
                    title="📅 Gastos Acumulados no Período",
                    labels={"data_registro": "Data", "acumulado": "Acumulado (R$)"},
                )
                fig_area.update_layout(**layout_cfg)
                fig_area.update_traces(
                    fill="tozeroy",
                    line=dict(color="#1B998B", width=2.5),
                    fillcolor="rgba(27,153,139,0.15)",
                )
                st.plotly_chart(fig_area, use_container_width=True)

        with c_g6:
            # Gauge de orçamento
            pct = (total_gastos / total_renda * 100) if total_renda > 0 else 0
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=pct,
                number={"suffix": "%", "font": {"size": 36, "color": "#FAFAFA"}},
                delta={"reference": 70, "increasing": {"color": "#FF6B6B"}, "decreasing": {"color": "#06D6A0"}},
                title={"text": "% do Orçamento Consumido", "font": {"size": 16, "color": "#8D99AE"}},
                gauge={
                    "axis": {"range": [0, 100], "tickwidth": 2, "tickcolor": "#8D99AE"},
                    "bar": {"color": "#1B998B", "thickness": 0.3},
                    "bgcolor": "rgba(30,33,48,0.6)",
                    "borderwidth": 0,
                    "steps": [
                        {"range": [0, 50], "color": "rgba(6,214,160,0.2)"},
                        {"range": [50, 70], "color": "rgba(255,209,102,0.2)"},
                        {"range": [70, 90], "color": "rgba(255,107,107,0.15)"},
                        {"range": [90, 100], "color": "rgba(239,71,111,0.25)"},
                    ],
                    "threshold": {
                        "line": {"color": "#FF6B6B", "width": 3},
                        "thickness": 0.8,
                        "value": 90,
                    },
                },
            ))
            fig_gauge.update_layout(
                **layout_cfg,
                height=320,
            )
            st.plotly_chart(fig_gauge, use_container_width=True)

        # ── Linha 4: Comparativo por Pessoa (perfis do cartão + conta conjunta) ──
        if "comprador" in df_gastos.columns and df_gastos["comprador"].nunique() > 1:
            st.markdown("---")
            st.subheader("🙋 Quem Está Gastando no Cartão")
            st.caption("Combina quem tem login (você e a conta conjunta) e os perfis-membro "
                      "sem login cadastrados para o cartão compartilhado.")

            c_p1, c_p2 = st.columns(2)

            with c_p1:
                fig_pessoa_pie = px.pie(
                    df_gastos, names="comprador", values="valor",
                    title="Participação de Cada Pessoa no Total",
                    hole=0.5, color_discrete_sequence=CHART_PALETTE,
                )
                fig_pessoa_pie.update_layout(**layout_cfg)
                fig_pessoa_pie.update_traces(textinfo="percent+label")
                st.plotly_chart(fig_pessoa_pie, use_container_width=True)

            with c_p2:
                fig_comp = px.bar(
                    df_gastos.groupby("comprador")["valor"].sum().reset_index().sort_values("valor"),
                    x="valor", y="comprador",
                    orientation="h",
                    title="Total Gasto por Pessoa",
                    color="comprador",
                    color_discrete_sequence=CHART_PALETTE,
                    text="valor",
                )
                fig_comp.update_layout(**layout_cfg, showlegend=False)
                fig_comp.update_traces(texttemplate="R$ %{text:,.2f}", textposition="outside")
                st.plotly_chart(fig_comp, use_container_width=True)

            # Barras agrupadas por categoria
            if "categoria" in df_gastos.columns:
                fig_comp_cat = px.bar(
                    df_gastos.groupby(["comprador", "categoria"])["valor"].sum().reset_index(),
                    x="categoria", y="valor", color="comprador",
                    barmode="group",
                    title="Gastos por Categoria — Comparativo entre Pessoas",
                    color_discrete_sequence=CHART_PALETTE,
                )
                fig_comp_cat.update_layout(**layout_cfg)
                st.plotly_chart(fig_comp_cat, use_container_width=True)

    else:
        st.info("📊 Lance despesas para gerar os gráficos de análise.")

# ══════════════════════════════════════════════
# TAB 3: CAIXINHAS / METAS
# ══════════════════════════════════════════════
with tab_metas:
    st.subheader("🎯 Metas e Caixinhas de Compra")

    if not df_metas.empty:
        for _, m in df_metas.iterrows():
            alvo = float(m["alvo"]) if m["alvo"] else 1
            atual = float(m["atual"]) if m["atual"] else 0
            prog = min(1.0, atual / alvo) if alvo > 0 else 0.0

            # Identificar se é meta conjunta
            is_joint = bool(m.get("joint_account_id"))
            tag = " 👥" if is_joint else ""

            col_info, col_pct = st.columns([4, 1])
            with col_info:
                st.markdown(f"**{m['nome']}{tag}** — R$ {atual:,.2f} de R$ {alvo:,.2f}")
            with col_pct:
                color = "#06D6A0" if prog >= 1.0 else ("#FFD166" if prog >= 0.5 else "#FF6B6B")
                st.markdown(f'<span style="color:{color}; font-weight:700; font-size:1.1rem;">{prog * 100:.0f}%</span>', unsafe_allow_html=True)

            st.progress(prog)

            # Aporte rápido
            col_m1, col_m2 = st.columns([3, 1])
            with col_m1:
                novo_deposito = st.number_input(
                    f"Aportar em {m['nome']}", min_value=0.0, step=20.0, key=f"dep_{m['id']}"
                )
            with col_m2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("➕ Atualizar", key=f"btn_{m['id']}"):
                    if novo_deposito > 0:
                        supabase.table("metas").update(
                            {"atual": atual + float(novo_deposito)}
                        ).eq("id", m["id"]).execute()
                        st.success("Aporte registrado!")
                        invalidar_cache()
                        st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)

    else:
        st.info("Nenhuma meta criada ainda. Crie sua primeira caixinha abaixo!")

    # Nova meta
    with st.expander("➕ Nova Caixinha"):
        with st.form("form_meta", clear_on_submit=True):
            nome_meta = st.text_input("Objetivo", placeholder="Ex: Reserva de Emergência, Viagem")
            alvo_meta = st.number_input("Valor Final Alvo (R$)", min_value=1.0, step=100.0)
            atual_meta = st.number_input("Valor Já Guardado (R$)", min_value=0.0, step=50.0)

            ja_info = get_joint_account_info()
            is_joint_meta = False
            if ja_info:
                is_joint_meta = st.checkbox(
                    "🤝 Meta conjunta (visível a todos da conta)",
                    value=False,
                )

            if st.form_submit_button("🎯 Criar Meta", use_container_width=True) and nome_meta.strip():
                meta_data = {
                    "profile_id": user_id,
                    "nome": nome_meta.strip(),
                    "alvo": float(alvo_meta),
                    "atual": float(atual_meta),
                }
                if is_joint_meta and ja_info:
                    meta_data["joint_account_id"] = ja_info["id"]

                supabase.table("metas").insert(meta_data).execute()
                st.success("✅ Meta criada!")
                invalidar_cache()
                st.rerun()

# ══════════════════════════════════════════════
# TAB CARTEIRA DE INVESTIMENTOS
# ══════════════════════════════════════════════
with tab_carteira:
    st.subheader("💰 Carteira de Investimentos")
    st.caption("Posições reais dos seus ativos e caixinhas — diferente da simulação hipotética da aba Projeções.")

    if not df_investimentos.empty:
        total_carteira = df_investimentos["valor_acumulado"].sum()
        total_aporte_mensal = df_investimentos["aporte_mensal_planejado"].sum()

        c_cart1, c_cart2, c_cart3 = st.columns(3)
        c_cart1.metric("💼 Total na Carteira", f"R$ {total_carteira:,.2f}")
        c_cart2.metric("📆 Aporte Mensal Planejado", f"R$ {total_aporte_mensal:,.2f}")
        c_cart3.metric("📊 Nº de Posições", f"{len(df_investimentos)}")

        st.markdown("---")

        c_cw1, c_cw2 = st.columns(2)
        with c_cw1:
            fig_carteira_pie = px.pie(
                df_investimentos, names="ativo", values="valor_acumulado",
                title="Distribuição da Carteira",
                hole=0.5, color_discrete_sequence=CHART_PALETTE,
            )
            fig_carteira_pie.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif", color="#FAFAFA"),
            )
            fig_carteira_pie.update_traces(textinfo="percent+label")
            st.plotly_chart(fig_carteira_pie, use_container_width=True)

        with c_cw2:
            fig_carteira_cat = px.bar(
                df_investimentos.groupby("categoria")["valor_acumulado"].sum().reset_index().sort_values("valor_acumulado"),
                x="valor_acumulado", y="categoria", orientation="h",
                title="Por Categoria", color="categoria",
                color_discrete_sequence=CHART_PALETTE, text="valor_acumulado",
            )
            fig_carteira_cat.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif", color="#FAFAFA"), showlegend=False,
            )
            fig_carteira_cat.update_traces(texttemplate="R$ %{text:,.2f}", textposition="outside")
            st.plotly_chart(fig_carteira_cat, use_container_width=True)

        st.markdown("---")
        st.markdown("**Suas posições:**")

        for _, inv in df_investimentos.iterrows():
            with st.container():
                col_i1, col_i2, col_i3 = st.columns([3, 1.5, 1.5])
                with col_i1:
                    st.markdown(f"**{inv['ativo']}** &nbsp; <span class='badge-info'>{inv['categoria']}</span>",
                               unsafe_allow_html=True)
                    st.caption(f"Aporte mensal: R$ {inv['aporte_mensal_planejado']:,.2f} • "
                              f"Taxa: {inv['taxa_anual_estimada']:.1f}% a.a.")
                with col_i2:
                    aporte_extra = st.number_input(
                        "Aportar (R$)", min_value=0.0, step=20.0, key=f"aporte_inv_{inv['id']}",
                        label_visibility="collapsed", placeholder="Aportar (R$)",
                    )
                with col_i3:
                    b1, b2 = st.columns(2)
                    if b1.button("➕", key=f"btn_aporte_inv_{inv['id']}", help="Registrar aporte"):
                        if aporte_extra > 0:
                            novo_valor = float(inv["valor_acumulado"]) + float(aporte_extra)
                            supabase.table("investimentos").update(
                                {"valor_acumulado": novo_valor}
                            ).eq("id", inv["id"]).execute()
                            st.success("Aporte registrado!")
                            invalidar_cache()
                            st.rerun()
                    if inv["profile_id"] == user_id and b2.button("🗑️", key=f"btn_del_inv_{inv['id']}", help="Remover posição"):
                        supabase.table("investimentos").delete().eq("id", inv["id"]).execute()
                        st.success(f"'{inv['ativo']}' removido da carteira.")
                        invalidar_cache()
                        st.rerun()
                st.markdown(f"R$ {inv['valor_acumulado']:,.2f}")
                st.markdown("---")
    else:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-icon">💰</div>
            <div>Nenhuma posição cadastrada ainda.<br>Use "📈 Nova Posição (Carteira)" no menu lateral para começar.</div>
        </div>
        """, unsafe_allow_html=True)

# ══════════════════════════════════════════════
# TAB 4: PROJEÇÕES / SIMULADOR
# ══════════════════════════════════════════════
with tab_simulador:
    st.subheader("📈 Simulador de Aportes Mensais")

    aporte_sugerido = float(df_investimentos["aporte_mensal_planejado"].sum()) if not df_investimentos.empty else 0.0
    if aporte_sugerido == 0.0:
        aporte_sugerido = max(0.0, float(saldo_livre))

    c_s1, c_s2, c_s3 = st.columns(3)
    with c_s1:
        aporte_sim = st.number_input(
            "Aporte Mensal (R$)", value=aporte_sugerido, step=25.0, format="%.2f",
            help="Pré-preenchido com a soma dos aportes planejados na sua Carteira (ou o saldo livre, se a carteira estiver vazia).",
        )
    with c_s2:
        taxa_ano = st.number_input("Taxa Anual (% a.a.)", value=10.0, step=0.5)
    with c_s3:
        meses_sim = st.slider("Prazo (meses)", min_value=6, max_value=120, value=36, step=6)

    if aporte_sim > 0:
        taxa_m = (1 + taxa_ano / 100) ** (1 / 12) - 1
        saldo_proj = 0.0
        investido_proj = 0.0
        linhas = []
        marcos = {}

        for m_idx in range(1, meses_sim + 1):
            saldo_proj = (saldo_proj + aporte_sim) * (1 + taxa_m)
            investido_proj += aporte_sim
            linhas.append({
                "Mês": m_idx,
                "Total Investido": round(investido_proj, 2),
                "Montante com Juros": round(saldo_proj, 2),
                "Rendimento": round(saldo_proj - investido_proj, 2),
            })
            if m_idx in (6, 12, 24, 36, 60, 120):
                marcos[m_idx] = {"investido": investido_proj, "montante": saldo_proj}

        df_proj = pd.DataFrame(linhas)

        # Gráfico Plotly (ao invés de st.line_chart)
        fig_proj = go.Figure()
        fig_proj.add_trace(go.Scatter(
            x=df_proj["Mês"], y=df_proj["Total Investido"],
            name="Total Investido",
            line=dict(color="#118AB2", width=2.5, dash="dot"),
            fill="tonexty" if len(df_proj) > 1 else None,
        ))
        fig_proj.add_trace(go.Scatter(
            x=df_proj["Mês"], y=df_proj["Montante com Juros"],
            name="Montante com Juros",
            line=dict(color="#06D6A0", width=3),
            fill="tonexty",
            fillcolor="rgba(6,214,160,0.1)",
        ))
        fig_proj.add_trace(go.Scatter(
            x=df_proj["Mês"], y=df_proj["Rendimento"],
            name="Rendimento Acumulado",
            line=dict(color="#FFD166", width=2, dash="dash"),
        ))
        fig_proj.update_layout(
            title="Projeção de Patrimônio",
            xaxis_title="Meses",
            yaxis_title="Valor (R$)",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, sans-serif", color="#FAFAFA"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
        )
        st.plotly_chart(fig_proj, use_container_width=True)

        # Marcos resumidos
        st.subheader("📍 Marcos de Prazo")
        marco_cols = st.columns(min(len(marcos), 4))
        for i, (mes, vals) in enumerate(marcos.items()):
            with marco_cols[i % len(marco_cols)]:
                rend = vals["montante"] - vals["investido"]
                st.metric(
                    f"{mes} meses",
                    f"R$ {vals['montante']:,.2f}",
                    delta=f"Rend: R$ {rend:,.2f}",
                )

        st.markdown("---")
        st.markdown(
            f"**💰 Total aportado:** R$ {investido_proj:,.2f} &nbsp;|&nbsp; "
            f"**📈 Montante final:** R$ {saldo_proj:,.2f} &nbsp;|&nbsp; "
            f"**✨ Rendimento:** R$ {saldo_proj - investido_proj:,.2f}"
        )
    else:
        st.info("Configure um aporte mensal maior que zero para ver a projeção.")

# ══════════════════════════════════════════════
# TAB 5: PERFIS & CONTA CONJUNTA
# ══════════════════════════════════════════════
with tab_perfis:
    st.subheader("👤 Meu Perfil")

    # Editar nome
    col_p1, col_p2 = st.columns([3, 1])
    with col_p1:
        new_name = st.text_input(
            "Nome de exibição",
            value=display_name,
            key="edit_display_name",
        )
    with col_p2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✏️ Atualizar Nome"):
            if new_name.strip() and new_name.strip() != display_name:
                update_display_name(new_name.strip())
                st.success("Nome atualizado!")
                st.rerun()

    st.markdown(f"**E-mail:** {user.get('email', '—')}")

    st.markdown("---")

    # ── Perfis do Cartão (sem login) ──
    st.subheader("👥 Perfis do Cartão Compartilhado")
    st.caption(
        "Perfis sem login — ideais para cartão de crédito compartilhado. "
        "Cadastre cada pessoa que usa o cartão (filhos, cônjuge, familiares) "
        "para marcar quem fez cada compra na hora de lançar o gasto, sem precisar "
        "criar uma conta para ela."
    )

    membros_atuais = carregar_membros(user_id)

    if membros_atuais:
        for m in membros_atuais:
            col_m_info, col_m_edit, col_m_del = st.columns([5, 1.2, 1.2])
            with col_m_info:
                st.markdown(f"""
                <div class="member-card">
                    <div class="member-left">
                        <div class="member-avatar" style="background:{m.get('cor', '#1B998B')};">
                            {m.get('emoji', '🙂')}
                        </div>
                        <div>
                            <div class="member-name">{m['nome']}</div>
                            <div class="member-sub">Perfil sem login • cartão compartilhado</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            with col_m_edit:
                with st.popover("✏️ Editar", use_container_width=True):
                    novo_nome_m = st.text_input("Nome", value=m["nome"], key=f"edit_nome_{m['id']}")
                    novo_emoji_m = st.selectbox(
                        "Ícone", MEMBER_EMOJIS,
                        index=MEMBER_EMOJIS.index(m["emoji"]) if m.get("emoji") in MEMBER_EMOJIS else 0,
                        key=f"edit_emoji_{m['id']}",
                    )
                    nova_cor_m = st.selectbox(
                        "Cor", MEMBER_COLORS,
                        index=MEMBER_COLORS.index(m["cor"]) if m.get("cor") in MEMBER_COLORS else 0,
                        key=f"edit_cor_{m['id']}",
                    )
                    if st.button("💾 Salvar", key=f"save_membro_{m['id']}", use_container_width=True):
                        update_member(m["id"], nome=novo_nome_m.strip(), emoji=novo_emoji_m, cor=nova_cor_m)
                        st.success("Perfil atualizado!")
                        invalidar_cache()
                        st.rerun()
            with col_m_del:
                if st.button("🗑️ Remover", key=f"del_membro_{m['id']}", use_container_width=True):
                    delete_member(m["id"])
                    st.success(f"Perfil '{m['nome']}' removido. O histórico de gastos foi mantido.")
                    invalidar_cache()
                    st.rerun()
    else:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-icon">👥</div>
            <div>Nenhum perfil do cartão cadastrado ainda.<br>Use o formulário abaixo para adicionar o primeiro.</div>
        </div>
        """, unsafe_allow_html=True)

    with st.expander("➕ Adicionar Perfil do Cartão"):
        with st.form("form_novo_membro_perfis", clear_on_submit=True):
            c_nm1, c_nm2 = st.columns([1, 2])
            with c_nm1:
                novo_emoji = st.selectbox("Ícone", MEMBER_EMOJIS, key="novo_membro_emoji")
            with c_nm2:
                novo_nome = st.text_input("Nome", placeholder="Ex: Maria, João", key="novo_membro_nome")
            nova_cor = st.selectbox("Cor", MEMBER_COLORS, key="novo_membro_cor")
            if st.form_submit_button("➕ Adicionar", use_container_width=True):
                if novo_nome.strip():
                    if create_member(novo_nome.strip(), novo_emoji, nova_cor):
                        st.success(f"Perfil '{novo_nome}' criado!")
                        invalidar_cache()
                        st.rerun()
                else:
                    st.warning("Informe um nome para o perfil.")

    st.markdown("---")

    # ── Conta Conjunta ──
    st.subheader("🤝 Conta Conjunta")

    ja_info = get_joint_account_info()
    members = get_joint_members()

    if ja_info:
        st.success(f"Você faz parte da conta conjunta: **{ja_info['nome']}**")

        # Código de convite
        st.markdown(f"""
        <div class="invite-code">
            <p style="color:#8D99AE; margin-bottom:6px; font-size:0.85rem;">
                Compartilhe este código para convidar membros:
            </p>
            <code>{ja_info['invite_code']}</code>
        </div>
        """, unsafe_allow_html=True)

        # Membros
        st.markdown("**Membros da conta:**")
        for member in members:
            is_me = member["id"] == user_id
            initial = (member.get("display_name") or "?")[0].upper()
            name = member.get("display_name", "Membro")
            badge = ' <span class="badge-info">Você</span>' if is_me else ""
            st.markdown(f"""
            <div class="profile-card">
                <div class="profile-avatar">{initial}</div>
                <div class="profile-info">
                    <h4>{name}{badge}</h4>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚪 Sair da Conta Conjunta", type="secondary"):
            leave_joint_account()
            st.success("Você saiu da conta conjunta.")
            st.rerun()

    else:
        st.info("Você não está em nenhuma conta conjunta.")
        st.markdown("Crie uma nova ou entre em uma existente usando um código de convite.")

        col_ja1, col_ja2 = st.columns(2)

        with col_ja1:
            st.markdown("**🆕 Criar Nova Conta**")
            with st.form("form_create_ja", clear_on_submit=True):
                ja_nome = st.text_input("Nome da Conta", placeholder="Ex: Casa do Casal")
                if st.form_submit_button("Criar Conta Conjunta", use_container_width=True):
                    if ja_nome.strip():
                        result = create_joint_account(ja_nome.strip())
                        if result:
                            st.success(f"Conta '{ja_nome}' criada! Código: **{result['invite_code']}**")
                            st.rerun()

        with col_ja2:
            st.markdown("**🔗 Entrar com Código**")
            with st.form("form_join_ja", clear_on_submit=True):
                invite_input = st.text_input("Código de Convite", placeholder="Ex: a1b2c3d4")
                if st.form_submit_button("Ingressar", use_container_width=True):
                    if invite_input.strip():
                        if join_joint_account(invite_input.strip()):
                            st.rerun()

# ──────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<p style="text-align:center; color:#8D99AE; font-size:0.8rem;">'
    '💳 Gestor Financeiro Multi-Perfil &nbsp;•&nbsp; Dados sincronizados em nuvem via Supabase'
    '</p>',
    unsafe_allow_html=True,
)
