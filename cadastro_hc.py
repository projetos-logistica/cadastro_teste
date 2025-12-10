# cadastro_hc.py
# ---------------------------------------------------------------
# Requisitos:
#   pip install -r requirements.txt
#   (inclua: psycopg2-binary, SQLAlchemy, pandas, streamlit, openpyxl etc.)
# Rode com: streamlit run cadastro_hc.py
# ---------------------------------------------------------------

import streamlit as st
import pandas as pd
import os
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from typing import List, Tuple, Dict

# Conexão com Supabase/Postgres
from DB_supabase import get_conn, test_connection, get_config

# ------------------------------
# Config Básica
# ------------------------------
st.set_page_config(page_title="Presenças - Logística", layout="wide")

STATUS_OPCOES = ["", "PRESENTE", "BH", "ATRASADO", "FALTA", "FÉRIAS",
                 "ATESTADO", "AFASTADO", "ANIVERSÁRIO", "SAIDA ANTC",
                 "SIN ECOM", "SIN DIST", "SIN AVI", "SIN REC", "SIN EXP",
                 "SIN ALM", "SIN TEC", "DSR", "CURSO", "DESLIGADO", "-"]

OPCOES_SETORES = [
    "Aviamento",
    "Tecido",
    "Distribuição",
    "Almoxarifado",
    "PAF",
    "Recebimento",
    "Expedição",
    "E-commerce",
]
OPCOES_TURNOS = ["1°", "2°", "3°", "ÚNICO", "INTERMEDIARIO"]

# quais status "SIN" redirecionam o setor do dia
SIN_TO_SETOR = {
    "SIN AVI":  "Aviamento",
    "SIN REC":  "Recebimento",
    "SIN EXP":  "Expedição",
    "SIN ALM":  "Almoxarifado",
    "SIN TEC":  "Tecido",
    "SIN ECOM": "E-commerce",
    "SIN DIST": "Distribuição",
}

def normaliza_turno(t: str) -> str:
    t = (t or "").strip().upper().replace("º", "°")
    if t == "UNICO":
        t = "ÚNICO"
    if t == "INTERMEDIÁRIO":
        t = "INTERMEDIARIO"
    return t if t in ["1°", "2°", "3°", "ÚNICO", "INTERMEDIARIO"] else "1°"

# --- LOGIN por e-mail (sem senha) --------------------------------------------
ALLOWED_EMAILS_DEFAULT = {
    "projetos.logistica@somagrupo.com.br",  # admin
    "lucas.silverio@somagrupo.com.br",
  "rodrigo.pessoa@somagrupo.com.br",
  "marcos.lima@somagrupo.com.br", 
  "luiz.anchieta@somagrupo.com.br", 
  "carlos.desouza@somagrupo.com.br",
  "natanael.junior@somagrupo.com.br", 
  "luiz.silva@somagrupo.com.br", 
  "alessandro.jorge@farmrio.com.br",
  "eduardo.oliveira@somagrupo.com.br", 
  "allan.pires@somagrupo.com.br", 
  "marlon.freitas@somagrupo.com.br",
  "fernando.souza@animale.com.br",
  "patrick.lima@somagrupo.com.br",
  "leandro.fernandes@somagrupo.com.br",
  "bruno.soares@animale.com.br",
  "lucas.mlima@somagrupo.com.br",
  "vinicius.stefano@somagrupo.com.br",
  "gabriella.sozinho@animale.com.br", #usuário comum (sem admin)
}

ADMIN_EMAILS = {
    "projetos.logistica@somagrupo.com.br",
}

def _allowed_emails():
    emails = {e.lower() for e in ALLOWED_EMAILS_DEFAULT}
    try:
        secret_users = st.secrets.get("users", {})
        if isinstance(secret_users, dict):
            emails |= {k.lower() for k in secret_users.keys()}
        elif isinstance(secret_users, (list, set, tuple)):
            emails |= {str(e).lower() for e in secret_users}
    except Exception:
        pass
    return emails

def is_admin() -> bool:
    email = (st.session_state.get("user_email") or "").lower()
    try:
        admins_extra = set([e.lower() for e in st.secrets.get("admins", [])])
    except Exception:
        admins_extra = set()
    return email in (ADMIN_EMAILS | admins_extra)

def display_name_from_email(email: str) -> str:
    local = (email or "").split("@")[0]
    if not local:
        return ""
    parts = local.replace("_", ".").replace("-", ".").split(".")
    parts = [p for p in parts if p]
    return " ".join(w.capitalize() for w in parts)

def show_login():
    st.markdown("<h2 style='text-align:center;'>Login</h2>", unsafe_allow_html=True)
    with st.form("login_somente_email"):
        email = st.text_input("E-mail").strip().lower()
        ok = st.form_submit_button("Entrar")

    if ok:
        allowed = _allowed_emails()
        if email in allowed:
            st.session_state["auth"] = True
            st.session_state["user_email"] = email
            st.success("Acesso liberado!")
            st.rerun()
        else:
            st.error("E-mail não autorizado.")
    st.stop()

# ------------------------------
# Banco (Postgres/Supabase) - Tabelas
# ------------------------------
def init_db():
    """Cria tabelas caso não existam (seguro para rodar várias vezes)."""
    with get_conn() as cn, cn.cursor() as cur:
        cur.execute("""
        create table if not exists public.leaders (
          id          bigserial primary key,
          nome        varchar(200) not null,
          setor       varchar(100) not null,
          turno       varchar(20)  not null,
          created_at  timestamptz  not null default now()
        );
        """)
        cur.execute("""
        create table if not exists public.colaboradores (
          id          bigserial primary key,
          nome        varchar(200) not null,
          setor       varchar(100) not null,
          turno       varchar(20)  not null,
          ativo       boolean      not null default true,
          created_at  timestamptz  not null default now()
        );
        """)
        cur.execute("""
        create table if not exists public.presencas (
          id              bigserial primary key,
          colaborador_id  bigint      not null,
          data            date        not null,
          status          varchar(20),
          setor           varchar(100) not null,
          turno           varchar(20)  not null,
          leader_nome     varchar(200),
          created_at      timestamptz  not null default now(),
          updated_at      timestamptz,
          constraint uq_presenca unique (colaborador_id, data),
          constraint fk_presenca_colab
            foreign key (colaborador_id) references public.colaboradores(id)
        );
        """)
        cn.commit()


def _try_auto_import_seed():
    caminhos = [
        "Turno Colaboradores.xlsx",
        "turnos.xlsx",
        "turnos.csv",
        "/mnt/data/Turno Colaboradores.xlsx",
    ]
    for p in caminhos:
        try:
            if os.path.exists(p):
                with open(p, "rb") as f:
                    importar_turnos_de_arquivo(f, setor_padrao=None)
                break
        except Exception:
            pass

# ------------------------------
# Utilitários de período (16..15)
# ------------------------------
MESES_PT = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]

def periodo_por_data(ref: date) -> Tuple[date, date]:
    if ref.day >= 16:
        inicio = ref.replace(day=16)
    else:
        inicio = (ref.replace(day=1) - relativedelta(months=1)).replace(day=16)
    fim = (inicio + relativedelta(months=1)).replace(day=15)
    return inicio, fim

def listar_periodos(n: int = 12) -> List[Tuple[str, date, date]]:
    hoje = date.today()
    inicio_atual, _ = periodo_por_data(hoje)
    periodos = []
    for i in range(n):
        ini = inicio_atual - relativedelta(months=i)
        fim = (ini + relativedelta(months=1)).replace(day=15)
        rotulo = f"{ini.day} {MESES_PT[ini.month-1]} {ini.year} – {fim.day} {MESES_PT[fim.month-1]} {fim.year}"
        periodos.append((rotulo, ini, fim))
    return periodos

def datas_do_periodo(inicio: date, fim: date) -> List[date]:
    n = (fim - inicio).days + 1
    return [inicio + timedelta(days=i) for i in range(n)]

def data_minima_preenchimento(hoje: date | None = None) -> date:
    h = hoje or date.today()
    inicio, _ = periodo_por_data(h)
    return inicio

# ------------------------------
# Camada de dados (Postgres)
# ------------------------------
def get_or_create_leader(nome: str, setor: str, turno: str) -> int:
    cn = get_conn(); cur = cn.cursor()
    cur.execute(
        "SELECT id FROM public.leaders WHERE nome=%s AND setor=%s AND turno=%s",
        (nome.strip(), setor, turno)
    )
    row = cur.fetchone()
    if row:
        cur.close(); cn.close()
        return int(row[0])  # <-- r[0] em vez de row["id"]

    cur.execute(
        "INSERT INTO public.leaders (nome, setor, turno) VALUES (%s, %s, %s) RETURNING id",
        (nome.strip(), setor, turno),
    )
    new_id = cur.fetchone()[0]  # <-- índice 0
    cn.commit(); cur.close(); cn.close()
    return int(new_id)


def listar_colaboradores(setor: str, turno: str, somente_ativos=True) -> pd.DataFrame:
    cn = get_conn()
    query = "SELECT id, nome, setor, turno, ativo FROM public.colaboradores WHERE setor=%s AND turno=%s"
    if somente_ativos:
        query += " AND ativo=true"
    df = pd.read_sql(query, cn, params=(setor, turno))
    cn.close()
    return df

def listar_colaboradores_por_setor(setor: str, somente_ativos=True) -> pd.DataFrame:
    cn = get_conn()
    query = "SELECT id, nome, setor, turno, ativo FROM public.colaboradores WHERE setor=%s"
    params = [setor]
    if somente_ativos:
        query += " AND ativo=true"
    df = pd.read_sql(query, cn, params=params)
    cn.close()
    return df

def listar_colaboradores_setor_turno(setor: str, turno: str, somente_ativos=True) -> pd.DataFrame:
    cn = get_conn()
    query = "SELECT id, nome, setor, turno, ativo FROM public.colaboradores WHERE setor=%s AND turno=%s"
    params = [setor, turno]
    if somente_ativos:
        query += " AND ativo=true"
    df = pd.read_sql(query, cn, params=params)
    cn.close()
    return df

def listar_todos_colaboradores(somente_ativos: bool = False) -> pd.DataFrame:
    cn = get_conn()
    query = "SELECT id, nome, setor, turno, ativo FROM public.colaboradores"
    if somente_ativos:
        query += " WHERE ativo=true"
    df = pd.read_sql(query, cn)
    cn.close()
    return df

def adicionar_colaborador(nome: str, setor: str, turno: str):
    turno = normaliza_turno(turno)
    cn = get_conn(); cur = cn.cursor()
    cur.execute(
        "INSERT INTO public.colaboradores (nome, setor, turno, ativo) VALUES (%s, %s, %s, true)",
        (nome.strip(), setor, turno),
    )
    cn.commit(); cur.close(); cn.close()

def atualizar_turno_colaborador(colab_id: int, novo_turno: str):
    novo_turno = normaliza_turno(novo_turno)
    cn = get_conn(); cur = cn.cursor()
    cur.execute("UPDATE public.colaboradores SET turno=%s WHERE id=%s", (novo_turno, colab_id))
    cn.commit(); cur.close(); cn.close()

def upsert_colaborador_turno(nome: str, setor: str, turno: str):
    turno = normaliza_turno(turno)
    cn = get_conn(); cur = cn.cursor()
    cur.execute("SELECT id FROM public.colaboradores WHERE nome=%s AND setor=%s", (nome.strip(), setor))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE public.colaboradores SET turno=%s, ativo=true WHERE id=%s", (turno, int(row[0])))  # r[0]
    else:
        cur.execute(
            "INSERT INTO public.colaboradores (nome, setor, turno, ativo) VALUES (%s, %s, %s, true)",
            (nome.strip(), setor, turno),
        )
    cn.commit(); cur.close(); cn.close()


def atualizar_ativo_colaboradores(ids_para_inativar: List[int], ids_para_ativar: List[int]):
    cn = get_conn(); cur = cn.cursor()
    if ids_para_inativar:
        cur.execute("UPDATE public.colaboradores SET ativo=false WHERE id = ANY(%s)", (ids_para_inativar,))
    if ids_para_ativar:
        cur.execute("UPDATE public.colaboradores SET ativo=true  WHERE id = ANY(%s)", (ids_para_ativar,))
    cn.commit(); cur.close(); cn.close()

def carregar_presencas(colab_ids: List[int], inicio: date, fim: date) -> Dict[Tuple[int, str], str]:
    if not colab_ids:
        return {}
    cn = get_conn(); cur = cn.cursor()
    cur.execute(
        """
        SELECT colaborador_id, data, status
          FROM public.presencas
         WHERE colaborador_id = ANY(%s)
           AND data BETWEEN %s AND %s
        """,
        (colab_ids, inicio, fim),
    )
    rows = cur.fetchall()
    # r[0]=colaborador_id, r[1]=data (date), r[2]=status
    out = {(int(r[0]), r[1].isoformat()): (r[2] or "") for r in rows}
    cur.close(); cn.close()
    return out


def salvar_presencas(df_editado: pd.DataFrame, mapa_id_por_nome: Dict[str, int],
                     inicio: date, fim: date, setor: str, turno: str, leader_nome: str):
    """
    Salva as presenças do período. Se o status for um dos "SIN_*",
    o setor gravado para aquele dia é sobrescrito pelo setor do SIN.
    O turno gravado, se existir a coluna 'Turno' na grade, vem da própria linha;
    caso contrário, usa o turno selecionado no topo (parâmetro 'turno').
    """
    date_cols = [c for c in df_editado.columns if c not in ("Colaborador", "Setor", "Turno")]
    melt = df_editado.melt(
        id_vars=[c for c in ("Colaborador", "Setor", "Turno") if c in df_editado.columns],
        value_vars=date_cols,
        var_name="data",
        value_name="status"
    )

    melt["data_iso"] = pd.to_datetime(melt["data"]).dt.date
    melt["colaborador_id"] = melt["Colaborador"].map(mapa_id_por_nome)
    melt = melt.dropna(subset=["colaborador_id"])

    cn = get_conn(); cur = cn.cursor()

    for _, r in melt.iterrows():
        status = (r["status"] or "").strip()
        cid    = int(r["colaborador_id"])
        dte    = r["data_iso"]

        setor_base = r.get("Setor", setor)
        setor_para_gravar = SIN_TO_SETOR.get(status, setor_base)
        turno_para_gravar = r.get("Turno", turno)

        if status == "":
            cur.execute("DELETE FROM public.presencas WHERE colaborador_id=%s AND data=%s", (cid, dte))
        else:
            cur.execute(
    """
    INSERT INTO public.presencas
      (colaborador_id, data, status, setor, turno, leader_nome, created_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, now(), now())
    ON CONFLICT (colaborador_id, data) DO UPDATE
      SET status      = EXCLUDED.status,
          setor       = EXCLUDED.setor,
          turno       = EXCLUDED.turno,
          leader_nome = EXCLUDED.leader_nome,
          updated_at  = now()
      -- só atualiza se houve mudança de algum campo relevante
      WHERE presencas.status IS DISTINCT FROM EXCLUDED.status
         OR presencas.setor  IS DISTINCT FROM EXCLUDED.setor
         OR presencas.turno  IS DISTINCT FROM EXCLUDED.turno;
    """,
    (cid, dte, status, setor_para_gravar, turno_para_gravar, leader_nome),
)

    cn.commit()
    cur.close(); cn.close()

def aplicar_status_em_periodo(
    nomes_colaboradores: List[str],
    df_cols: pd.DataFrame,
    mapa_id_por_nome: Dict[str, int],
    inicio: date,
    fim: date,
    status: str,
    setor: str,
    turno_selecao: str,
    leader_nome: str,
):
    if not nomes_colaboradores:
        return

    turnos_por_nome = df_cols.set_index("nome")["turno"].to_dict()

    dias = datas_do_periodo(inicio, fim)
    df = pd.DataFrame({
        "Colaborador": nomes_colaboradores,
        "Setor": [setor] * len(nomes_colaboradores),
        "Turno": [turnos_por_nome.get(n, turno_selecao) for n in nomes_colaboradores],
    })

    for d in dias:
        df[d.isoformat()] = status

    salvar_presencas(
        df_editado=df,
        mapa_id_por_nome=mapa_id_por_nome,
        inicio=inicio,
        fim=fim,
        setor=setor,
        turno=turno_selecao,
        leader_nome=leader_nome or "",
    )

# ------------------------------
# UI Helpers
# ------------------------------
def montar_grid_presencas(df_cols: pd.DataFrame, inicio: date, fim: date) -> pd.DataFrame:
    dias = datas_do_periodo(inicio, fim)
    base = pd.DataFrame({"Colaborador": df_cols["nome"].tolist(), "Setor": df_cols["setor"].tolist()})
    for d in dias:
        base[d.isoformat()] = ""
    return base

def aplicar_status_existentes(base: pd.DataFrame,
                              presencas: Dict[Tuple[int, str], str],
                              mapa_id_por_nome: Dict[str, int]):
    for nome, cid in mapa_id_por_nome.items():
        for col in base.columns:
            if col in ("Colaborador", "Setor", "Turno"):
                continue
            key = (cid, col)
            if key in presencas:
                base.loc[base["Colaborador"] == nome, col] = presencas[key]
    return base

def coluna_config_datas(inicio: date, fim: date) -> Dict[str, st.column_config.Column]:
    cfg = {}
    dias = datas_do_periodo(inicio, fim)
    for d in dias:
        label = d.strftime("%d/%m")
        cfg[d.isoformat()] = st.column_config.SelectboxColumn(
            label=label,
            help="Selecione o status para este dia",
            options=STATUS_OPCOES,
            required=False,
        )
    return cfg

# ------------------------------
# Páginas
# ------------------------------
def pagina_colaboradores():
    st.markdown("### Colaboradores por Setor/Turno")
    colf1, colf2 = st.columns([1, 1])
    with colf1:
        setor = st.selectbox("Setor", OPCOES_SETORES, index=0, key="cols_setor")
    with colf2:
        turno_filtro = st.selectbox("Turno", ["Todos"] + OPCOES_TURNOS, index=0, key="cols_turno")

    if turno_filtro == "Todos":
        df_all = listar_colaboradores_por_setor(setor, somente_ativos=False)
    else:
        df_all = listar_colaboradores_setor_turno(setor, turno_filtro, somente_ativos=False)

    df_ativos = df_all[df_all["ativo"] == True]
    df_inativos = df_all[df_all["ativo"] == False]

    with st.expander("Adicionar novo colaborador", expanded=False):
        with st.form("add_colab"):
            nome = st.text_input("Nome do colaborador")
            turno_new = st.selectbox("Turno", OPCOES_TURNOS, index=0)
            ok = st.form_submit_button("Adicionar")
        if ok:
            if nome.strip():
                adicionar_colaborador(nome, setor, turno_new)
                st.success(f"Colaborador '{nome}' adicionado ao setor {setor} com turno {turno_new}!")
                st.rerun()
            else:
                st.warning("Informe um nome válido.")

    with st.expander("Excluir colaborador (remover da lista)", expanded=False):
        st.caption("A exclusão aqui **inativa** o colaborador (não apaga o histórico).")
        if df_ativos.empty:
            st.info("Não há colaboradores ativos nesse filtro.")
        else:
            opcoes_del = {
                f"{row['nome']} (ID {row['id']})": int(row['id'])
                for _, row in df_ativos.sort_values('nome').iterrows()
            }
            escolha_del = st.selectbox("Selecione o colaborador para excluir", list(opcoes_del.keys()))
            if st.button("Excluir colaborador", type="primary", key="btn_del_colab"):
                atualizar_ativo_colaboradores([opcoes_del[escolha_del]], [])
                st.success("Colaborador removido da lista de ativos (inativado).")
                st.rerun()

    with st.expander("Editar turno de colaborador", expanded=False):
        if df_all.empty:
            st.info("Nenhum colaborador listado no filtro atual.")
        else:
            opcoes = {f"{row['nome']} (ID {row['id']})": int(row['id']) for _, row in df_all.sort_values('nome').iterrows()}
            escolha = st.selectbox("Selecione o colaborador", list(opcoes.keys()))
            novo_turno = st.selectbox("Novo turno", OPCOES_TURNOS, index=0)
            if st.button("Atualizar turno"):
                atualizar_turno_colaborador(opcoes[escolha], novo_turno)
                st.success("Turno atualizado!")
                st.rerun()

    colA, colB = st.columns(2)
    with colA:
        st.subheader("Ativos")
        if len(df_ativos) == 0:
            st.info("Nenhum colaborador ativo para este filtro.")
        else:
            st.dataframe(
                df_ativos[["id", "nome", "turno"]]
                .rename(columns={"id": "ID", "nome": "Nome", "turno": "Turno"}),
                use_container_width=True
            )
    with colB:
        st.subheader("Inativos")
        st.dataframe(
            df_inativos[["id", "nome", "turno"]]
            .rename(columns={"id": "ID", "nome": "Nome", "turno": "Turno"}),
            use_container_width=True
        )

def pagina_preenchimento():
    return pagina_lancamento_diario()

def pagina_relatorios_globais():
    st.markdown("### Relatórios Globais (todos os setores/turnos)")
    col1, col2 = st.columns(2)
    with col1:
        dt_ini = st.date_input("Data inicial", value=periodo_por_data(date.today())[0])
    with col2:
        dt_fim = st.date_input("Data final", value=periodo_por_data(date.today())[1])

    col3, col4 = st.columns(2)
    with col3:
        setor_sel = st.selectbox("Filtrar por Setor", ["Todos"] + OPCOES_SETORES, index=0)
    with col4:
        turno_sel = st.selectbox("Filtrar por Turno", ["Todos"] + OPCOES_TURNOS, index=0)

    if st.button("Gerar relatório"):
        params = [dt_ini, dt_fim]
        if setor_sel != "Todos":
            params.append(setor_sel)
        if turno_sel != "Todos":
            params.append(turno_sel)

        df = pd.read_sql(
            f"""
            SELECT c.nome AS colaborador, p.data, p.status, p.setor, p.turno, p.leader_nome
              FROM public.presencas p JOIN public.colaboradores c ON c.id = p.colaborador_id
             WHERE p.data BETWEEN %s AND %s
             {"AND p.setor = %s" if setor_sel != "Todos" else ""}
             {"AND p.turno = %s" if turno_sel != "Todos" else ""}
             ORDER BY p.setor, p.turno, c.nome, p.data
            """,
            get_conn(),
            params=params,
        )

        if df.empty:
            st.info("Sem dados no intervalo/filtros informados.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            tag_setor = setor_sel if setor_sel != "Todos" else "todos_setores"
            tag_turno = turno_sel if turno_sel != "Todos" else "todos_turnos"
            csv = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Baixar CSV",
                data=csv,
                file_name=f"presencas_{tag_setor}_{tag_turno}_{dt_ini}_{dt_fim}.csv",
                mime="text/csv",
            )

# ------------------------------
# Seed de colaboradores (opcional / one-off)
# ------------------------------
SEED_LISTAS = {
    "Aviamento": """GIL FERNANDO DANTAS PORTELA
PEDRO WILLIAM MARQUES ALVES
MAURO DA SILVA GUERRA
ALISSON RICHARD MOREIRA DOS SANTOS
JOSUE DE OLIVEIRA SOARES
FABRICIO SILVA MACHADO DA COSTA
THAIS LOPES LIMA
SIMONE AGUIAR SOUZA
MARIANA GOMES MARINHO
MARCIA CRISTINA REIS DO MONTE SILVA E SILVA
LILIANE CASTRO DE OLIVEIRA
JORGE LUIZ DA SILVA
MARCELO DA SILVA
GILMARA DE ASSIS
ELIANE PORTELLA LOPES
EDNA CEZAR NOGUEIRA DA SILVA
CARLOS EDUARDO LUIZ DE SOUZA
ANA ROSA PEREIRA COSTA
CAMILA SANTOS DE OLIVEIRA DA PAZ
AMANDA VIANNA ROSA
THAYNA NASCIMENTO DA SILVA
RODRIGO DE OLIVEIRA PESSOA
NATHALIA HELLEN VIDAL GOMES
SUELLEN TAVARES VIANA
AMANDA PEREIRA XAVIER
MARIA EDUARDA GRAVINO MUNIZ
MARCIO HERCULANO DE OLIVEIRA
REGINALDO GUEDES BEZERRA
LUIZ GUSTAVO ANCHIETA
JUAN LUCAS DA SILVA DE MORAES
FABIANO BARROS DE FREITAS
ROBERTA REIS DE ALMEIDA
THAIS MELLO DOS SANTOS
DOUGLAS OLIVEIRA DOS SANTOS
ANTHONY PAULO DA SILVA
ANDRE LUIS DE OLIVEIRA ARAUJO
SAIMER GONCALVES DA SILVA
CRISTIAN DA SILVA SALES
MARLY RODRIGUES DA SILVA ALEDI
CASSIA DE SOUZA SANTANA""",
    "Tecido": """FELIPE RAMOS TEIXEIRA
DOUGLAS DE ALBUQUERQUE MUNIZ
JEFFERSON GONCALVES DE SOUZA
HUDSON PAULO NASCIMENTO DE SOUZA
JOAO VICTOR CORDEIRO MOURA
LUCAS MATTOS SENNA PEREIRA
MARCIO FONTES
LUIZ FERNANDO SANTOS FURTADO
OSEIAS RIBEIRO DOS SANTOS
RAFAEL DE MELO SOBRINHO
JOAO VITOR DE ARRUDA GERONIMO
NATAN DUARTE RODRIGUES DA SILVA
RODRIGO ESTEVES BALBINO
EDUARDO MIGUEL DA SILVA
PATRICK DA SILVA MONSORES CASEMIRO
WESLEY VIANA DOS SANTOS
MAXWELL RONALD COSTA DA SILVA
EMERSON DE OLIVEIRA QUEIROZ DA SILVA
ROGERIO SANTA ROSA DE SANTANNA
JOSUE SANTOS DA PAZ
ISAC FRANK MELLO DOS SANTOS
ALEXSSANDRO REIS DE ANDRADE
GLEISON SOUZA SERRA
IRINEU ARAUJO DE SOUSA
LUCAS YAN NASCIMENTO DA SILVA""",
    "Distribuição": """ADRIANO DE OLIVEIRA GOMES
ALLAN ANSELMO SABINO FERNANDES
ANA CAROLINE DE MELO MOUTINHO
ANA CAROLINA NASCIMENTO BARBOSA
ANDERSON DA SILVA SOUZA
ANDRE DE OLIVEIRA ALBUQUERQUE
ANDRE GONCALVES DE OLIVEIRA MARTINS
AUGUSTO SANTOS DA SILVA
BEATRIZ CONCEIÇÃO DEODORO DA SILVA DA ROCHA
BRENO DOS SANTOS MOREIRA ROCHA
CLAUDETE PEREIRA
CRISTIANE DE MENEZES RODRIGUES
EDENILSON SOUZA DE MORAIS
EDSON VANDER DA SILVA LOPES
FABIANE CORSO VERMELHO
FABIO DA ROCHA SILVA JUNIOR
ISRAEL MIGUEL SOUZA
ISRAEL VANTINE FERNANDES
IVO DE LYRA JUNIOR
JOÃO MARCOS
JOÃO VICTOR
LEONARDO SANTANA DE ALMEIDA
LUIZ EDUARDO
LUCAS AZEVEDO
MATEUS DE MELLO
MATHEUS FERREIRA DE SOUZA
PEDRO PAULO DA SILVA
RODRIGO MOURA
Severina Lídia da Silva
WILLIAM SOUZA DA SILVA
WILSON MATEUS
WLADIMIR HORA
PEDRO HENRIQUE MENDES DOS SANTOS RIBEIRO
ADILSON DE ARAUJO SIQUEIRA
ANDERSON GARCEZ DOS SANTOS JUNIOR
BRENO GASPAR
DEIVISSON SILVA ALCANTARA
EVELIN
EZEQUIEL DA SILVA SOARES
HUDSON
IZABELA ROZA DUARTE DE SOUZA
JACQUELINE PAULINA FERREIRA
JUAN MICHEL DE OLIVEIRA SOUZA
LAERCIO BALDUINO ANDRADE
LUCAS DO NASCIMENTO FONTE
LUIZ CARLOS DURANS DO NASCIMENTO
MARCOS VINICIUS ANDRADE DOS SANTOS BRAGA
MATHEUS HENRIQUE FERREIRA
PATRICK MURILO OLIVEIRA DO NASCIMENTO
RAMON CORREA
RICARDO CORREIA DAS CHAGAS
RUANA PAIVA RANGEL
SAMUEL NOGUEIRA PERREIRA SOUZA MENDONÇA
SEBASTIÃO
TIAGO LEANDRO DAS CHAGAS
VALERIO
WILLIAN ALVAREGA
YURI AVILA
BRUNO DE SOUSA GAMA
DIEGO ASSUNÇÃO RODRIGUES DOS SANTOS
GABRIEL ALMEIDA DE LIMA SOUSA
GABRIEL CORREIA DA SILVA
GEIBERSON FELICIANO ARAGAO
GILSON ALVES DE SOUZA
IGOR FERREIRA  MUNIZ
JORGE THADEU DA SILVA BATISTA
LUAN BERNADO DO CARMO
LUCAS HENRIQUE DE ADRIANO GUILHERME
LUIS FERNANDO MONTEIRO DE MELO
MARCOS ALEXANDRE DA SILVA PRATES
MATEUS WILLIAN CASTRO BELISARIO DA SILVA
MATHEUS WASHINGTON FREIRES DOS SANTOS
NICOLLAS RIGAR VIRTUOSO
PEDRO JOSE DOS SANTOS MELO
VANDERLEY PEREIRA LEAL JUNIOR
WELLINGTON PEREIRA DA PAIXAO
WALLACE
HUDSON
LUCAS SILVA DO NASCIMENTO""",
    "Almoxarifado": """MARCIO LIMA DOS SANTOS
PATRICK DOS ANJOS LIMA
CARLA ALVES DOS SANTOS
WELLINGTON MATOS
LEANDRO FERNANDES DE OLIVEIRA
ANITOAN ALVES FEITOSA
RENNAN DA SILVA GOMES
GUILHERME DOS SANTOS FEITOSA
RAMON ROCHA DO CARMO""",
    "PAF": """DAVID DE ARAUJO MAIA
FELIPE SILVA DE FIGUEIREDO
JOELSON DOS SANTOS COUTINHO
RAPHAEL ABNER RODRIGUES MARREIROS
ROBSON SANTANA SILVA
SERGIO MURILO SIQUEIRA JUNIOR
WILLIAN LAUERMANN OLIVEIRA
CARLOS AUGUSTO LIMA MOURAO
ADRIANO MARINE WERNECK DE SOUSA
AGATA GURJAO FERREIRA
ANNA LUYSA SEVERINO NASCIMENTO
BRUNO DOS SANTOS BARRETO DO NASCIMENTO
MANOEL ARTUR SOUZA SANTOS
MOISES AUGUSTO DOS SANTOS DIAS
VICTOR HUGO MOTA CAMILLO
DIEGO FIGUEIREDO MARQUES
ALESSANDRO BOUCAS JORGE""",
    "Recebimento": """ANDREZA VALERIANO RAMOS PASSOS
BRAULIO CARDOSO DA SILVA
CHARLES DA SILVA COSTA
DENIS RODRIGUES DE SOUSA
EMERSON SANTOS
FABIO DA CONCEICAO FERREIRA
FLAVIO SANTOS DA SILVA
GABRIELLE DA SILVA PEREIRA
LUIZ EDUARDO CAMPOS DE SOUZA
MARCIA CRISTINA BARBOSA DE FREITAS
MARCOS VINICIUS SOUZA MARTINS
ROMULO DANIEL MARTINS PEREIRA
THAIS LIMA DE ANDRADE
THIAGO GOMES DE ARAUJO
UANDERSON FELIPE
WALLACY DE LIRA LEITE
ALLAN PIRES RODRIGUES
CLAUDIO DA SILVA
DANDARA MONTEIRO DA SILVA
HIGO JESSE PACHECO DE SOUZA
IAGO DE ALMEIDA ALVES PEREIRA
JEAN DE SA CARROCOSA
KAUÃ PABLO SIMIÃO DOS SANTOS
KAUANN SOUZA DE OLIVEIRA GOMES
LUCIANO SANTOS DE ARAUJO
LUIZ FILIPE SOUZA DE LIMA
MARLON DOUGLAS DE FREITAS
RAFAELA ANDRADE DA SILVA GUERRA
RENATO FERREIRA DOS SANTOS
RIGOALBERTO JOSUE VINOLES SALAZAR
SHEILA RIBEIRO DIAS TIBURCIO
THALIS DA SILVA FRANCO
YASMIM VIRGILIO DA SILVA
JULIO CESAR ALVES DE CARVALHO
LUIZ DOUGLAS PEREIRA
MARCOS ROBERTO
PATRICK COSTA DA SILVA BRAGA
VICTOR DA COSTA TEIXEIRA""",
    "Expedição": """ALEXSANDRO DOS REIS BASTOS
CARLOS JUNIOR FERREIRA SANTOS
DIEGO BORGES MARTINS
EMERSON ALVES PIRES
JOAO VITOR DE OLIVEIRA DE SOUZA
JONATHAN DOS SANTOS FEITOSA
LEANDRO COUTINHO
LEONARDO DOS SANTOS BARBOSA DA SILVA
LUIS CLAUDIO DIAS DA ROCHA
MARLON ALEXANDRE DE SOUSA
MATHEUS DOS SANTOS SILVA
MAYARA COUTINHO
PEDRO GUILHERME SANTOS QUELUCI
SAMUEL DA CONCEICAO SILVA
UDIRLEY OLIVEIRA SOARES
ANA CAROLINY DA SILVA
CLEISSON COSTA FERNANDES
DAVI DAS GRAÇAS MUNIZ BORGES
FELIPE MATOS DA ROCHA
GABRIEL LIMA TRAJANO DA SILVA
GABRIELLE SOZINHO LOUZA
JHONNATHA GABRIEL RIBEIRO DOS SANTOS LIMA
KAYKE ARAUJO MARQUES
LEONARDO DA SILVA GUIMARÃES
PEDRO HENRIQUE GONÇALVES DA ROCHA
RODRIGO SOUZA BRAGA
TAINARA CRISTINE DO NASCIMENTO
VINICIUS STEFANO DA SILVA BARBOSA
GUILHERME BORGES SANTOS""",
    "E-commerce": """ANA PAULA LIMA MOYSES
ARI RODRIGUES DO NASCIMENTO
CARLOS EDUARDO DE JESUS TEIXEIRA
DAIANA DA SILVA OLIVEIRA
EDILSON MATHEUS GONÇALVES DA SILVA
FELIPE DE SOUZA TOLEDO
JEFFERSON MATHEUS BITTENCOURT DA SILVA MACHADO
JONATHAN VIRGILIO DA SILVA
KAYKY WANDER ROSA SIMPLÍCIO
LEANDRO RODRIGUES DOS SANTOS
LEONARDO ROCHA SANTOS
LUCAS VICTOR DE SOUZA FERREIRA
LUIZA PEREIRA DOS SANTOS
LUZMARY DEL VALLE SALAZAR HERNANDEZ
NICHOLLAS RONNY COUTINHO FERREIRA
PEDRO JEMERSON ALVES DO NASCIMENTO
RAFAEL BRENDO SALES SANTANA
RAFAEL HENRIQUE MARCELINO ROMAO
RENATA DE LIMA ANDRADE
RODRIGO DOS SANTOS AZEVEDO
RONALDO INACIO DA SILVA
SHIRLEI MELLO DOS SANTOS
TATIANA GARCIA  CORREIA DO NASCIMENTO
WALLACE DE REZENDE SILVA
WESLEY DA SILVA BARCELOS
WILLIAM SILVA DE JESUS
ANA PAULA CUSTODIO DA SILVA GOMES DA SILVA
ANA PAULA LOPES DA CRUZ
ANDRÉA DA SILVA REIS
ANDREZA DE AZEVEDO NASCIMENTO DA SILVA
DANIELLE DA COSTA VIEIRA CAMARA
DAVI FRADIQUE DOS SANTOS SILVA
EDGARD DAS NEVES SILVA
EMILLY REIS GUILHERME FERREIRA
FABIANA MAGALHAES BRAGA
GUILHERME SILVA DE MELLO
ISABELA IARA SOUZA DA SILVA
JONAS SILVA DE SOUZA
JOYCE BOMFIM DE SANT ANNA
KAMILLE DOS SANTOS SOARES
KETLEN DOS REIS NASCIMENTO
LUAN CARVALHO SANTOS
LUCAS DE OLIVEIRA CASTRO
MARCELE SILVA DE OLIVEIRA
MARIANA PIRES VIEIRA
MATEUS DE SOUZA GOMES
MATHEUS PEREIRA CARNEIRO CESAR
RAYSSA SILVA DE OLIVEIRA CASTRO
RENAN PAIVA RANGEL
RICHARD RODRIGUES DE JESUS
VINICIUS DA SILVA OLIVEIRA
VITÓRIA SILVA ARAUJO
WENDEL PERIARD SILVA
WERICSON DA SILVA BARCELOS PAULA
YASMIN OLIVEIRA DE AVELLAR DA COSTA
ANA KAROLINA GOMES BRAZIL DE OLIVEIRA
ANDERSON SOARES DE SOUZA
ANTONIO CARLOS TORRACA
DALILA FERREIRA DA SILVA
DOUGLAS DE SOUZA LINS TOLEDO
GABRIEL MATEUS PATRICIO DA COSTA
JOSÉ RICARDO DA SILVA JUNIOR
MAYCON DOUGLAS DA COSTA SARMENTO
PABLO LUIZ PAES DE PAULA
PETER DOUGLAS FERREIRA DE SOUZA
RAFAELA CRISTINA DA SILVA MARQUES
RODRIGO SOARES BASTOS ROSALINO
RONALDO PINHEIRO ABREU
SUELEN CRISTINA DA SILVA BRAGA
THIAGO DA SILVA MOTA
VIVIANE MARTINS DE FREITAS
WALLACE ALVEZ COUTINHO
WELLINGTON MAURICIO
ZILTO PRATES JUNIOR
GIOVANNA DE CASTRO EMIDGIO
CHARLES RIBEIRO GONCALVES JUNIOR
TARCIANE GOMES DA CONCEIÇÃO
VITORIA ALVES BRAGA""",
}

def _parse_names(blob: str):
    return [n.strip().strip('"').strip("'") for n in blob.splitlines() if n.strip()]

def seed_colaboradores_iniciais(turno_default: str = "1°"):
    for setor, blob in SEED_LISTAS.items():
        for nome in _parse_names(blob):
            cn = get_conn(); cur = cn.cursor()
            cur.execute(
                "SELECT 1 FROM public.colaboradores WHERE nome=%s AND setor=%s AND turno=%s",
                (nome, setor, turno_default),
            )
            exists = cur.fetchone()
            cur.close(); cn.close()
            if not exists:
                adicionar_colaborador(nome, setor, turno_default)

# ------------------------------
# Importador de turnos (xlsx/csv)
# ------------------------------
def _normalize_setor(nome_sheet: str) -> str:
    s = (nome_sheet or "").strip().upper()
    mapa = {
        "AVIAMENTO": "Aviamento",
        "TECIDO": "Tecido",
        "DISTRIBUICAO": "Distribuição",
        "DISTRIBUIÇÃO": "Distribuição",
        "ALMOXARIFADO": "Almoxarifado",
        "PAF": "PAF",
        "RECEBIMENTO": "Recebimento",
        "EXPEDICAO": "Expedição",
        "EXPEDIÇÃO": "Expedição",
        "E-COMMERCE": "E-commerce",
        "ECOMMERCE": "E-commerce",
        "E COMMERCE": "E-commerce",
    }
    return mapa.get(s, nome_sheet)

def importar_turnos_de_arquivo(arquivo, setor_padrao: str | None = None) -> int:
    nome = getattr(arquivo, "name", "").lower()
    total = 0

    def _process_df(df: pd.DataFrame, setor_hint: str | None = None):
        nonlocal total
        cols = {c.upper(): c for c in df.columns}
        nome_col = cols.get("NOME COMPLETO") or cols.get("NOME")
        turno_col = cols.get("TURNO")
        setor_col = cols.get("SETOR")
        if not nome_col or not turno_col:
            return 0
        linhas = 0
        for _, row in df.iterrows():
            nome_val = str(row[nome_col]).strip()
            if not nome_val:
                continue
            turno_val = normaliza_turno(str(row[turno_col]).strip())
            setor_val = _normalize_setor(str(row[setor_col]).strip()) if setor_col else setor_hint or setor_padrao
            if not setor_val:
                raise ValueError("Defina o setor (coluna SETOR no arquivo ou selecione na UI para CSV sem SETOR).")
            upsert_colaborador_turno(nome_val, setor_val, turno_val)
            linhas += 1
        total += linhas
        return linhas

    if nome.endswith((".xlsx", ".xls")):
        xls = pd.ExcelFile(arquivo)
        for aba in xls.sheet_names:
            df = xls.parse(aba)
            _process_df(df, setor_hint=_normalize_setor(aba))
    else:
        try:
            df = pd.read_csv(arquivo)
        except Exception:
            df = pd.read_csv(arquivo, encoding="latin1", sep=None, engine="python")
        _process_df(df, setor_hint=None)

    return total

# ------------------------------
# Página de Lançamento Diário
# ------------------------------
def pagina_lancamento_diario():
    st.markdown("### Lançamento diário de presença (por setor)")

    colA, colB, colC, colD, colE = st.columns([1, 1, 1, 1, 2])

    with colA:
        setor = st.selectbox("Setor", OPCOES_SETORES, index=0, key="lan_setor")

    with colB:
        turno_sel = st.selectbox("Turno", ["Todos"] + OPCOES_TURNOS, index=0, key="lan_turno")

    with colC:
        min_permitida = data_minima_preenchimento()
        data_dia = st.date_input(
            "Data do preenchimento",
            value=max(date.today(), min_permitida),
            min_value=min_permitida,
            format="DD/MM/YYYY",
            key="lan_data",
        )

    with colD:
        filtro_st = st.multiselect(
            "Filtro",
            options=["SOMA", "TERCEIROS"],
            default=["SOMA", "TERCEIROS"],
            key="lan_filtro_st"
        )

    with colE:
        default_name = display_name_from_email(st.session_state.get("user_email", ""))
        if default_name:
            st.text_input("Seu nome", value=default_name, key="lan_nome", disabled=True)
            nome_preenchedor = default_name
        else:
            nome_preenchedor = st.text_input("Seu nome (opcional)", key="lan_nome")

    if turno_sel == "Todos":
        df_cols = listar_colaboradores_por_setor(setor, somente_ativos=True)
    else:
        df_cols = listar_colaboradores_setor_turno(setor, turno_sel, somente_ativos=True)

    mask_terceiro = df_cols["nome"].str.contains(r"-\s*terceiro\s*$", case=False, na=False)

    escolha = set(filtro_st)
    if escolha == {"SOMA"}:
        df_cols = df_cols[~mask_terceiro]
    elif escolha == {"TERCEIROS"}:
        df_cols = df_cols[mask_terceiro]
    else:
        pass

    if len(df_cols) == 0:
        st.warning("Nenhum colaborador cadastrado para este filtro.")
        st.stop()

    iso = data_dia.isoformat()
    base = pd.DataFrame(
        {
            "Colaborador": df_cols["nome"].tolist(),
            "Setor": df_cols["setor"].tolist(),
            "Turno": df_cols["turno"].tolist(),
            iso: ""
        },
        dtype="object"
    )

    pres = carregar_presencas(df_cols["id"].tolist(), data_dia, data_dia)
    mapa = dict(zip(df_cols["nome"], df_cols["id"]))
    base = aplicar_status_existentes(base, pres, mapa)

    cfg = {
        "Colaborador": st.column_config.TextColumn("Colaborador", disabled=True),
        "Setor": st.column_config.TextColumn("Setor", disabled=True),
        "Turno": st.column_config.TextColumn("Turno", disabled=True),
        iso: st.column_config.SelectboxColumn(
            label=data_dia.strftime("%d/%m"),
            options=STATUS_OPCOES,
            required=False,
        ),
    }

    st.markdown("#### Tabela do dia")
    editor_key = f"editor_dia_{iso}_{setor}_{turno_sel}_{'-'.join(sorted(filtro_st) or ['TODOS'])}"
    editado = st.data_editor(
        base,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config=cfg,
        key=editor_key,
    )

    # Quem já estava salvo como FÉRIAS no banco para este dia
    ja_em_ferias = {nome for nome, cid in mapa.items() if pres.get((cid, iso)) == "FÉRIAS"}

    # Quem está marcado como FÉRIAS no editor agora
    marcados_no_editor = editado.loc[editado[iso] == "FÉRIAS", "Colaborador"].tolist()

    # Aplique somente para os RECÉM marcados (exclui quem já estava de férias)
    recem_marcados = [n for n in marcados_no_editor if n not in ja_em_ferias]

    if recem_marcados:
        with st.expander("Aplicar FÉRIAS para um período", expanded=True):
            st.caption(
            "Você marcou FÉRIAS em "
            + data_dia.strftime("%d/%m/%Y")
            + " para: "
            + ", ".join(recem_marcados)
        )

        ini_periodo_atual, fim_periodo_atual = periodo_por_data(data_dia)

        colf1, colf2 = st.columns(2)
        with colf1:
            ferias_ini = st.date_input(
                "Início das férias",
                value=data_dia,
                min_value=data_minima_preenchimento(),
                format="DD/MM/YYYY",
                key=f"ferias_ini_{editor_key}",
            )
        with colf2:
            ferias_fim = st.date_input(
                "Fim das férias",
                value=fim_periodo_atual,
                min_value=ferias_ini,
                format="DD/MM/YYYY",
                key=f"ferias_fim_{editor_key}",
            )

        # (Opcional) permitir desmarcar alguém desta aplicação
        selecionados = st.multiselect(
            "Aplicar para:",
            options=recem_marcados,
            default=recem_marcados,
            key=f"sele_ferias_{editor_key}",
        )

        if selecionados and st.button(
            "Aplicar FÉRIAS no período para os colaboradores selecionados",
            type="primary",
            key=f"btn_aplicar_ferias_{editor_key}",
        ):
            aplicar_status_em_periodo(
                nomes_colaboradores=selecionados,
                df_cols=df_cols,
                mapa_id_por_nome=mapa,
                inicio=ferias_ini,
                fim=ferias_fim,
                status="FÉRIAS",
                setor=setor,
                turno_selecao=(turno_sel if turno_sel != "Todos" else "-"),
                leader_nome=nome_preenchedor,
            )
            st.success("FÉRIAS aplicadas no período selecionado!")
            st.rerun()


    if st.button("Salvar dia"):
        salvar_presencas(
            editado,
            mapa,
            data_dia,
            data_dia,
            setor,
            turno=(turno_sel if turno_sel != "Todos" else "-"),
            leader_nome=nome_preenchedor or "",
        )
        st.success("Registros salvos/atualizados!")
        st.session_state.pop(editor_key, None)
        st.rerun()

    with st.expander("Exportar CSV do dia", expanded=False):
        df = pd.read_sql(
            """
            SELECT c.nome AS colaborador, p.data, p.status, p.setor, p.turno, p.leader_nome
              FROM public.presencas p JOIN public.colaboradores c ON c.id = p.colaborador_id
             WHERE p.setor = %s AND p.data = %s
             ORDER BY colaborador
            """,
            get_conn(),
            params=(setor, iso),
        )
        if df.empty:
            st.info("Sem dados salvos para esse dia.")
        else:
            csv = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Baixar CSV",
                data=csv,
                file_name=f"presencas_{setor}_{iso}.csv",
                mime="text/csv",
            )

# ------------------------------
# Página de Configuração do DB
# ------------------------------
def pagina_db():
    st.markdown("### Configuração do Banco (Postgres/Supabase)")
    cfg = get_config()
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Host", value=cfg["HOST"], disabled=True)
        st.text_input("Base de Dados", value=cfg["DBNAME"], disabled=True)
        st.text_input("Usuário", value=cfg["USER"], disabled=True)
    with col2:
        st.text_input("SSL Mode", value=cfg["SSLMODE"], disabled=True)
        st.text_input("Porta", value=cfg["PORT"], disabled=True)
        st.text_input("Timeout (s)", value=str(cfg["CONNECT_TIMEOUT"]), disabled=True)

    st.caption("As credenciais vêm das variáveis PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD.")

    if st.button("🔌 Testar conexão"):
        try:
            ok = test_connection()
            if ok:
                st.success("Conexão OK (SELECT 1 executado com sucesso).")
        except Exception as e:
            st.error(f"Falha ao conectar: {e}")

# ------------------------------
# Roteamento (com login)
# ------------------------------
if not st.session_state.get("auth", False):
    show_login()

if not st.session_state.get("seed_loaded", False):
    # _try_auto_import_seed()  # opcional
    st.session_state["seed_loaded"] = True

# >>> ADICIONE ESTE BLOCO <<<
if not st.session_state.get("db_inited"):
    try:
        init_db()  # cria tabelas se não existirem; só roda depois do login
        st.session_state["db_inited"] = True
    except Exception as e:
        st.error("Falha ao inicializar/abrir o banco. Verifique os Secrets (PGHOST/PGUSER/PGPASSWORD).")
        st.caption(str(e))
        st.stop()

st.sidebar.title("Menu")
st.sidebar.caption(f"Usuário: {st.session_state.get('user_email','')}")
if st.sidebar.button("Sair"):
    for k in ("auth", "user_email"):
        st.session_state.pop(k, None)
    st.rerun()

nav_opts = ["Lançamento diário"] + (["Colaboradores"] if is_admin() else []) + ["Relatórios"] + (["DB"] if is_admin() else [])
escolha = st.sidebar.radio("Navegação", nav_opts, index=0)

if is_admin():
    with st.sidebar.expander("⚙️ Admin"):
        coladm1, coladm2 = st.columns([1,1])
        if coladm1.button("Carregar lista inicial de colaboradores"):
            seed_colaboradores_iniciais(turno_default="1°")
            st.success("Seed aplicado (somente adiciona quem não existe).")

        up = st.file_uploader("Importar turnos (xlsx/csv)", type=["xlsx", "xls", "csv"], key="up_turnos")
        setor_default = st.selectbox("Se o CSV não tiver coluna SETOR, aplicar a:",
                                     ["(obrigatório se CSV sem SETOR)"] + OPCOES_SETORES, index=0)
        if st.button("Aplicar turnos do arquivo"):
            if up is None:
                st.warning("Selecione um arquivo .xlsx ou .csv")
            else:
                try:
                    n = importar_turnos_de_arquivo(up, setor_padrao=None if str(setor_default).startswith("(") else setor_default)
                    st.success(f"Turnos aplicados/atualizados para {n} colaboradores.")
                except Exception as e:
                    st.error(f"Erro ao importar: {e}")

if escolha == "Lançamento diário":
    pagina_lancamento_diario()
elif escolha == "Colaboradores":
    if not is_admin():
        st.error("Acesso restrito aos administradores.")
        st.stop()
    pagina_colaboradores()
elif escolha == "Relatórios":
    pagina_relatorios_globais()
elif escolha == "DB":
    if not is_admin():
        st.error("Acesso restrito aos administradores.")
        st.stop()
    pagina_db()

# Fim do arquivo
