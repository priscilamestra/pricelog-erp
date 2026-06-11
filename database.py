import psycopg2
import streamlit as st
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    "host": st.secrets["postgres"]["host"],
    "database": st.secrets["postgres"]["database"],
    "user": st.secrets["postgres"]["user"],
    "password": st.secrets["postgres"]["password"],
    "port": st.secrets["postgres"]["port"]
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def inicializar_banco():
    conn = get_connection()
    cursor = conn.cursor()

    # Cria tabela se não existir (schema já com 'categoria')
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id SERIAL PRIMARY KEY,
            codigo VARCHAR(50) UNIQUE NOT NULL,
            marca VARCHAR(100),
            tipo VARCHAR(100),
            modelo VARCHAR(200),
            categoria VARCHAR(100),
            preco_unitario NUMERIC(10, 2),
            custo NUMERIC(10, 2),
            obs TEXT
        );
    """)

    # ── Migração automática: renomeia 'segmento' → 'categoria' se ainda existir ──
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'produtos' AND column_name = 'segmento';
    """)
    if cursor.fetchone():
        # Só renomeia se 'categoria' ainda não existir (evita conflito)
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'produtos' AND column_name = 'categoria';
        """)
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE produtos RENAME COLUMN segmento TO categoria;")
        else:
            # Ambas existem: copia dados e dropa a antiga
            cursor.execute("UPDATE produtos SET categoria = segmento WHERE categoria IS NULL OR categoria = '';")
            cursor.execute("ALTER TABLE produtos DROP COLUMN segmento;")

    # ── Garante que 'modelo' e 'categoria' existam (bancos muito antigos) ──
    for col, tipo in [("modelo", "VARCHAR(200)"), ("categoria", "VARCHAR(100)")]:
        cursor.execute(f"""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'produtos' AND column_name = '{col}';
        """)
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE produtos ADD COLUMN {col} {tipo};")

    conn.commit()
    cursor.close()
    conn.close()


def listar_produtos():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    # Ordem explícita das colunas — nunca depende do schema do banco
    cursor.execute("""
        SELECT id, codigo, marca, tipo, modelo, categoria,
               preco_unitario, custo, obs
        FROM produtos ORDER BY id ASC;
    """)
    dados = cursor.fetchall()
    cursor.close()
    conn.close()
    return dados


def criar_produto(codigo, marca, tipo, modelo, categoria, preco, custo, obs):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO produtos (codigo, marca, tipo, modelo, categoria, preco_unitario, custo, obs)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """, (codigo, marca, tipo, modelo, categoria, preco, custo, obs))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def atualizar_produto(id_produto, codigo, marca, tipo, modelo, categoria, preco, custo, obs):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE produtos
        SET codigo=%s, marca=%s, tipo=%s, modelo=%s, categoria=%s,
            preco_unitario=%s, custo=%s, obs=%s
        WHERE id=%s;
    """, (codigo, marca, tipo, modelo, categoria, preco, custo, obs, id_produto))
    conn.commit()
    cursor.close()
    conn.close()


def deletar_produto(id_produto):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM produtos WHERE id = %s;", (id_produto,))
    conn.commit()
    cursor.close()
    conn.close()


def resetar_banco():
    print("\n--- INICIANDO RESET COMPLETO DO BANCO ---")
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("TRUNCATE TABLE itens_analise RESTART IDENTITY CASCADE;")
        conn.commit()
        cursor.execute("TRUNCATE TABLE analises RESTART IDENTITY CASCADE;")
        conn.commit()
        cursor.execute("TRUNCATE TABLE produtos RESTART IDENTITY CASCADE;")
        conn.commit()
        print("Reset completo.")
    except Exception as e:
        print(f"ERRO: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def inicializar_tabelas_monitor():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analises (
            id SERIAL PRIMARY KEY,
            data_criacao TIMESTAMP DEFAULT NOW(),
            total_produtos INTEGER,
            total_alertas INTEGER,
            expira_em DATE,
            modo VARCHAR(20) DEFAULT 'Rápido',
            fonte VARCHAR(50) DEFAULT 'Zoom.com.br'
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS itens_analise (
            id SERIAL PRIMARY KEY,
            analise_id INTEGER REFERENCES analises(id) ON DELETE CASCADE,
            codigo_produto VARCHAR(50),
            nome_produto VARCHAR(200),
            seu_preco NUMERIC(10,2),
            preco_mercado NUMERIC(10,2),
            diferenca_percent NUMERIC(6,2),
            margem_percent NUMERIC(6,2),
            status VARCHAR(30)
        );
    """)
    cursor.execute("ALTER TABLE analises ADD COLUMN IF NOT EXISTS modo VARCHAR(20) DEFAULT 'Rápido';")
    cursor.execute("ALTER TABLE analises ADD COLUMN IF NOT EXISTS fonte VARCHAR(50) DEFAULT 'Zoom.com.br';")
    conn.commit()
    cursor.close()
    conn.close()


def salvar_analise(itens: list, modo: str = "Rápido", fonte: str = "Zoom.com.br") -> int:
    from datetime import date, timedelta
    total   = len(itens)
    alertas = sum(1 for i in itens if i["status"] in ["⚠️ Moderado", "🔴 Crítico"])
    expira  = date.today() + timedelta(days=15)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO analises (total_produtos, total_alertas, expira_em, modo, fonte)
        VALUES (%s, %s, %s, %s, %s) RETURNING id;
    """, (total, alertas, expira, modo, fonte))
    analise_id = cursor.fetchone()[0]

    for item in itens:
        cursor.execute("""
            INSERT INTO itens_analise
            (analise_id, codigo_produto, nome_produto, seu_preco, preco_mercado,
             diferenca_percent, margem_percent, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """, (
            analise_id, item["codigo"], item["nome"], item["seu_preco"],
            item["preco_mercado"], item["diferenca_percent"],
            item["margem_percent"], item["status"]
        ))
    conn.commit()
    cursor.close()
    conn.close()
    return analise_id


def listar_analises():
    from datetime import date
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("DELETE FROM analises WHERE expira_em < %s;", (date.today(),))
    conn.commit()
    cursor.execute("""
        SELECT id, data_criacao, total_produtos, total_alertas, expira_em,
               COALESCE(modo, 'Rápido') as modo,
               COALESCE(fonte, 'Zoom.com.br') as fonte
        FROM analises ORDER BY data_criacao DESC;
    """)
    dados = cursor.fetchall()
    cursor.close()
    conn.close()
    return dados


def buscar_itens_analise(analise_id: int):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT * FROM itens_analise WHERE analise_id = %s ORDER BY status DESC;
    """, (analise_id,))
    dados = cursor.fetchall()
    cursor.close()
    conn.close()
    return dados