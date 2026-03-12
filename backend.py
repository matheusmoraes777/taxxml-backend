import os
import time
import uuid
import zipfile
import json
import threading
import datetime
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import mercadopago
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# SETUP: FLASK E FIREBASE
# ==========================================
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

# ==========================================
# SISTEMA ANTI-AMNÉSIA DO RENDER (PASTA FÍSICA)
# ==========================================
os.makedirs("tmp_tasks", exist_ok=True)

def atualizar_progresso(task_id, processados, total, concluido=False):
    """Salva o progresso num arquivo físico, assim nenhum Trabalhador do Render perde a memória"""
    estado = {"processados": processados, "total": total, "concluido": concluido}
    try:
        with open(f"tmp_tasks/{task_id}.json", "w") as f:
            json.dump(estado, f)
    except: pass

def ler_progresso(task_id):
    try:
        if os.path.exists(f"tmp_tasks/{task_id}.json"):
            with open(f"tmp_tasks/{task_id}.json", "r") as f:
                return json.load(f)
    except: pass
    return {"processados": 0, "total": 1, "concluido": False} # Nunca mais dá erro 404!

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
# O MOTOR DE DOWNLOAD À PROVA DE FALHAS
# ==========================================
def baixar_xml_seguro(chave):
    headers = { "Api-Key": API_KEY_MEU_DANFE, "Content-Type": "application/json" }
    url_get = f"https://api.meudanfe.com.br/v2/fd/get/xml/{chave}"
    url_add = f"https://api.meudanfe.com.br/v2/fd/add/{chave}"
    try:
        r1 = requests.get(url_get, headers=headers, timeout=12)
        c1 = r1.text.strip()
        xml = r1.json().get('data') or r1.json().get('xml') if c1.startswith('{') else c1 if c1.startswith('<') else None
        if xml and "<nfeProc" in xml: return True, chave, xml[xml.find("<"):].encode('utf-8')
        
        requests.put(url_add, headers=headers, timeout=12)
        time.sleep(4)
        
        r2 = requests.get(url_get, headers=headers, timeout=12)
        c2 = r2.text.strip()
        xml = r2.json().get('data') or r2.json().get('xml') if c2.startswith('{') else c2 if c2.startswith('<') else None
        if xml and "<nfeProc" in xml: return True, chave, xml[xml.find("<"):].encode('utf-8')
    except: pass
    return False, chave, None

def processar_lote_bg(task_id, chaves):
    total = len(chaves)
    processados = 0
    atualizar_progresso(task_id, processados, total, False)
    
    zip_path = f"tmp_tasks/{task_id}.zip"
    
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Usando max_workers=5 para evitar que o Meu Danfe bloqueie por excesso de velocidade
            with ThreadPoolExecutor(max_workers=5) as exe:
                futures = {exe.submit(baixar_xml_seguro, c): c for c in chaves}
                for future in as_completed(futures):
                    try:
                        ok, ch, xml_data = future.result()
                        if ok and xml_data:
                            zf.writestr(f"{ch}.xml", xml_data)
                    except: pass
                    processados += 1
                    atualizar_progresso(task_id, processados, total, False)
    except Exception as e:
        print(f"Erro Crítico Geral: {e}")
    finally:
        # Garante que a tela vai ser destravada
        atualizar_progresso(task_id, processados, total, True)

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
    atualizar_progresso(task_id, 0, len(chaves), False) # Cria o arquivo imediatamente
    
    threading.Thread(target=processar_lote_bg, args=(task_id, chaves)).start()
    
    return jsonify({"task_id": task_id, "novo_saldo": novo_saldo})

@app.route('/api/progresso/<task_id>', methods=['GET'])
def ver_progresso(task_id):
    estado = ler_progresso(task_id)
    return jsonify(estado)

@app.route('/api/baixar-zip/<task_id>', methods=['GET'])
def baixar_zip(task_id):
    caminho = f"tmp_tasks/{task_id}.zip"
    if os.path.exists(caminho):
        return send_file(caminho, mimetype='application/zip', as_attachment=True, download_name='TaxXML_Lote.zip')
    return jsonify({"erro": "Arquivo expirou ou não foi gerado"}), 404

@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    if not db: return jsonify({"clientes": 0})
    return jsonify({"clientes": sum(1 for _ in db.collection('usuarios').stream())})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
