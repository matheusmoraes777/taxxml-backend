import { useState, useEffect } from 'react'
import { FileText, Download, Loader2, LogOut, Wallet, CheckCircle, Clock, Settings, User, PlusCircle, ShieldCheck, QrCode, UserPlus, ArrowRight, BarChart3, Users, DollarSign, Activity } from 'lucide-react'
import { auth, loginComGoogle, sairDaConta } from './firebase'
import { onAuthStateChanged } from 'firebase/auth'

const API_URL = 'https://taxxml-api.onrender.com'
const PRECO_XML = 0.08

function App() {
  const [usuario, setUsuario] = useState(null)
  const [saldo, setSaldo] = useState(0.0)
  const [view, setView] = useState('login') // login, register, app, admin
  const [activeTab, setActiveTab] = useState('download') 
  const [isAdmin, setIsAdmin] = useState(false)
  
  // States Download
  const [keys, setKeys] = useState('')
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState({ ativo: false, processados: 0, total: 0, concluido: false, taskId: null })
  
  // States Crédito e Admin
  const [valorCustom, setValorCustom] = useState('')
  const [qrBase64, setQrBase64] = useState('')
  const [payId, setPayId] = useState(null)
  const [adminStats, setAdminStats] = useState({ clientes: 0 })
  
  // Dados de Login e Registro
  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')

  const validKeys = keys.split('\n').map(k => k.trim()).filter(k => k.length === 44)
  const total = validKeys.length
  const custoTotal = total * PRECO_XML

  // ==========================================
  // SEGURANÇA E AUTENTICAÇÃO
  // ==========================================
  useEffect(() => {
    // Escuta se o usuário logou pelo Google ou se já tinha sessão
    const unsubscribe = onAuthStateChanged(auth, async (user) => { 
      if (user) { 
        setLoading(true)
        try {
          const res = await fetch(`${API_URL}/api/sync-user`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: user.email, nome: user.displayName })
          })
          const data = await res.json()
          setSaldo(data.saldo || 0)
        } catch(e) { console.error("Erro ao sincronizar saldo") }
        setUsuario(user); 
        setView('app'); 
        setLoading(false)
      } 
    });
    return () => unsubscribe();
  }, []);

  const fazerLoginTradicional = async () => {
    if (!email || !senha) return alert("Preencha e-mail e senha.")
    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/login`, { 
        method: 'POST', headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify({ email, senha }) 
      })
      const data = await res.json()
      if (data.sucesso) { 
        setUsuario({ email: email, displayName: data.nome }); 
        setSaldo(data.saldo); 
        setView('app'); 
      } else { alert(data.erro) }
    } catch(e) { alert("Erro de conexão com o servidor") }
    setLoading(false)
  }

  const criarConta = async () => {
    if (!nome || !email || !senha) return alert("Preencha todos os campos!")
    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/registrar`, { 
        method: 'POST', headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify({ nome, email, senha }) 
      })
      const data = await res.json()
      if (data.sucesso) { 
        alert("Conta criada com sucesso! Faça o login."); 
        setView('login'); setNome(''); setSenha('');
      } else { alert(data.erro) }
    } catch(e) { alert("Erro de conexão.") }
    setLoading(false)
  }

  const handleLogout = async () => {
    await sairDaConta();
    setUsuario(null);
    setSaldo(0);
    setIsAdmin(false);
    setView('login');
    setEmail('');
    setSenha('');
  }

  const acessarAdmin = async () => {
    const s = prompt("Senha Mestre do Sistema:")
    if (s === "123456Mat") {
      setIsAdmin(true)
      try {
        const res = await fetch(`${API_URL}/api/admin/stats`)
        setAdminStats(await res.json())
        setView('admin')
      } catch (e) { alert("Erro ao buscar dados do painel.") }
    } else if (s !== null) { alert("Senha incorreta!") }
  }

  // ==========================================
  // OPERAÇÕES DO SISTEMA (CARTEIRA / DOWNLOAD)
  // ==========================================
  const iniciarDownloadComSaldo = async () => {
    if (total === 0) return alert("Insira as chaves válidas.")
    if (saldo < custoTotal) return setActiveTab('creditos')

    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/iniciar-download`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: usuario.email, chaves: validKeys })
      });
      const data = await res.json();
      if (res.status === 402) { setActiveTab('creditos'); setLoading(false); return; }
      
      setSaldo(data.novo_saldo)
      setProgress({ ativo: true, processados: 0, total: total, concluido: false, taskId: data.task_id })
      setKeys('')
      
      const checkInterval = setInterval(async () => {
        const resProg = await fetch(`${API_URL}/api/progresso/${data.task_id}`);
        const dataProg = await resProg.json();
        setProgress(p => ({ ...p, processados: dataProg.processados }));
        if (dataProg.concluido) { clearInterval(checkInterval); setProgress(p => ({ ...p, concluido: true })); }
      }, 2000); 

    } catch(e) { alert("Erro ao conectar com servidor.") }
    setLoading(false)
  }

  const gerarPixCredito = async (valor) => {
    if (valor < 1) return alert("Valor mínimo R$ 1,00")
    setLoading(true); setQrBase64(''); setPayId(null);
    try {
      const res = await fetch(`${API_URL}/api/comprar-creditos`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: usuario.email, valor: parseFloat(valor) })
      })
      const data = await res.json()
      if (data.qr_code_base64) { setQrBase64(data.qr_code_base64); setPayId(data.payment_id); }
    } catch(e) { alert("Erro ao gerar PIX") }
    setLoading(false)
  }

  const verificarPixCredito = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/verificar-pagamento/${payId}`)
      const data = await res.json()
      if (data.pago) {
        setSaldo(data.novo_saldo); setQrBase64(''); alert("Créditos adicionados com sucesso!"); setActiveTab('download');
      } else { alert("Pagamento ainda não aprovado. Aguarde e tente novamente.") }
    } catch(e) {}
    setLoading(false)
  }

  // ==========================================
  // RENDER: TELAS DO SISTEMA
  // ==========================================
  
  // TELA DE LOGIN
  if (view === 'login') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 font-sans p-6">
        <div className="bg-white p-10 rounded-3xl shadow-xl border border-slate-100 w-full max-w-md text-center">
          <img src="https://i.ibb.co/7x0Qyqr8/taxxml-logo.jpg" alt="Tax XML" className="w-48 mx-auto mb-8" />
          <h2 className="text-xl font-black text-slate-800 mb-6">Acesso ao Sistema</h2>
          
          <input type="email" placeholder="Seu E-mail" value={email} onChange={e=>setEmail(e.target.value)} className="w-full p-4 mb-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:border-sky-500 text-slate-700" />
          <input type="password" placeholder="Sua Senha" value={senha} onChange={e=>setSenha(e.target.value)} className="w-full p-4 mb-6 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:border-sky-500 text-slate-700" />
          
          <button onClick={fazerLoginTradicional} disabled={loading} className="w-full py-4 bg-slate-800 hover:bg-slate-900 text-white font-bold rounded-xl mb-4 transition-all shadow-md flex justify-center">
            {loading ? <Loader2 className="animate-spin" /> : "Entrar"}
          </button>
          
          <div className="flex items-center justify-center gap-2 mb-4">
             <div className="h-px w-full bg-slate-200"></div><span className="text-sm text-slate-400 font-bold">ou</span><div className="h-px w-full bg-slate-200"></div>
          </div>
          <button onClick={loginComGoogle} disabled={loading} className="w-full py-4 bg-white border-2 border-slate-200 text-slate-700 font-bold rounded-xl flex justify-center items-center gap-3 hover:bg-slate-50 transition-all shadow-sm">
            <img src="https://img.icons8.com/color/24/google-logo.png" /> Entrar com Google
          </button>

          {/* BOTÕES RESTAURADOS: CRIAR CONTA E ADMIN */}
          <div className="flex justify-between items-center mt-8 pt-4 border-t border-slate-100">
            <button onClick={() => setView('register')} className="text-sm font-bold text-sky-600 hover:text-sky-700">Criar uma Conta</button>
            <button onClick={acessarAdmin} className="text-slate-300 hover:text-red-500 transition-all" title="Painel Admin"><ShieldCheck size={20}/></button>
          </div>
        </div>
      </div>
    )
  }

  // TELA DE REGISTRO (RESTAURADA)
  if (view === 'register') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 font-sans p-6">
        <div className="bg-white p-10 rounded-3xl shadow-xl border border-slate-100 w-full max-w-md text-center">
          <img src="https://i.ibb.co/7x0Qyqr8/taxxml-logo.jpg" alt="Tax XML" className="w-40 mx-auto mb-6" />
          <h2 className="text-xl font-black text-slate-800 mb-2">Nova Conta</h2>
          <p className="text-slate-500 text-sm mb-6">Crie sua carteira digital para baixar XMLs.</p>
          
          <input type="text" placeholder="Seu Nome" value={nome} onChange={e=>setNome(e.target.value)} className="w-full p-4 mb-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:border-sky-500 text-slate-700" />
          <input type="email" placeholder="Seu E-mail" value={email} onChange={e=>setEmail(e.target.value)} className="w-full p-4 mb-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:border-sky-500 text-slate-700" />
          <input type="password" placeholder="Crie uma Senha" value={senha} onChange={e=>setSenha(e.target.value)} className="w-full p-4 mb-6 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:border-sky-500 text-slate-700" />
          
          <button onClick={criarConta} disabled={loading} className="w-full py-4 bg-sky-600 hover:bg-sky-700 text-white font-bold rounded-xl mb-4 transition-all shadow-md flex justify-center items-center gap-2">
            {loading ? <Loader2 className="animate-spin" /> : <><UserPlus size={18}/> Finalizar Cadastro</>}
          </button>
          
          <button onClick={() => setView('login')} className="text-sm font-bold text-slate-500 hover:text-slate-800">Voltar para o Login</button>
        </div>
      </div>
    )
  }

  // TELA ADMIN (RESTAURADA)
  if (view === 'admin') {
    return (
      <div className="min-h-screen bg-[#0f172a] text-slate-300 p-8 font-sans">
        <div className="max-w-5xl mx-auto">
          <div className="flex justify-between items-center mb-10">
             <h1 className="text-3xl font-black text-white flex items-center gap-3"><ShieldCheck className="text-sky-500"/> Painel Administrativo</h1>
             <button onClick={handleLogout} className="bg-slate-800 px-6 py-2 rounded-xl font-bold flex items-center gap-2 hover:bg-red-500/20 hover:text-red-500 transition-all"><LogOut size={16}/> Sair do Admin</button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-[#1e293b] p-8 rounded-3xl border border-slate-800 shadow-2xl">
               <Users className="text-sky-500 mb-4" size={32}/>
               <div className="text-sm font-bold text-slate-400 uppercase">Clientes Cadastrados</div>
               <div className="text-4xl font-black text-white">{adminStats.clientes}</div>
            </div>
            {/* O Backend simplificado atual só manda clientes. Os outros dados ficarão para o update futuro */}
            <div className="bg-[#1e293b] p-8 rounded-3xl border border-slate-800 shadow-2xl opacity-50">
               <DollarSign className="text-emerald-500 mb-4" size={32}/>
               <div className="text-sm font-bold text-slate-400 uppercase">Em breve</div>
               <div className="text-xl font-bold text-slate-500">Módulo Financeiro</div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // TELA DO APLICATIVO (CLIENTE LOGADO)
  if (view === 'app') {
    return (
      <div className="min-h-screen bg-slate-50 text-slate-800 font-sans">
        
        {/* CABEÇALHO */}
        <header className="bg-white border-b border-slate-200 px-4 md:px-8 py-4 flex flex-wrap justify-between items-center sticky top-0 z-50 shadow-sm">
          <div className="flex items-center gap-6">
            <img src="https://i.ibb.co/7x0Qyqr8/taxxml-logo.jpg" className="w-24 md:w-32 object-contain" alt="Logo" />
            <nav className="hidden lg:flex gap-6 mt-2">
              <button onClick={() => setActiveTab('download')} className={`flex items-center gap-2 text-sm font-bold pb-5 -mb-5 border-b-2 transition-all ${activeTab==='download' ? 'border-sky-500 text-sky-600' : 'border-transparent text-slate-500 hover:text-slate-800'}`}><Download size={18}/> Download Lote</button>
              <button onClick={() => setActiveTab('creditos')} className={`flex items-center gap-2 text-sm font-bold pb-5 -mb-5 border-b-2 transition-all ${activeTab==='creditos' ? 'border-sky-500 text-sky-600' : 'border-transparent text-slate-500 hover:text-slate-800'}`}><Wallet size={18}/> Recarregar Créditos</button>
              <button onClick={() => setActiveTab('operacoes')} className={`flex items-center gap-2 text-sm font-bold pb-5 -mb-5 border-b-2 transition-all ${activeTab==='operacoes' ? 'border-sky-500 text-sky-600' : 'border-transparent text-slate-500 hover:text-slate-800'}`}><Clock size={18}/> Histórico</button>
            </nav>
          </div>
          
          <div className="flex items-center gap-4">
            <button onClick={() => setActiveTab('creditos')} className="bg-sky-50 hover:bg-sky-100 border border-sky-200 px-4 py-2 rounded-xl text-sm font-black flex items-center gap-2 text-sky-700 transition-all shadow-sm">
              <Wallet size={16}/> Saldo: R$ {saldo.toFixed(2)}
            </button>
            <div className="hidden md:flex items-center gap-3 text-sm font-bold text-slate-600 border-l border-slate-200 pl-4">
              <User size={16} className="text-slate-400"/> {usuario?.displayName || usuario?.email.split('@')[0]}
            </div>
            <button onClick={handleLogout} className="text-red-500 hover:bg-red-50 p-2 rounded-lg transition-all" title="Sair do Sistema"><LogOut size={18}/></button>
          </div>
        </header>

        {/* NAVEGAÇÃO MOBILE */}
        <div className="lg:hidden flex overflow-x-auto bg-white border-b border-slate-200 p-2 gap-2">
           <button onClick={() => setActiveTab('download')} className={`flex-1 min-w-[120px] py-2 text-xs font-bold rounded-lg ${activeTab==='download' ? 'bg-sky-100 text-sky-700' : 'text-slate-500'}`}>Download</button>
           <button onClick={() => setActiveTab('creditos')} className={`flex-1 min-w-[120px] py-2 text-xs font-bold rounded-lg ${activeTab==='creditos' ? 'bg-sky-100 text-sky-700' : 'text-slate-500'}`}>Créditos</button>
           <button onClick={() => setActiveTab('operacoes')} className={`flex-1 min-w-[120px] py-2 text-xs font-bold rounded-lg ${activeTab==='operacoes' ? 'bg-sky-100 text-sky-700' : 'text-slate-500'}`}>Histórico</button>
        </div>

        <main className="max-w-6xl mx-auto p-4 md:p-8">
          
          {/* ABA: DOWNLOAD EM LOTE */}
          {activeTab === 'download' && (
            <div className="animate-in fade-in duration-300">
              <div className="mb-6">
                <h2 className="text-2xl font-black text-slate-800 mb-1">Download em Lote</h2>
                <p className="text-slate-500">Cole as chaves. O valor será descontado da sua carteira digital.</p>
              </div>
              
              <div className="grid lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 bg-white p-6 md:p-8 rounded-3xl border border-slate-200 shadow-sm">
                  <div className="flex items-center gap-2 mb-4 font-bold text-slate-700"><FileText size={18} className="text-sky-500"/> Chaves de Acesso (44 dígitos)</div>
                  <textarea 
                    className="w-full h-80 bg-slate-50 border border-slate-200 rounded-2xl p-4 text-sm font-mono text-slate-600 focus:outline-none focus:border-sky-500 focus:ring-4 focus:ring-sky-50 transition-all resize-none"
                    placeholder="Cole as chaves aqui..."
                    value={keys} onChange={e => setKeys(e.target.value)} disabled={progress.ativo}
                  />
                  <div className="mt-3 flex justify-between text-sm font-bold text-slate-500">
                    <span>{total} chaves identificadas</span>
                  </div>
                </div>

                <div className="bg-white p-6 md:p-8 rounded-3xl border border-slate-200 shadow-sm h-fit">
                  <h3 className="font-bold text-slate-800 mb-6 uppercase tracking-wider text-sm">Resumo da Operação</h3>
                  <div className="space-y-4 text-sm text-slate-600 border-b border-slate-100 pb-6 mb-6">
                    <div className="flex justify-between"><span>Chaves Válidas</span><span className="font-black text-slate-800">{total}</span></div>
                    <div className="flex justify-between"><span>Custo por Chave</span><span>R$ {PRECO_XML.toFixed(2)}</span></div>
                    <div className="flex justify-between pt-2"><span>Custo Total</span><span className="text-2xl text-sky-600 font-black">R$ {custoTotal.toFixed(2)}</span></div>
                  </div>
                  
                  {progress.ativo ? (
                    <div className="text-center bg-sky-50 p-6 rounded-2xl border border-sky-100">
                      <Loader2 className="animate-spin text-sky-500 mx-auto mb-3" size={32}/>
                      <p className="text-sm font-black text-sky-700">{progress.processados} / {progress.total} XMLs</p>
                      <p className="text-xs text-sky-600 mt-1">Buscando na Sefaz...</p>
                      {progress.concluido && (
                         <a href={`${API_URL}/api/baixar-zip/${progress.taskId}`} onClick={() => setProgress({ativo: false, processados: 0, total: 0, concluido: false})} className="mt-4 block w-full bg-emerald-500 hover:bg-emerald-600 text-white font-black py-4 rounded-xl shadow-lg transition-all text-center">
                           Salvar Arquivo ZIP
                         </a>
                      )}
                    </div>
                  ) : (
                    <button 
                      onClick={iniciarDownloadComSaldo} disabled={loading}
                      className={`w-full py-4 rounded-2xl font-black text-lg shadow-md transition-all flex justify-center items-center gap-2 ${saldo < custoTotal && total > 0 ? 'bg-red-50 text-red-600 border border-red-200 hover:bg-red-100' : 'bg-sky-500 hover:bg-sky-600 text-white'}`}
                    >
                      {loading ? <Loader2 className="animate-spin"/> : saldo < custoTotal && total > 0 ? 'Saldo Insuficiente' : 'Processar Lote'}
                    </button>
                  )}
                  {saldo < custoTotal && total > 0 && (
                     <button onClick={() => setActiveTab('creditos')} className="w-full mt-3 text-sm font-bold text-sky-600 hover:underline">Ir para Recarga</button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ABA: CRÉDITOS */}
          {activeTab === 'creditos' && (
            <div className="animate-in fade-in duration-300">
              <div className="mb-6">
                <h2 className="text-2xl font-black text-slate-800 mb-1">Carteira Digital</h2>
                <p className="text-slate-500">Adicione saldo via PIX. A liberação na conta é imediata.</p>
              </div>
              
              <div className="grid lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 space-y-6">
                  
                  {/* Card de Saldo */}
                  <div className="bg-slate-800 p-8 rounded-3xl shadow-xl flex items-center gap-6 text-white relative overflow-hidden">
                    <div className="w-16 h-16 bg-white/10 rounded-2xl flex items-center justify-center"><Wallet size={32} className="text-sky-400"/></div>
                    <div className="z-10">
                      <p className="text-sm text-slate-300 font-bold uppercase tracking-wider mb-1">Saldo Atual Disponível</p>
                      <h3 className="text-5xl font-black text-white">R$ {saldo.toFixed(2)}</h3>
                      <p className="text-sm text-emerald-400 mt-2 font-bold flex items-center gap-1"><CheckCircle size={14}/> Suficiente para {Math.floor(saldo / PRECO_XML)} downloads</p>
                    </div>
                  </div>

                  {/* Card de Compra */}
                  <div className="bg-white p-8 rounded-3xl border border-slate-200 shadow-sm">
                    <h3 className="font-black text-slate-800 mb-6 flex items-center gap-2"><PlusCircle className="text-sky-500"/> Pacotes de Recarga</h3>
                    
                    {!qrBase64 ? (
                      <>
                        <div className="grid grid-cols-2 gap-4 mb-6">
                          {[20, 50, 100, 200].map(val => (
                            <button key={val} onClick={() => gerarPixCredito(val)} className="p-5 bg-slate-50 border border-slate-200 hover:border-sky-500 rounded-2xl text-left transition-all">
                              <div className="text-2xl font-black text-slate-700">R$ {val},00</div>
                              <div className="text-sm font-bold text-slate-400 mt-1">{val / PRECO_XML} XMLs</div>
                            </button>
                          ))}
                        </div>
                        <div className="flex gap-3">
                          <input type="number" placeholder="Outro valor (R$)" value={valorCustom} onChange={e=>setValorCustom(e.target.value)} className="flex-1 bg-slate-50 border border-slate-200 rounded-2xl p-4 text-slate-700 outline-none focus:border-sky-500 font-bold"/>
                          <button onClick={() => gerarPixCredito(valorCustom)} disabled={loading} className="bg-slate-800 hover:bg-slate-900 text-white font-black px-8 rounded-2xl flex items-center justify-center">
                            {loading ? <Loader2 className="animate-spin" /> : "Gerar PIX"}
                          </button>
                        </div>
                      </>
                    ) : (
                      <div className="text-center bg-emerald-50 p-8 rounded-3xl border-2 border-dashed border-emerald-200">
                        <h4 className="font-black text-emerald-800 mb-4">Escaneie o QR Code</h4>
                        <img src={`data:image/png;base64,${qrBase64}`} className="mx-auto w-48 rounded-xl shadow-md mb-6 bg-white p-2" />
                        <button onClick={verificarPixCredito} className="bg-emerald-500 hover:bg-emerald-600 text-white font-black py-4 px-8 rounded-2xl transition-all shadow-lg w-full flex justify-center items-center gap-2">
                          {loading ? <Loader2 className="animate-spin"/> : <><QrCode/> Já realizei o pagamento</>}
                        </button>
                        <button onClick={() => setQrBase64('')} className="block w-full text-slate-500 hover:text-slate-700 text-sm font-bold mt-4">Cancelar operação</button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ABA: OPERAÇÕES */}
          {activeTab === 'operacoes' && (
            <div className="animate-in fade-in duration-300">
              <div className="mb-8">
                <h2 className="text-2xl font-black text-slate-800 mb-1">Minhas Operações</h2>
                <p className="text-slate-500">Histórico detalhado em breve.</p>
              </div>
              <div className="bg-white p-16 rounded-3xl border border-slate-200 text-center shadow-sm">
                 <h3 className="text-slate-700 font-black text-lg mb-2">Sem histórico</h3>
                 <p className="text-slate-500 mb-6">Você ainda não baixou nenhum lote.</p>
              </div>
            </div>
          )}
        </main>
      </div>
    )
  }

  return null
}

export default App
