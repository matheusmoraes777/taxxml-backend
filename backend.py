import os
import time
import uuid
import zipfile
import io
import threading
import datetime
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import mercadopago
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# FIREBASE - CONFIGURAÇÃO DE NUVEM (PRO)
# ==========================================
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
CORS(app)

# Lista de caminhos onde a chave pode estar (Render e PC)
caminhos_possiveis = [
    "/etc/secrets/firebase-key.json",  # Caminho padrão do Render
    "/etc/secrets/key.json",           # Alternativo caso mude no painel
    "firebase-key.json",               # Raiz do projeto (PC)
    "key.json"                         # Raiz do projeto (PC alternativo)
]

db = None
chave_encontrada = None

for caminho in caminhos_possiveis:
    if os.path.exists(caminho):
        try:
            cred = credentials.Certificate(caminho)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            chave_encontrada = caminho
            print(f"🔥 Firebase conectado com sucesso usando: {caminho}")
            break
        except Exception as e:
            print(f"Tentativa falhou em {caminho}: {e}")

if db is None:
    print("⚠️ ERRO CRÍTICO: Nenhuma chave Firebase encontrada nos caminhos verificados.")

# ==========================================
# CONFIGURAÇÕES E CHAVES
# ==========================================
API_KEY_MEU_DANFE = "36da320b-1b2d-47fa-b626-cc90dea64471"
MP_ACCESS_TOKEN = "APP_USR-1091359635861022-031115-4083f4ba9bf7da16cf148d67c053efdb-3243990562"
PRECO_POR_XML = 0.15

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
tarefas_download = {}

# ==========================================
# FUNÇÕES DE BANCO DE DADOS
# ==========================================
def salvar_venda(qtd, valor, metodo, email_cliente):
    if db:
        try:
            db.collection('vendas').add({
                'quantidade_xml': qtd,
                'valor_total': valor,
                'metodo': metodo,
                'email': email_cliente,
                'data_compra': datetime.datetime.now()
            })
        except Exception as e:
            print(f"Erro ao gravar venda: {e}")

# ==========================================
# ROTAS DE USUÁRIO E ADMIN
# ==========================================
@app.route('/api/registrar', methods=['POST'])
def registrar_usuario():
    dados = request.json
    if not db: return jsonify({"erro": "Banco de dados offline"}), 500
    try:
        users_ref = db.collection('usuarios')
        docs = users_ref.where('email', '==', dados['email']).stream()
        if len(list(docs)) > 0:
            return jsonify({"erro": "E-mail já cadastrado!"}), 400
        users_ref.add({
            'nome': dados['nome'],
            'email': dados['email'],
            'senha': dados['senha'],
            'data_criacao': datetime.datetime.now()
        })
        return jsonify({"sucesso": True, "mensagem": "Conta criada!"})
    except Exception as e: return jsonify({"erro": str(e)}), 500

@app.route('/api/login', methods=['POST'])
def fazer_login():
    dados = request.json
    if not db: return jsonify({"erro": "Banco de dados offline"}), 500
    try:
        docs = db.collection('usuarios').where('email', '==', dados['email']).where('senha', '==', dados['senha']).stream()
        for doc in docs:
            usuario = doc.to_dict()
            return jsonify({"sucesso": True, "nome": usuario.get('nome')})
        return jsonify({"erro": "E-mail ou senha incorretos."}), 401
    except Exception as e: return jsonify({"erro": str(e)}), 500

@app.route('/api/admin/stats', methods=['GET'])
def get_stats():
    if not db: return jsonify({"total_xmls": 0, "faturamento": 0, "clientes_ativos": 0})
    try:
        vendas_docs = db.collection('vendas').stream()
        total_xmls = 0
        faturamento = 0.0
        for venda in vendas_docs:
            d = venda.to_dict()
            total_xmls += d.get('quantidade_xml', 0)
            faturamento += d.get('valor_total', 0.0)
        clientes = sum(1 for _ in db.collection('usuarios').stream())
        return jsonify({"total_xmls": total_xmls, "faturamento": faturamento, "clientes_ativos": clientes})
    except:
        return jsonify({"total_xmls": 0, "faturamento": 0.0, "clientes_ativos": 0})

# ==========================================
# PAGAMENTOS
# ==========================================
@app.route('/api/pagar-pix', methods=['POST'])
def gerar_pix():
    try:
        dados = request.json
        qtd = dados.get('quantidade', 0)
        email = dados.get('email', 'desconhecido')
        valor = float(qtd * PRECO_POR_XML)
        salvar_venda(qtd, valor, "PIX", email)
        res = sdk.payment().create({
            "transaction_amount": valor,
            "description": f"Tax XML - {qtd} notas",
            "payment_method_id": "pix",
            "payer": {"email": email if "@" in email else "cliente@taxxml.com"}
        })["response"]
        return jsonify({"qr_code_base64": res["point_of_interaction"]["transaction_data"]["qr_code_base64"], "payment_id": res["id"]})
    except Exception as e: return jsonify({"erro": str(e)}), 400

@app.route('/api/pagar-cartao', methods=['POST'])
def gerar_cartao():
    try:
        dados = request.json
        qtd = dados.get('quantidade', 0)
        email = dados.get('email', 'desconhecido')
        valor = float(qtd * PRECO_POR_XML)
        salvar_venda(qtd, valor, "CARTAO", email)
        rastreio = str(uuid.uuid4())
        res = sdk.preference().create({
            "items": [{"title": f"Tax XML - {qtd} notas", "quantity": 1, "unit_price": valor, "currency_id": "BRL"}],
            "external_reference": rastreio,
            "back_urls": {"success": "https://taxxml.com.br", "failure": "https://taxxml.com.br", "pending": "https://taxxml.com.br"},
            "auto_return": "approved"
        })["response"]
        return jsonify({"checkout_url": res["init_point"], "rastreio": rastreio})
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
# MOTOR DE DOWNLOAD (BACKGROUND)
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
    with zipfile.ZipFile(zip_buf, "a", zipfile.ZIP_DEFLATED) as zf:
        with requests.Session() as sess:
            with ThreadPoolExecutor(max_workers=15) as exe:
                futures = {exe.submit(baixar_xml_original, sess, c): c for c in chaves}
                for i, j in enumerate(as_completed(futures)):
                    ok, ch, xml_data = j.result()
                    if ok:
                        zf.writestr(f"{ch}.xml", xml_data)
                        sucessos += 1
                    tarefas_download[task_id]['processados'] = i + 1
    tarefas_download[task_id]['sucessos'] = sucessos
    tarefas_download[task_id]['concluido'] = True
    tarefas_download[task_id]['zip_bytes'] = zip_buf.getvalue()

@app.route('/api/iniciar-download', methods=['POST'])
def iniciar_download():
    chaves = request.json.get('chaves', [])
    if not chaves: return jsonify({"erro": "Sem chaves"}), 400
    task_id = str(uuid.uuid4())
    tarefas_download[task_id] = {'processados': 0, 'total': len(chaves), 'sucessos': 0, 'concluido': False, 'zip_bytes': None}
    threading.Thread(target=processar_lote_bg, args=(task_id, chaves)).start()
    return jsonify({"task_id": task_id})

@app.route('/api/progresso/<task_id>', methods=['GET'])
def ver_progresso(task_id):
    tarefa = tarefas_download.get(task_id)
    if not tarefa: return jsonify({"erro": "Tarefa não encontrada"}), 404
    return jsonify({"processados": tarefa['processados'], "total": tarefa['total'], "concluido": tarefa['concluido']})

@app.route('/api/baixar-zip/<task_id>', methods=['GET'])
def baixar_zip(task_id):
    tarefa = tarefas_download.get(task_id)
    if not tarefa or not tarefa['concluido']: return jsonify({"erro": "Ainda não está pronto"}), 400
    return send_file(io.BytesIO(tarefa['zip_bytes']), mimetype='application/zip', as_attachment=True, download_name='TaxXML_Lote.zip')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
