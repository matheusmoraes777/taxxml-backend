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
# CONFIGURAÇÃO INICIAL E FIREBASE
# ==========================================
app = Flask(__name__)
CORS(app)

import firebase_admin
from firebase_admin import credentials, firestore

# Busca a chave no Render ou Localmente
caminhos_chave = ["/etc/secrets/firebase-key.json", "firebase-key.json"]
db = None
for caminho in caminhos_chave:
    if os.path.exists(caminho):
        try:
            cred = credentials.Certificate(caminho)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            print(f"🔥 Firebase Conectado via: {caminho}")
            break
        except: pass

# ==========================================
# CHAVES DE API
# ==========================================
API_KEY_MEU_DANFE = "36da320b-1b2d-47fa-b626-cc90dea64471"
MP_ACCESS_TOKEN = "APP_USR-1091359635861022-031115-4083f4ba9bf7da16cf148d67c053efdb-3243990562"
PRECO_POR_XML = 0.15

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
tarefas_download = {} # Armazena progresso dos zips em memória

# ==========================================
# ROTAS DE USUÁRIO (LOGIN / REGISTRO)
# ==========================================
@app.route('/api/registrar', methods=['POST'])
def registrar():
    if not db: return jsonify({"erro": "Banco offline"}), 500
    dados = request.json
    try:
        users_ref = db.collection('usuarios')
        if len(list(users_ref.where('email', '==', dados['email']).stream())) > 0:
            return jsonify({"erro": "E-mail já cadastrado"}), 400
        users_ref.add({
            'nome': dados['nome'], 'email': dados['email'], 
            'senha': dados['senha'], 'data': datetime.datetime.now()
        })
        return jsonify({"sucesso": True})
    except Exception as e: return jsonify({"erro": str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    if not db: return jsonify({"erro": "Banco offline"}), 500
    dados = request.json
    docs = db.collection('usuarios').where('email', '==', dados['email']).where('senha', '==', dados['senha']).stream()
    for doc in docs: return jsonify({"sucesso": True, "nome": doc.to_dict().get('nome')})
    return jsonify({"erro": "Dados incorretos"}), 401

# ==========================================
# ROTA ADMIN (DASHBOARD REAL)
# ==========================================
@app.route('/api/admin/stats', methods=['GET'])
def get_stats():
    if not db: return jsonify({"total_xmls": 0, "faturamento": 0, "clientes_ativos": 0})
    try:
        vendas = db.collection('vendas').stream()
        t_xml = 0
        fat = 0.0
        for v in vendas:
            d = v.to_dict()
            t_xml += d.get('quantidade_xml', 0)
            fat += d.get('valor_total', 0.0)
        u_count = sum(1 for _ in db.collection('usuarios').stream())
        return jsonify({"total_xmls": t_xml, "faturamento": fat, "clientes_ativos": u_count})
    except: return jsonify({"erro": "erro stats"}), 500

# ==========================================
# ROTAS DE PAGAMENTO (MERCADO PAGO)
# ==========================================
@app.route('/api/pagar-pix', methods=['POST'])
def gerar_pix():
    try:
        dados = request.json
        qtd = int(dados.get('quantidade', 0))
        email = dados.get('email', 'cliente@taxxml.com')
        valor = float(qtd * PRECO_POR_XML)

        res = sdk.payment().create({
            "transaction_amount": valor,
            "description": f"Download {qtd} XMLs - TaxXML",
            "payment_method_id": "pix",
            "payer": {"email": email if "@" in email else "comprador@taxxml.com"}
        })["response"]

        # Salva log da venda no Firebase (Silencioso)
        if db:
            try:
                db.collection('vendas').add({
                    'quantidade_xml': qtd, 'valor_total': valor, 
                    'email': email, 'metodo': 'PIX', 'data_compra': datetime.datetime.now()
                })
            except: pass

        return jsonify({"qr_code_base64": res["point_of_interaction"]["transaction_data"]["qr_code_base64"], "payment_id": res["id"]})
    except Exception as e: return jsonify({"erro": str(e)}), 400

@app.route('/api/status-pix/<int:pay_id>', methods=['GET'])
def status_pix(pay_id):
    res = sdk.payment().get(pay_id)
    return jsonify({"pago": res["response"].get("status") == "approved"})

# ==========================================
# MOTOR DE DOWNLOAD (THREADS EM LOTE)
# ==========================================
def baixar_xml_original(session, chave):
    headers = { "Api-Key": API_KEY_MEU_DANFE, "Content-Type": "application/json" }
    try:
        r = session.get(f"https://api.meudanfe.com.br/v2/fd/get/xml/{chave}", headers=headers, timeout=12)
        c = r.text.strip()
        xml = r.json().get('data') or r.json().get('xml') if c.startswith('{') else c if c.startswith('<') else None
        if xml and "<nfeProc" in xml: return True, chave, xml[xml.find("<"):].encode('utf-8')
        
        session.put(f"https://api.meudanfe.com.br/v2/fd/add/{chave}", headers=headers, timeout=12)
        time.sleep(5)
        
        r = session.get(f"https://api.meudanfe.com.br/v2/fd/get/xml/{chave}", headers=headers, timeout=12)
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
    task_id = str(uuid.uuid4())
    tarefas_download[task_id] = {'processados': 0, 'total': len(chaves), 'concluido': False, 'zip_bytes': None}
    threading.Thread(target=processar_lote_bg, args=(task_id, chaves)).start()
    return jsonify({"task_id": task_id})

@app.route('/api/progresso/<task_id>', methods=['GET'])
def ver_progresso(task_id):
    t = tarefas_download.get(task_id)
    if not t: return jsonify({"erro": "404"}), 404
    return jsonify({"processados": t['processados'], "total": t['total'], "concluido": t['concluido']})

@app.route('/api/baixar-zip/<task_id>', methods=['GET'])
def baixar_zip(task_id):
    t = tarefas_download.get(task_id)
    if not t or not t['concluido']: return jsonify({"erro": "Aguarde"}), 400
    return send_file(io.BytesIO(t['zip_bytes']), mimetype='application/zip', as_attachment=True, download_name='TaxXML_Lote.zip')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
