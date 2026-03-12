from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import mercadopago
import requests
import time
import zipfile
import io
import uuid
import sqlite3
import threading # A MÁGICA DO SEGUNDO PLANO
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)
CORS(app)

API_KEY_MEU_DANFE = "36da320b-1b2d-47fa-b626-cc90dea64471"
MP_ACCESS_TOKEN = "APP_USR-1091359635861022-031115-4083f4ba9bf7da16cf148d67c053efdb-3243990562"
PRECO_POR_XML = 0.15
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# DICIONÁRIO PARA GUARDAR O PROGRESSO DOS DOWNLOADS
tarefas_download = {}

def conectar_banco():
    conn = sqlite3.connect('banco_taxxml.db')
    conn.row_factory = sqlite3.Row
    return conn

def iniciar_banco():
    conn = conectar_banco()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, email TEXT UNIQUE NOT NULL, senha TEXT NOT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS vendas (id INTEGER PRIMARY KEY AUTOINCREMENT, quantidade_xml INTEGER, valor_total REAL, metodo TEXT)''')
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios (nome, email, senha) VALUES ('Moraes Admin', 'admin@moraes.com', 'admin123')")
    conn.commit()
    conn.close()

iniciar_banco()

# (ROTAS DE LOGIN E REGISTRO MANTIDAS IGUAIS)
@app.route('/api/registrar', methods=['POST'])
def registrar_usuario():
    dados = request.json
    try:
        conn = conectar_banco()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO usuarios (nome, email, senha) VALUES (?, ?, ?)", (dados['nome'], dados['email'], dados['senha']))
        conn.commit()
        conn.close()
        return jsonify({"sucesso": True, "mensagem": "Conta criada!"})
    except sqlite3.IntegrityError: return jsonify({"erro": "E-mail cadastrado!"}), 400
    except Exception as e: return jsonify({"erro": str(e)}), 500

@app.route('/api/login', methods=['POST'])
def fazer_login():
    dados = request.json
    conn = conectar_banco()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE email = ? AND senha = ?", (dados['email'], dados['senha']))
    usuario = cursor.fetchone()
    conn.close()
    if usuario: return jsonify({"sucesso": True, "nome": usuario['nome']})
    return jsonify({"erro": "E-mail/senha incorretos."}), 401

@app.route('/api/admin/stats', methods=['GET'])
def get_stats():
    conn = conectar_banco()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(quantidade_xml), SUM(valor_total) FROM vendas")
    vendas = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    clientes = cursor.fetchone()[0]
    conn.close()
    return jsonify({"total_xmls": vendas[0] or 0, "faturamento": vendas[1] or 0.0, "clientes_ativos": clientes})

def salvar_venda(qtd, valor, metodo):
    conn = conectar_banco()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO vendas (quantidade_xml, valor_total, metodo) VALUES (?, ?, ?)", (qtd, valor, metodo))
    conn.commit()
    conn.close()

@app.route('/api/pagar-pix', methods=['POST'])
def gerar_pix():
    try:
        qtd = request.json.get('quantidade', 0)
        valor = float(qtd * PRECO_POR_XML)
        salvar_venda(qtd, valor, "PIX") 
        res = sdk.payment().create({"transaction_amount": valor, "description": f"Tax XML - {qtd} notas", "payment_method_id": "pix", "payer": {"email": "cliente@taxxml.com"}})["response"]
        return jsonify({"qr_code_base64": res["point_of_interaction"]["transaction_data"]["qr_code_base64"], "qr_code": res["point_of_interaction"]["transaction_data"]["qr_code"], "payment_id": res["id"]})
    except Exception as e: return jsonify({"erro": str(e)}), 400

@app.route('/api/pagar-cartao', methods=['POST'])
def gerar_cartao():
    try:
        qtd = request.json.get('quantidade', 0)
        valor = float(qtd * PRECO_POR_XML)
        salvar_venda(qtd, valor, "CARTAO") 
        codigo_rastreio = str(uuid.uuid4())
        res = sdk.preference().create({"items": [{"title": f"Tax XML - {qtd} notas", "quantity": 1, "unit_price": valor, "currency_id": "BRL"}], "payer": {"email": "cliente@taxxml.com"}, "payment_methods": {"installments": 1}, "external_reference": codigo_rastreio})["response"]
        return jsonify({"checkout_url": res["init_point"], "rastreio": codigo_rastreio})
    except Exception as e: return jsonify({"erro": str(e)}), 400

@app.route('/api/status-pix/<int:pay_id>', methods=['GET'])
def status_pix(pay_id):
    status = sdk.payment().get(pay_id)["response"].get("status")
    return jsonify({"pago": status == "approved"})

@app.route('/api/status-cartao/<rastreio>', methods=['GET'])
def status_cartao(rastreio):
    busca = sdk.payment().search({"external_reference": rastreio})["response"].get("results", [])
    pago = any(p.get("status") == "approved" for p in busca)
    return jsonify({"pago": pago})

# ==========================================
# MOTOR DE DOWNLOAD (NOVA ARQUITETURA)
# ==========================================
def baixar_xml_original(session, chave):
    headers = { "Api-Key": API_KEY_MEU_DANFE, "Content-Type": "application/json" }
    url_get = f"https://api.meudanfe.com.br/v2/fd/get/xml/{chave}"
    url_add = f"https://api.meudanfe.com.br/v2/fd/add/{chave}"
    try:
        r = session.get(url_get, headers=headers, timeout=12)
        c = r.text.strip()
        xml = r.json().get('data') or r.json().get('xml') if c.startswith('{') else c if c.startswith('<') else None
        if xml and "<nfeProc" in xml: return True, chave, xml[xml.find("<"):].encode('utf-8')
        session.put(url_add, headers=headers, timeout=12)
        time.sleep(5)
        r = session.get(url_get, headers=headers, timeout=12)
        c = r.text.strip()
        xml = r.json().get('data') or r.json().get('xml') if c.startswith('{') else c if c.startswith('<') else None
        if xml and "<nfeProc" in xml: return True, chave, xml[xml.find("<"):].encode('utf-8')
    except: pass
    return False, chave, None

def processar_lote_bg(task_id, chaves):
    zip_buf = io.BytesIO()
    sucessos = 0
    # Processa as notas em paralelo (15 funcionários)
    with zipfile.ZipFile(zip_buf, "a", zipfile.ZIP_DEFLATED) as zf:
        with requests.Session() as sess:
            with ThreadPoolExecutor(max_workers=15) as exe:
                futures = {exe.submit(baixar_xml_original, sess, c): c for c in chaves}
                for i, j in enumerate(as_completed(futures)):
                    ok, ch, xml_data = j.result()
                    if ok:
                        zf.writestr(f"{ch}.xml", xml_data)
                        sucessos += 1
                    # ATUALIZA O PROGRESSO A CADA NOTA!
                    tarefas_download[task_id]['processados'] = i + 1
                    
    tarefas_download[task_id]['sucessos'] = sucessos
    tarefas_download[task_id]['concluido'] = True
    tarefas_download[task_id]['zip_bytes'] = zip_buf.getvalue()

@app.route('/api/iniciar-download', methods=['POST'])
def iniciar_download():
    chaves = request.json.get('chaves', [])
    if not chaves: return jsonify({"erro": "Sem chaves"}), 400
    
    task_id = str(uuid.uuid4())
    # Cria a "ficha" de acompanhamento
    tarefas_download[task_id] = {'processados': 0, 'total': len(chaves), 'sucessos': 0, 'concluido': False, 'zip_bytes': None}
    
    # Manda um "trabalhador" processar isso no fundo, e libera a tela na hora
    threading.Thread(target=processar_lote_bg, args=(task_id, chaves)).start()
    
    return jsonify({"task_id": task_id})

@app.route('/api/progresso/<task_id>', methods=['GET'])
def ver_progresso(task_id):
    tarefa = tarefas_download.get(task_id)
    if not tarefa: return jsonify({"erro": "Tarefa não encontrada"}), 404
    # Devolve a % de conclusão para a tela sem mandar o arquivo ainda
    return jsonify({"processados": tarefa['processados'], "total": tarefa['total'], "concluido": tarefa['concluido']})

@app.route('/api/baixar-zip/<task_id>', methods=['GET'])
def baixar_zip(task_id):
    tarefa = tarefas_download.get(task_id)
    if not tarefa or not tarefa['concluido']: return jsonify({"erro": "Não pronto"}), 400
    
    # Agora sim, devolve o arquivo físico pro cliente
    return send_file(io.BytesIO(tarefa['zip_bytes']), mimetype='application/zip', as_attachment=True, download_name='TaxXML_Lote.zip')

if __name__ == '__main__':
    app.run(port=5000, debug=True)