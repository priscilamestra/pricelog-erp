import streamlit as st
import pandas as pd
import database as db
import rpa_monitor
import time

st.set_page_config(page_title="Pricelog ERP", page_icon="💲", layout="wide")

st.markdown("""
    <style>
    div[data-testid="InputInstructions"] { display: none !important; }
    [data-testid="stFileUploadDropzone"] {
        min-height: 180px !important;
        border-radius: 12px !important;
        border: 2px dashed #a0a0a0 !important;
        background-color: #fcfcfc !important;
    }
    [data-testid="stFileUploadDropzone"] small { display: none !important; }

    /* Tamanho das abas — seletores individuais forçam aplicação em qualquer versão Streamlit */
    button[data-baseweb="tab"] p { font-size: 22px !important; font-weight: 600 !important; }
    button[data-baseweb="tab"] span { font-size: 22px !important; font-weight: 600 !important; }
    [data-testid="stTab"] p { font-size: 22px !important; font-weight: 600 !important; }
    [data-testid="stTab"] span { font-size: 22px !important; font-weight: 600 !important; }
    button[role="tab"] p { font-size: 22px !important; font-weight: 600 !important; }
    button[role="tab"] span { font-size: 22px !important; font-weight: 600 !important; }
    div[data-baseweb="tab-list"] button { font-size: 22px !important; font-weight: 600 !important; }

    button[kind="primary"] {
        background-color: transparent !important;
        border: 1px solid rgba(250,250,250,0.2) !important;
        color: #fafafa !important;
        transition: all 0.3s ease-in-out !important;
    }
    button[kind="primary"]:hover {
        background-color: #ff4b4b !important;
        border: 1px solid #ff4b4b !important;
        color: #ffffff !important;
    }
    </style>""", unsafe_allow_html=True)

db.inicializar_banco()
db.inicializar_tabelas_monitor()

# ── Session state defaults ──────────────────────────────────────────────────
for key, val in {
    'autenticado':              False,
    'mostrar_tabela_cadastro':  False,
    'gerenciar_gen':            0,
    'codigos_pre_selecionados': [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = val


def _get_serpapi_key() -> str | None:
    try:
        key = st.secrets["serpapi"]["api_key"]
        return key if key else None
    except (KeyError, AttributeError, Exception):
        return None


# ── LOGIN ───────────────────────────────────────────────────────────────────
if not st.session_state['autenticado']:
    st.title("🔒 Pricelog ERP")
    st.markdown("Insira suas credenciais para acessar o sistema.")
    with st.form("login_form"):
        email = st.text_input("E-mail")
        senha = st.text_input("Senha de Acesso", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if (email == st.secrets["login_sistema"]["email_admin"] and
                    senha == st.secrets["login_sistema"]["senha_admin"]):
                st.session_state['autenticado'] = True
                st.rerun()
            else:
                st.error("Credenciais inválidas. Acesso negado.")
    st.stop()

# ── DASHBOARD ───────────────────────────────────────────────────────────────
col_titulo, col_sair = st.columns([8.5, 1.5])
with col_titulo:
    st.title("Pricelog Dashboard", anchor=False)
with col_sair:
    if st.button("Sign out", width="stretch"):
        st.session_state['autenticado'] = False
        st.rerun()

dados_banco = db.listar_produtos()
df_produtos = pd.DataFrame(dados_banco)

COLUNAS_INTERNAS = ["id", "codigo", "marca", "tipo", "modelo", "categoria",
                    "preco_unitario", "custo", "obs"]

if not df_produtos.empty:
    if "segmento" in df_produtos.columns:
        if "categoria" not in df_produtos.columns or df_produtos["categoria"].isna().all():
            df_produtos = df_produtos.rename(columns={"segmento": "categoria"})
        else:
            df_produtos = df_produtos.drop(columns=["segmento"])
    for col in COLUNAS_INTERNAS:
        if col not in df_produtos.columns:
            df_produtos[col] = ""
    df_produtos = df_produtos[COLUNAS_INTERNAS].sort_values(by="id", ascending=True)

COLS_EXIBICAO_COM_ID = {
    "id": "ID", "codigo": "Código", "marca": "Marca", "tipo": "Tipo",
    "modelo": "Modelo", "categoria": "Categoria",
    "preco_unitario": "Preço (R$)", "custo": "Custo (R$)", "obs": "Observações"
}
COLS_EXIBICAO_SEM_ID = {
    "codigo": "Código", "marca": "Marca", "tipo": "Tipo",
    "modelo": "Modelo", "categoria": "Categoria",
    "preco_unitario": "Preço (R$)", "custo": "Custo (R$)", "obs": "Observações"
}

aba_cadastrar, aba_gerenciar, aba_automacoes = st.tabs(
    ["📦 Cadastrar", "🗂️ Gerenciar", "⚙️ Automações"]
)

# ════════════════════════════════════════════════════════════════════════════
# 1. CADASTRAR
# ════════════════════════════════════════════════════════════════════════════
with aba_cadastrar:
    st.markdown("<br>", unsafe_allow_html=True)
    _, col_q, _ = st.columns([2, 4, 2])
    with col_q:
        arquivo = st.file_uploader("📥 Importação de Base (.csv)", type=["csv"],
                                    label_visibility="collapsed")
        if arquivo is not None:
            if st.button("Processar Arquivo", type="secondary", width="stretch"):
                df_csv = pd.read_csv(arquivo)
                if "segmento" in df_csv.columns and "categoria" not in df_csv.columns:
                    df_csv = df_csv.rename(columns={"segmento": "categoria"})
                sucessos = 0
                for _, row in df_csv.iterrows():
                    try:
                        db.criar_produto(
                            str(row['codigo']), str(row['marca']), str(row['tipo']),
                            str(row.get('modelo', '')), str(row.get('categoria', '')),
                            float(row['preco_unitario']), float(row['custo']),
                            str(row['obs']) if str(row['obs']) != 'nan' else "")
                        sucessos += 1
                    except Exception:
                        pass
                st.session_state['mostrar_tabela_cadastro'] = True
                st.success(f"Sincronização concluída: {sucessos} registros integrados.")
                st.rerun()
        st.caption("* Colunas esperadas: codigo, marca, tipo, modelo, categoria, preco_unitario, custo, obs")

    st.subheader("Novo Produto", anchor=False)
    with st.form("form_novo_produto", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            n_cod    = st.text_input("Código de Identificação")
            n_marca  = st.text_input("Marca")
            n_tipo   = st.text_input("Tipo  (ex: Notebook, Mouse)")
        with c2:
            n_modelo   = st.text_input("Modelo  (ex: MacBook Air M2)")
            n_segmento = st.text_input("Categoria  (ex: Notebook, Celular)")
        with c3:
            n_preco = st.number_input("Preço de Venda (R$)", min_value=0.0,
                                       step=0.01, value=None, placeholder="0,00")
            n_custo = st.number_input("Custo de Aquisição (R$)", min_value=0.0,
                                       step=0.01, value=None, placeholder="0,00")
        n_obs = st.text_area("Observações", height=60)
        cb1, _, cb2 = st.columns([2, 4, 2])
        with cb1:
            btn_add    = st.form_submit_button("Adicionar Produto", type="primary", width="stretch")
        with cb2:
            btn_limpar = st.form_submit_button("Limpar formulário", width="stretch")

    msg = st.empty()
    if btn_add:
        if n_cod:
            try:
                db.criar_produto(n_cod, n_marca, n_tipo, n_modelo, n_segmento,
                                  n_preco or 0.0, n_custo or 0.0, n_obs)
                st.session_state['mostrar_tabela_cadastro'] = True
                msg.success(f"Item [{n_cod}] catalogado com sucesso!")
                time.sleep(2)
                st.rerun()
            except Exception:
                msg.error("Erro ao salvar. Verifique se o código já existe.")
        else:
            msg.warning("O Código de Identificação é obrigatório.")

    if st.session_state['mostrar_tabela_cadastro'] and not df_produtos.empty:
        st.subheader("Preview tabela atualizada", anchor=False)
        df_preview = df_produtos[list(COLS_EXIBICAO_SEM_ID.keys())].rename(columns=COLS_EXIBICAO_SEM_ID)
        st.dataframe(df_preview, width="stretch", hide_index=True)
        _, col_btn = st.columns([6, 2])
        with col_btn:
            if st.button("Limpar Tabela", width="stretch"):
                st.session_state['mostrar_tabela_cadastro'] = False
                st.rerun()
    else:
        st.info("Nenhuma importação ou cadastro realizado nesta sessão.")

# ════════════════════════════════════════════════════════════════════════════
# 2. GERENCIAR
# ════════════════════════════════════════════════════════════════════════════
with aba_gerenciar:
    st.subheader("Gerenciamento de Registro", anchor=False)

    if not df_produtos.empty:
        gen = st.session_state["gerenciar_gen"]

        opcoes_produtos = {
            f"ID {row['id']} — {row['codigo']}": row["id"]
            for _, row in df_produtos.iterrows()
        }

        produto_selecionado = st.selectbox(
            "Busque pelo ID ou código do produto:",
            options=list(opcoes_produtos.keys()),
            index=None,
            placeholder="Digite um ID ou código",
            key=f"sel_id_{gen}",
        )

        id_editar = (
            opcoes_produtos[produto_selecionado]
            if produto_selecionado is not None
            else None
        )

        if id_editar is not None:
            p = df_produtos[df_produtos["id"] == id_editar].iloc[0]
            v = {
                col: p[col]
                for col in [
                    "codigo",
                    "marca",
                    "tipo",
                    "modelo",
                    "categoria",
                    "preco_unitario",
                    "custo",
                    "obs",
                ]
            }
            v["preco_unitario"] = float(v["preco_unitario"])
            v["custo"] = float(v["custo"])
        else:
            v = {
                "codigo": "",
                "marca": "",
                "tipo": "",
                "modelo": "",
                "categoria": "",
                "preco_unitario": None,
                "custo": None,
                "obs": "",
            }

        c1, c2, c3 = st.columns(3)
        with c1:
            e_cod = st.text_input("Código", value=v["codigo"])
            e_marca = st.text_input("Marca", value=v["marca"])
            e_tipo = st.text_input("Tipo", value=v["tipo"])

        with c2:
            e_modelo = st.text_input("Modelo", value=v["modelo"])
            e_categoria = st.text_input("Categoria", value=v["categoria"])

        with c3:
            e_preco = st.number_input(
                "Preço de Venda (R$)",
                value=v["preco_unitario"],
                step=0.01,
                placeholder="0,00",
            )
            e_custo = st.number_input(
                "Custo (R$)",
                value=v["custo"],
                step=0.01,
                placeholder="0,00",
            )

        e_obs = st.text_area(
            "Observações",
            value=v["obs"],
            key=f"obs_{gen}_{id_editar}",
        )

        st.markdown("<br>", unsafe_allow_html=True)

        b1, b2, b3 = st.columns(3)
        aviso = st.empty()

        with b1:
            if st.button(
                "Salvar alterações",
                type="primary",
                width="stretch",
            ):
                if id_editar is not None:
                    db.atualizar_produto(
                        id_editar,
                        e_cod,
                        e_marca,
                        e_tipo,
                        e_modelo,
                        e_categoria,
                        e_preco,
                        e_custo,
                        e_obs,
                    )
                    aviso.success("Alterações salvas!")
                    time.sleep(1)
                    st.session_state["gerenciar_gen"] += 1
                    st.rerun()
                else:
                    aviso.warning("Selecione um produto primeiro!")

        with b2:
            if st.button(
                "Limpar formulário",
                type="primary",
                width="stretch",
            ):
                st.session_state["gerenciar_gen"] += 1
                st.rerun()

        with b3:
            if st.button(
                "Excluir item",
                type="primary",
                width="stretch",
            ):
                if id_editar is not None:
                    db.deletar_produto(id_editar)
                    aviso.success("Item removido!")
                    time.sleep(1)
                    st.session_state["gerenciar_gen"] += 1
                    st.rerun()
                else:
                    aviso.warning("Selecione um produto primeiro!")

    st.write("---")
    st.subheader("Produtos Cadastrados", anchor=False)

    if not df_produtos.empty:
        col_busca, col_aviso_ger = st.columns([5, 4])

        with col_busca:
            termo = st.text_input(
                "Buscar:",
                placeholder=" 🔍",
                label_visibility="collapsed",
                key="busca_ger",
            )

        df_ex = df_produtos.rename(columns=COLS_EXIBICAO_COM_ID)

        if termo:
            tl = termo.lower()
            mask = df_ex.astype(str).apply(
                lambda c: c.str.lower().str.contains(tl, na=False)
            ).any(axis=1)

            df_fil = df_ex[mask]

            if df_fil.empty:
                av = col_aviso_ger.empty()
                av.info(f'🔍 Nenhum produto encontrado para "{termo}".')
                time.sleep(3)
                av.empty()
                st.dataframe(
                    df_ex,
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.dataframe(
                    df_fil,
                    width="stretch",
                    hide_index=True,
                )
        else:
            st.dataframe(
                df_ex,
                width="stretch",
                hide_index=True,
            )
    else:
        st.info("Nenhuma mercadoria localizada na base ativa.")

# ════════════════════════════════════════════════════════════════════════════
# 3. AUTOMAÇÕES
# ════════════════════════════════════════════════════════════════════════════
with aba_automacoes:
    st.subheader("Monitor de Preços Online", anchor=False)

    modo = st.radio("Modo de análise:",
        ["⚡ Rápido (Google Shopping - API)",
         "🖥️ Detalhado (Navegador - Playwright)"],
        horizontal=True)
    modo_rapido = modo.startswith("⚡")

    st.markdown("<br>", unsafe_allow_html=True)

    site_escolhido = "Mercado Livre"
    if not modo_rapido:
        st.warning("⚠️ Modo Detalhado limitado a **5 produtos** por sessão (2 min entre sessões).")
        site_escolhido = st.selectbox("Site de pesquisa:",
                                       list(rpa_monitor.SITES_DISPONIVEIS.keys()))

    analises_salvas = db.listar_analises()

    opcoes = {"— Selecione uma análise para carregar alertas —": None}
    for a in analises_salvas:
        if a["total_alertas"] > 0:
            fmt  = a["data_criacao"].strftime("%d/%m/%Y às %H:%M")
            icon = "⚡" if a.get("modo") == "Rápido" else "🖥️"
            opcoes[f"📊 {fmt} — {a['total_alertas']} moderado/crítico — {icon} {a.get('modo','Rápido')} · {a.get('fonte','')}"] = a["id"]

    if len(opcoes) > 1:
        escolha = st.selectbox("Carregar moderados/críticos de uma análise salva:",
                                list(opcoes.keys()), index=0, key="sel_analise_alertas")
        if opcoes[escolha] is not None:
            if st.button("Carregar seleção desta análise", width="content"):
                itens = db.buscar_itens_analise(opcoes[escolha])
                codigos = [i["codigo_produto"] for i in itens
                           if i["status"] in ["⚠️ Moderado","⚠️ Alerta","🔴 Crítico"]]
                st.session_state["codigos_pre_selecionados"] = codigos[:5] if not modo_rapido else codigos
                st.session_state['gerenciar_gen'] += 1
                st.rerun()
    else:
        st.caption("Nenhuma análise com moderado ou crítico encontrada.")

    # ════════════════════════════════════════════════════════════════════════
    # FRAGMENT: seleção de produtos com checkboxes
    # ════════════════════════════════════════════════════════════════════════
    @st.fragment
    def tabela_selecao(df_produtos, modo_rapido, COLUNAS_INTERNAS):
        pre_sel = list(st.session_state.get("codigos_pre_selecionados", []))
        gen     = st.session_state['gerenciar_gen']

        if modo_rapido:
            st.markdown("**Selecione os produtos**:")
        else:
            st.markdown("**Selecione até 10 produtos para auditar:**")

        col_busca, col_aviso_a, col_lmp, col_tudo = st.columns([4, 3, 1.5, 1.5])
        with col_busca:
            filtro = st.text_input("Filtrar:", placeholder="🔍 Código, Marca, Modelo...",
                                   label_visibility="collapsed", key="filtro_auto")
        with col_lmp:
            if st.button("Limpar", width="stretch", key="btn_limpar_sel"):
                st.session_state["codigos_pre_selecionados"] = []
                st.session_state['gerenciar_gen'] += 1
                st.rerun()
        with col_tudo:
            if st.button("☑️ Todos", width="stretch", key="btn_todos_sel"):
                todos = df_produtos["codigo"].tolist() if not df_produtos.empty else []
                st.session_state["codigos_pre_selecionados"] = todos[:5] if not modo_rapido else todos
                st.session_state['gerenciar_gen'] += 1
                st.rerun()

        df_base = (df_produtos.copy() if not df_produtos.empty
                   else pd.DataFrame(columns=COLUNAS_INTERNAS))
        df_filtrado = df_base.copy()

        if filtro and not df_base.empty:
            tl   = filtro.lower()
            mask = df_base.astype(str).apply(
                lambda c: c.str.lower().str.contains(tl, na=False)
            ).any(axis=1)
            df_filtrado = df_base[mask]
            if df_filtrado.empty:
                av = col_aviso_a.empty()
                av.info(f'🔍 Nenhum produto para "{filtro}".')
                time.sleep(3)
                av.empty()
                df_filtrado = df_base.copy()

        if not df_filtrado.empty:
            df_exib = df_filtrado[
                ["codigo","marca","tipo","modelo","categoria","preco_unitario"]
            ].copy()
            df_exib.columns = ["Código","Marca","Tipo","Modelo","Categoria","Preço (R$)"]
            df_exib.insert(0, "✓", df_filtrado["codigo"].isin(pre_sel))

            editor_key = f"editor_{gen}_{hash(filtro)}"
            editado = st.data_editor(
                df_exib,
                column_config={"✓": st.column_config.CheckboxColumn("✓", default=False)},
                disabled=["Código","Marca","Tipo","Modelo","Categoria","Preço (R$)"],
                hide_index=True,
                width="stretch",
                key=editor_key,
            )

            checked  = set(editado.loc[editado["✓"], "Código"].tolist())
            in_view  = set(df_filtrado["codigo"].tolist())
            out_view = set(pre_sel) - in_view
            nova_sel = list(out_view | checked)
            if set(nova_sel) != set(pre_sel):
                st.session_state["codigos_pre_selecionados"] = nova_sel
        else:
            st.info("Nenhum produto cadastrado para selecionar.")

        total_sel = len(st.session_state.get("codigos_pre_selecionados", []))
        if not modo_rapido and total_sel > 5:
            st.error(f"Selecionados: {total_sel}. Máximo: 5 no modo Detalhado.")
        else:
            st.caption(f"{total_sel}/{'30' if modo_rapido else '5'} produtos selecionados.")

    tabela_selecao(df_produtos, modo_rapido, COLUNAS_INTERNAS)

    selecao_final = st.session_state.get("codigos_pre_selecionados", [])
    total_sel     = len(selecao_final)

    margem_minima = st.slider("Margem mínima aceitável (%)", 5, 80, 30)

    col_btn, _ = st.columns([2, 6])
    with col_btn:
        btn_analisar = st.button("🔍 Gerar Nova Análise", type="primary", width="stretch")

    if btn_analisar:
        if df_produtos.empty:
            st.warning("Nenhum produto cadastrado.")
        elif not modo_rapido and total_sel == 0:
            st.warning("Selecione ao menos 1 produto para o Modo Detalhado.")
        elif not modo_rapido and total_sel > 5:
            st.error("Reduza a seleção para no máximo 5 produtos por sessão.")
        else:
            produtos_lista = (
                df_produtos[df_produtos["codigo"].isin(selecao_final)].to_dict("records")
                if total_sel > 0 else df_produtos.to_dict("records")
            )

            if modo_rapido:
                serpapi_key = _get_serpapi_key()
                if not serpapi_key:
                    st.warning("⚠️ Chave SerpAPI não configurada. "
                               "Adicione [serpapi] api_key no secrets.toml.")
                    st.stop()

                prog = st.progress(0, text="Iniciando consulta...")
                def cb_r(atual, total, nome):
                    prog.progress(int(atual/total*100),
                                  text=f"Consultando {atual}/{total}: {nome}")

                with st.spinner("Consultando Google Shopping..."):
                    try:
                        res = rpa_monitor.analisar_rapido(
                            produtos_lista, margem_minima, cb_r,
                            serpapi_key=serpapi_key)
                        db.salvar_analise(res, modo="Rápido", fonte="Google Shopping")
                        prog.progress(100, text="Concluído!")
                        st.success(f"✅ {len(res)} produtos analisados.")
                        st.session_state["codigos_pre_selecionados"] = []
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")
            else:
                total_s = max(1, -(-total_sel // 10))
                prog    = st.progress(0, text="Iniciando auditoria...")
                st_sess = st.empty()
                st_wait = st.empty()

                def cb_p(atual, total, nome, sn, ts):
                    prog.progress(int(atual/total*100),
                                  text=f"Sessão {sn}/{ts} — {atual}/{total}: {nome}")
                    st_sess.info(f"🔍 Sessão {sn} de {ts} em andamento...")

                def cb_w(sn, ts, seg):
                    m, s = divmod(seg, 60)
                    pct  = int((180-seg)/180*100)
                    st_wait.info(
                        f"⏳ Sessão {sn}/{ts}. Próxima em {m}m{s:02d}s "
                        f"[{'█'*(pct//10)}{'░'*(10-pct//10)}] {pct}%")

                try:
                    res = rpa_monitor.analisar_detalhado_sessoes(
                        produtos_lista, margem_minima, site_escolhido, cb_p, cb_w)
                    db.salvar_analise(res, modo="Detalhado", fonte=site_escolhido)
                    prog.progress(100, text="Concluído!")
                    st_sess.empty()
                    st_wait.empty()
                    st.success(f"✅ {len(res)} produtos auditados via {site_escolhido}.")
                    st.session_state["codigos_pre_selecionados"] = []
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

    st.write("---")

    # ── Histórico ────────────────────────────────────────────────────────────
    st.subheader("Análises salvas (últimos 15 dias)", anchor=False)
    analises = db.listar_analises()

    if not analises:
        st.info("Nenhuma análise gerada ainda.")
    else:
        for a in analises:
            data_fmt   = a["data_criacao"].strftime("%d/%m/%Y às %H:%M")
            expira_fmt = a["expira_em"].strftime("%d/%m/%Y")
            icon       = "⚡" if a.get("modo") == "Rápido" else "🔍"
            label = (f"📊  {data_fmt}  —  {a['total_produtos']} produtos  |  "
                     f"{a['total_alertas']} moderado/crítico  |  "
                     f"{icon} {a.get('modo','Rápido')} · {a.get('fonte','')}  |  "
                     f"expira {expira_fmt}")
            with st.expander(label):
                itens = db.buscar_itens_analise(a["id"])
                if itens:
                    df_it = pd.DataFrame(itens).rename(columns={
                        "codigo_produto": "Código",
                        "nome_produto":   "Produto",
                        "seu_preco":      "Seu Preço (R$)",
                        "preco_mercado":  "Mercado (R$)",
                        "diferenca_percent": "Diferença %",
                        "margem_percent": "Margem %",
                        "status":         "Status",
                    }).drop(columns=["id","analise_id"], errors="ignore")

                    df_it["Mercado (R$)"] = pd.to_numeric(df_it["Mercado (R$)"], errors="coerce")

                    # Coluna Mercado: preço OU "Bloqueado" OU "Não encontrado"
                    # Convertida para string uniforme → evita crash ArrowInvalid
                    def _fmt_mercado(row):
                        val = row["Mercado (R$)"]
                        if pd.notna(val) and float(val) > 0:
                            return f"{float(val):.2f}"
                        if row["Status"] == "🚫 Erro":
                            return "Bloqueado"
                        return "Não encontrado"
                    df_it["Mercado (R$)"] = df_it.apply(_fmt_mercado, axis=1).astype(str)

                    mod = len(df_it[df_it["Status"].isin(["⚠️ Moderado","⚠️ Alerta"])])
                    ca, cb, cc = st.columns(3)
                    ca.metric("✅ OK",       len(df_it[df_it["Status"] == "✅ OK"]))
                    cb.metric("⚠️ Moderado", mod)
                    cc.metric("🔴 Crítico",  len(df_it[df_it["Status"] == "🔴 Crítico"]))
                    st.dataframe(df_it, width="stretch", hide_index=True)

    # ── Painel de testes ──────────────────────────────────────────────────────
    with st.expander("🛠️ Painel de Controle de Testes (Remover antes do Deploy)"):
        st.subheader("🔑 Diagnóstico de APIs", anchor=False)

        serpapi_key_atual = _get_serpapi_key()
        if serpapi_key_atual:
            st.success(f"✅ SerpAPI configurada: `...{serpapi_key_atual[-6:]}`")
        else:
            st.error("❌ SerpAPI NÃO encontrada.\n"
                     "Verifique se secrets.toml tem:\n```\n[serpapi]\napi_key = \"SUA_CHAVE\"\n```")

        produto_teste = st.text_input("Produto para testar:", value="Logitech MX Master 3S",
                                      key="prod_teste_api")
        if st.button("🧪 Testar SerpAPI agora", width="content"):
            if not serpapi_key_atual:
                st.error("Configure a chave SerpAPI primeiro.")
            else:
                with st.spinner("Chamando SerpAPI..."):
                    resultado = rpa_monitor.testar_serpapi(serpapi_key_atual, produto_teste)
                st.json(resultado)
                if resultado.get("total_resultados", 0) > 0:
                    st.success(f"✅ SerpAPI OK! {resultado['total_resultados']} resultados.")
                elif resultado.get("erro_api"):
                    st.error(f"Erro: {resultado['erro_api']}")
                else:
                    st.warning("API respondeu mas sem resultados de shopping.")

        st.write("---")
        st.warning("Apaga TODOS os dados do banco e zera os IDs.")
        if st.button("🚨 Reset de Fábrica: Apagar Tudo e Zerar IDs"):
            db.resetar_banco()
            st.success("Banco resetado com sucesso!")
            st.rerun()