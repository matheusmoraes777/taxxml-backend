from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import mercadopago
import requests
import time
import zipfile
import io
import uuid
import threading
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# NOVO: IMPORTANDO O FIREBASE (BANDO DE DADOS CLOUD)
# ==========================================
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
CORS(app)

# ==========================================
# INICIALIZANDO O FIREBASE
# ==========================================
# O Python vai procurar o arquivo 'firebase-key.json' na mesma pasta
try:
    cred = credentials.Certificate("firebase-key.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("🔥 Firebase Cloud Firestore conectado com sucesso!")
except Exception as e:
    print(f"⚠️ Erro Crítico ao conectar no Firebase. O arquivo 'firebase-key.json' está na pasta? Erro: {e}")

# ==========================================
# CONFIGURAÇÕES E CHAVES
# ==========================================
API_KEY_MEU_DANFE = "36da320b-1b2d-47fa-b626-cc90dea64471"
MP_ACCESS_TOKEN = "APP_USR-1091359635861022-031115-4083f4ba9bf7da16cf148d67c053efdb-3243990562"
PRECO_POR_XML = 0.15

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
tarefas_download = {}

# ==========================================
# FUNÇÃO PARA SALVAR A VENDA NA NUVEM
# ==========================================
def salvar_venda(qtd, valor, metodo, email_cliente):
    try:
        db.collection('vendas').add({
            'quantidade_xml': qtd,
            'valor_total': valor,
            'metodo': metodo,
            'email': email_cliente,
            'data_compra': datetime.datetime.now()
        })
    except Exception as e:
        print(f"Erro ao gravar venda no Firestore: {e}")

# ==========================================
# ROTAS DE USUÁRIO (AGORA NO FIREBASE)
# ==========================================
@app.route('/api/registrar', methods=['POST'])
def registrar_usuario():
    dados = request.json
    try:
        users_ref = db.collection('usuarios')
        
        # Verifica se o e-mail já existe
        docs = users_ref.where('email', '==', dados['email']).stream()
        if len(list(docs)) > 0:
            return jsonify({"erro": "Este e-mail já está cadastrado!"}), 400
            
        # Grava o novo usuário na nuvem
        users_ref.add({
            'nome': dados['nome'],
            'email': dados['email'],
            'senha': dados['senha'],
            'data_criacao': datetime.datetime.now()
        })
        return jsonify({"sucesso": True, "mensagem": "Conta criada com sucesso!"})
    except Exception as e: 
        return jsonify({"erro": str(e)}), 500

@app.route('/api/login', methods=['POST'])
def fazer_login():
    dados = request.json
    try:
        users_ref = db.collection('usuarios')
        # Procura o usuário no Firebase
        docs = users_ref.where('email', '==', dados['email']).where('senha', '==', dados['senha']).stream()
        
        for doc in docs:
            usuario = doc.to_dict()
            return jsonify({"sucesso": True, "nome": usuario.get('nome')})
            
        return jsonify({"erro": "E-mail ou senha incorretos."}), 401
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ==========================================
# A SUA DASHBOARD: BUSCANDO OS DADOS REAIS
# ==========================================
@app.route('/api/admin/stats', methods=['GET'])
def get_stats():
    try:
        # Busca todas as vendas no Firebase
        vendas_docs = db.collection('vendas').stream()
        total_xmls = 0
        faturamento = 0.0
        
        for venda in vendas_docs:
            dados = venda.to_dict()
            total_xmls += dados.get('quantidade_xml', 0)
            faturamento += dados.get('valor_total', 0.0)
            
        # Conta quantos clientes existem
        clientes_ativos = sum(1 for _ in db.collection('usuarios').stream())
        
        return jsonify({
            "total_xmls": total_xmls, 
            "faturamento": faturamento, 
            "clientes_ativos": clientes_ativos
        })
    except Exception as e:
        print(f"Erro ao buscar stats: {e}")
        # Retorna zerado em caso de erro para não quebrar a tela
        return jsonify({"total_xmls": 0, "faturamento": 0.0, "clientes_ativos": 0})

# ==========================================
# ROTAS DE PAGAMENTO E CHECKOUT
# ==========================================
@app.route('/api/pagar-pix', methods=['POST'])
def gerar_pix():
    try:
        qtd = request.json.get('quantidade', 0)
        email_cliente = request.json.get('email', 'desconhecido') # Pega o email que o novo Frontend envia
        valor = float(qtd * PRECO_POR_XML)
        
        # Salva na nuvem antes de gerar o código
        salvar_venda(qtd, valor, "PIX", email_cliente) 
        
        res = sdk.payment().create({
            "transaction_amount": valor, 
            "description": f"Tax XML - {qtd} notas", 
            "payment_method_id": "pix", 
            "payer": {"email": "cliente@taxxml.com"}
        })["response"]
        return jsonify({
            "qr_code_base64": res["point_of_interaction"]["transaction_data"]["qr_code_base64"], 
            "payment_id": res["id"]
        })
    except Exception as e: return jsonify({"erro": str(e)}), 400

@app.route('/api/pagar-cartao', methods=['POST'])
def gerar_cartao():
    try:
        qtd = request.json.get('quantidade', 0)
        email_cliente = request.json.get('email', 'desconhecido')
        valor = float(qtd * PRECO_POR_XML)
        
        salvar_venda(qtd, valor, "CARTAO", email_cliente) 
        codigo_rastreio = str(uuid.uuid4())
        
        res = sdk.preference().create({
            "items": [{"title": f"Tax XML - {qtd} notas", "quantity": 1, "unit_price": valor, "currency_id": "BRL"}], 
            "payer": {"email": "cliente@taxxml.com"}, 
            "payment_methods": {"installments": 1}, 
            "external_reference": codigo_rastreio,
            "back_urls": {
                "success": "https://taxxml.com.br",
                "failure": "https://taxxml.com.br",
                "pending": "https://taxxml.com.br"
            },
            "auto_return": "approved"
        })["response"]
        
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
# MOTOR DE DOWNLOAD (BACKGROUND TASK - INTACTO)
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
    app.run(port=5000, debug=True)
