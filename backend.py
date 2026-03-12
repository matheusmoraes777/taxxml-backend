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

app = Flask(__name__)
CORS(app)

import firebase_admin
from firebase_admin import credentials, firestore

caminhos_possiveis = ["/etc/secrets/firebase-key.json", "firebase-key.json", "key.json"]
db = None
for caminho in caminhos_possiveis:
    if os.path.exists(caminho):
        try:
            cred = credentials.Certificate(caminho)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            print(f"🔥 Firebase conectado via: {caminho}")
            break
        except: pass

API_KEY_MEU_DANFE = "36da320b-1b2d-47fa-b626-cc90dea64471"
MP_ACCESS_TOKEN = "APP_USR-1091359635861022-031115-4083f4ba9bf7da16cf148d67c053efdb-3243990562"
PRECO_POR_XML = 0.08

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
tarefas_download = {}

# ==========================================
# ROTAS DE USUÁRIO E SALDO
# ==========================================
@app.route('/api/sync-user', methods=['POST'])
def sync_user():
    dados = request.json
    email = dados.get('email')
    nome = dados.get('nome', 'Usuário')
    if not db or not email: return jsonify({"erro": "Dados inválidos"}), 400
    user_ref = db.collection('usuarios').document(email)
    doc = user_ref.get()
    if not doc.exists:
        user_ref.set({'nome': nome, 'email': email, 'saldo': 0.0, 'data_criacao': datetime.datetime.now()})
        return jsonify({"sucesso": True, "saldo": 0.0, "nome": nome})
    return jsonify({"sucesso": True, "saldo": doc.to_dict().get('saldo', 0.0), "nome": doc.to_dict().get('nome')})

@app.route('/api/login', methods=['POST'])
def login():
    dados = request.json
    if not db: return jsonify({"erro": "DB Offline"}), 500
    doc = db.collection('usuarios').document(dados.get('email')).get()
    if doc.exists and doc.to_dict().get('senha') == dados.get('senha'):
        return jsonify({"sucesso": True, "nome": doc.to_dict().get('nome'), "saldo": doc.to_dict().get('saldo', 0.0)})
    return jsonify({"erro": "Credenciais incorretas"}), 401

@app.route('/api/registrar', methods=['POST'])
def registrar():
    dados = request.json
    if not db: return jsonify({"erro": "DB Offline"}), 500
    user_ref = db.collection('usuarios').document(dados.get('email'))
    if user_ref.get().exists: return jsonify({"erro": "E-mail já existe"}), 400
    user_ref.set({'nome': dados['nome'], 'email': dados.get('email'), 'senha': dados.get('senha'), 'saldo': 0.0, 'data': datetime.datetime.now()})
    return jsonify({"sucesso": True})

@app.route('/api/comprar-creditos', methods=['POST'])
def comprar_creditos():
    try:
        dados = request.json
        email = dados.get('email')
        valor = float(dados.get('valor', 0))
        if valor < 1: return jsonify({"erro": "Mínimo R$ 1,00"}), 400

        res = sdk.payment().create({
            "transaction_amount": valor, "description": "Recarga Tax XML",
            "payment_method_id": "pix", "payer": {"email": email}
        })["response"]
        
        if db:
            db.collection('pagamentos_pendentes').document(str(res["id"])).set({
                'email': email, 'valor': valor, 'status': 'pendente', 'data': datetime.datetime.now()
            })
        return jsonify({"qr_code_base64": res["point_of_interaction"]["transaction_data"]["qr_code_base64"], "payment_id": res["id"]})
    except Exception as e: return jsonify({"erro": str(e)}), 400

@app.route('/api/verificar-pagamento/<int:pay_id>', methods=['GET'])
def verificar_pagamento(pay_id):
    try:
        res = sdk.payment().get(pay_id)["response"]
        if res.get("status") == "approved":
            doc_ref = db.collection('pagamentos_pendentes').document(str(pay_id))
            doc = doc_ref.get()
            if doc.exists and doc.to_dict().get('status') == 'pendente':
                dados = doc.to_dict()
                user_ref = db.collection('usuarios').document(dados['email'])
                saldo_atual = user_ref.get().to_dict().get('saldo', 0.0)
                user_ref.update({'saldo': saldo_atual + dados['valor']})
                doc_ref.update({'status': 'concluido'})
                return jsonify({"pago": True, "novo_saldo": saldo_atual + dados['valor']})
            return jsonify({"pago": True, "mensagem": "Já processado"})
        return jsonify({"pago": False})
    except Exception: return jsonify({"erro": "erro"}), 500

# ==========================================
# O SEU MOTOR DE DOWNLOAD ORIGINAL
# ==========================================
def baixar_xml_original(session, chave):
    headers = { "Api-Key": API_KEY_MEU_DANFE, "Content-Type": "application/json" }
    url_get = f"https://api.meudanfe.com.br/v2/fd/get/xml/{chave}"
    url_add = f"https://api.meudanfe.com.br/v2/fd/add/{chave}"
    try:
        r = session.get(url_get, headers=headers, timeout=15)
        c = r.text.strip()
        xml = r.json().get('data') or r.json().get('xml') if c.startswith('{') else c if c.startswith('<') else None
        if xml and "<nfeProc" in xml: return True, chave, xml[xml.find("<"):].encode('utf-8')
        
        session.put(url_add, headers=headers, timeout=15)
        time.sleep(5)
        
        r = session.get(url_get, headers=headers, timeout=15)
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
    dados = request.json
    email = dados.get('email')
    chaves = dados.get('chaves', [])
    if not chaves or not email: return jsonify({"erro": "Dados incompletos"}), 400
    
    custo_total = len(chaves) * PRECO_POR_XML
    user_ref = db.collection('usuarios').document(email)
    saldo_atual = user_ref.get().to_dict().get('saldo', 0.0)
    
    if saldo_atual < custo_total: return jsonify({"erro": "Saldo insuficiente"}), 402
    
    # Desconta e Inicia
    novo_saldo = saldo_atual - custo_total
    user_ref.update({'saldo': novo_saldo})
    
    task_id = str(uuid.uuid4())
    tarefas_download[task_id] = {'processados': 0, 'total': len(chaves), 'concluido': False, 'zip_bytes': None}
    threading.Thread(target=processar_lote_bg, args=(task_id, chaves)).start()
    
    return jsonify({"task_id": task_id, "novo_saldo": novo_saldo})

@app.route('/api/progresso/<task_id>', methods=['GET'])
def ver_progresso(task_id):
    tarefa = tarefas_download.get(task_id)
    return jsonify(tarefa) if tarefa else ({"erro": "404"}, 404)

@app.route('/api/baixar-zip/<task_id>', methods=['GET'])
def baixar_zip(task_id):
    tarefa = tarefas_download.get(task_id)
    return send_file(io.BytesIO(tarefa['zip_bytes']), mimetype='application/zip', as_attachment=True, download_name='TaxXML.zip')

@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    if not db: return jsonify({"clientes": 0})
    return jsonify({"clientes": sum(1 for _ in db.collection('usuarios').stream())})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
