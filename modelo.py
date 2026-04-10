from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import mercadopago

# --- CONFIGURAÇÃO DO MERCADO PAGO ---
mp_access_token = "APP_USR-3737362852835395-093010-3d28d03d695b0bc3ea1203d69edff8a9-820609374"
sdk = mercadopago.SDK(mp_access_token)

# 1. CONFIGURAÇÃO DO BANCO DE DADOS
SQLALCHEMY_DATABASE_URL = "sqlite:///./saas.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. TABELAS DO BANCO DE DADOS
class TenantDB(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, index=True)
    nome_negocio = Column(String, index=True)
    dono = Column(String)
    senha_dono = Column(String)
    telefone_whatsapp = Column(String, default="") 
    hora_abertura = Column(String, default="09:00")
    hora_fechamento = Column(String, default="18:00")
    dias_funcionamento = Column(String, default="0,1,2,3,4,5")
    intervalo_agenda = Column(Integer, default=30)

class ProfessionalDB(Base):
    __tablename__ = "professionals"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    nome = Column(String)
    senha = Column(String)

class ServiceDB(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    nome_servico = Column(String)
    tipo_preco = Column(String)
    preco_base = Column(Float)
    max_deposito_pct = Column(Float, default=30.0)
    duracao_minutos = Column(Integer, default=30)

class ServiceProfessionalLink(Base):
    __tablename__ = "service_professional_link"
    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id"))
    professional_id = Column(Integer, ForeignKey("professionals.id"))

class BookingDB(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    service_id = Column(Integer, ForeignKey("services.id"))
    professional_id = Column(Integer, ForeignKey("professionals.id"))
    nome_cliente = Column(String)
    telefone_cliente = Column(String, default="") 
    data_hora_inicio = Column(DateTime)
    data_hora_fim = Column(DateTime)
    status_pagamento = Column(String, default="PENDENTE")
    valor_total = Column(Float)
    valor_sinal = Column(Float)
    codigo_pix = Column(String)

Base.metadata.create_all(bind=engine)

# 3. MODELOS DE ENTRADA
class TenantCreate(BaseModel):
    nome_negocio: str
    dono: str
    senha_dono: str
    telefone_whatsapp: Optional[str] = ""
    hora_abertura: str = "09:00"
    hora_fechamento: str = "18:00"
    dias_funcionamento: str = "0,1,2,3,4,5"
    intervalo_agenda: int = 30

class ConfiguracoesRequest(BaseModel):
    telefone_whatsapp: str
    hora_abertura: str
    hora_fechamento: str
    dias_funcionamento: str

class ProfessionalCreate(BaseModel):
    nome: str
    senha: str

class ServiceCreate(BaseModel):
    nome_servico: str
    tipo_preco: str
    preco_base: float
    max_deposito_pct: float = 30.0
    duracao_minutos: int = 30
    profissionais_ids: List[int] = []

class BookingRequest(BaseModel):
    service_id: int
    professional_id: Optional[int] = None
    client_name: str
    telefone_cliente: str 
    data_hora: datetime
    deposit_percentage: float
    negotiated_price: Optional[float] = None

class ManualBookingRequest(BaseModel): 
    service_id: int
    professional_id: int
    client_name: str
    telefone_cliente: Optional[str] = "" 
    data_hora: datetime

class LoginRequest(BaseModel):
    tipo_acesso: str
    prof_id: Optional[int] = None
    senha: str

# 4. INICIANDO O SERVIDOR E ROTAS
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(title="SaaS de Agendamento")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# --- LOGIN E NEGÓCIO ---
@app.post("/negocios/{tenant_id}/login/")
def fazer_login(tenant_id: int, req: LoginRequest, db: Session = Depends(get_db)):
    if req.tipo_acesso == "dono":
        negocio = db.query(TenantDB).filter(TenantDB.id == tenant_id).first()
        if not negocio or negocio.senha_dono != req.senha: raise HTTPException(status_code=401, detail="Senha incorreta")
        return {"mensagem": "Login aprovado", "acesso": "dono"}
    else:
        prof = db.query(ProfessionalDB).filter(ProfessionalDB.id == req.prof_id, ProfessionalDB.tenant_id == tenant_id).first()
        if not prof or prof.senha != req.senha: raise HTTPException(status_code=401, detail="Senha incorreta")
        return {"mensagem": "Login aprovado", "acesso": "profissional"}

@app.post("/negocios/")
def criar_negocio(tenant: TenantCreate, db: Session = Depends(get_db)):
    novo = TenantDB(**tenant.dict())
    db.add(novo)
    db.commit()
    return {"id_negocio": novo.id, "nome_negocio": novo.nome_negocio}

@app.get("/negocios/{tenant_id}")
def obter_negocio(tenant_id: int, db: Session = Depends(get_db)):
    negocio = db.query(TenantDB).filter(TenantDB.id == tenant_id).first()
    if not negocio: raise HTTPException(status_code=404)
    return negocio

@app.put("/negocios/{tenant_id}/configuracoes/")
def atualizar_configuracoes(tenant_id: int, config: ConfiguracoesRequest, db: Session = Depends(get_db)):
    negocio = db.query(TenantDB).filter(TenantDB.id == tenant_id).first()
    if negocio:
        negocio.telefone_whatsapp = config.telefone_whatsapp
        negocio.hora_abertura = config.hora_abertura
        negocio.hora_fechamento = config.hora_fechamento
        negocio.dias_funcionamento = config.dias_funcionamento
        db.commit()
    return {"mensagem": "Configurações atualizadas"}

# --- PROFISSIONAIS E SERVIÇOS ---
@app.post("/negocios/{tenant_id}/profissionais/")
def criar_profissional(tenant_id: int, prof: ProfessionalCreate, db: Session = Depends(get_db)):
    novo = ProfessionalDB(tenant_id=tenant_id, **prof.dict())
    db.add(novo)
    db.commit()
    return {"id_profissional": novo.id, "nome": novo.nome}

@app.get("/negocios/{tenant_id}/profissionais/")
def listar_profissionais(tenant_id: int, db: Session = Depends(get_db)):
    profs = db.query(ProfessionalDB).filter(ProfessionalDB.tenant_id == tenant_id).all()
    return {"profissionais": [{"id": p.id, "nome": p.nome} for p in profs]}

@app.put("/negocios/{tenant_id}/profissionais/{prof_id}")
def editar_profissional(tenant_id: int, prof_id: int, prof: ProfessionalCreate, db: Session = Depends(get_db)):
    db_prof = db.query(ProfessionalDB).filter(ProfessionalDB.id == prof_id, ProfessionalDB.tenant_id == tenant_id).first()
    if db_prof:
        db_prof.nome = prof.nome
        if prof.senha: db_prof.senha = prof.senha
        db.commit()
    return {"mensagem": "Atualizado"}

@app.delete("/negocios/{tenant_id}/profissionais/{prof_id}")
def deletar_profissional(tenant_id: int, prof_id: int, db: Session = Depends(get_db)):
    prof = db.query(ProfessionalDB).filter(ProfessionalDB.id == prof_id, ProfessionalDB.tenant_id == tenant_id).first()
    if prof:
        db.delete(prof)
        db.commit()
    return {"mensagem": "Removido"}

@app.post("/negocios/{tenant_id}/servicos/")
def criar_servico(tenant_id: int, servico: ServiceCreate, db: Session = Depends(get_db)):
    novo = ServiceDB(tenant_id=tenant_id, nome_servico=servico.nome_servico, tipo_preco=servico.tipo_preco, preco_base=servico.preco_base, max_deposito_pct=servico.max_deposito_pct, duracao_minutos=servico.duracao_minutos)
    db.add(novo)
    db.commit()
    db.refresh(novo)
    for prof_id in servico.profissionais_ids:
        db.add(ServiceProfessionalLink(service_id=novo.id, professional_id=prof_id))
    db.commit()
    return {"id_servico": novo.id}

@app.get("/negocios/{tenant_id}/servicos/")
def listar_servicos(tenant_id: int, db: Session = Depends(get_db)):
    servicos = db.query(ServiceDB).filter(ServiceDB.tenant_id == tenant_id).all()
    resultado = []
    for s in servicos:
        links = db.query(ServiceProfessionalLink).filter(ServiceProfessionalLink.service_id == s.id).all()
        prof_ids = [link.professional_id for link in links]
        profs = db.query(ProfessionalDB).filter(ProfessionalDB.id.in_(prof_ids)).all()
        resultado.append({"id": s.id, "nome_servico": s.nome_servico, "preco_base": s.preco_base, "duracao_minutos": s.duracao_minutos, "max_deposito_pct": s.max_deposito_pct, "profissionais_nomes": [p.nome for p in profs], "profissionais_ids": prof_ids, "profissionais_info": [{"id": p.id, "nome": p.nome} for p in profs]})
    return {"servicos": resultado}

@app.put("/negocios/{tenant_id}/servicos/{servico_id}")
def editar_servico(tenant_id: int, servico_id: int, servico: ServiceCreate, db: Session = Depends(get_db)):
    db_servico = db.query(ServiceDB).filter(ServiceDB.id == servico_id, ServiceDB.tenant_id == tenant_id).first()
    if db_servico:
        db_servico.nome_servico = servico.nome_servico; db_servico.preco_base = servico.preco_base; db_servico.duracao_minutos = servico.duracao_minutos; db_servico.max_deposito_pct = servico.max_deposito_pct
        db.query(ServiceProfessionalLink).filter(ServiceProfessionalLink.service_id == servico_id).delete()
        for prof_id in servico.profissionais_ids: db.add(ServiceProfessionalLink(service_id=servico_id, professional_id=prof_id))
        db.commit()
    return {"mensagem": "Atualizado"}

@app.delete("/negocios/{tenant_id}/servicos/{servico_id}")
def deletar_servico(tenant_id: int, servico_id: int, db: Session = Depends(get_db)):
    servico = db.query(ServiceDB).filter(ServiceDB.id == servico_id, ServiceDB.tenant_id == tenant_id).first()
    if servico:
        db.query(ServiceProfessionalLink).filter(ServiceProfessionalLink.service_id == servico_id).delete()
        db.delete(servico)
        db.commit()
    return {"mensagem": "Removido"}

# --- AGENDA E HORÁRIOS ---
@app.get("/negocios/{tenant_id}/horarios-disponiveis/")
def buscar_horarios(tenant_id: int, data: str, service_id: int, professional_id: Optional[int] = None, db: Session = Depends(get_db)):
    negocio = db.query(TenantDB).filter(TenantDB.id == tenant_id).first()
    servico = db.query(ServiceDB).filter(ServiceDB.id == service_id).first()
    
    if not negocio or not servico: return {"data": data, "horarios_disponiveis": []}

    data_inicio = datetime.strptime(f"{data} 00:00", "%Y-%m-%d %H:%M")
    
    dia_semana = str(data_inicio.weekday())
    dias_permitidos = negocio.dias_funcionamento.split(",") if negocio.dias_funcionamento else []
    if dia_semana not in dias_permitidos:
        return {"data": data, "horarios_disponiveis": []}

    links = db.query(ServiceProfessionalLink).filter(ServiceProfessionalLink.service_id == service_id).all()
    prof_ids_habilitados = [link.professional_id for link in links]
    
    if professional_id:
        if professional_id not in prof_ids_habilitados: return {"data": data, "horarios_disponiveis": []}
        prof_ids_habilitados = [professional_id]
    
    profissionais = db.query(ProfessionalDB).filter(ProfessionalDB.tenant_id == tenant_id, ProfessionalDB.id.in_(prof_ids_habilitados)).all()
    if not profissionais: return {"data": data, "horarios_disponiveis": []}

    data_fim = datetime.strptime(f"{data} 23:59", "%Y-%m-%d %H:%M")
    horario_abertura = datetime.strptime(f"{data} {negocio.hora_abertura}", "%Y-%m-%d %H:%M")
    horario_fechamento = datetime.strptime(f"{data} {negocio.hora_fechamento}", "%Y-%m-%d %H:%M")
    
    # Arrumando o relógio de Londres para o Brasil (UTC-3)
    agora = datetime.utcnow() - timedelta(hours=3)
    
    horarios_livres_set = set()
    
    for prof in profissionais:
        reservas_prof = db.query(BookingDB).filter(BookingDB.tenant_id == tenant_id, BookingDB.professional_id == prof.id, BookingDB.data_hora_inicio >= data_inicio, BookingDB.data_hora_inicio <= data_fim).order_by(BookingDB.data_hora_inicio.asc()).all()
        blocos_livres = []
        tempo_atual = horario_abertura
        
        for reserva in reservas_prof:
            if tempo_atual < reserva.data_hora_inicio: blocos_livres.append((tempo_atual, reserva.data_hora_inicio))
            tempo_atual = max(tempo_atual, reserva.data_hora_fim)
            
        if tempo_atual < horario_fechamento: blocos_livres.append((tempo_atual, horario_fechamento))
            
        for inicio_bloco, fim_bloco in blocos_livres:
            slot_atual = inicio_bloco
            while slot_atual + timedelta(minutes=servico.duracao_minutos) <= fim_bloco:
                if slot_atual > agora: horarios_livres_set.add(slot_atual.strftime("%H:%M"))
                slot_atual += timedelta(minutes=servico.duracao_minutos)
                
    return {"data": data, "horarios_disponiveis": sorted(list(horarios_livres_set))}

# 🚀 ROTA ATUALIZADA: GERAR PIX REAL NO MERCADO PAGO (COM TRATAMENTO DE ERRO SEGURO E RETORNO DE ID) 🚀
@app.post("/gerar-pix-reserva/")
def criar_reserva(booking: BookingRequest, db: Session = Depends(get_db)):
    # 1. CORREÇÃO DO FUSO HORÁRIO
    agora_brasil = datetime.utcnow() - timedelta(hours=3)
    if booking.data_hora < agora_brasil - timedelta(minutes=15):
        raise HTTPException(status_code=400, detail="Data ou horário no passado.")

    servico = db.query(ServiceDB).filter(ServiceDB.id == booking.service_id).first()
    hora_fim = booking.data_hora + timedelta(minutes=servico.duracao_minutos)
    
    profissionais = db.query(ProfessionalDB).filter(ProfessionalDB.tenant_id == servico.tenant_id).all()
    prof_escolhido = booking.professional_id if booking.professional_id else profissionais[0].id

    final_price = booking.negotiated_price if booking.negotiated_price else servico.preco_base
    deposit_amount = round(final_price * (servico.max_deposito_pct / 100), 2)
    
    # SALVA A RESERVA PRIMEIRO
    nova_reserva = BookingDB(
        tenant_id=servico.tenant_id, service_id=servico.id, professional_id=prof_escolhido, 
        nome_cliente=booking.client_name, telefone_cliente=booking.telefone_cliente, 
        data_hora_inicio=booking.data_hora, data_hora_fim=hora_fim, 
        status_pagamento="PENDENTE", valor_total=final_price, valor_sinal=deposit_amount, 
        codigo_pix="GERANDO..." 
    )
    db.add(nova_reserva)
    db.commit()
    db.refresh(nova_reserva)
    
    # 2. CORREÇÃO DO TELEFONE E INCLUSÃO DE CPF GENÉRICO
    telefone_limpo = "".join(filter(str.isdigit, booking.telefone_cliente)) if booking.telefone_cliente else "anonimo"
    email_falso = f"cliente_{telefone_limpo}@teste.com"

    payment_data = {
        "transaction_amount": round(deposit_amount, 2), # Arredondando para evitar o erro de centavos
        "description": f"Sinal Reserva - {servico.nome_servico}",
        "payment_method_id": "pix",
        "external_reference": str(nova_reserva.id),
        
        # 🚀 A CARTADA MESTRE: Forçando o Mercado Pago a usar essa URL para avisar do pagamento!
        "notification_url": "https://saas-agendamento-backend.onrender.com/webhook/mercadopago/",
        
        "payer": {
            "email": email_falso,
            "first_name": booking.client_name,
            "identification": {
                "type": "CPF",
                "number": "19119119100"
            }
        }
    }

    try:
        payment_response = sdk.payment().create(payment_data)
        payment = payment_response.get("response", {})
        
        if "point_of_interaction" not in payment:
            erro_mp = payment.get("message", "Erro desconhecido")
            detalhes = payment.get("cause", [])
            if detalhes and len(detalhes) > 0:
                erro_mp += f" - Detalhe: {detalhes[0].get('description', '')}"
            raise Exception(f"Motivo MP: {erro_mp}")
            
        pix_code_real = payment["point_of_interaction"]["transaction_data"]["qr_code"]
        
        # 🖼️ PEGANDO A IMAGEM DO QR CODE AQUI:
        qr_code_img = payment["point_of_interaction"]["transaction_data"]["qr_code_base64"]
        
    except Exception as e:
        try:
            db.delete(nova_reserva)
            db.commit()
        except:
            pass
        raise HTTPException(status_code=400, detail=str(e))
    
    nova_reserva.codigo_pix = pix_code_real
    db.commit()
    
    # 🚀 ENVIANDO A IMAGEM PARA O SITE AQUI:
    return {
        "mensagem": "Reserva iniciada!", 
        "codigo_pix": pix_code_real, 
        "qr_code_base64": qr_code_img, 
        "reserva_id": nova_reserva.id
    }

# 🚀 NOVA ROTA: O RADAR DE PAGAMENTO 🚀
@app.get("/reservas/{reserva_id}/status")
def checar_status_reserva(reserva_id: int, db: Session = Depends(get_db)):
    reserva = db.query(BookingDB).filter(BookingDB.id == reserva_id).first()
    if not reserva:
        raise HTTPException(status_code=404, detail="Reserva não encontrada")
    return {"status_pagamento": reserva.status_pagamento}

# 🚀 A ROTA DO WEBHOOK BLINDADA (A PORTA DE ENTRADA DO MERCADO PAGO) 🚀
@app.post("/webhook/mercadopago/")
async def webhook_mercadopago(request: Request, db: Session = Depends(get_db)):
    try:
        # Tenta pegar os dados que o Mercado Pago enviou
        dados = await request.json()
        print(f"📩 Webhook recebido: {dados}") # Vai imprimir no log do Render para a gente ver!
        
        payment_id = None
        
        # O Mercado Pago tem várias formas de mandar o aviso, vamos tentar todas:
        if dados.get("type") == "payment" or dados.get("topic") == "payment" or str(dados.get("action", "")).startswith("payment"):
            payment_id = dados.get("data", {}).get("id")
            if not payment_id:
                payment_id = dados.get("id")
                
        # Se não veio no corpo (JSON), tenta pegar na URL
        if not payment_id:
            params = request.query_params
            if params.get("topic") == "payment" or params.get("type") == "payment":
                payment_id = params.get("data.id") or params.get("id")
                
        if payment_id:
            print(f"🔍 Verificando pagamento ID: {payment_id}")
            # Pergunta pro Mercado Pago: "Esse pagamento foi aprovado mesmo?"
            payment_info = sdk.payment().get(payment_id)
            payment = payment_info.get("response", {})
            
            if payment.get("status") == "approved":
                # Pega aquele ID da reserva que mandamos no "external_reference"
                reserva_id = payment.get("external_reference")
                
                if reserva_id:
                    reserva = db.query(BookingDB).filter(BookingDB.id == int(reserva_id)).first()
                    if reserva and reserva.status_pagamento != "PAGO":
                        reserva.status_pagamento = "PAGO" # MUDA O STATUS!
                        db.commit()
                        print(f"✅ Reserva {reserva_id} PAGA com sucesso!")
                    else:
                        print(f"⚠️ Reserva {reserva_id} já estava paga ou não existe.")
            else:
                print(f"⏳ Pagamento {payment_id} ainda não está aprovado. Status: {payment.get('status')}")
                            
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")
        
    # O Mercado Pago exige que a gente responda rápido com "OK"
    return {"status": "ok"}

@app.post("/negocios/{tenant_id}/agendamento-manual/")
def agendamento_manual(tenant_id: int, booking: ManualBookingRequest, db: Session = Depends(get_db)):
    servico = db.query(ServiceDB).filter(ServiceDB.id == booking.service_id).first()
    hora_fim = booking.data_hora + timedelta(minutes=servico.duracao_minutos)
    
    nova_reserva = BookingDB(tenant_id=tenant_id, service_id=servico.id, professional_id=booking.professional_id, nome_cliente=booking.client_name, telefone_cliente=booking.telefone_cliente, data_hora_inicio=booking.data_hora, data_hora_fim=hora_fim, status_pagamento="MANUAL", valor_total=servico.preco_base, valor_sinal=0, codigo_pix="MANUAL")
    db.add(nova_reserva)
    db.commit()
    return {"mensagem": "Agendamento manual realizado com sucesso!"}

@app.get("/negocios/{tenant_id}/agenda/")
def ver_agenda(tenant_id: int, data: Optional[str] = None, professional_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(BookingDB).filter(BookingDB.tenant_id == tenant_id)
    if professional_id: query = query.filter(BookingDB.professional_id == professional_id)
    if data:
        data_inicio = datetime.strptime(f"{data} 00:00", "%Y-%m-%d %H:%M")
        data_fim = datetime.strptime(f"{data} 23:59", "%Y-%m-%d %H:%M")
        query = query.filter(BookingDB.data_hora_inicio >= data_inicio, BookingDB.data_hora_inicio <= data_fim)
    else:
        hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(BookingDB.data_hora_inicio >= hoje)
        
    reservas = query.order_by(BookingDB.data_hora_inicio.asc()).all()
    resultado = []
    for r in reservas:
        prof = db.query(ProfessionalDB).filter(ProfessionalDB.id == r.professional_id).first()
        servico = db.query(ServiceDB).filter(ServiceDB.id == r.service_id).first()
        resultado.append({"id": r.id, "nome_cliente": r.nome_cliente, "telefone_cliente": r.telefone_cliente, "nome_profissional": prof.nome if prof else "", "nome_servico": servico.nome_servico if servico else "", "data_hora_inicio": r.data_hora_inicio, "data_hora_fim": r.data_hora_fim, "status_pagamento": r.status_pagamento})
    return {"agenda": resultado}
