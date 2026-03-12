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
# FIREBASE - CONFIGURAÇÃO (SEM TRAVAR)
# ==========================================
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
CORS(app)

# Caminhos da chave (Render e Local)
caminhos_possiveis = ["/etc/secrets/firebase-key.json", "firebase-key.json"]
db = None

for caminho in caminhos_possiveis:
    if os.path.exists(caminho):
        try:
            cred = credentials.Certificate(caminho)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            print(f"🔥 Firebase conectado com sucesso: {caminho}")
            break
        except: pass

# ==========================================
# CONFIGURAÇÕES MERCADO PAGO E MEU DANFE
# ==========================================
API_KEY_MEU_DANFE = "36da320b-1b2d-47fa-b626-cc90dea64471"
MP_ACCESS_TOKEN = "APP_USR-1091359635861022-031115-4083f4ba9bf7da16cf148d67c053efdb-3243990562"
PRECO_POR_XML = 0.15

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
tarefas_download = {}

def salvar_venda_silencioso(qtd, valor, metodo, email_cliente):
    """Salva no banco sem interromper o fluxo principal se falhar"""
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
            print(f"⚠️ Log Firebase falhou: {e}")

# ==========================================
# ROTAS DE PAGAMENTO (REVISADAS)
# ==========================================

@app.route('/api/pagar-pix', methods=['POST'])
def gerar_pix():
    try:
        dados = request.json
        qtd = int(dados.get('quantidade', 0))
        email = dados.get('email', 'cliente@taxxml.com')
        valor = round(float(qtd * PRECO_POR_XML), 2)

        if valor < 0.50: # Valor mínimo para evitar erros no MP
            return jsonify({"erro": "Valor muito baixo para gerar PIX"}), 400

        res = sdk.payment().create({
            "transaction_amount": valor,
            "description": f"Tax XML - {qtd} notas",
            "payment_method_id": "pix",
            "payer": {"email": email if "@" in email else "comprador@taxxml.com"}
        })

        if res["status"] == 201 or res["status"] == 200:
            salvar_venda_silencioso(qtd, valor, "PIX", email)
            return jsonify({
                "qr_code_base64": res["response"]["point_of_interaction"]["transaction_data"]["qr_code_base64"],
                "payment_id": res["response"]["id"]
            })
        return jsonify({"erro": "Mercado Pago recusou a criação do PIX"}), 400
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/pagar-cartao', methods=['POST'])
def gerar_cartao():
    try:
        dados = request.json
        qtd = int(dados.get('quantidade', 0))
        email = dados.get('email', 'cliente@taxxml.com')
        valor = round(float(qtd * PRECO_POR_XML), 2)

        res = sdk.preference().create({
            "items": [{"title": f"Lote {qtd} XMLs", "quantity": 1, "unit_price": valor, "currency_id": "BRL"}],
            "payer": {"email": email if "@" in email else "comprador@taxxml.com"},
            "auto_return": "approved",
            "back_urls": {"success": "https://taxxml.com.br", "failure": "https://taxxml.com.br"}
        })

        if res["status"] == 201 or res["status"] == 200:
            salvar_venda_silencioso(qtd, valor, "CARTAO", email)
            return jsonify({"checkout_url": res["response"]["init_point"]})
        return jsonify({"erro": "Erro ao criar preferência de cartão"}), 400
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ==========================================
# OUTRAS ROTAS (LOGIN, ADMIN, DOWNLOAD)
# ==========================================

@app.route('/api/admin/stats', methods=['GET'])
def get_stats():
    if not db: return jsonify({"total_xmls": 0, "faturamento": 0, "clientes_ativos": 0})
    try:
        vendas = db.collection('vendas').stream()
        total_xmls = 0
        faturamento = 0.0
        for v in vendas:
            d = v.to_dict()
            total_xmls += d.get('quantidade_xml', 0)
            faturamento += d.get('valor_total', 0.0)
        clientes = sum(1 for _ in db.collection('usuarios').stream())
        return jsonify({"total_xmls": total_xmls, "faturamento": faturamento, "clientes_ativos": clientes})
    except: return jsonify({"erro": "stats fail"}), 500

@app.route('/api/registrar', methods=['POST'])
def registrar():
    dados = request.json
    if not db: return jsonify({"erro": "DB Offline"}), 500
    db.collection('usuarios').add({'nome': dados['nome'], 'email': dados['email'], 'senha': dados['senha'], 'data_criacao': datetime.datetime.now()})
    return jsonify({"sucesso": True})

@app.route('/api/login', methods=['POST'])
def login():
    dados = request.json
    docs = db.collection('usuarios').where('email', '==', dados['email']).where('senha', '==', dados['senha']).stream()
    for doc in docs: return jsonify({"sucesso": True, "nome": doc.to_dict().get('nome')})
    return jsonify({"erro": "Incorreto"}), 401

@app.route('/api/iniciar-download', methods=['POST'])
def iniciar_download():
    chaves = request.json.get('chaves', [])
    task_id = str(uuid.uuid4())
    tarefas_download[task_id] = {'processados': 0, 'total': len(chaves), 'concluido': False, 'zip_bytes': None}
    # Aqui entraria a lógica de Thread do processar_lote_bg (mesma de antes)
    return jsonify({"task_id": task_id})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
