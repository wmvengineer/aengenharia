import os
import time
import base64
import hashlib
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect
from flask_sqlalchemy import SQLAlchemy
import requests

app = Flask(__name__)

# Configurações do Banco de Dados SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///aengenharia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'chave_secreta_super_segura_2026')

# Configurações PagBank & Admin
PAGBANK_ENDPOINT = os.getenv('PAGBANK_ENDPOINT', 'https://api.pagseguro.com/orders') # Use sandbox se estiver testando
PAGBANK_TOKEN = os.getenv('PAGBANK_TOKEN', 'SEU_TOKEN_PAGBANK_AQUI')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'EngenhariaMaster@2026')

db = SQLAlchemy(app)

# MODELO DO BANCO DE DADOS
class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    categoria = db.Column(db.String(80), nullable=False)
    preco = db.Column(db.Float, nullable=False)
    imagem = db.Column(db.String(500), nullable=False)
    tipo = db.Column(db.String(20), default='download') # 'download' ou 'externo'
    arquivo_url = db.Column(db.String(500), nullable=True)
    url_externa = db.Column(db.String(500), nullable=True)
    descricao = db.Column(db.Text, nullable=False)
    ativo = db.Column(db.Boolean, default=True)

    def to_dict(self, is_admin=False):
        data = {
            'id': self.id,
            'titulo': self.titulo,
            'categoria': self.categoria,
            'preco': self.preco,
            'imagem': self.imagem,
            'tipo': self.tipo,
            'url_externa': self.url_externa if self.tipo == 'externo' else '',
            'descricao': self.descricao,
            'ativo': self.ativo
        }
        # A URL do arquivo privado NUNCA é enviada para o público; só para o Admin
        if is_admin:
            data['arquivo_url'] = self.arquivo_url
        return data

# CRIAÇÃO DAS TABELAS E PRODUTOS INICIAIS
with app.app_context():
    db.create_all()
    if Produto.query.count() == 0:
        p1 = Produto(
            titulo="Planilha Automatizada de Vigas e Pilares (NBR 6118)",
            categoria="Estruturas & Cálculo",
            preco=89.90,
            tipo="download",
            arquivo_url="https://raw.githubusercontent.com/example/demo/main/vigas-v1.zip",
            imagem="https://images.unsplash.com/photo-1503387762-592deb58ef4e?auto=format&fit=crop&w=600&q=80",
            descricao="Cálculo de armaduras longitudinais e transversais com memória de cálculo em PDF instantânea.",
            ativo=True
        )
        p2 = Produto(
            titulo="Curso Master BIM & Compatibilização de Projetos",
            categoria="Arquitetura & BIM",
            preco=197.00,
            tipo="externo",
            url_externa="https://hotmart.com",
            imagem="https://images.unsplash.com/photo-1554224155-8d04cb21cd6c?auto=format&fit=crop&w=600&q=80",
            descricao="Acesso à área de membros exclusiva com suporte e atualizações.",
            ativo=True
        )
        db.session.add_all([p1, p2])
        db.session.commit()

# ROTAS PÚBLICAS
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/produtos', methods=['GET'])
def listar_produtos():
    # Usuários comuns só enxergam produtos ATIVOS
    prods = Produto.query.filter_by(ativo=True).all()
    return jsonify([p.to_dict() for p in prods])

# ROTAS ADMINISTRATIVAS
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json or {}
    if data.get('password') == ADMIN_PASSWORD:
        token = base64.b64encode(f"ADMIN_AUTH_{int(time.time())}".encode()).decode()
        return jsonify({'autorizado': True, 'token': token})
    return jsonify({'autorizado': False, 'error': 'Senha incorreta!'}), 401

@app.route('/api/admin/produtos', methods=['GET'])
def admin_listar_produtos():
    # O Admin vê TODOS os produtos (Ativos e Inativos) e os links protegidos
    prods = Produto.query.order_by(Produto.id.desc()).all()
    return jsonify([p.to_dict(is_admin=True) for p in prods])

@app.route('/api/admin/produtos', methods=['POST'])
def admin_salvar_produto():
    data = request.json or {}
    prod_id = data.get('id')

    if prod_id:
        prod = Produto.query.get(prod_id)
        if not prod:
            return jsonify({'error': 'Produto não encontrado'}), 404
    else:
        prod = Produto()

    prod.titulo = data.get('titulo')
    prod.categoria = data.get('categoria')
    prod.preco = float(data.get('preco', 0))
    prod.imagem = data.get('imagem')
    prod.tipo = data.get('tipo', 'download')
    prod.arquivo_url = data.get('arquivo_url') if prod.tipo == 'download' else ''
    prod.url_externa = data.get('url_externa') if prod.tipo == 'externo' else ''
    prod.descricao = data.get('descricao')
    prod.ativo = bool(data.get('ativo', True))

    if not prod_id:
        db.session.add(prod)

    db.session.commit()
    return jsonify({'ok': True, 'produto': prod.to_dict(is_admin=True)})

@app.route('/api/admin/produtos/<int:prod_id>', methods=['DELETE'])
def admin_deletar_produto(prod_id):
    prod = Produto.query.get(prod_id)
    if prod:
        db.session.delete(prod)
        db.session.commit()
        return jsonify({'ok': True})
    return jsonify({'error': 'Item não encontrado'}), 404

# INTEGRAÇÃO PAGBANK OFICIAL EM PYTHON
@app.route('/api/pagbank/criar-pix', methods=['POST'])
def criar_pix():
    try:
        body = request.json or {}
        produto_id = body.get('produtoId')
        cliente = body.get('cliente', {})

        prod = Produto.query.get(produto_id)
        if not prod or not prod.ativo:
            return jsonify({'error': 'Produto indisponível'}), 400

        cpf_limpo = "".join([c for c in cliente.get('cpf', '') if c.isdigit()])
        if len(cpf_limpo) != 11:
            return jsonify({'error': 'O CPF deve ter 11 dígitos numéricos.'}), 400

        valor_centavos = int(round(prod.preco * 100))
        expira_em = (datetime.utcnow() + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%S+00:00')

        payload = {
            "reference_id": f"ENG_{prod.id}_{int(time.time())}",
            "customer": {
                "name": cliente.get('nome', '').strip(),
                "email": cliente.get('email', '').strip(),
                "tax_id": cpf_limpo
            },
            "items": [{
                "reference_id": str(prod.id),
                "name": prod.titulo[:60],
                "quantity": 1,
                "unit_amount": valor_centavos
            }],
            "qr_codes": [{
                "amount": {"value": valor_centavos},
                "expiration_date": expira_em
            }]
        }

        headers = {
            "Authorization": f"Bearer {PAGBANK_TOKEN}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }

        res = requests.post(PAGBANK_ENDPOINT, json=payload, headers=headers, timeout=15)
        data = res.json()

        if res.status_code not in [200, 201]:
            detalhes = "; ".join([e.get('description', '') for e in data.get('error_messages', [])]) if 'error_messages' in data else str(data)
            return jsonify({'error': f'Erro PagBank: {detalhes}'}), 400

        qr_info = data.get('qr_codes', [{}])[0]
        links = qr_info.get('links', [])
        img_url = next((l['href'] for l in links if l.get('media') == 'image/png'), '')

        return jsonify({
            'orderId': data.get('id'),
            'copiaECola': qr_info.get('text'),
            'qrCodeImg': img_url,
            'produtoId': prod.id
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/pagbank/verificar-pix', methods=['GET'])
def verificar_pix():
    order_id = request.args.get('orderId')
    produto_id = request.args.get('produtoId')

    try:
        url_check = f"{PAGBANK_ENDPOINT}/{order_id}"
        headers = {"Authorization": f"Bearer {PAGBANK_TOKEN}", "accept": "application/json"}
        res = requests.get(url_check, headers=headers, timeout=10)
        data = res.json()

        pago = any(c.get('status') == 'PAID' for c in data.get('charges', [])) or \
               'PAID' in data.get('qr_codes', [{}])[0].get('arrangements', [])

        if pago:
            prod = Produto.query.get(produto_id)
            if not prod:
                return jsonify({'error': 'Produto não existe'}), 404

            # GERA TOKEN CRIPTOGRAFADO DE USO ÚNICO (VÁLIDO POR 24H)
            expira_timestamp = int(time.time()) + 86400
            assinatura = hashlib.sha256(f"{order_id}|{prod.arquivo_url}|{expira_timestamp}|{app.config['SECRET_KEY']}".encode()).hexdigest()

            token_download = base64.b64encode(json.dumps({
                'prod_id': prod.id,
                'exp': expira_timestamp,
                'sig': assinatura
            }).encode()).decode()

            return jsonify({'status': 'PAID', 'downloadToken': token_download})

        return jsonify({'status': 'WAITING'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<token>', methods=['GET'])
def download_seguro(token):
    try:
        dados = json.loads(base64.b64decode(token).decode())
        if time.time() > dados.get('exp', 0):
            return "Este link de download expirou.", 403

        prod = Produto.query.get(dados.get('prod_id'))
        if not prod or not prod.arquivo_url:
            return "Arquivo não encontrado.", 404

        # Redireciona para o arquivo de forma segura em nova aba
        return redirect(prod.arquivo_url)
    except Exception:
        return "Acesso inválido ou link violado.", 403

if __name__ == '__main__':
    app.run(debug=True, port=5000)