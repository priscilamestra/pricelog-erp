## ERP de Gestão e Monitoramento Competitivo de Preços

Sistema ERP desenvolvido para empresas que precisam gerenciar seu catálogo de produtos e monitorar automaticamente os preços praticados pela concorrência no e-commerce brasileiro. O sistema resolve um problema real de inteligência comercial: saber, sem trabalho manual, se os preços da empresa estão competitivos, com margem saudável e alinhados ao mercado — produto a produto, em escala.

A automação de monitoramento opera por duas frentes: consulta via API de busca (Google Shopping) para análises rápidas de todo o catálogo, e scraping via navegador real (Playwright) para análises detalhadas com navegação autenticada nos sites dos concorrentes.

### Funcionalidades

#### 📦 Cadastrar
- Cadastro manual de produtos com os campos: Código, Marca, Tipo, Modelo, Categoria, Preço de Venda, Custo de Aquisição e Observações
- Importação em lote via arquivo `.csv`
- Preview da tabela apenas com os produtos cadastrados na sessão atual após cada importação ou cadastro manual
- Validação de código único — o sistema rejeita duplicatas automaticamente

#### 🗂️ Gerenciar
- Tabela completa com todos os produtos registrados no banco de dados, disponível a cada sessão
- Edição de qualquer campo de um produto existente via seleção por ID
- Exclusão de produtos individualmente
- Busca em tempo real por qualquer coluna (código, marca, modelo, categoria etc.)
- Aviso visual quando nenhum resultado é encontrado, com retorno automático à listagem completa após 3 segundos

#### ⚙️ Automações — Monitor de Preços
Dois modos de análise competitiva:

##### ⚡ Modo Rápido — API de preços (Google Shopping via SerpAPI)
- Consulta os preços de mercado via chamada de API para todos os produtos do catálogo ou uma seleção específica
- O sistema foi projetado para que o usuário tenha liberdade de substituir a SerpAPI por qualquer outra API de busca de preços (ex: ScraperAPI, ShoppingScraper, Outscraper), bastando adaptar a função `_buscar_preco_serpapi` em `rpa_monitor.py`
- A SerpAPI pode ser mantida como fallback para garantir retorno mesmo quando a fonte principal falhar — importante considerar que o plano gratuito da SerpAPI libera 250 buscas por mês, o que pode ser insuficiente para catálogos grandes em uso contínuo
- Extração de pares `(título do produto, preço)` com filtro de relevância por similaridade textual: apenas preços de produtos semanticamente relacionados à query são considerados, eliminando falsos positivos de acessórios, fretes e anúncios não relacionados
- Delay de 1 segundo entre produtos para respeitar os limites da API
- Resultado salvo no banco com expiração de 15 dias

##### 🔍 Modo Detalhado — Navegador real (Playwright)
- Abre um browser Chromium real e navega pelos sites de e-commerce simulando comportamento humano
- Seleção manual de até 5 produtos por sessão via tabela com checkboxes
- Para mais de 5 produtos, executa múltiplas sessões automaticamente com pausa de 2 minutos entre elas
- Comportamento anti-detecção:
  - Scroll irregular com 5–10 passos e variação de 600–1800ms por passo, incluindo scroll de volta simulando releitura
  - Movimentos de mouse com trajetória suave em múltiplos passos intermediários
  - Espera de 18–32 segundos entre produtos
  - Espera de 5–9 segundos após carregamento da página
- Extração inteligente por JavaScript evaluate: obtém pares `(título, preço)` dos cards de produto e aplica filtro de relevância antes de calcular a mediana
- Fallback em três camadas: JS extrator → CSS seletores → regex no HTML completo
- Detecção de bloqueio por frases específicas (captcha, "access denied" etc.) com distinção entre "Bloqueado" e "Não encontrado" no resultado

##### Classificação dos resultados
Cada produto analisado recebe um status baseado em margem e diferença de preço em relação ao mercado:

| Status | Condição |
|---|---|
| ✅ OK | Margem >= 15% e diferença de preço <= 5% do mercado |
| ⚠️ Moderado | Diferença > 5% ou margem abaixo do mínimo configurado |
| 🔴 Crítico | Margem < 15% ou diferença > 20% do mercado |
| ⚪ Sem referência | Produto não encontrado nos sites consultados |
| 🚫 Erro | Site bloqueou a requisição (403, captcha etc.) |

- Coluna **Mercado (R$)** exibe o preço encontrado, `"Bloqueado"` ou `"Não encontrado"` de forma legível
- Margem mínima aceitável configurável por análise (slider de 5% a 80%)
- Histórico de todas as análises dos últimos 15 dias com expiração automática
- Carregamento de seleção a partir de análises anteriores, filtrando apenas itens Moderados e Críticos para reanálise


### Arquitetura

```
erp_cadastro_sistema/
├── app.py              # Interface Streamlit — abas, UI, estado de sessão
├── rpa_monitor.py      # Motor de coleta — API de preços + Playwright
├── database.py         # Camada de acesso ao PostgreSQL (psycopg2)
├── .streamlit/
│   └── secrets.toml    # Credenciais (não versionado)
├── pyproject.toml
└── README.md
```

### Fluxo de dados

```
Usuário → app.py (Streamlit)
              │
              ├── db.listar_produtos()      → PostgreSQL
              ├── db.criar_produto()        → PostgreSQL
              │
              ├── rpa_monitor.analisar_rapido()
              │         └── API de preços (SerpAPI / substituta)
              │                 └── _filtrar_precos_por_relevancia()
              │
              └── rpa_monitor.analisar_detalhado_sessoes()
                        └── Playwright Chromium (navegador real)
                                ├── _extrair_pares_js()
                                ├── _filtrar_precos_por_relevancia()
                                └── filtrar_precos_inteligente() (IQR)
```


### Stack tecnológica

| Camada | Tecnologia |
|---|---|
| Interface web | [Streamlit](https://streamlit.io) |
| Banco de dados | PostgreSQL via [psycopg2](https://pypi.org/project/psycopg2/) |
| Coleta via API | [SerpAPI](https://serpapi.com) — Google Shopping (substituível) |
| Coleta via browser | [Playwright](https://playwright.dev/python/) (Chromium) |
| Parsing HTML | regex, BeautifulSoup4 |
| Similaridade textual | `difflib.SequenceMatcher` (stdlib Python) |
| Filtro de outliers | IQR (Interquartile Range) implementado nativamente |
| Gerenciamento de deps | [uv](https://github.com/astral-sh/uv) + pyproject.toml |



### Configuração

##### Pré-requisitos
- Python 3.11+
- PostgreSQL 14+
- Conta em uma API de busca de preços — o sistema usa [SerpAPI](https://serpapi.com) por padrão (plano gratuito: 250 buscas/mês), mas foi projetado para ser substituível por qualquer provedor equivalente como ScraperAPI, ShoppingScraper ou Outscraper, adaptando a função `_buscar_preco_serpapi` em `rpa_monitor.py` e mantendo a SerpAPI como fallback se necessário

##### Instalação

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/erp_cadastro_sistema.git
cd erp_cadastro_sistema

# Instale as dependências
uv sync
# ou: pip install -r requirements.txt

# Instale os browsers do Playwright
playwright install chromium
```

##### Configuração de credenciais

Crie o arquivo `.streamlit/secrets.toml`:

```toml
# Banco de dados PostgreSQL
[postgres]
host     = "localhost"
database = "db_cadastro_sistema_erp"
user     = "postgres"
password = "sua_senha"
port     = "5432"

# Credenciais de acesso ao sistema
[login_sistema]
email_admin = "admin@empresa.com"
senha_admin = "senha_segura"

# API de busca de preços (SerpAPI por padrão — substituível)
[serpapi]
api_key = "sua_chave_serpapi"
```

> O arquivo `secrets.toml` contém credenciais sensíveis. Ele está incluído no `.gitignore` e nunca deve ser versionado.

##### Banco de dados

O schema é criado automaticamente na primeira execução. As tabelas geradas são:

```sql
-- Catálogo de produtos
produtos (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(50) UNIQUE NOT NULL,
    marca VARCHAR(100),
    tipo VARCHAR(100),
    modelo VARCHAR(200),
    categoria VARCHAR(100),
    preco_unitario NUMERIC(10,2),
    custo NUMERIC(10,2),
    obs TEXT
)

-- Histórico de análises
analises (
    id SERIAL PRIMARY KEY,
    data_criacao TIMESTAMP DEFAULT NOW(),
    total_produtos INTEGER,
    total_alertas INTEGER,
    expira_em DATE,
    modo VARCHAR(20),   -- 'Rápido' ou 'Detalhado'
    fonte VARCHAR(50)   -- 'Google Shopping', 'Amazon' etc.
)

-- Resultados individuais por análise
itens_analise (
    id SERIAL PRIMARY KEY,
    analise_id INTEGER REFERENCES analises(id) ON DELETE CASCADE,
    codigo_produto VARCHAR(50),
    nome_produto VARCHAR(200),
    seu_preco NUMERIC(10,2),
    preco_mercado NUMERIC(10,2),
    diferenca_percent NUMERIC(6,2),
    margem_percent NUMERIC(6,2),
    status VARCHAR(30)
)
```

##### Executando o sistema

```bash
streamlit run app.py
```

O sistema estará disponível em `http://localhost:8501`.



### Formato do CSV de importação

```
codigo,marca,tipo,modelo,categoria,preco_unitario,custo,obs
MOL000251,Logitech,Mouse,MX Master 3S,Periféricos,349.90,210.00,
MOL000192,Logitech,Mouse,M330 Silent Plus,Periféricos,189.90,110.00,Produto silencioso
```

- `codigo`: identificador único do produto (obrigatório)
- `obs`: pode estar vazia
- Separador: vírgula. Encoding: UTF-8.



### Sites suportados no Modo Detalhado

| Site | Status |
|---|---|
| Amazon | Funcional — melhor taxa de sucesso |
| Americanas | Funcional — boa cobertura de eletrônicos |
| Google Shopping | Funcional — resultados de múltiplos vendedores |
| AliExpress | Parcial — funciona melhor para produtos com nome em inglês |



### Algoritmo de extração de preços

O pipeline de extração evita preços irreais sem usar limites arbitrários de valor mínimo ou máximo:

1. **Extração estruturada (JS evaluate):** obtém pares `(título_produto, preço)` diretamente dos cards de resultado de cada site via JavaScript no contexto da página
2. **Filtro de relevância por similaridade:** calcula o score entre cada título extraído e a query usando SequenceMatcher ratio + cobertura de palavras-chave. Apenas produtos com score >= 50% do melhor match são considerados
3. **Filtro IQR:** remove outliers estatísticos dos preços relevantes (Q1 - 2×IQR, Q3 + 2×IQR)
4. **Mediana:** o preço final é a mediana dos valores filtrados, resistente a preços extremos de estoque antigo ou promoções relâmpago
5. **Fallback em cascata:** se o extrator JS não retornar resultados, tenta CSS seletores e depois regex no HTML completo



### Painel de diagnóstico

O sistema inclui um painel de testes que permite verificar se a chave da API está configurada e carregada, testar uma chamada real com qualquer produto e ver o JSON de resposta completo, e resetar o banco de dados (uso exclusivo em desenvolvimento).

> Remover o expander `🛠️ Painel de Controle de Testes` do `app.py` antes do deploy em produção.



### Deploy

Para deploy no [Streamlit Community Cloud](https://streamlit.io/cloud):

1. Faça push do repositório para o GitHub (sem o `secrets.toml`)
2. Acesse [share.streamlit.io](https://share.streamlit.io) e conecte o repositório
3. Configure os secrets em **Settings → Secrets** usando o mesmo formato do `secrets.toml`
4. Certifique-se de que o PostgreSQL está acessível publicamente (ex: Supabase, Neon, Railway)

Para deploy com Docker ou servidor próprio:

```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```



### Licença

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
