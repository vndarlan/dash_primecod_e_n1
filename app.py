import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import os

# Configuração da página
st.set_page_config(
    page_title="Dashboard de Efetividade",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configuração do banco de dados
@st.cache_resource
def init_connection():
    """Inicializa conexão com PostgreSQL Railway"""
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        try:
            DATABASE_URL = st.secrets["DATABASE_URL"]
        except:
            st.error("❌ Configure DATABASE_URL nas variáveis de ambiente ou secrets")
            st.stop()
    
    engine = create_engine(DATABASE_URL)
    return engine

# Funções de banco de dados para N1
def criar_tabelas(engine):
    """Cria tabelas necessárias no banco"""
    with engine.connect() as conn:
        # Tabela de uploads N1
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS uploads_n1 (
                id SERIAL PRIMARY KEY,
                nome_arquivo VARCHAR(255) NOT NULL,
                periodo_inicio DATE,
                periodo_fim DATE,
                data_upload TIMESTAMP DEFAULT NOW(),
                total_registros INTEGER
            )
        """))
        
        # Tabela dados N1
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dados_n1 (
                id SERIAL PRIMARY KEY,
                upload_id INTEGER REFERENCES uploads_n1(id) ON DELETE CASCADE,
                order_number VARCHAR(50),
                shipping_number VARCHAR(100),
                completed_date TIMESTAMP NULL,
                customer VARCHAR(255),
                payment VARCHAR(50),
                sku VARCHAR(100),
                product_name VARCHAR(255),
                total_revenues DECIMAL(10,2),
                quantity INTEGER,
                product_cost DECIMAL(10,2),
                order_status VARCHAR(50),
                last_tracking VARCHAR(255),
                last_tracking_date DATE NULL,
                platform VARCHAR(50),
                zip_code VARCHAR(20),
                province_code VARCHAR(10),
                pais VARCHAR(20)
            )
        """))
        
        conn.commit()

def processar_dados_n1(df, pais_manual=None):
    """Processa dados do Excel da N1"""
    df_clean = df.copy()
    
    # Remover primeira linha se for header duplicado
    if len(df_clean) > 0 and not str(df_clean.iloc[0, 0]).startswith('#'):
        df_clean = df_clean.iloc[1:].reset_index(drop=True)
    
    # Remover última linha se contiver "Total"
    if len(df_clean) > 1:
        last_row = df_clean.iloc[-1]
        last_row_str = ' '.join([str(val) for val in last_row if pd.notna(val)]).lower()
        if 'total' in last_row_str:
            df_clean = df_clean.iloc[:-1].reset_index(drop=True)
    
    # Mapeamento das colunas
    column_mapping = {
        'Order #': 'order_number',
        'Shipping #': 'shipping_number', 
        'Completed date': 'completed_date',
        'Customer': 'customer',
        'Payment': 'payment',
        'Sku': 'sku',
        'Product name': 'product_name',
        'Total revenues': 'total_revenues',
        'Quantity': 'quantity',
        'Product cost': 'product_cost',
        'Order status': 'order_status',
        'Last tracking': 'last_tracking',
        'Last tracking date': 'last_tracking_date',
        'Platform': 'platform',
        'Zip': 'zip_code',
        'Province code': 'province_code'
    }
    
    # Filtrar colunas existentes
    available_columns = {k: v for k, v in column_mapping.items() if k in df_clean.columns}
    df_processed = df_clean[list(available_columns.keys())].copy()
    df_processed = df_processed.rename(columns=available_columns)
    
    # Limpar dados inválidos
    if 'order_number' in df_processed.columns:
        df_processed = df_processed[df_processed['order_number'].notna()]
        df_processed = df_processed[df_processed['order_number'] != '']
        df_processed = df_processed[df_processed['order_number'].astype(str).str.startswith('#')]
    
    # Processar datas
    if 'completed_date' in df_processed.columns:
        df_processed['completed_date'] = pd.to_datetime(df_processed['completed_date'], format='%d/%m/%Y %H:%M', errors='coerce')
        # Converter para string, mas manter None para valores inválidos
        df_processed['completed_date'] = df_processed['completed_date'].apply(
            lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(x) else None
        )
    
    if 'last_tracking_date' in df_processed.columns:
        df_processed['last_tracking_date'] = pd.to_datetime(df_processed['last_tracking_date'], format='%d/%m/%Y', errors='coerce')
        # Converter para string, mas manter None para valores inválidos  
        df_processed['last_tracking_date'] = df_processed['last_tracking_date'].apply(
            lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else None
        )
    
    # Processar tipos numéricos
    numeric_columns = ['total_revenues', 'quantity', 'product_cost']
    for col in numeric_columns:
        if col in df_processed.columns:
            df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce')
    
    # Processar strings (não datas)
    string_columns = ['zip_code', 'province_code', 'customer', 'payment', 'sku', 'last_tracking', 'platform']
    for col in string_columns:
        if col in df_processed.columns:
            df_processed[col] = df_processed[col].astype(str).replace('nan', '')
    
    # Preencher apenas campos de texto com strings vazias, manter datas e números como None/NaN
    text_columns = ['order_number', 'shipping_number', 'customer', 'payment', 'sku', 
                    'product_name', 'last_tracking', 'platform', 'zip_code', 'province_code', 'pais']
    
    for col in text_columns:
        if col in df_processed.columns:
            df_processed[col] = df_processed[col].fillna('')
    
    # Identificar país
    def identificar_pais(row):
        province_code = str(row.get('province_code', '')).upper().strip()
        zip_code = str(row.get('zip_code', '')).strip()
        
        if len(province_code) == 2 and province_code.isalpha() and province_code != '':
            return 'Italia'
        
        if zip_code and zip_code != '' and zip_code.isdigit():
            if len(zip_code) == 5:
                return 'Italia'
            elif len(zip_code) == 6:
                return 'Romania'
        
        return 'Italia'
    
    df_processed['pais'] = df_processed.apply(identificar_pais, axis=1)
    return df_processed

def salvar_dados_n1(df, nome_personalizado, engine):
    """Salva dados da N1 no banco"""
    try:
        with engine.begin() as conn:
            # Calcular período
            periodo_inicio = None
            periodo_fim = None
            
            if 'completed_date' in df.columns:
                # Filtrar apenas datas válidas (não None)
                datas_validas = df[df['completed_date'].notna()]['completed_date']
                if not datas_validas.empty:
                    dates_series = pd.to_datetime(datas_validas, errors='coerce')
                    dates_series = dates_series.dropna()
                    if not dates_series.empty:
                        periodo_inicio = dates_series.min().date()
                        periodo_fim = dates_series.max().date()
            
            # Salvar upload
            upload_data = {
                'nome_arquivo': nome_personalizado,
                'periodo_inicio': periodo_inicio,
                'periodo_fim': periodo_fim,
                'total_registros': len(df)
            }
            
            result = conn.execute(text("""
                INSERT INTO uploads_n1 (nome_arquivo, periodo_inicio, periodo_fim, total_registros)
                VALUES (:nome_arquivo, :periodo_inicio, :periodo_fim, :total_registros)
                RETURNING id
            """), upload_data)
            
            upload_id = result.fetchone()[0]
            
            # Salvar dados
            df_copy = df.copy()
            df_copy['upload_id'] = upload_id
            
            # Para arquivos grandes, usar chunks menores
            chunk_size = 100 if len(df_copy) > 500 else 500
            
            # Inserir em chunks para evitar timeout e problemas de memória
            total_chunks = (len(df_copy) // chunk_size) + (1 if len(df_copy) % chunk_size > 0 else 0)
            
            for i in range(0, len(df_copy), chunk_size):
                chunk = df_copy.iloc[i:i + chunk_size]
                chunk.to_sql('dados_n1', conn, if_exists='append', index=False)
                
                # Mostrar progresso para arquivos grandes
                if total_chunks > 1:
                    chunk_num = (i // chunk_size) + 1
                    print(f"Processando chunk {chunk_num}/{total_chunks} ({len(chunk)} registros)")
            
            return upload_id
            
    except Exception as e:
        raise e

def carregar_uploads_n1(engine):
    """Carrega lista de uploads da N1"""
    query = """
        SELECT id, nome_arquivo, periodo_inicio, periodo_fim, data_upload, total_registros
        FROM uploads_n1 
        ORDER BY data_upload DESC
    """
    return pd.read_sql(query, engine)

def carregar_dados_n1(upload_id, pais_filtro, engine):
    """Carrega dados da N1 para análise"""
    upload_id = int(upload_id)
    
    query = "SELECT * FROM dados_n1 WHERE upload_id = %(upload_id)s"
    params = {'upload_id': upload_id}
    
    if pais_filtro != 'Todos':
        query += " AND pais = %(pais)s"
        params['pais'] = pais_filtro
    
    df = pd.read_sql(query, engine, params=params)
    
    # Converter datas
    if 'completed_date' in df.columns:
        df['completed_date'] = pd.to_datetime(df['completed_date'], errors='coerce')
    
    if 'last_tracking_date' in df.columns:
        df['last_tracking_date'] = pd.to_datetime(df['last_tracking_date'], errors='coerce')
    
    return df

def calcular_metricas_n1(df):
    """Calcula métricas por produto"""
    if df.empty:
        return pd.DataFrame()
    
    # Agrupar por produto
    metricas = df.groupby('product_name').agg({
        'order_number': 'count',
        'shipping_number': 'count',
    }).reset_index()
    
    metricas.columns = ['Product', 'Pedidos Totais', 'Pedidos Enviados']
    
    # Calcular entregues e devoluções
    status_counts = df.groupby(['product_name', 'order_status']).size().unstack(fill_value=0)
    
    entregues = status_counts.get('Delivered', pd.Series(0, index=status_counts.index))
    devolucoes = status_counts.get('Return', pd.Series(0, index=status_counts.index)) + \
                status_counts.get('Returned', pd.Series(0, index=status_counts.index))
    
    metricas['Entregues'] = metricas['Product'].map(entregues).fillna(0).astype(int)
    metricas['Devoluções'] = metricas['Product'].map(devolucoes).fillna(0).astype(int)
    metricas['Shipping'] = metricas['Pedidos Enviados']
    
    # Calcular efetividade
    metricas['Efetividade'] = (metricas['Entregues'] / metricas['Pedidos Totais'] * 100).round(2)
    
    return metricas

def excluir_upload_n1(upload_id, engine):
    """Exclui upload N1 e seus dados"""
    try:
        # Converter para int para evitar erro numpy.int64
        upload_id = int(upload_id)
        
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM uploads_n1 WHERE id = :upload_id"), {'upload_id': upload_id})
        return True
    except Exception as e:
        st.error(f"Erro ao excluir: {str(e)}")
        return False

def aplicar_cores_efetividade(df):
    """Aplica cores na coluna de efetividade"""
    def color_efetividade(val):
        if pd.isna(val):
            return ''
        try:
            # Remover % e converter para float
            num_val = float(str(val).replace('%', ''))
            if num_val >= 60:
                return 'background-color: #28a745; color: white'  # Verde escuro
            elif num_val >= 50:
                return 'background-color: #6bc950; color: white'  # Verde claro
            elif num_val >= 40:
                return 'background-color: #ffc107; color: black'  # Amarelo
            else:
                return 'background-color: #dc3545; color: white'  # Vermelho
        except:
            return ''
    
    # Aplicar estilo apenas na coluna Efetividade
    return df.style.applymap(color_efetividade, subset=['Efetividade'])

# Dashboard N1
def dashboard_n1(engine):
    st.header("🇪🇺 Dashboard N1")
    
    # Session state para controlar upload
    if 'upload_success_n1' not in st.session_state:
        st.session_state.upload_success_n1 = False
    
    # Sidebar para upload
    with st.sidebar:
        st.subheader("📁 Upload de Dados N1")
        
        # Resetar campos se upload foi bem sucedido
        if st.session_state.upload_success_n1:
            st.session_state.upload_success_n1 = False
            st.rerun()
        
        nome_personalizado = st.text_input(
            "Nome do upload:", 
            placeholder="Ex: Dados Abril 2025",
            help="Nome que aparecerá na lista de análises",
            key="nome_upload_n1"
        )
        
        # Seletor de país MANUAL
        pais_manual = st.selectbox(
            "País dos dados:", 
            ["Automático", "Italia", "Espanha", "Polonia", "Romania"],
            help="Selecione o país ou deixe 'Automático' para detecção automática",
            key="pais_manual_n1"
        )
        
        uploaded_file = st.file_uploader(
            "Selecione o arquivo Excel da N1", 
            type=['xlsx', 'xls'],
            help="Formato esperado: relatório de pedidos da N1",
            key="file_upload_n1"
        )
        
        if uploaded_file is not None and nome_personalizado.strip():
            try:
                df_raw = pd.read_excel(uploaded_file)
                
                # Passar país manual para processamento
                pais_para_processar = pais_manual if pais_manual != 'Automático' else None
                df_processed = processar_dados_n1(df_raw, pais_para_processar)
                
                st.success(f"✅ Arquivo processado: {len(df_processed)} registros")
                
                with st.expander("👁️ Preview dos dados"):
                    st.dataframe(df_processed.head(3))
                    
                    # Estatísticas de processamento
                    col1, col2 = st.columns(2)
                    with col1:
                        pais_detectado = df_processed['pais'].unique()
                        if pais_manual != 'Automático':
                            st.info(f"🌍 País: {pais_manual} (selecionado manualmente)")
                        else:
                            st.info(f"🌍 Países detectados: {', '.join(pais_detectado)}")
                        
                        # Contar datas válidas
                        if 'completed_date' in df_processed.columns:
                            datas_validas = df_processed['completed_date'].notna().sum()
                            st.info(f"📅 Datas válidas: {datas_validas}/{len(df_processed)}")
                    
                    with col2:
                        # Status dos pedidos
                        if 'order_status' in df_processed.columns:
                            status_counts = df_processed['order_status'].value_counts()
                            st.info(f"📊 Status mais comum: {status_counts.index[0]} ({status_counts.iloc[0]})")
                            
                        # Produtos únicos
                        if 'product_name' in df_processed.columns:
                            produtos_unicos = df_processed['product_name'].nunique()
                            st.info(f"🏷️ Produtos únicos: {produtos_unicos}")
                    
                    # Informação sobre identificação
                    if pais_manual == 'Automático':
                        st.caption("🔍 **Detecção automática ativa** - Se não funcionar corretamente, selecione o país manualmente")
                    else:
                        st.caption(f"✅ **País fixo:** Todos os registros serão marcados como {pais_manual}")
                
                if st.button("💾 Salvar no Banco de Dados", use_container_width=True, key="save_n1"):
                    try:
                        # Mostrar alerta para arquivos grandes
                        if len(df_processed) > 500:
                            st.info(f"📊 Arquivo grande detectado ({len(df_processed)} registros). O processamento pode levar alguns minutos...")
                        
                        with st.spinner("Salvando dados no banco..."):
                            upload_id = salvar_dados_n1(df_processed, nome_personalizado.strip(), engine)
                            st.success(f"✅ Dados salvos com sucesso! ({len(df_processed)} registros)")
                            st.session_state.upload_success_n1 = True
                            st.cache_data.clear()
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao salvar: {str(e)}")
                        st.info("💡 Para arquivos muito grandes, tente dividir em arquivos menores.")
                        
            except ValueError as ve:
                st.error(f"❌ Erro na estrutura do arquivo: {str(ve)}")
                st.info("""
                **💡 Verifique se o arquivo contém:**
                - Colunas esperadas (Order #, Product name, Order status, etc.)
                - Números de pedidos válidos (qualquer formato: #ITA123, LL15278, etc.)
                - Dados válidos nas linhas
                
                **🇪🇸 Para arquivos da Espanha:** Selecione "Espanha" no seletor de país acima
                """)
                
                # Debug: mostrar colunas encontradas
                try:
                    if 'df_raw' in locals():
                        with st.expander("🔍 Debug - Colunas encontradas no arquivo"):
                            st.write("**Colunas disponíveis:**")
                            st.write(list(df_raw.columns))
                            st.write("**Primeiras 3 linhas:**")
                            st.dataframe(df_raw.head(3))
                            
                            # Mostrar amostras de pedidos
                            if 'Order #' in df_raw.columns:
                                pedidos_amostra = df_raw['Order #'].head(5).tolist()
                                st.write("**Amostras de números de pedidos:**", pedidos_amostra)
                except:
                    pass
            except Exception as e:
                st.error(f"❌ Erro ao processar arquivo: {str(e)}")
                st.info("💡 Certifique-se de que o arquivo é um Excel válido (.xlsx ou .xls)")
                
                # Debug: informações do arquivo
                try:
                    if 'df_raw' in locals():
                        with st.expander("🔍 Debug - Informações do arquivo"):
                            st.write(f"**Formato:** {uploaded_file.type}")
                            st.write(f"**Tamanho:** {len(df_raw)} linhas x {len(df_raw.columns)} colunas")
                            st.write("**Colunas:**", list(df_raw.columns))
                except:
                    st.write(f"**Tipo do arquivo:** {uploaded_file.type if uploaded_file else 'Desconhecido'}")
        
        elif uploaded_file is not None and not nome_personalizado.strip():
            st.warning("⚠️ Digite um nome para o upload")
        
        # Seção de exclusão
        st.subheader("🗑️ Excluir Dados N1")
        uploads = carregar_uploads_n1(engine)
        
        if not uploads.empty:
            upload_para_excluir = st.selectbox(
                "Selecione upload para excluir:",
                options=range(len(uploads)),
                format_func=lambda x: uploads.iloc[x]['nome_arquivo'],
                key="select_delete_n1"
            )
            
            if st.button("🗑️ Excluir Dados", type="secondary", use_container_width=True, key="delete_n1"):
                upload_id = int(uploads.iloc[upload_para_excluir]['id'])  # Converter para int
                nome = uploads.iloc[upload_para_excluir]['nome_arquivo']
                
                if st.session_state.get('confirm_delete_n1') != upload_id:
                    st.session_state.confirm_delete_n1 = upload_id
                    st.warning(f"⚠️ Confirme a exclusão de '{nome}' clicando novamente no botão")
                else:
                    if excluir_upload_n1(upload_id, engine):
                        st.success(f"✅ '{nome}' foi excluído com sucesso!")
                        st.session_state.confirm_delete_n1 = None
                        st.cache_data.clear()  # Limpar cache após exclusão
                        st.rerun()
        else:
            st.info("Nenhum upload N1 encontrado")
    
    # Área principal - análise
    st.subheader("📊 Análise de Dados N1")
    
    uploads = carregar_uploads_n1(engine)
    
    if uploads.empty:
        st.info("📤 Faça upload de um arquivo na barra lateral para começar.")
        return
    
    # Seletor de País
    pais_selecionado = st.selectbox(
        "Selecione o país:", 
        ["Todos", "Italia", "Espanha", "Polonia", "Romania"],
        help="Filtra os períodos disponíveis pelo país selecionado",
        key="pais_n1"
    )
    
    # Filtrar uploads por país
    if pais_selecionado == "Todos":
        uploads_filtrados = uploads
    else:
        uploads_com_pais = []
        for _, upload in uploads.iterrows():
            with engine.connect() as conn:
                count_pais = conn.execute(
                    text("SELECT COUNT(*) FROM dados_n1 WHERE upload_id = :upload_id AND pais = :pais"),
                    {'upload_id': upload['id'], 'pais': pais_selecionado}
                ).fetchone()[0]
                
                if count_pais > 0:
                    uploads_com_pais.append(upload['id'])
        
        uploads_filtrados = uploads[uploads['id'].isin(uploads_com_pais)]
    
    if uploads_filtrados.empty:
        st.warning(f"⚠️ Nenhum upload encontrado com dados de {pais_selecionado}.")
        return
    
    # Seletor de upload
    upload_options = []
    for _, row in uploads_filtrados.iterrows():
        if pd.notna(row['periodo_inicio']) and pd.notna(row['periodo_fim']):
            inicio = pd.to_datetime(row['periodo_inicio']).strftime('%d/%m/%Y')
            fim = pd.to_datetime(row['periodo_fim']).strftime('%d/%m/%Y')
            periodo = f"({inicio} - {fim})"
        else:
            periodo = ""
        
        if pais_selecionado == "Todos":
            registros_info = f"{row['total_registros']} registros"
        else:
            with engine.connect() as conn:
                count_pais = conn.execute(
                    text("SELECT COUNT(*) FROM dados_n1 WHERE upload_id = :upload_id AND pais = :pais"),
                    {'upload_id': row['id'], 'pais': pais_selecionado}
                ).fetchone()[0]
                registros_info = f"{count_pais} registros ({pais_selecionado})"
        
        upload_options.append(f"{row['nome_arquivo']} {periodo} - {registros_info}")
    
    upload_selecionado = st.selectbox("Selecione o período para análise:", upload_options, key="periodo_n1")
    upload_id = int(uploads_filtrados.iloc[upload_options.index(upload_selecionado)]['id'])
    
    # Carregar e analisar dados
    dados = carregar_dados_n1(upload_id, pais_selecionado, engine)
    
    if dados.empty:
        st.warning("⚠️ Nenhum dado encontrado para os filtros selecionados.")
        return
    
    # Calcular métricas
    metricas = calcular_metricas_n1(dados)
    
    # Filtrar produtos válidos
    metricas = metricas[metricas['Product'] != '']
    metricas = metricas[metricas['Pedidos Totais'] > 0]
    
    # Métricas principais
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total de Pedidos", metricas['Pedidos Totais'].sum())
    
    with col2:
        st.metric("Total Entregues", metricas['Entregues'].sum())
    
    with col3:
        st.metric("Total Devoluções", metricas['Devoluções'].sum())
    
    with col4:
        efetividade_geral = (metricas['Entregues'].sum() / metricas['Pedidos Totais'].sum() * 100) if metricas['Pedidos Totais'].sum() > 0 else 0
        st.metric("Efetividade Geral", f"{efetividade_geral:.2f}%")
    
    # Tabela com cores
    st.subheader("📋 Tabela de Efetividade por Produto")
    
    df_display = metricas.copy()
    df_display['Efetividade'] = df_display['Efetividade'].apply(lambda x: f"{x:.2f}%")
    
    # Aplicar cores e exibir
    styled_df = aplicar_cores_efetividade(df_display)
    st.dataframe(styled_df, use_container_width=True, height=400)
    
    # Download
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("📥 Download CSV", use_container_width=True, key="download_n1"):
            csv = metricas.to_csv(index=False)
            st.download_button(
                label="⬇️ Baixar Relatório",
                data=csv,
                file_name=f"relatorio_n1_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True,
                key="download_btn_n1"
            )

# Dashboard Prime COD
def dashboard_prime_cod():
    st.header("🚀 Dashboard Prime COD")
    
    st.info("""
    **Prime COD Dashboard**
    
    Esta página será desenvolvida quando os dados específicos do Prime COD estiverem disponíveis.
    """)

# Interface principal
def main():
    st.title("📊 Dashboard de Efetividade de Produtos")
    
    # Inicializar conexão
    engine = init_connection()
    criar_tabelas(engine)
    
    # Sidebar para navegação
    st.sidebar.title("🧭 Navegação")
    pagina = st.sidebar.selectbox("Escolha o fornecedor:", ["N1", "Prime COD"])
    
    if pagina == "N1":
        dashboard_n1(engine)
    else:
        dashboard_prime_cod()

if __name__ == "__main__":
    main()